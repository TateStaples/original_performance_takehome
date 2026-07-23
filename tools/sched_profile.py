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

import argparse
import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from perf_takehome import KernelBuilder  # noqa: E402
from problem import SLOT_LIMITS, VLEN  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402


def build(overrides=None):
    kwargs = dict(BASE_KWARGS, **(overrides or {}))
    kb = KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(
        SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs
    )
    return kb, kwargs


def named_lookup(kb):
    """addr -> scratch block name (None for pool temps / anon broadcasts)."""
    blocks = sorted((a, n, ln) for a, (n, ln) in kb.scratch_debug.items())

    def lookup(addr):
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


def name_class(name):
    if name is None:
        return "pool/anon"
    for pfx in ("val", "st", "nv", "va", "rec"):
        if name.startswith(pfx) and name[len(pfx):].isdigit():
            return pfx
    return name


def replay(trace):
    """Re-derive each op's dep ready-time and binding hazard, in emission
    order (trace order == put order == the order the scheduler saw)."""
    lw = {}  # addr -> (cycle, op_idx)
    lr = {}
    mem_w = (-1, None)
    mem_r = (-1, None)
    info = []
    for idx, (c, engine, tag, slot, reads, writes, m_r, m_w) in enumerate(trace):
        dep = 0
        bind = ("none", None, None)  # kind, addr, producer idx
        for a in reads:
            t = lw.get(a)
            if t is not None and t[0] + 1 > dep:
                dep = t[0] + 1
                bind = ("RAW", a, t[1])
        for a in writes:
            t = lw.get(a)
            if t is not None and t[0] + 1 > dep:
                dep = t[0] + 1
                bind = ("WAW", a, t[1])
            t = lr.get(a)
            if t is not None and t[0] > dep:
                dep = t[0]
                bind = ("WAR", a, t[1])
        if m_r and mem_w[0] + 1 > dep:
            dep = mem_w[0] + 1
            bind = ("MEM-RAW", None, mem_w[1])
        if m_w:
            if mem_w[0] + 1 > dep:
                dep = mem_w[0] + 1
                bind = ("MEM-WAW", None, mem_w[1])
            if mem_r[0] > dep:
                dep = mem_r[0]
                bind = ("MEM-WAR", None, mem_r[1])
        info.append((dep, bind))
        for a in reads:
            t = lr.get(a)
            if t is None or t[0] < c:
                lr[a] = (c, idx)
        for a in writes:
            lw[a] = (c, idx)
        if m_r and mem_r[0] < c:
            mem_r = (c, idx)
        if m_w and mem_w[0] < c:
            mem_w = (c, idx)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--detail", type=int, default=0,
                    help="print the N largest per-cycle gaps with blockers")
    ap.add_argument("--timeline", default=None,
                    help="write a per-cycle occupancy/tag dump to this path")
    args = ap.parse_args()

    overrides = {}
    for item in args.set:
        key, _, val = item.partition("=")
        overrides[key] = parse_value(val)

    kb, kwargs = build(overrides)
    trace = kb.sched_trace
    lookup = named_lookup(kb)
    period = SHAPE["forest_height"] + 1

    span = max(e[0] for e in trace) + 1
    occ = [dict.fromkeys(SLOT_LIMITS, 0) for _ in range(span)]
    cyc_tags = [set() for _ in range(span)]  # (r, g) tags of ops in cycle
    valu_ops_at = defaultdict(list)  # cycle -> [op_idx] (valu only)
    for idx, (c, engine, tag, slot, *_rest) in enumerate(trace):
        occ[c][engine] += 1
        if tag is not None and isinstance(tag, tuple):
            cyc_tags[c].add(tag)
        if engine == "valu":
            valu_ops_at[c].append(idx)

    nonempty = [c for c in range(span) if any(occ[c].values())]
    n_cycles = len(nonempty)
    valu_slots = sum(o["valu"] for o in occ)
    floor = -(-valu_slots // SLOT_LIMITS["valu"])
    # empty valu slots on cycles that exist in the final stream
    empty = {c: SLOT_LIMITS["valu"] - occ[c]["valu"]
             for c in nonempty if occ[c]["valu"] < SLOT_LIMITS["valu"]}

    print(f"config overrides: {overrides or '(mainline)'}")
    print(f"machine cycles (non-empty bundles): {n_cycles}   "
          f"scheduler span: {span}   dropped-empty: {span - n_cycles}")
    print(f"valu slots: {valu_slots}   floor ceil(/6): {floor}   "
          f"friction: {n_cycles - floor} cycles   "
          f"empty valu slots: {sum(empty.values())} "
          f"over {len(empty)} gap cycles")

    hist = Counter(occ[c]["valu"] for c in nonempty)
    print("\n== valu occupancy histogram (non-empty cycles) ==")
    for k in range(SLOT_LIMITS["valu"] + 1):
        print(f"  {k}/6: {hist.get(k, 0):>5}")

    # --- locate the gaps -------------------------------------------------
    tagged_cycles = [c for c in range(span) if cyc_tags[c]]
    first_tag_c, last_tag_c = tagged_cycles[0], tagged_cycles[-1]

    def region(c):
        if c < first_tag_c:
            return "setup-ramp"
        if c > last_tag_c:
            return "store-drain"
        if not cyc_tags[c]:
            return "untagged"
        rounds_here = sorted({t[0] for t in cyc_tags[c]})
        lv = sorted({r % period for r in rounds_here})
        return f"r{rounds_here[0]}-{rounds_here[-1]} L{','.join(map(str, lv))}"

    by_region = Counter()
    for c, e in empty.items():
        by_region[region(c)] += e
    print("\n== empty valu slots by region (rounds in flight, levels) ==")
    for reg, e in by_region.most_common():
        print(f"  {e:>4}  {reg}")

    # --- why: replay deps, find blockers ---------------------------------
    info = replay(trace)

    def op_desc(idx):
        c, engine, tag, slot, *_ = trace[idx]
        return f"{engine}:{slot[0]}@{c}{'' if tag is None else f' rg{tag}'}"

    # For each gap cycle, the valu ops placed in the next cycles are the
    # frontier that COULD have filled it were their deps ready.
    kind_cnt = Counter()   # binding hazard kind, weighted by empty slots
    prod_cnt = Counter()   # producer engine:opcode
    addr_cnt = Counter()   # blocked-on address class
    blocked_cnt = Counter()  # blocked op opcode
    details = []
    for c, e in sorted(empty.items()):
        frontier = []
        for cc in range(c + 1, min(c + 4, span)):
            frontier = valu_ops_at.get(cc, [])
            if frontier:
                break
        reasons = []
        for idx in frontier[:6]:
            dep, (kind, addr, prod) = info[idx]
            aname = name_class(lookup(addr)) if addr is not None else "mem"
            pdesc = op_desc(prod) if prod is not None else "-"
            ptag_eng = trace[prod][1] if prod is not None else "-"
            popc = trace[prod][3][0] if prod is not None else "-"
            reasons.append((kind, aname, f"{ptag_eng}:{popc}",
                            trace[idx][3][0], idx, prod, dep))
        w = e / max(len(reasons), 1)
        for kind, aname, peng, bopc, *_ in reasons:
            kind_cnt[kind] += w
            prod_cnt[peng] += w
            addr_cnt[aname] += w
            blocked_cnt[bopc] += w
        details.append((e, c, reasons))

    print("\n== gap blocker attribution (weighted by empty slots) ==")
    print("hazard kinds:")
    for k, v in kind_cnt.most_common():
        print(f"  {v:>7.1f}  {k}")
    print("producer (engine:opcode of the op the frontier waits on):")
    for k, v in prod_cnt.most_common(12):
        print(f"  {v:>7.1f}  {k}")
    print("blocked-on address class:")
    for k, v in addr_cnt.most_common(12):
        print(f"  {v:>7.1f}  {k}")
    print("blocked valu opcode (the op that just missed the gap):")
    for k, v in blocked_cnt.most_common(12):
        print(f"  {v:>7.1f}  {k}")

    if args.detail:
        print(f"\n== {args.detail} largest gap cycles ==")
        for e, c, reasons in sorted(details, reverse=True)[: args.detail]:
            print(f"cycle {c}: {e} empty  region={region(c)}  "
                  f"occ={ {k: occ[c][k] for k in SLOT_LIMITS} }")
            for kind, aname, peng, bopc, idx, prod, dep in reasons[:4]:
                print(f"    valu:{bopc} rg{trace[idx][2]} ready@{dep} "
                      f"{kind} on {aname} <- {op_desc(prod) if prod is not None else '-'}")

    if args.timeline:
        with open(args.timeline, "w") as f:
            for c in range(span):
                o = occ[c]
                tags = sorted(cyc_tags[c])
                rounds_here = sorted({t[0] for t in tags})
                f.write(
                    f"{c:>5} valu={o['valu']} alu={o['alu']:>2} "
                    f"load={o['load']} flow={o['flow']} store={o['store']} "
                    f"| r={rounds_here} tags={len(tags)}\n"
                )
        print(f"\ntimeline written to {args.timeline}")


if __name__ == "__main__":
    main()
