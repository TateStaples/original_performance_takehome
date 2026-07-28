"""H-061: the PHASE profile -- per-engine idleness banded over the schedule.

The load regret is not uniform: the head is compute-saturated with an idle
load engine, the middle is triple-saturated, the tail drains.  This prints
the per-engine empty-slot count in bands so the phase mismatch is visible,
and (`x`) cross-tabulates: how many cycles have load idle while valu is
full, and vice versa.

Usage: python3 tools/h061_phase.py [gmin ...]
       python3 tools/h061_phase.py x [gmin ...]
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

BANDS = 20
ENG = ("valu", "alu", "load", "flow")


def profile(a: str) -> None:
    g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
    data, ops, preds, floors = A.capture_stream(g)
    place = [op[9] for op in ops]
    n = max(place) + 1
    occ = A.occupancy(ops, place, n)
    print(f"== {a}: {n} cycles ==")
    print(f"{'band':>12} " + " ".join(f"{e:>12}" for e in ENG)
          + "   (empty slots / capacity in band)")
    step = -(-n // BANDS)
    for b0 in range(0, n, step):
        b1 = min(n, b0 + step)
        cells = []
        for e in ENG:
            cap = SLOT_LIMITS[e] * (b1 - b0)
            used = sum(occ[c][e] for c in range(b0, b1))
            cells.append(f"{cap-used:>5}/{cap:<6}")
        print(f"{b0:>5}-{b1:<6} " + " ".join(f"{c:>12}" for c in cells))
    tot = {e: SLOT_LIMITS[e] * n - sum(occ[c][e] for c in range(n)) for e in ENG}
    print("  total empty:", {e: tot[e] for e in ENG})


def cross(a: str) -> None:
    g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
    data, ops, preds, floors = A.capture_stream(g)
    place = [op[9] for op in ops]
    n = max(place) + 1
    occ = A.occupancy(ops, place, n)
    lc, vc = SLOT_LIMITS["load"], SLOT_LIMITS["valu"]
    both = load_only = valu_only = neither = 0
    load_free_valu_full = valu_free_load_full = 0
    for c in range(n):
        lf = lc - occ[c]["load"]
        vf = vc - occ[c]["valu"]
        if lf and vf:
            both += 1
        elif lf:
            load_only += 1
            load_free_valu_full += lf
        elif vf:
            valu_only += 1
            valu_free_load_full += vf
        else:
            neither += 1
    print(f"== {a}: {n} cycles ==")
    print(f"  both engines full          : {neither}")
    print(f"  load idle, valu FULL       : {load_only} cyc "
          f"({load_free_valu_full} load slots wasted)")
    print(f"  valu idle, load FULL       : {valu_only} cyc "
          f"({valu_free_load_full} valu slots wasted)")
    print(f"  both idle                  : {both}")


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "x":
        for a in (args[1:] or ["main", "12,31", "16,31", "20,31", "28,31"]):
            cross(a)
        return
    for a in (args or ["main", "16,31", "20,31"]):
        profile(a)


if __name__ == "__main__":
    main()
