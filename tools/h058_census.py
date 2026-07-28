"""H-058: exact fungibility census of the 1006 mainline.

Phase-2 needs the 1006 op multiset decomposed the way the capacity algebra
sees it, not the way the purpose report prints it:

  * plain  lane-ops -- 1 alu slot per lane OR 1 valu slot per 8 lanes
  * madd   lane-ops -- 1 valu slot per 8 lanes fused; 2 alu slots per lane
  * scalar-only alu slots (const/setup/bookkeeping with no vector form)
  * select lane-ops  -- additionally flow-eligible at 8 lanes / flow slot
  * load / store / flow-misc slots

plus the scratch ledger (words by allocation class) and the per-level
serving/gather/prime census derived from the shipped config.

Read-only: imports `tools/diagnose_kernel.py`'s classifier and
`perf_takehome.KernelBuilder`; modifies nothing.

Usage (repo root): python3 tools/h058_census.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from typing import cast

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagnose_kernel as D  # noqa: E402
from problem import VLEN  # noqa: E402

# Problem shape (graded): 2,047-node forest, 256 walkers = 32 groups of 8,
# 16 rounds, level of round r = r mod 11.
PERIOD = 11
ROUNDS = 16
N_GROUPS = 32
# group-rounds per level: levels 0-4 appear in rounds d and d+11 -> 64.
GD = {d: (64 if d <= 4 else 32) for d in range(PERIOD)}


def main() -> None:
    kb = D.build_diagnostic_kernel()
    lookup = D.named_range_lookup(kb)
    cycles = len(kb.instrs)

    cross: Counter[tuple[str, str, str]] = Counter()   # purpose, engine, opcode
    for bundle in kb.instrs:
        for engine, slots in bundle.items():
            if engine == "debug":
                continue
            for slot in slots:
                cross[(D.classify(engine, slot, lookup), engine,
                       D.opcode_key(engine, slot[0]))] += 1

    print(f"== H-058 census @ {cycles} cycles ==\n")
    print(f"{'purpose':<9}{'engine':<7}{'opcode':<14}{'slots':>7}{'lane-ops':>10}")
    for (purpose, engine, op), n in sorted(cross.items()):
        lanes = n * (VLEN if engine in ("valu", "flow")
                     and op not in ("pause", "add_imm") else 1)
        print(f"{purpose:<9}{engine:<7}{op:<14}{n:>7}{lanes:>10}")

    # ---- fungibility decomposition -------------------------------------
    plain = madd = 0          # lane-ops
    scalar_only = 0           # alu slots with no vector form
    sel_slots = 0             # flow vselect slots (8 lanes of selection)
    loads = stores = flow_misc = 0
    bcast_lanes = 0
    for (purpose, engine, op), n in cross.items():
        if engine == "alu":
            plain += n
        elif engine == "valu":
            if op == "multiply_add":
                madd += VLEN * n
            elif op == "vbroadcast":
                bcast_lanes += VLEN * n
            else:
                plain += VLEN * n
        elif engine == "load":
            loads += n
            if op == "const":
                scalar_only += 0     # const is a load slot, not alu
        elif engine == "store":
            stores += n
        elif engine == "flow":
            if op == "vselect":
                sel_slots += n
            else:
                flow_misc += n

    print("\n== fungibility decomposition (measured) ==")
    print(f"plain lane-ops        {plain:>7}   (1 alu slot/lane | 1 valu slot/8 lanes)")
    print(f"madd  lane-ops        {madd:>7}   (1 valu slot/8 lanes | 2 alu slots/lane)")
    print(f"vbroadcast lane-ops   {bcast_lanes:>7}   (valu-only in practice; 8 alu copies/lane-set)")
    print(f"scalar-only alu slots {scalar_only:>7}")
    print(f"flow vselect slots    {sel_slots:>7}   (= {sel_slots * VLEN} lane-ops of selection)")
    print(f"flow misc slots       {flow_misc:>7}")
    print(f"load slots            {loads:>7}")
    print(f"store slots           {stores:>7}")
    total_av = plain + madd + bcast_lanes
    print(f"\nalu+valu lane-ops TOTAL {total_av}  "
          f"(capacity/cyc 60 -> combined floor {total_av / 60:.1f})")

    # ---- serving census, derived from the shipped predicates ------------
    # perf_takehome ships: tournament_level_count=3 (L0-L3 fully served),
    # L4 = 4 served for g >= l4_gmin[epoch], mem-primed in place; L5 primed
    # via primed_gather_levels; L6-L10 raw gathers.
    src = open(os.path.join(REPO_ROOT, "perf_takehome.py")).read()
    gmin = None
    for line in src.splitlines():
        if "l4_gmin" in line and "=" in line and "def " not in line and "(" in line:
            gmin = line.strip()
            break
    print("\n== serving census (levels x group-rounds) ==")
    print(f"config line: {gmin}")
    gath = defaultdict(int)
    served = defaultdict(int)
    for r in range(ROUNDS):
        d = r % PERIOD
        for g in range(N_GROUPS):
            if d <= 3:
                served[d] += 1
            elif d == 4:
                # threshold read below from the emitted load count
                pass
            else:
                gath[d] += 1
    n_gather_loads = sum(n for (p, e, o), n in cross.items()
                         if e == "load" and o == "load")
    gathered_grp_rounds = n_gather_loads // VLEN
    l4_total = GD[4]
    l4_gathered = gathered_grp_rounds - sum(gath.values())
    print(f"gather loads {n_gather_loads} -> {gathered_grp_rounds} gathered group-rounds")
    print(f"  L5-L10 gathered: {sum(gath.values())}   L4 gathered: {l4_gathered}"
          f" / {l4_total}  (L4 served {l4_total - l4_gathered})")
    print(f"  served w/o load: L0 {GD[0]}, L1 {GD[1]}, L2 {GD[2]}, L3 {GD[3]},"
          f" L4 {l4_total - l4_gathered}"
          f"  = {GD[0] + GD[1] + GD[2] + GD[3] + l4_total - l4_gathered}")
    print(f"  total group-rounds {sum(GD.values())}")

    # ---- scratch ledger --------------------------------------------------
    print("\n== scratch ledger ==")
    words = Counter()
    named = 0
    for addr, (name, length) in kb.scratch_debug.items():
        base = name.rstrip("0123456789")
        words[base] += length
        named += length
    print(f"scratch_next_addr {kb.scratch_next_addr} / 1536"
          f"  (named {named}, anonymous pools {kb.scratch_next_addr - named})")
    for base, n in words.most_common(20):
        print(f"  {base:<14}{n:>6}")


if __name__ == "__main__":
    main()


def defuse() -> None:
    """Exact def-use split of the ambiguous buckets.

    Two numbers decide the whole 940 arithmetic and the purpose report
    cannot separate them:
      * how many valu multiply_adds are GATHER-ADDRESS COMBINES vs
        TOURNAMENT FOLDS (both land in the Routing bucket), and
      * how many flow vselects are tournament folds vs index/boundary
        selects (H-029) that serve no table at all.
    Resolved by walking the program in order, tracking the last writer of
    every scratch word, and asking what each gather's address operand and
    each vselect's operands actually are.
    """
    kb = D.build_diagnostic_kernel()
    lookup = D.named_range_lookup(kb)

    last: dict[int, tuple[str, str]] = {}     # addr -> (engine, opcode)
    addr_producer: Counter[tuple[str, str]] = Counter()
    sel_kind: Counter[str] = Counter()
    n_gather = 0
    for bundle in kb.instrs:
        writes_this_cycle = []
        for engine, slots in bundle.items():
            if engine == "debug":
                continue
            for slot in slots:
                reads, writes = D.slot_operands(engine, slot)
                if engine == "load" and slot[0] == "load":
                    n_gather += 1
                    addr_producer[last.get(slot[2], ("?", "?"))] += 1
                if engine == "flow" and slot[0] == "vselect":
                    names = {lookup(a) for a in reads} | {lookup(a) for a in writes}
                    # cast: `- {None}` drops the Nones but pyright cannot
                    # narrow a set difference's element type (same pattern as
                    # diagnose_kernel.classify); output-neutral.
                    names = cast("set[str]", names - {None})
                    if any(n.startswith("st") for n in names):
                        sel_kind["idx/boundary select (touches st)"] += 1
                    elif any(n.startswith("nv") for n in names):
                        sel_kind["fold writing nv (final tournament fold)"] += 1
                    else:
                        sel_kind["tournament fold (pools/tables only)"] += 1
                writes_this_cycle.append((writes, engine,
                                          D.opcode_key(engine, slot[0])))
        for writes, engine, op in writes_this_cycle:
            for w in writes:
                last[w] = (engine, op)

    print("\n== def-use: what produces each gather address ==")
    print(f"gathers {n_gather}")
    for k, n in addr_producer.most_common():
        print(f"  {k[0]:<6}{k[1]:<16}{n:>6}  ({n / VLEN:.0f} group-rounds)")
    print("\n== def-use: flow vselect kinds ==")
    for k, n in sel_kind.most_common():
        print(f"  {k:<44}{n:>6}")
