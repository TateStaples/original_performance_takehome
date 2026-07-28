"""P3-B: can the `omf` two-way constant choice in the gather-address
recurrence be eliminated?  (Cross-axis answer to P3-A's C9 / 920 claim.)

The recurrence is  gaddr' = 2*gaddr + omf +/- par,  omf = 1 - forest_values_p
= -6.  The shipped kernel spells the addend as a flow vselect between two
live constants (perf_takehome.py:1650-1656), costing 0 alu/valu lane-ops and
1 flow slot per gathered group-round.  P3-A's C9 assumes that op can be made
to VANISH, which drops its floor 939 -> 920.

This tool reproduces P3-A's own census (importing tools/p3a_model.py,
unmodified) for C1* and for the corrected C9, where "eliminating" the select
is charged its true price: the only representations whose addend is a
one-op parity form are S = idx+1 (addend `par`) and S = idx+3 (addend
`par-2` via `val | 0xFFFFFFFE`), and NEITHER is a loadable address, so each
gathered group-round must materialise A = S + 6 / S + 4 -- one VALU-ONLY op
replacing one FLOW-ELIGIBLE op.

Usage (repo root): python3 tools/p3b_omf.py
"""

from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import p3a_model as PA  # noqa: E402  (read-only import)

# --- P3-A's C1* optimum, reconstructed from research/strains/p3a/STATE.md ---
SERVED = {1: 64, 2: 64, 3: 64, 4: 29}       # s = 221
EXITS = 35
EXIT_EXTRA = 2
SETUP_VEC = 69          # back-solved from C1* = 56,272 lane-ops
SETUP_FLOW = 2          # 22 - 20, the `add_imm`->alu move (P3-A T3)
SETUP_LOAD = 60 + 4     # +4 loads for the store-engine broadcasts


def census(C: int, omf_flow_eligible: bool) -> dict:
    s = sum(SERVED.values())
    g = PA.VALUE_GR - s
    leaves = sum(n * 2 ** (L - 1) for L, n in SERVED.items())
    inter = sum(n * (2 ** (L - 1) - 1) for L, n in SERVED.items())

    idx_valu = g + EXIT_EXTRA * EXITS
    idx_selects = g
    if not omf_flow_eligible:
        # the addend op stops being a select; instead every gathered
        # group-round pays a valu-only address recovery A = S + const
        idx_valu += g
        idx_selects = 0

    base = (PA.HASH_CORE_VEC + PA.FOLDIN_VEC + PA.PARITY_VEC
            + idx_valu + SETUP_VEC)

    flow_avail = max(0, C - SETUP_FLOW)
    x_i = min(inter, flow_avail)
    rem = flow_avail - x_i
    x_rest = min(leaves + idx_selects, rem)
    spill = 2 * (inter - x_i) + 1 * (leaves + idx_selects - x_rest)

    vec = base + spill
    loads = 8 * g + SETUP_LOAD
    flow = SETUP_FLOW + x_i + x_rest
    return dict(s=s, g=g, leaves=leaves, inter=inter, spill=spill,
                lane=8 * vec, loads=loads, flow=flow,
                f_av=8 * vec / 60.0, f_ld=loads / 2.0, f_fl=float(flow))


def show(C: int) -> None:
    print(f"\n=== cycle budget C = {C} "
          f"(capacity {60*C} lane-ops / {2*C} load / {C} flow) ===")
    for label, elig in (("C1*  omf as a flow-eligible select (shipped form)", True),
                        ("C9'  omf 'eliminated' via S=idx+3, A=S+4 on valu", False)):
        c = census(C, elig)
        ok = (c["lane"] <= 60 * C and c["loads"] <= 2 * C and c["flow"] <= C)
        print(f"  {label}")
        print(f"      alu+valu {c['lane']:>6} | load {c['loads']:>5} | "
              f"flow {c['flow']:>4}   floors {c['f_av']:.1f} / {c['f_ld']:.1f}"
              f" / {c['f_fl']:.1f}   [{'PASS' if ok else 'FAIL'}]")


def dominance_proof() -> None:
    print("\n=== DOMINANCE (holds for every design and every C) ===")
    print("  Let  rem  = flow slots left after the interior selects,")
    print("       L    = leaf selects (save-1 pool), g = gathered group-rounds.")
    print("  shipped :  valu cost from the save-1 pool = max(0, L + g - rem)")
    print("  S=idx+3 :  valu cost                      = g + max(0, L - rem)")
    print("  If L >= rem  both equal L + g - rem            (exact tie)")
    print("  If L <  rem  shipped = max(0, L+g-rem) <= g    (strictly better)")
    print("  => the biased representation is WEAKLY DOMINATED, never better.")
    for L, g, rem in ((680, 227, 479), (680, 227, 900), (300, 227, 900)):
        a = max(0, L + g - rem)
        b = g + max(0, L - rem)
        print(f"    L={L:>4} g={g:>4} rem={rem:>4} -> shipped {a:>4} vs "
              f"biased {b:>4}   {'tie' if a == b else 'shipped wins'}")


if __name__ == "__main__":
    show(940)
    show(939)
    show(920)
    dominance_proof()
