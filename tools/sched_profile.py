"""
H-021 scheduler-strain friction profiler.

The mainline kernel runs ~26 cycles above its valu op-mix floor
(slots/6). This tool explains WHERE those cycles live and WHY each
partially-empty valu cycle could not be filled, using the default-off
placement trace in ListScheduler (perf_takehome.py):

  1. Build the kernel (mainline config or --set overrides) with
     `kb.sched_trace = []`, capturing every put() as
     (cycle, engine, tag, slot, reads, writes, mem_read, mem_write),
     where tag = (round, group) inside emit_group_round, None for setup
     and the final stores.
  2. Replay the trace in emission order re-deriving each op's dependency
     ready-time and its BINDING hazard (RAW/WAW/WAR + address + producer
     op). Because the scheduler is greedy earliest-feasible in program
     order, an empty valu slot at cycle c means every valu op placed
     later had dep_ready > c at its emission -- so the ops placed just
     after a gap, and their binding producers, are exactly what the gap
     was waiting on.
  3. Aggregate: gap location (setup ramp / steady state / drain tail,
     rounds-in-flight label), binding-hazard kinds, producer engines,
     and blocked-op opcodes. Optional per-gap-cycle detail and a
     timeline dump for eyeballing.

Usage (repo root):
    python tools/sched_profile.py                       # mainline config
    python tools/sched_profile.py --set skew=8,2        # any variant
    python tools/sched_profile.py --detail 40           # per-gap lines
    python tools/sched_profile.py --timeline /tmp/t.txt # per-cycle dump
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

# dev.py keeps the flag-configurable build_kernel_scheduled + sched_trace
# hook this profiler needs; perf_takehome.py is the flag-free submission.
from dev import KernelBuilder  # noqa: E402
from problem import SLOT_LIMITS, VLEN  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402


def build_traced_kernel(
    overrides: dict[str, Any] | None = None,
) -> tuple[KernelBuilder, dict[str, Any]]:
    kwargs = dict(BASE_KWARGS, **(overrides or {}))
    kb = KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(
        SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs
    )
    return kb, kwargs


def build_scratch_name_lookup(kb: KernelBuilder) -> Callable[[int], str | None]:
    """addr -> scratch block name (None for pool temps / anon broadcasts)."""
    blocks = sorted((a, n, ln) for a, (n, ln) in kb.scratch_debug.items())

    def lookup(addr: int) -> str | None:
        lo, hi = 0, len(blocks)
        while lo < hi:
            mid = (lo + hi) // 2
            if blocks[mid][0] <= addr:
                lo = mid + 1
            else:
                hi = mid
        if lo:
            base, name, ln = blocks[lo - 1]
            if addr < base + ln:
                return name
        return None

    return lookup


def classify_scratch_name(name: str | None) -> str:
    if name is None:
        return "pool/anon"
    for prefix in ("val", "st", "nv", "va", "rec"):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return prefix
    return name


def replay(
    trace: list[tuple[Any, ...]],
) -> list[tuple[int, tuple[str, int | None, int | None]]]:
    """Re-derive each op's ready_cycle and binding hazard, in emission
    order (trace order == put order == the order the scheduler saw)."""
    last_write: dict[int, tuple[int, int]] = {}  # addr -> (cycle, op_idx)
    last_read: dict[int, tuple[int, int]] = {}
    last_mem_write: tuple[int, int | None] = (-1, None)
    last_mem_read: tuple[int, int | None] = (-1, None)
    replay_info: list[tuple[int, tuple[str, int | None, int | None]]] = []
    for idx, (c, engine, tag, slot, reads, writes, mem_read, mem_write) in enumerate(trace):
        ready_cycle = 0
        binding_hazard: tuple[str, int | None, int | None] = ("none", None, None)  # kind, addr, producer idx
        for a in reads:
            t = last_write.get(a)
            if t is not None and t[0] + 1 > ready_cycle:
                ready_cycle = t[0] + 1
                binding_hazard = ("RAW", a, t[1])
        for a in writes:
            t = last_write.get(a)
            if t is not None and t[0] + 1 > ready_cycle:
                ready_cycle = t[0] + 1
                binding_hazard = ("WAW", a, t[1])
            t = last_read.get(a)
            if t is not None and t[0] > ready_cycle:
                ready_cycle = t[0]
                binding_hazard = ("WAR", a, t[1])
        if mem_read and last_mem_write[0] + 1 > ready_cycle:
            ready_cycle = last_mem_write[0] + 1
            binding_hazard = ("MEM-RAW", None, last_mem_write[1])
        if mem_write:
            if last_mem_write[0] + 1 > ready_cycle:
                ready_cycle = last_mem_write[0] + 1
                binding_hazard = ("MEM-WAW", None, last_mem_write[1])
            if last_mem_read[0] > ready_cycle:
                ready_cycle = last_mem_read[0]
                binding_hazard = ("MEM-WAR", None, last_mem_read[1])
        replay_info.append((ready_cycle, binding_hazard))
        for a in reads:
            t = last_read.get(a)
            if t is None or t[0] < c:
                last_read[a] = (c, idx)
        for a in writes:
            last_write[a] = (c, idx)
        if mem_read and last_mem_read[0] < c:
            last_mem_read = (c, idx)
        if mem_write and last_mem_write[0] < c:
            last_mem_write = (c, idx)
    return replay_info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--detail", type=int, default=0,
                    help="print the N largest per-cycle gaps with blockers")
    ap.add_argument("--timeline", default=None,
                    help="write a per-cycle occupancy/tag dump to this path")
    args = ap.parse_args()

    overrides: dict[str, Any] = {}
    for override_arg in args.set:
        key, _, val = override_arg.partition("=")
        overrides[key] = parse_value(val)

    kb, kwargs = build_traced_kernel(overrides)
    trace = kb.sched_trace
    lookup = build_scratch_name_lookup(kb)
    period = SHAPE["forest_height"] + 1

    span = max(trace_entry[0] for trace_entry in trace) + 1
    occupancy = [dict.fromkeys(SLOT_LIMITS, 0) for _ in range(span)]
    cycle_tags = [set() for _ in range(span)]  # (r, g) tags of ops in cycle
    valu_ops_at: defaultdict[int, list[int]] = defaultdict(list)  # cycle -> [op_idx] (valu only)
    for idx, (c, engine, tag, slot, *_rest) in enumerate(trace):
        occupancy[c][engine] += 1
        if tag is not None and isinstance(tag, tuple):
            cycle_tags[c].add(tag)
        if engine == "valu":
            valu_ops_at[c].append(idx)

    nonempty = [c for c in range(span) if any(occupancy[c].values())]
    n_cycles = len(nonempty)
    valu_slots = sum(cycle_occupancy["valu"] for cycle_occupancy in occupancy)
    floor = -(-valu_slots // SLOT_LIMITS["valu"])
    # empty valu slots on cycles that exist in the final stream
    empty = {c: SLOT_LIMITS["valu"] - occupancy[c]["valu"]
             for c in nonempty if occupancy[c]["valu"] < SLOT_LIMITS["valu"]}

    print(f"config overrides: {overrides or '(mainline)'}")
    print(f"machine cycles (non-empty bundles): {n_cycles}   "
          f"scheduler span: {span}   dropped-empty: {span - n_cycles}")
    print(f"valu slots: {valu_slots}   floor ceil(/6): {floor}   "
          f"friction: {n_cycles - floor} cycles   "
          f"empty valu slots: {sum(empty.values())} "
          f"over {len(empty)} gap cycles")

    hist = Counter(occupancy[c]["valu"] for c in nonempty)
    print("\n== valu occupancy histogram (non-empty cycles) ==")
    for k in range(SLOT_LIMITS["valu"] + 1):
        print(f"  {k}/6: {hist.get(k, 0):>5}")

    # --- locate the gaps -------------------------------------------------
    tagged_cycles = [c for c in range(span) if cycle_tags[c]]
    first_tag_c, last_tag_c = tagged_cycles[0], tagged_cycles[-1]

    def region(c: int) -> str:
        if c < first_tag_c:
            return "setup-ramp"
        if c > last_tag_c:
            return "store-drain"
        if not cycle_tags[c]:
            return "untagged"
        rounds_here = sorted({t[0] for t in cycle_tags[c]})
        lv = sorted({r % period for r in rounds_here})
        return f"r{rounds_here[0]}-{rounds_here[-1]} L{','.join(map(str, lv))}"

    by_region: Counter[str] = Counter()
    for c, empty_slots in empty.items():
        by_region[region(c)] += empty_slots
    print("\n== empty valu slots by region (rounds in flight, levels) ==")
    for region_label, empty_slots in by_region.most_common():
        print(f"  {empty_slots:>4}  {region_label}")

    # --- why: replay deps, find blockers ---------------------------------
    replay_info = replay(trace)

    def op_desc(idx: int) -> str:
        c, engine, tag, slot, *_ = trace[idx]
        return f"{engine}:{slot[0]}@{c}{'' if tag is None else f' rg{tag}'}"

    # For each gap cycle, the valu ops placed in the next cycles are the
    # frontier that COULD have filled it were their deps ready.
    hazard_kind_weight: Counter[str] = Counter()   # binding hazard kind, weighted by empty slots
    producer_weight: Counter[str] = Counter()   # producer engine:opcode
    addr_class_weight: Counter[str] = Counter()   # blocked-on address class
    blocked_opcode_weight: Counter[str] = Counter()  # blocked op opcode
    details: list[tuple[int, int, list[tuple[Any, ...]]]] = []
    for c, empty_slots in sorted(empty.items()):
        frontier: list[int] = []
        for cc in range(c + 1, min(c + 4, span)):
            frontier = valu_ops_at.get(cc, [])
            if frontier:
                break
        reasons: list[tuple[Any, ...]] = []
        for idx in frontier[:6]:
            ready_cycle, (kind, addr, producer_idx) = replay_info[idx]
            addr_class = classify_scratch_name(lookup(addr)) if addr is not None else "mem"
            pdesc = op_desc(producer_idx) if producer_idx is not None else "-"
            producer_engine = trace[producer_idx][1] if producer_idx is not None else "-"
            producer_opcode = trace[producer_idx][3][0] if producer_idx is not None else "-"
            reasons.append((kind, addr_class, f"{producer_engine}:{producer_opcode}",
                            trace[idx][3][0], idx, producer_idx, ready_cycle))
        weight = empty_slots / max(len(reasons), 1)
        # typeshed types Counter values as int, but these accumulate float
        # weights; the runtime is unaffected. type: ignore is the narrow fix.
        for kind, addr_class, producer_desc, blocked_opcode, *_ in reasons:
            hazard_kind_weight[kind] += weight  # type: ignore[arg-type]
            producer_weight[producer_desc] += weight  # type: ignore[arg-type]
            addr_class_weight[addr_class] += weight  # type: ignore[arg-type]
            blocked_opcode_weight[blocked_opcode] += weight  # type: ignore[arg-type]
        details.append((empty_slots, c, reasons))

    print("\n== gap blocker attribution (weighted by empty slots) ==")
    print("hazard kinds:")
    for k, weight in hazard_kind_weight.most_common():
        print(f"  {weight:>7.1f}  {k}")
    print("producer (engine:opcode of the op the frontier waits on):")
    for k, weight in producer_weight.most_common(12):
        print(f"  {weight:>7.1f}  {k}")
    print("blocked-on address class:")
    for k, weight in addr_class_weight.most_common(12):
        print(f"  {weight:>7.1f}  {k}")
    print("blocked valu opcode (the op that just missed the gap):")
    for k, weight in blocked_opcode_weight.most_common(12):
        print(f"  {weight:>7.1f}  {k}")

    if args.detail:
        print(f"\n== {args.detail} largest gap cycles ==")
        for empty_slots, c, reasons in sorted(details, reverse=True)[: args.detail]:
            print(f"cycle {c}: {empty_slots} empty  region={region(c)}  "
                  f"occupancy={ {k: occupancy[c][k] for k in SLOT_LIMITS} }")
            for kind, addr_class, producer_desc, blocked_opcode, idx, producer_idx, ready_cycle in reasons[:4]:
                print(f"    valu:{blocked_opcode} rg{trace[idx][2]} ready@{ready_cycle} "
                      f"{kind} on {addr_class} <- {op_desc(producer_idx) if producer_idx is not None else '-'}")

    if args.timeline:
        with open(args.timeline, "w") as f:
            for c in range(span):
                cycle_occupancy = occupancy[c]
                tags = sorted(cycle_tags[c])
                rounds_here = sorted({t[0] for t in tags})
                f.write(
                    f"{c:>5} valu={cycle_occupancy['valu']} alu={cycle_occupancy['alu']:>2} "
                    f"load={cycle_occupancy['load']} flow={cycle_occupancy['flow']} store={cycle_occupancy['store']} "
                    f"| r={rounds_here} tags={len(tags)}\n"
                )
        print(f"\ntimeline written to {args.timeline}")


if __name__ == "__main__":
    main()
