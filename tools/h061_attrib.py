"""H-061: regret attribution on deliberately LOAD-BOUND streams.

Calls tools/backtrack_sched.py in-process (its H51_OVERRIDES patched to the
stream under test), then answers the one question the hypothesis needs:

  at every cycle where a load slot is empty, is the load engine
  SATURATED-elsewhere, or IDLE-BUT-BLOCKED -- and by what?

Because the offline model reproduces greedy exactly (validate), the logic is
airtight: greedy places each op at the earliest slot-feasible cycle >= its
dependency-ready cycle, so an empty load slot at cycle c means every load op
still unplaced at c had dep-ready > c.  For each such op we recover the
BINDING predecessor (the edge that set ready) and classify it:

  addr    RAW on a scratch word -> the gather's address/index computation
  mem-w   the coarse whole-memory write clock (mem_prime stores)
  war     WAR (someone still had to read the destination register)
  waw     WAW on the destination register (pool reuse / liveness)
  floor   an explicit min_cycle

Usage (repo root):
  python3 tools/h061_attrib.py census  [gmin ...]   # load idle/blocked census
  python3 tools/h061_attrib.py regret  <gmin>       # F-jumps + load context
  python3 tools/h061_attrib.py blockers <gmin>      # binding-edge histogram
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtrack_sched as B  # noqa: E402
import h061_common as C  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

ENGINES = B.ENGINES


def capture_stream(gmin: tuple[int, int] | None, rings: bool | None = None,
                   **extra: Any):
    """Capture the op stream for one config (patching B.H51_OVERRIDES)."""
    if rings is None:
        rings = gmin is None
    kw = C.kwargs(gmin, rings=rings, **extra)
    old = B.H51_OVERRIDES
    B.H51_OVERRIDES = {}
    try:
        data = B.capture(kw)
    finally:
        B.H51_OVERRIDES = old
    ops = data["ops"]
    preds, floors = B.build_model(ops, data["pair_writes"])
    return data, ops, preds, floors


def ready_and_bind(ops, preds, floors, place):
    """ready[i] and the binding predecessor index (or None)."""
    n = len(ops)
    ready = [0] * n
    bind = [None] * n
    for i in range(n):
        r = floors[i]
        b = None
        for j, lag in preds[i]:
            t = place[j] + lag
            if t > r:
                r, b = t, j
        ready[i] = r
        bind[i] = b
    return ready, bind


def edge_kind(ops, i, j) -> str:
    """Why does op i depend on op j?"""
    _, _, ri, wi, mri, mwi, *_ = ops[i]
    _, _, rj, wj, mrj, mwj, *_ = ops[j]
    si, swi = set(ri), set(wi)
    sj, swj = set(rj), set(wj)
    if swj & si:
        return "raw"
    if swj & swi:
        return "waw"
    if sj & swi:
        return "war"
    if mri and mwj:
        return "mem-w"
    if mwi and mrj:
        return "mem-r"
    if mwi and mwj:
        return "mem-ww"
    return "?"


def opname_of(op):
    """Human-readable opcode for an op tuple."""
    for x in op[1]:
        if isinstance(x, str):
            return x
    return str(op[1][0])


def occupancy(ops, place, n_cycles):
    occ = [dict.fromkeys(ENGINES, 0) for _ in range(n_cycles)]
    for i, c in enumerate(place):
        occ[c][ops[i][0]] += 1
    return occ


def load_census(label, ops, preds, floors, place) -> dict[str, Any]:
    n_cycles = max(place) + 1
    occ = occupancy(ops, place, n_cycles)
    ready, bind = ready_and_bind(ops, preds, floors, place)
    cap = SLOT_LIMITS["load"]

    load_idx = [i for i in range(len(ops)) if ops[i][0] == "load"]
    # per-cycle empty load slots, and whether any load op was dep-ready
    empty = 0
    idle_cycles = 0
    # sort load ops by ready to answer "was any unplaced load ready at c?"
    by_place = defaultdict(list)
    for i in load_idx:
        by_place[place[i]].append(i)
    remaining_ready = sorted((ready[i], i) for i in load_idx)
    # blocked histogram: for each empty-slot cycle, look at the load ops
    # placed at the NEXT non-empty position and classify what set their ready
    blockers: Counter[str] = Counter()
    blocker_tags: Counter[Any] = Counter()
    empty_by_region: Counter[str] = Counter()

    ptr = 0
    pend: list[tuple[int, int]] = []
    for c in range(n_cycles):
        free = cap - occ[c]["load"]
        if free <= 0:
            continue
        empty += free
        idle_cycles += 1
        # the earliest-ready unplaced load op(s) at this cycle
        cand = [i for i in load_idx if place[i] > c]
        if not cand:
            empty_by_region["drain"] += free
            continue
        if c < 60:
            empty_by_region["ramp"] += free
        else:
            empty_by_region["mid"] += free
        # nearest-ready unplaced ops explain the bubble
        cand.sort(key=lambda i: ready[i])
        for i in cand[:free]:
            j = bind[i]
            if j is None:
                blockers["floor"] += 1
            else:
                blockers[edge_kind(ops, i, j)] += 1
                blocker_tags[(ops[j][0], ops[j][1][0])] += 1

    slot_wait = [place[i] - ready[i] for i in load_idx]
    return {
        "label": label,
        "cycles": n_cycles,
        "load_slots": len(load_idx),
        "load_floor": -(-len(load_idx) // cap),
        "empty_load_slots": empty,
        "cycles_with_free_load": idle_cycles,
        "empty_by_region": dict(empty_by_region),
        "blocker_kinds": dict(blockers),
        "blocker_producers": {f"{e}:{o}": n
                              for (e, o), n in blocker_tags.most_common(8)},
        "load_slot_wait_mean": round(sum(slot_wait) / max(1, len(slot_wait)), 2),
        "load_at_dep_ready": sum(1 for w in slot_wait if w == 0),
        "engine_slots": {e: sum(1 for op in ops if op[0] == e) for e in ENGINES},
    }


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "census"
    args = sys.argv[2:]

    def parse(a):
        if a in ("main", "mainline"):
            return None
        return tuple(int(x) for x in a.split(","))

    if cmd == "census":
        for a in (args or ["main", "6,31", "16,31", "20,31", "24,31", "28,31"]):
            g = parse(a)
            data, ops, preds, floors = capture_stream(g)
            place = [op[9] for op in ops]
            pl, ne = B.greedy_schedule(ops, preds, floors)
            assert pl == place, f"model mismatch for {a}"
            print(json.dumps(load_census(a, ops, preds, floors, place)),
                  flush=True)
        return

    if cmd == "regret":
        a = args[0] if args else "main"
        g = parse(a)
        data, ops, preds, floors = capture_stream(g)
        place = [op[9] for op in ops]
        pl, ne = B.greedy_schedule(ops, preds, floors)
        print(json.dumps({"validate_exact": pl == place, "cycles": ne}))
        lb = B.lb_total(ops, preds, floors)
        print("LB:", json.dumps(lb))
        F, eng_lb, cp_lb = B.regret_profile(ops, preds, floors, place)
        occ = occupancy(ops, place, max(place) + 1)
        ready, bind = ready_and_bind(ops, preds, floors, place)
        print(f"cycles {max(place)+1}  LB {lb['lb']}  regret "
              f"{max(place)+1-lb['lb']}")
        prev = lb["lb"]
        for c in range(len(F)):
            if F[c] > prev:
                # load context at the jump
                nxt = [i for i in range(len(ops))
                       if ops[i][0] == "load" and place[i] > c]
                kinds: Counter[str] = Counter()
                for i in sorted(nxt, key=lambda i: ready[i])[:4]:
                    j = bind[i]
                    kinds[edge_kind(ops, i, j) if j is not None else "floor"] += 1
                tags = sorted({ops[i][10][0] for i in range(len(ops))
                               if place[i] == c and ops[i][10]})
                print(f"  c={c:>4} +{F[c]-prev} F={F[c]} engLB={eng_lb[c]} "
                      f"cpLB={cp_lb[c]} occ={ {e: occ[c][e] for e in ENGINES} } "
                      f"loadblock={dict(kinds)} rounds={tags}")
            prev = max(prev, F[c])
        return

    if cmd == "edges":
        # binding-edge kind over ALL load ops (not just bubble cycles):
        # what sets each gather's dependency-ready cycle?
        for a in (args or ["main", "20,31"]):
            g = parse(a)
            data, ops, preds, floors = capture_stream(g)
            place = [op[9] for op in ops]
            ready, bind = ready_and_bind(ops, preds, floors, place)
            kinds: Counter[str] = Counter()
            prod: Counter[str] = Counter()
            waits: Counter[str] = Counter()
            for i in range(len(ops)):
                if ops[i][0] != "load":
                    continue
                j = bind[i]
                k = "floor" if j is None else edge_kind(ops, i, j)
                kinds[k] += 1
                if j is not None:
                    prod[f"{ops[j][0]}:{ops[j][1][0]}"] += 1
                waits[k] += place[i] - ready[i]
            print(json.dumps({
                "label": a, "binding_edge_kinds": dict(kinds),
                "producers": dict(prod.most_common(6)),
                "slot_wait_by_kind": dict(waits),
            }))
        return

    if cmd == "blockers":
        a = args[0] if args else "main"
        g = parse(a)
        data, ops, preds, floors = capture_stream(g)
        place = [op[9] for op in ops]
        ready, bind = ready_and_bind(ops, preds, floors, place)
        occ = occupancy(ops, place, max(place) + 1)
        rows = []
        for c in range(max(place) + 1):
            free = SLOT_LIMITS["load"] - occ[c]["load"]
            if free:
                rows.append((c, free, occ[c]["valu"], occ[c]["alu"],
                             occ[c]["flow"]))
        print(f"free-load cycles: {len(rows)}  free slots "
              f"{sum(r[1] for r in rows)}")
        # compress into runs
        runs = []
        for c, free, v, al, fl in rows:
            if runs and c == runs[-1][1] + 1:
                runs[-1][1] = c
                runs[-1][2] += free
            else:
                runs.append([c, c, free])
        print(f"runs: {len(runs)}")
        for lo, hi, tot in runs:
            if tot >= 4:
                print(f"  [{lo}..{hi}] free={tot}")
        return

    raise SystemExit(f"unknown cmd {cmd}")


if __name__ == "__main__":
    main()
