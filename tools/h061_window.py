"""H-061: per-cycle window dump around the load bubbles.

Prints, for a cycle range, every engine's occupancy plus what the load
engine was waiting on (the earliest-ready unplaced load op, its binding
predecessor and that predecessor's engine/opcode/tag).

Usage: python3 tools/h061_window.py <gmin|main> <lo> <hi> [--loads]
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def opname(op):
    slot = op[1]
    for x in slot:
        if isinstance(x, str):
            return x
    return str(slot[0])


def main() -> None:
    a = sys.argv[1] if len(sys.argv) > 1 else "main"
    lo = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3]) if len(sys.argv) > 3 else 80
    g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
    data, ops, preds, floors = A.capture_stream(g)
    place = [op[9] for op in ops]
    ready, bind = A.ready_and_bind(ops, preds, floors, place)
    occ = A.occupancy(ops, place, max(place) + 1)
    load_idx = [i for i in range(len(ops)) if ops[i][0] == "load"]

    print(f"== {a}: cycles {max(place)+1}, window [{lo},{hi}) ==")
    print(f"{'cyc':>5} {'valu':>4} {'alu':>4} {'load':>4} {'flow':>4} {'st':>3}"
          f"   next-load(ready, blocked-by)")
    for c in range(lo, min(hi, max(place) + 1)):
        cand = [i for i in load_idx if place[i] > c]
        note = ""
        if cand and occ[c]["load"] < SLOT_LIMITS["load"]:
            i = min(cand, key=lambda i: ready[i])
            j = bind[i]
            if j is None:
                note = f"load@{place[i]} ready={ready[i]} floor"
            else:
                note = (f"{opname(ops[i])}@{place[i]} ready={ready[i]} "
                        f"<- {A.edge_kind(ops, i, j)} {ops[j][0]}:{opname(ops[j])}"
                        f"@{place[j]} tag={ops[j][10]}")
        print(f"{c:>5} {occ[c]['valu']:>4} {occ[c]['alu']:>4} "
              f"{occ[c]['load']:>4} {occ[c]['flow']:>4} {occ[c]['store']:>3}"
              f"   {note}")

    # summary of what the loads in the window are
    kinds: Counter[str] = Counter()
    for i in load_idx:
        if lo <= place[i] < hi:
            kinds[f"{opname(ops[i])}|tag={ops[i][10]}"] += 1
    print("\nloads placed in window (top 12):")
    for k, n in kinds.most_common(12):
        print(f"  {n:>4}  {k}")


if __name__ == "__main__":
    main()
