#!/usr/bin/env python3
"""H-051: bounded-backtrack schedule search over the captured op stream.

The mainline scheduler is ONLINE greedy: build_kernel_scheduled emits ops
one at a time and ListScheduler places each at its earliest feasible cycle
immediately. This tool decouples SEARCH from EMISSION:

  1. `capture`: monkeypatch dev.ListScheduler with a subclass that records,
     for every placed op, the exact hazard context the scheduler saw
     (engine, slot, reads, writes, mem flags, ignore-hazard flags,
     min_cycle, builder tag) plus the cycle greedy chose. The captured
     stream has all emit_any race spellings baked in (every spelling is
     semantically equivalent, so re-placing the same spellings is correct).
  2. Offline constraint model: processing ops in emission order with the
     scheduler's own running-maxima hazard rules yields an explicit
     precedence DAG (RAW/WAW lag 1, WAR lag 0, coarse-mem edges honoring
     store_pair + the H-031 ignore flags). ANY placement satisfying the
     DAG + per-cycle SLOT_LIMITS is a correct program; the machine drops
     empty bundles, so the objective is the number of NON-EMPTY cycles.
  3. `validate`: offline greedy in emission order must reproduce the
     captured placements EXACTLY (model soundness check).
  4. `regret`: for each prefix cycle c of the greedy schedule compute
     F(c) = max over lower bounds of (finish | prefix fixed):
     per-engine slot counts of the remaining ops, and critical path
     (release + tail height) through the remaining DAG. regret(c) =
     F(c) - F(-1); the cycles where regret JUMPS are where the schedule
     falls behind the bound.
  5. `probe` / `search`: alternative offline schedules -- priority list
     scheduling (parallel SGS by tail height), and a bounded-backtrack /
     delay-plan local search (force min-cycle floors on selected ops, rerun
     greedy; prune with the same bound arithmetic). Any improved schedule
     is re-verified end-to-end on the frozen grader via program
     reconstruction (`verify`).

Usage (repo root):
    python tools/backtrack_sched.py capture
    python tools/backtrack_sched.py validate
    python tools/backtrack_sched.py regret [--fungible]
    python tools/backtrack_sched.py probe
    python tools/backtrack_sched.py search --windows auto --budget 600
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import sys
import time
from collections import defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import dev  # noqa: E402
from dev import KernelBuilder, ListScheduler  # noqa: E402
from problem import SLOT_LIMITS, VLEN  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE  # noqa: E402

SCRATCH_DIR = os.environ.get(
    "H51_SCRATCH",
    "/private/tmp/claude-501/-Users-tatestaples-Code-original-performance-takehome/"
    "5cfbd141-00dc-4755-aaa3-3deea70ab9f0/scratchpad",
)
CAPTURE_PATH = os.path.join(SCRATCH_DIR, "h51_capture.pkl")

# The 1031 mainline-equivalent dev config (loop context, 2026-07-27).
H51_OVERRIDES: dict[str, Any] = {
    "parity_ring": True,
    "l4_gmin": (8, 30),
    "parity_ring_plan": (
        ((0, 5), (193, 201, 601)),
        ((0, 6), (609, 617, 625)),
        ((0, 15), (185, 1225, 1233)),
        ((0, 16), (193, 201, 1297)),
    ),
    "flow_spelling_plan": ((354, 1),),
}

ENGINES = tuple(e for e in SLOT_LIMITS if e != "debug")


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
_INSTANCES: list["RichScheduler"] = []


class RichScheduler(ListScheduler):
    """ListScheduler that records the full hazard context of every put()."""

    def __init__(self) -> None:
        super().__init__()
        self.ops: list[tuple[Any, ...]] = []
        self._ctx = (0, False, False)  # (min_cycle, ignore_mem_read, ignore_mem_write)
        _INSTANCES.append(self)

    def emit(self, engine, slot, reads=(), writes=(), mem_read=False,
             mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
             ignore_mem_write_hazard=False):
        self._ctx = (min_cycle, ignore_mem_read_hazard, ignore_mem_write_hazard)
        try:
            return super().emit(engine, slot, reads, writes, mem_read,
                                mem_write, min_cycle, ignore_mem_read_hazard,
                                ignore_mem_write_hazard)
        finally:
            self._ctx = (0, False, False)

    def put(self, engine, slot, cycle, reads=(), writes=(), mem_read=False,
            mem_write=False):
        min_cycle, ig_mr, ig_mw = self._ctx
        self.ops.append((engine, slot, tuple(reads), tuple(writes),
                         bool(mem_read), bool(mem_write), ig_mr, ig_mw,
                         min_cycle, cycle, self.tag))
        super().put(engine, slot, cycle, reads, writes, mem_read, mem_write)


def capture(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    kwargs = dict(BASE_KWARGS, **H51_OVERRIDES, **(overrides or {}))
    assert not kwargs.get("speculative_fold_levels"), \
        "capture does not support spec_fold's snapshot/rollback"
    _INSTANCES.clear()
    orig = dev.ListScheduler
    dev.ListScheduler = RichScheduler  # type: ignore[misc]
    try:
        kb = KernelBuilder()
        kb.build_kernel_scheduled(
            SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs
        )
    finally:
        dev.ListScheduler = orig  # type: ignore[misc]
    # find the scheduler instance whose bundles became kb.instrs (identity)
    chosen = None
    for inst in _INSTANCES:
        filtered = [b for b in inst.bundles if b]
        if len(filtered) == len(kb.instrs) and all(
            a is b for a, b in zip(filtered, kb.instrs)
        ):
            chosen = inst
            break
    assert chosen is not None, "could not identify the final build's scheduler"
    data = {
        "kwargs_note": {k: repr(v) for k, v in H51_OVERRIDES.items()},
        "ops": chosen.ops,
        "pair_writes": chosen.pair_writes,
        "n_cycles": len(kb.instrs),
        "span": len(chosen.bundles),
        "scratch_debug": dict(kb.scratch_debug),
    }
    return data


# ---------------------------------------------------------------------------
# Constraint model
# ---------------------------------------------------------------------------
def build_model(ops: list[tuple[Any, ...]], pair_writes: bool):
    """preds[i] = list of (j, lag) meaning c_i >= c_j + lag. floors[i] =
    absolute min cycle. Derived with the scheduler's own semantics processed
    in emission order (see module docstring for the domination argument on
    the coarse mem clocks)."""
    n = len(ops)
    preds: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    floors = [0] * n
    last_writer: dict[int, int] = {}
    readers_since: dict[int, list[int]] = defaultdict(list)
    last_mem_writer = -1
    mem_readers_since: list[int] = []
    store_idxs: list[int] = []
    for i, (eng, slot, reads, writes, mem_read, mem_write, ig_mr, ig_mw,
            min_cycle, cycle, tag) in enumerate(ops):
        p = preds[i]
        if slot == ("pause",) and min_cycle:
            # The final pause is emitted with min_cycle=last_store_cycle --
            # a greedy-DERIVED floor. The true constraint is "no earlier
            # than any store"; model it as lag-0 edges so search schedules
            # remain correct without inheriting greedy's absolute cycle.
            floors[i] = 0
            for j in store_idxs:
                p.append((j, 0))
        else:
            floors[i] = min_cycle
        if eng == "store":
            store_idxs.append(i)
        for a in reads:
            j = last_writer.get(a)
            if j is not None:
                p.append((j, 1))
        for a in writes:
            j = last_writer.get(a)
            if j is not None:
                p.append((j, 1))
            for j in readers_since.get(a, ()):
                if j != i:
                    p.append((j, 0))
        if mem_read and not ig_mw and last_mem_writer >= 0:
            p.append((last_mem_writer, 1))
        if mem_write:
            if last_mem_writer >= 0:
                p.append((last_mem_writer, 0 if pair_writes else 1))
            if not ig_mr:
                for j in mem_readers_since:
                    p.append((j, 0))
        # state update
        for a in reads:
            readers_since[a].append(i)
        for a in writes:
            last_writer[a] = i
            readers_since[a] = []
        if mem_read:
            mem_readers_since.append(i)
        if mem_write:
            last_mem_writer = i
            mem_readers_since = []
    # dedupe, keep max lag per (i, j)
    for i in range(n):
        if len(preds[i]) > 1:
            best: dict[int, int] = {}
            for j, lag in preds[i]:
                if best.get(j, -1) < lag:
                    best[j] = lag
            preds[i] = sorted(best.items())
    return preds, floors


def greedy_schedule(ops, preds, floors, extra_floors: dict[int, int] | None = None,
                    limit: int | None = None):
    """Offline greedy earliest-feasible in emission order. Returns
    (placements, n_nonempty_cycles) or (None, None) if `limit` exceeded."""
    n = len(ops)
    place = [0] * n
    occ: list[list[int]] = []          # occ[cycle] indexed by engine idx
    eng_idx = {e: k for k, e in enumerate(ENGINES)}
    caps = [SLOT_LIMITS[e] for e in ENGINES]
    hint = [0] * len(ENGINES)
    for i in range(n):
        ready = floors[i]
        if extra_floors:
            ef = extra_floors.get(i)
            if ef is not None and ef > ready:
                ready = ef
        for j, lag in preds[i]:
            t = place[j] + lag
            if t > ready:
                ready = t
        e = eng_idx[ops[i][0]]
        cap = caps[e]
        c = ready if ready > hint[e] else hint[e]
        if ready > c:
            c = ready
        while c < len(occ) and occ[c][e] >= cap:
            c += 1
        while len(occ) <= c:
            occ.append([0] * len(ENGINES))
        occ[c][e] += 1
        place[i] = c
        if limit is not None and c >= limit:
            return None, None
        if occ[c][e] >= cap and c == hint[e]:
            h = c
            while h < len(occ) and occ[h][e] >= cap:
                h += 1
            hint[e] = h
    nonempty = sum(1 for row in occ if any(row))
    return place, nonempty


# ---------------------------------------------------------------------------
# Bounds + regret
# ---------------------------------------------------------------------------
def tails(ops, preds):
    """h[i] = max over paths to any sink of sum(lags). c_i + h_i <= last cycle."""
    n = len(ops)
    h = [0] * n
    for i in range(n - 1, -1, -1):
        hi = h[i]
        for j, lag in preds[i]:
            v = hi + lag
            if v > h[j]:
                h[j] = v
    return h


def ests(ops, preds, floors):
    n = len(ops)
    est = [0] * n
    for i in range(n):
        v = floors[i]
        for j, lag in preds[i]:
            t = est[j] + lag
            if t > v:
                v = t
        est[i] = v
    return est


def lb_total(ops, preds, floors):
    est = ests(ops, preds, floors)
    h = tails(ops, preds)
    cp = max(e + t for e, t in zip(est, h)) + 1
    counts = defaultdict(int)
    for op in ops:
        counts[op[0]] += 1
    eng = {e: -(-counts[e] // SLOT_LIMITS[e]) for e in counts}
    return {"cp": cp, "engine": eng, "lb": max(cp, max(eng.values()))}


def fungible_lb(ops_subset) -> int:
    """H-044-style fungibility bound for a set of ops (ignores deps): plain
    vector lane-ops may run on alu 1:1, madd 2:1; scalar alu ops stay alu;
    flow/load/store rigid. Lower bound = min C s.t. feasible."""
    plain_lanes = 0.0
    madd_slots = 0
    scalar = 0
    flow = 0
    load = 0
    store = 0
    valu_other = 0
    from dev import _SCALARIZABLE
    for op in ops_subset:
        eng, slot = op[0], op[1]
        if eng == "valu":
            if slot[0] == "multiply_add":
                madd_slots += 1
            elif slot[0] in _SCALARIZABLE:
                plain_lanes += VLEN
            else:
                valu_other += 1  # vbroadcast etc.
        elif eng == "alu":
            scalar += 1  # already scalar; 1:1 lane-op (could re-vectorize but keep rigid-ish)
        elif eng == "flow":
            flow += 1
        elif eng == "load":
            load += 1
        elif eng == "store":
            store += 1
    lo, hi = 0, 6000
    total_plain = plain_lanes + scalar  # scalar ops counted as fungible lanes

    def feasible(C: int) -> bool:
        if flow > C or load > 2 * C or store > 2 * C:
            return False
        alu_cap = 12 * C
        a_plain = min(total_plain, alu_cap)
        a_madd = min(madd_slots * VLEN, (alu_cap - a_plain) / 2.0)
        valu_lanes = (total_plain - a_plain) + (madd_slots * VLEN - a_madd)
        return valu_lanes / VLEN + valu_other <= 6 * C

    while lo < hi:
        mid = (lo + hi) // 2
        if feasible(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def regret_profile(ops, preds, floors, place, use_fungible=False):
    """F(c) for every prefix cycle c of the schedule `place`."""
    n = len(ops)
    h = tails(ops, preds)
    total_cycles = max(place) + 1
    # ops sorted by placement cycle
    by_cycle: list[list[int]] = [[] for _ in range(total_cycles)]
    for i, c in enumerate(place):
        by_cycle[c].append(i)
    # engine remaining counts as we advance the cutoff
    counts = defaultdict(int)
    for op in ops:
        counts[op[0]] += 1
    # release_i given prefix <= c fixed: computed incrementally is awkward;
    # do a per-cutoff forward pass over remaining ops only when needed is
    # O(n * cycles) -- too slow. Instead: est'_i for cutoff c equals
    # max(floors_i, max_{j pred, place_j <= c}(place_j + lag),
    #     max_{j pred, place_j > c}(est'_j + lag)).
    # Sweep c from total_cycles-1 down: when c decreases, ops move from
    # "placed" to "remaining". Simpler: sweep c upward and recompute est'
    # lazily only for a tail window; n_cycles ~1031, n ~19k, preds ~3 =>
    # full O(n) pass per cutoff is ~20M edge visits per 1000 cutoffs = too
    # slow in Python. Use the equivalent formulation:
    #   est'_i(c) = max(est_i_full, ???) -- actually est'_i(c) =
    #   max over paths ending at i of (place_anchor + lags) where anchors
    #   are placed ops or floors. Since place_j >= est_j always, and the
    #   anchor value place_j + lag uses the ACTUAL placement, est' is the
    #   "conditional est". We compute it per cutoff with a single pass over
    #   ops with place > c, in emission order (preds are earlier-emitted).
    # To keep it tractable we only evaluate cutoffs where something can
    # change the answer: every cycle (1031 passes) over suffix ops only.
    # Average suffix size ~n/2 => ~10M op-visits total. Acceptable.
    F = [0] * total_cycles
    eng_lb_at = [0] * total_cycles
    cp_lb_at = [0] * total_cycles
    remaining = dict(counts)
    est_cond: dict[int, int] = {}
    # process cutoffs ascending; maintain remaining counts
    order_by_place = sorted(range(n), key=lambda i: place[i])
    ptr = 0
    suffix_start_idx = 0  # into order_by_place
    emission_suffix = list(range(n))
    for c in range(total_cycles):
        # remove ops placed at cycle c from remaining AFTER computing F(c-1)?
        # F(c) fixes prefix cycles 0..c => remaining ops have place > c.
        while ptr < n and place[order_by_place[ptr]] <= c:
            remaining[ops[order_by_place[ptr]][0]] -= 1
            ptr += 1
        # engine bound
        eng_lb = 0
        for e, cnt in remaining.items():
            if cnt:
                v = -(-cnt // SLOT_LIMITS[e])
                if v > eng_lb:
                    eng_lb = v
        # critical path bound over remaining ops
        cp = 0
        est_cond.clear()
        for i in emission_suffix:
            if place[i] <= c:
                continue
            v = floors[i]
            if v < c + 1:
                v = c + 1
            for j, lag in preds[i]:
                if place[j] <= c:
                    t = place[j] + lag
                else:
                    t = est_cond[j] + lag
                if t > v:
                    v = t
            est_cond[i] = v
            t = v + h[i]
            if t > cp:
                cp = t
        # prune emission_suffix lazily (keep only remaining ops now and then)
        if c % 64 == 63:
            emission_suffix = [i for i in emission_suffix if place[i] > c]
        cp_lb = cp + 1 - (c + 1) if est_cond else 0
        f = (c + 1) + max(eng_lb, cp_lb)
        if use_fungible and est_cond:
            fb = fungible_lb([ops[i] for i in est_cond])
            if (c + 1) + fb > f:
                f = (c + 1) + fb
        F[c] = f
        eng_lb_at[c] = eng_lb
        cp_lb_at[c] = cp_lb
    return F, eng_lb_at, cp_lb_at


# ---------------------------------------------------------------------------
# Priority (parallel SGS) scheduling
# ---------------------------------------------------------------------------
def priority_schedule(ops, preds, floors, priority):
    """Cycle-by-cycle parallel schedule generation: at each cycle place
    ready ops (all pred constraints satisfied at this cycle) into free
    slots, highest priority first. WAR lag-0 edges make 'ready at cycle c'
    depend on same-cycle placements of predecessors: an op with a lag-0
    pred not yet placed is held back until the pred is placed (then it can
    go the same cycle if the pred's cycle <= c)."""
    import heapq
    n = len(ops)
    eng_of = [op[0] for op in ops]
    succs: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    npred = [0] * n
    for i in range(n):
        for j, lag in preds[i]:
            succs[j].append((i, lag))
        npred[i] = len(preds[i])
    ready_at = [0] * n  # earliest cycle given placed preds
    for i in range(n):
        if floors[i] > ready_at[i]:
            ready_at[i] = floors[i]
    heaps: dict[str, list] = {e: [] for e in ENGINES}
    pend = list(npred)
    for i in range(n):
        if pend[i] == 0:
            heapq.heappush(heaps[eng_of[i]], (-priority[i], i))
    place = [-1] * n
    placed = 0
    c = 0
    deferred: dict[str, list] = {e: [] for e in ENGINES}
    while placed < n:
        newly = []
        for e in ENGINES:
            cap = SLOT_LIMITS[e]
            heap = heaps[e]
            used = 0
            defer = deferred[e]
            while heap and used < cap:
                pr, i = heapq.heappop(heap)
                if ready_at[i] > c:
                    defer.append((pr, i))
                    continue
                place[i] = c
                placed += 1
                used += 1
                newly.append(i)
            # unplaced ready ops stay in heap; re-add deferred
            for item in defer:
                heapq.heappush(heap, item)
            defer.clear()
        # release successors of newly placed (may become ready THIS cycle
        # via lag-0 edges -> loop same cycle until fixpoint)
        while newly:
            frontier = []
            for i in newly:
                for j, lag in succs[i]:
                    t = place[i] + lag
                    if t > ready_at[j]:
                        ready_at[j] = t
                    pend[j] -= 1
                    if pend[j] == 0:
                        heapq.heappush(heaps[eng_of[j]], (-priority[j], j))
                        if ready_at[j] <= c:
                            frontier.append(j)
            # try to fill remaining slots this cycle with lag-0-released ops
            newly = []
            if frontier:
                for e in ENGINES:
                    cap = SLOT_LIMITS[e]
                    heap = heaps[e]
                    used = sum(1 for i in range(n) if False)  # recompute below
                # recompute used per engine at cycle c
                used_now = defaultdict(int)
                for i, pc in enumerate(place):
                    if pc == c:
                        used_now[eng_of[i]] += 1
                progress = True
                while progress:
                    progress = False
                    for e in ENGINES:
                        cap = SLOT_LIMITS[e]
                        heap = heaps[e]
                        defer = deferred[e]
                        while heap and used_now[e] < cap:
                            pr, i = heapq.heappop(heap)
                            if place[i] >= 0:
                                continue
                            if ready_at[i] > c or pend[i] > 0:
                                defer.append((pr, i))
                                continue
                            place[i] = c
                            placed += 1
                            used_now[e] += 1
                            newly.append(i)
                            progress = True
                        for item in defer:
                            heapq.heappush(heap, item)
                        defer.clear()
        c += 1
    total = max(place) + 1
    occ = [0] * total
    for i, pc in enumerate(place):
        occ[pc] = 1
    nonempty = sum(occ)
    return place, nonempty


# ---------------------------------------------------------------------------
# Reconstruction + verification on the frozen grader
# ---------------------------------------------------------------------------
def check_feasible(ops, preds, floors, place) -> bool:
    occ: dict[tuple[int, str], int] = defaultdict(int)
    for i, c in enumerate(place):
        if c < floors[i]:
            return False
        for j, lag in preds[i]:
            if c < place[j] + lag:
                return False
        occ[(c, ops[i][0])] += 1
    return all(v <= SLOT_LIMITS[e] for (c, e), v in occ.items())


def reconstruct_and_verify(ops, place, seeds=(1, 2, 3, 7, 42, 99),
                           overrides: dict[str, Any] | None = None):
    """Rebuild kb with the same config, replace instrs with the re-placed
    bundles, run the frozen grader on multiple seeds."""
    from frozen_problem import (  # type: ignore
        Machine, N_CORES, Tree, Input, build_mem_image, reference_kernel2,
    )
    kwargs = dict(BASE_KWARGS, **H51_OVERRIDES, **(overrides or {}))
    kb = KernelBuilder()
    kb.build_kernel_scheduled(
        SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs
    )
    # rebuild bundles from placements
    total = max(place) + 1
    bundles: list[dict[str, list]] = [dict() for _ in range(total)]
    for i, c in enumerate(place):
        eng, slot = ops[i][0], ops[i][1]
        bundles[c].setdefault(eng, []).append(slot)
    instrs = [b for b in bundles if b]
    kb.instrs = instrs
    results = []
    for seed in seeds:
        random.seed(seed)
        forest = Tree.generate(SHAPE["forest_height"])
        problem_input = Input.generate(forest, SHAPE["batch_size"], SHAPE["rounds"])
        mem = build_mem_image(forest, problem_input)
        machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES)
        machine.enable_pause = False
        machine.enable_debug = False
        machine.run()
        for ref_mem in reference_kernel2(mem):
            pass
        input_values_ptr = ref_mem[6]
        value_count = len(problem_input.values)
        correct = (machine.mem[input_values_ptr:input_values_ptr + value_count]
                   == ref_mem[input_values_ptr:input_values_ptr + value_count])
        results.append({"seed": seed, "cycles": machine.cycle, "correct": correct})
    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def load_capture():
    with open(CAPTURE_PATH, "rb") as f:
        return pickle.load(f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["capture", "validate", "regret", "probe",
                                    "cp", "search", "pairs", "bound",
                                    "verify"])
    ap.add_argument("--fungible", action="store_true")
    ap.add_argument("--budget", type=float, default=900.0,
                    help="search wall-clock budget (seconds)")
    ap.add_argument("--windows", default="auto",
                    help="comma list like 530-545,905-940 or 'auto'/'all'")
    ap.add_argument("--delays", default="1,2",
                    help="comma list of per-op delay amounts to try")
    ap.add_argument("--engines", default="valu,load,flow,alu,store")
    args = ap.parse_args()

    if args.cmd == "capture":
        t0 = time.time()
        data = capture()
        with open(CAPTURE_PATH, "wb") as f:
            pickle.dump(data, f)
        print(json.dumps({
            "ops": len(data["ops"]), "n_cycles": data["n_cycles"],
            "span": data["span"], "pair_writes": data["pair_writes"],
            "secs": round(time.time() - t0, 1), "path": CAPTURE_PATH,
        }))
        return

    data = load_capture()
    ops = data["ops"]
    preds, floors = build_model(ops, data["pair_writes"])

    if args.cmd == "validate":
        place, nonempty = greedy_schedule(ops, preds, floors)
        captured = [op[9] for op in ops]
        mism = [i for i in range(len(ops)) if place[i] != captured[i]]
        print(json.dumps({
            "ops": len(ops), "offline_cycles": nonempty,
            "captured_cycles": data["n_cycles"],
            "exact_match": not mism, "n_mismatch": len(mism),
            "first_mismatches": [
                (i, captured[i], place[i], ops[i][0], ops[i][1][0]) for i in mism[:8]
            ],
        }, default=str))
        return

    if args.cmd == "regret":
        place = [op[9] for op in ops]
        lb = lb_total(ops, preds, floors)
        print("LB(total):", json.dumps(lb))
        # Energetic staircase bounds: ops with est >= t cannot start before
        # t => makespan >= t + ceil(count_e(est>=t)/cap_e); ops with tail
        # h >= k cannot run in the last k cycles => makespan >=
        # ceil(count_e(h>=k)/cap_e) + k. Valid for ANY packing of this
        # stream -- the tight side quantifies unavoidable ramp/drain loss.
        est = ests(ops, preds, floors)
        h = tails(ops, preds)
        for name, key in (("release(est)", est), ("tail(h)", h)):
            best_v, best_at = 0, None
            for e in ENGINES:
                vals = sorted((key[i] for i in range(len(ops))
                               if ops[i][0] == e), reverse=True)
                # count of ops with key >= t is found by scanning sorted desc
                for cnt, t in enumerate(vals, 1):
                    v = t + -(-cnt // SLOT_LIMITS[e])
                    if v > best_v:
                        best_v, best_at = v, (e, t, cnt)
            print(f"staircase bound [{name}]: {best_v}  (engine, threshold, "
                  f"ops beyond): {best_at}")
        F, eng_lb, cp_lb = regret_profile(ops, preds, floors, place,
                                          use_fungible=args.fungible)
        base = F[-1]  # F at the end equals total cycles
        f_start = max(lb["lb"], F[0] - 1)  # F(-1) ~ lb
        print(f"total cycles {max(place) + 1}   F(-1)=LB {lb['lb']}   "
              f"final regret {max(place) + 1 - lb['lb']}")
        prev = lb["lb"]
        jumps = []
        for c in range(len(F)):
            if F[c] > prev:
                jumps.append((c, F[c] - prev, F[c], eng_lb[c], cp_lb[c]))
            prev = max(prev, F[c])
        print("cycles where F (finish lower bound) jumps:")
        for c, d, f, e, cp in jumps:
            tagset = sorted({ops[i][10][0] for i in range(len(ops))
                             if place[i] == c and ops[i][10]})
            print(f"  c={c:>4} +{d} F={f} engLB={e} cpLB={cp} rounds={tagset}")
        return

    if args.cmd == "cp":
        # Re-derive edges WITH hazard kinds, walk one tight critical path,
        # and classify its composition.
        n = len(ops)
        kinds: dict[tuple[int, int], tuple[int, str, Any]] = {}
        last_writer: dict[int, int] = {}
        readers_since: dict[int, list[int]] = defaultdict(list)
        last_mem_writer = -1
        mem_readers_since: list[int] = []
        pw = data["pair_writes"]

        def add(i, j, lag, kind, addr):
            cur = kinds.get((i, j))
            if cur is None or cur[0] < lag:
                kinds[(i, j)] = (lag, kind, addr)

        for i, (eng, slot, reads, writes, mem_read, mem_write, ig_mr, ig_mw,
                min_cycle, cycle, tag) in enumerate(ops):
            for a in reads:
                j = last_writer.get(a)
                if j is not None:
                    add(i, j, 1, "RAW", a)
            for a in writes:
                j = last_writer.get(a)
                if j is not None:
                    add(i, j, 1, "WAW", a)
                for j in readers_since.get(a, ()):
                    if j != i:
                        add(i, j, 0, "WAR", a)
            if mem_read and not ig_mw and last_mem_writer >= 0:
                add(i, last_mem_writer, 1, "MEM-RAW", None)
            if mem_write:
                if last_mem_writer >= 0:
                    add(i, last_mem_writer, 0 if pw else 1, "MEM-WAW", None)
                if not ig_mr:
                    for j in mem_readers_since:
                        add(i, j, 0, "MEM-WAR", None)
            for a in reads:
                readers_since[a].append(i)
            for a in writes:
                last_writer[a] = i
                readers_since[a] = []
            if mem_read:
                mem_readers_since.append(i)
            if mem_write:
                last_mem_writer = i
                mem_readers_since = []

        est = ests(ops, preds, floors)
        h = tails(ops, preds)
        total = max(e + t for e, t in zip(est, h))
        est_nofloor = ests(ops, preds, [0] * n)
        total_nofloor = max(e + t for e, t in zip(est_nofloor, h))
        nz_floors = sum(1 for f in floors if f)
        print(f"CP length {total + 1}  (without min_cycle floors: "
              f"{total_nofloor + 1}; nonzero floors: {nz_floors})")

        # scratch name lookup
        blocks = sorted((a, nm, ln) for a, (nm, ln) in data["scratch_debug"].items())

        def sname(addr):
            if addr is None:
                return "mem"
            import bisect
            k = bisect.bisect_right([b[0] for b in blocks], addr) - 1
            if k >= 0:
                base, nm, ln = blocks[k]
                if addr < base + ln:
                    return nm
            return "pool/anon"

        # build successor map restricted to tight edges
        succs_k: list[list[tuple[int, int, str, Any]]] = [[] for _ in range(n)]
        for (i, j), (lag, kind, addr) in kinds.items():
            succs_k[j].append((i, lag, kind, addr))
        # find a tight source: est==floor or est==0, est+h == total
        cur = None
        for i in range(n):
            if est[i] + h[i] == total and all(
                est[i] > est[j] + lag for j, lag in preds[i]
            ):
                cur = i
                break
        assert cur is not None
        path = [cur]
        edge_seq = []
        while h[cur] > 0:
            nxt = None
            for i, lag, kind, addr in succs_k[cur]:
                if est[i] == est[cur] + lag and est[i] + h[i] == total and h[cur] == lag + h[i]:
                    nxt = (i, lag, kind, addr)
                    break
            assert nxt is not None, (cur, est[cur], h[cur])
            i, lag, kind, addr = nxt
            edge_seq.append((cur, i, lag, kind, addr))
            path.append(i)
            cur = i
        from collections import Counter
        kind_ct = Counter((k for _, _, lag, k, _ in edge_seq if lag > 0))
        kind0_ct = Counter((k for _, _, lag, k, _ in edge_seq if lag == 0))
        addr_ct = Counter(
            f"{k}:{sname(a)}" for _, _, lag, k, a in edge_seq if lag > 0)
        opcode_ct = Counter(
            f"{ops[j][0]}:{ops[j][1][0]}" for _, j, lag, _, _ in edge_seq if lag > 0)
        print(f"path ops {len(path)}  lag-1 edges {sum(1 for e in edge_seq if e[2] > 0)}")
        print("lag-1 edge kinds:", dict(kind_ct))
        print("lag-0 edge kinds on path:", dict(kind0_ct))
        print("lag-1 kinds by scratch block (top 20):")
        for k, v in addr_ct.most_common(20):
            print(f"  {v:>5}  {k}")
        print("consumer op on lag-1 edges (top 15):")
        for k, v in opcode_ct.most_common(15):
            print(f"  {v:>5}  {k}")
        # dump the path with cycles for eyeballing
        outp = os.path.join(SCRATCH_DIR, "h51_cp_path.txt")
        with open(outp, "w") as f:
            for i0, i1, lag, kind, addr in edge_seq:
                f.write(f"{est[i0]:>4} {ops[i0][0]:>5}:{ops[i0][1][0]:<14} "
                        f"tag={ops[i0][10]} -[{kind} lag{lag} {sname(addr)}]-> "
                        f"{est[i1]:>4} {ops[i1][0]:>5}:{ops[i1][1][0]:<14} tag={ops[i1][10]}\n")
        print("full path dumped to", outp)
        return

    if args.cmd == "verify":
        # End-to-end proof of the reconstruction path: rebuild the program
        # from recorded placements (or the checkpointed incumbent if one
        # exists and beats baseline) and run the frozen grader multi-seed.
        place = [op[9] for op in ops]
        src = "greedy(identity)"
        inc_path = os.path.join(SCRATCH_DIR, "h51_incumbent.pkl")
        if os.path.exists(inc_path):
            with open(inc_path, "rb") as f:
                inc = pickle.load(f)
            if inc["cycles"] < max(place) + 1:
                place = inc["place"]
                src = f"incumbent({inc['cycles']}, floors={inc['floors']})"
        ok = check_feasible(ops, preds, floors, place)
        print(f"source: {src}  feasible={ok}")
        res = reconstruct_and_verify(ops, place)
        print(json.dumps(res))
        return

    if args.cmd == "bound":
        # Two-sided energetic interval bound: for makespan C, every op has
        # release est_i and deadline C-1-h_i; if for some engine e and
        # window [t1, t2] the ops confined to it exceed (t2-t1+1)*cap_e,
        # C is infeasible. Largest infeasible C + 1 is a valid LB for ANY
        # packing of this op stream.
        est = ests(ops, preds, floors)
        h = tails(ops, preds)

        def feasible(C: int) -> bool:
            for e in ENGINES:
                cap = SLOT_LIMITS[e]
                pts = [(est[i], C - 1 - h[i]) for i in range(len(ops))
                       if ops[i][0] == e]
                if not pts:
                    continue
                if any(d < r for r, d in pts):
                    return False
                t1s = sorted({r for r, _ in pts})
                for t1 in t1s:
                    dls = sorted(d for r, d in pts if r >= t1)
                    for k, t2 in enumerate(dls, 1):
                        if k > (t2 - t1 + 1) * cap:
                            return False
            return True

        lo, hi = 1000, 1032  # bracket
        while not feasible(hi):
            hi += 8
        while lo < hi:
            mid = (lo + hi) // 2
            if feasible(mid):
                hi = mid
            else:
                lo = mid + 1
        print(f"energetic interval LB (any packing of this stream): {lo}")
        return

    if args.cmd == "search":
        # Delay-plan local search: force min_cycle floors on single ops in
        # the high-regret windows and rerun offline greedy end-to-end.
        # First-improvement hill climb; accepted floors accumulate. Any
        # improved schedule is checked feasible and checkpointed; final
        # verification on the frozen grader is a separate step.
        place0 = [op[9] for op in ops]
        base_cycles = max(place0) + 1
        if args.windows == "auto":
            # windows: +-8 around every F-jump cycle (recompute quickly)
            F, _, _ = regret_profile(ops, preds, floors, place0)
            jumps = []
            prev = 0
            for c in range(len(F)):
                if F[c] > prev and c > 0:
                    jumps.append(c)
                prev = max(prev, F[c])
            wins = [(max(0, c - 8), c + 8) for c in jumps]
        elif args.windows == "all":
            wins = [(0, base_cycles)]
        else:
            wins = []
            for part in args.windows.split(","):
                a, _, b = part.partition("-")
                wins.append((int(a), int(b)))
        engset = set(args.engines.split(","))
        delays = [int(x) for x in args.delays.split(",")]
        in_window = [any(a <= c <= b for a, b in wins) for c in place0]
        candidates = [i for i in range(len(ops))
                      if in_window[i] and ops[i][0] in engset]
        print(f"windows: {wins}")
        print(f"candidates: {len(candidates)} ops, delays {delays}, "
              f"budget {args.budget}s, incumbent {base_cycles}")
        accepted: dict[int, int] = {}
        best = base_cycles
        best_place = place0
        t0 = time.time()
        tried = 0
        improved_log = []
        stop = False
        rounds_since_improve = 0
        while not stop:
            any_improve = False
            for i in candidates:
                if time.time() - t0 > args.budget:
                    stop = True
                    break
                for d in delays:
                    tgt = best_place[i] + d
                    if accepted.get(i, -1) == tgt:
                        continue
                    trial = dict(accepted)
                    trial[i] = tgt
                    place, n = greedy_schedule(ops, preds, floors,
                                               extra_floors=trial)
                    tried += 1
                    if n is not None and n < best:
                        accepted = trial
                        best = n
                        best_place = place
                        any_improve = True
                        improved_log.append((best, dict(accepted)))
                        print(f"  IMPROVED -> {best} cycles with "
                              f"{len(accepted)} floors after {tried} trials "
                              f"({time.time() - t0:.0f}s)")
                        with open(os.path.join(SCRATCH_DIR,
                                               "h51_incumbent.pkl"), "wb") as f:
                            pickle.dump({"cycles": best, "floors": accepted,
                                         "place": best_place}, f)
            if not any_improve:
                rounds_since_improve += 1
                if rounds_since_improve >= 1:
                    break
        print(f"search done: {tried} trials in {time.time() - t0:.0f}s; "
              f"best {best} (baseline {base_cycles})")
        if best < base_cycles:
            ok = check_feasible(ops, preds, floors, best_place)
            print(f"best schedule feasible={ok}; verifying on frozen grader...")
            res = reconstruct_and_verify(ops, best_place)
            print(json.dumps(res))
        return

    if args.cmd == "pairs":
        # Joint 2-deviation search (the discrepancy-2 slice of the bounded
        # backtrack): delay PAIRS of ops that both sit in the neighborhood
        # of the same regret-jump cycle. Covers improvements needing two
        # simultaneous deviations with no improving single step.
        place0 = [op[9] for op in ops]
        base_cycles = max(place0) + 1
        F, _, _ = regret_profile(ops, preds, floors, place0)
        jumps = []
        prev = 0
        for c in range(len(F)):
            if F[c] > prev and c > 0:
                jumps.append(c)
            prev = max(prev, F[c])
        engset = set(args.engines.split(","))
        rad = 3
        t0 = time.time()
        best = base_cycles
        tried = 0
        for jc in jumps:
            cand = [i for i in range(len(ops))
                    if abs(place0[i] - jc) <= rad and ops[i][0] in engset]
            print(f"jump c={jc}: {len(cand)} candidates "
                  f"({time.time() - t0:.0f}s, tried {tried})", flush=True)
            for ai in range(len(cand)):
                if time.time() - t0 > args.budget:
                    print("budget exhausted", flush=True)
                    break
                i = cand[ai]
                for bi in range(ai + 1, len(cand)):
                    j = cand[bi]
                    for di in (1, 2):
                        for dj in (1, 2):
                            trial = {i: place0[i] + di, j: place0[j] + dj}
                            place, n2 = greedy_schedule(ops, preds, floors,
                                                        extra_floors=trial)
                            tried += 1
                            if n2 is not None and n2 < best:
                                best = n2
                                print(f"  IMPROVED -> {best} with {trial}",
                                      flush=True)
                                with open(os.path.join(
                                        SCRATCH_DIR, "h51_incumbent.pkl"),
                                        "wb") as f:
                                    pickle.dump({"cycles": best,
                                                 "floors": trial,
                                                 "place": place}, f)
            else:
                continue
            break
        print(f"pairs done: {tried} trials in {time.time() - t0:.0f}s; "
              f"best {best} (baseline {base_cycles})")
        return

    if args.cmd == "probe":
        h = tails(ops, preds)
        est = ests(ops, preds, floors)
        place0, n0 = greedy_schedule(ops, preds, floors)
        print(f"greedy emission order: {n0}")
        for name, pr in [
            ("tail_height", h),
            ("est+tail (CP)", [e + t for e, t in zip(est, h)]),
            ("neg emission (sanity)", [-i for i in range(len(ops))]),
        ]:
            t0 = time.time()
            place, n = priority_schedule(ops, preds, floors, pr)
            ok = check_feasible(ops, preds, floors, place)
            print(f"priority {name}: {n} cycles feasible={ok} "
                  f"({time.time() - t0:.1f}s)")
        return


if __name__ == "__main__":
    main()
