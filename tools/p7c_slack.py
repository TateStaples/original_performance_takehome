"""P7-C: where do the 11 cycles between realized 1006 and the valu slot
floor 995 live? Per-cycle engine occupancy of the shipped 1006 program.
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402

LIM = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1}


def main() -> None:
    kb, prog = C.build(C.frontier())
    n = len(prog)
    occ = [{e: len(instr.get(e, ())) for e in LIM} for instr in prog]
    print(f"bundles={n} floors={C.floors(prog)}")
    for e in LIM:
        deficit = sum(LIM[e] - o[e] for o in occ)
        full = sum(1 for o in occ if o[e] >= LIM[e])
        empty = sum(1 for o in occ if o[e] == 0)
        print(f"{e:6s} full_cycles={full:5d} idle_cycles={empty:5d} "
              f"unused_slots={deficit:6d}")
    # valu deficit by region
    print("\nvalu occupancy histogram:", dict(Counter(o["valu"] for o in occ)))
    under = [i for i, o in enumerate(occ) if o["valu"] < 6]
    print(f"valu-underfull cycles: {len(under)}  first20={under[:20]}")
    print(f"                        last20={under[-20:]}")
    # where the underfull cycles cluster
    buckets = Counter(i // 100 for i in under)
    print("underfull by 100-cycle bucket:",
          {f"{k*100}-{k*100+99}": v for k, v in sorted(buckets.items())})
    tot_missing = sum(6 - occ[i]["valu"] for i in under)
    print(f"total missing valu slots = {tot_missing} "
          f"(=> {tot_missing/6:.1f} cycles' worth)")


if __name__ == "__main__":
    main()
