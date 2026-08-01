"""P4-B: is P3-C's 994.0 max-floor for the best L5-serving design the SAME 994
that corsix scores, or a coincidence?

Reuses tools/p3c_design_cost.py unchanged (validated to +0.08% against the
measured 1006 kernel) and asks three questions:

 1. Which L5-serving designs exist, ranked by max-floor?  Full census of the
    best one (the "994.0" design) so it can be compared against whatever the
    primary source actually does.
 2. Which designs' max-floor lands on each published leaderboard score
    (958, 971, 981, 994, 1002)?  If many unrelated designs land within a
    cycle of 994, the match is worthless as evidence.
 3. How dense is the max-floor distribution near 994 -- i.e. what is the
    prior probability that a random design in the space matches to +-0.5?

Read-only.  Usage:  python3 tools/p4b_994.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")
from tools.p3c_design_cost import (                    # noqa: E402
    HDR, MEASURED_IDX_VEC, census, enumerate_space, index_cost, row, shipped,
    SCRATCH_SIZE,
)

MEAS_SLACK = MEASURED_IDX_VEC - index_cost(shipped())[0]
SCORES = [958, 971, 981, 994, 1002]


def main() -> None:
    scored = enumerate_space(MEAS_SLACK, 0.222, 0.43)
    print(f"space = {len(scored)} designs   (as-built support coefficients)")

    print("\n== 1. best L5-SERVING designs (any L5 count > 0) ==")
    print(HDR)
    l5 = [(c, d) for c, d in scored if d.served.get(5, 0) > 0]
    for c, d in l5[:12]:
        print(row(c, d))
    print(f"  L5-serving designs: {len(l5)};  best max-floor "
          f"{l5[0][0].maxfloor:.2f}")
    c, d = l5[0]
    print("\n  FULL CENSUS of the best L5-serving design:")
    print(f"    label            {d.label}")
    print(f"    served/level     "
          + " ".join(f"L{k}:{d.served.get(k,0)}" for k in range(1, 11)))
    print(f"    lane-ops         {c.lane:.0f}  ({c.vec:.1f} vec-ops)")
    print(f"    load / flow / st {c.load:.0f} / {c.flow:.0f} / {c.store:.0f}")
    print(f"    folds total      {c.folds_total:.0f} "
          f"(on flow {c.folds_on_flow:.0f})")
    print(f"    idx              {c.idx_vec:.0f} vec / {c.idx_flow:.0f} flow")
    print(f"    served gr        {c.served_gr}   gathered gr {c.gathered_gr}")
    print(f"    scratch          {c.scratch:.0f} / {SCRATCH_SIZE}"
          f"{'   ** OVER **' if c.scratch > SCRATCH_SIZE else ''}")
    print(f"    floors           cmp {c.f_compute:.1f}  ld {c.f_load:.1f}  "
          f"flw {c.f_flow:.1f}  st {c.f_store:.1f}  -> {c.binder} "
          f"{c.maxfloor:.2f}")

    print("\n== 1b. best L5-serving design that FITS scratch (K=32) ==")
    fit = [(c, d) for c, d in l5 if c.scratch <= SCRATCH_SIZE]
    print(f"  {len(fit)} of {len(l5)} fit at K=32" if fit else
          "  NONE fit at K=32")
    for c, d in fit[:5]:
        print(row(c, d))

    print("\n== 2. designs whose max-floor matches a published score (+-0.5) ==")
    for s in SCORES:
        hits = [(c, d) for c, d in scored if abs(c.maxfloor - s) <= 0.5]
        print(f"\n  score {s}: {len(hits)} design(s) within 0.5 cycles")
        for c, d in hits[:6]:
            print("   " + row(c, d))

    print("\n== 3. density of the max-floor distribution near each score ==")
    print(f"{'score':>7}{'designs within +-0.5':>22}{'within +-2':>12}"
          f"{'  P(match|random design)':>24}")
    n = len(scored)
    for s in SCORES:
        a = sum(1 for c, _ in scored if abs(c.maxfloor - s) <= 0.5)
        b = sum(1 for c, _ in scored if abs(c.maxfloor - s) <= 2.0)
        print(f"{s:>7}{a:>22}{b:>12}{a / n * 100:>23.2f}%")

    print("\n== 4. where do the shipped shape and its neighbours land ==")
    print(HDR)
    for c, d in scored:
        if d.label.startswith("full=L1L2L3 +L4") and d.served.get(4) in (
                26, 27, 28, 39, 64):
            print(row(c, d))
    for c, d in scored[:3]:
        print(row(c, d))


if __name__ == "__main__":
    main()
