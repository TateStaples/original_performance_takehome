#!/usr/bin/env python3
"""P6-A: premise ledger — required violation magnitude per premise.

For every premise of the P5-A/P5-F budget inversion, ask: holding all other
premises at their proved values, HOW MUCH must this one premise leak for a
C-cycle kernel (904 with-idx / 889 no-idx) to become feasible at k=11
(i.e. with the hash census intact)?

Also: the gambling arithmetic (data-dependent assumptions, their exact
probability under the real instance distribution, and expected submissions).

Read-only analysis; imports the P5-A model coefficients (re-stated here so
this file is self-contained and auditable).

Usage: python3 tools/p6a_premise.py
"""

from __future__ import annotations

import math

# --- P5-A / P5-F coefficients (research/strains/p5a, p5e, p5f) --------------
VLEN = 8
LANES_PER_CYC = 60          # 12 alu + 6 valu*8 == 12 + 48
SETUP_LANES = 600
SETUP_FLOW = 22
SETUP_LOAD = 60
BASE_STORES = 46
TAIL_LANES = 808
TAIL_LOAD, TAIL_STORE = 1, 32
IDX_FLOOR = 6608
INVENTORY = [(d, 64 if d <= 4 else 32, 2 ** d - 1) for d in range(11)]
TOTAL_GR = 512


def hash_lanes(k: float, per_op: int = 4096, elis: int = 1408) -> float:
    """P5-F exact census: hash(k) = 512k + 176 vec-ops = 4096k + 1408 lanes."""
    return per_op * k + elis


def min_folds(g: int) -> int:
    to_serve = TOTAL_GR - g
    folds = 0
    for _, n, f in INVENTORY:
        take = min(n, to_serve)
        folds += take * f
        to_serve -= take
        if to_serve == 0:
            break
    return folds


def cell(C: int, k: float, g: int, *, tail: bool, idx=IDX_FLOOR,
         serve_scale: float = 1.0, loads_per_gr: float = 8.0,
         lanes_per_cyc: float = LANES_PER_CYC, setup: float = SETUP_LANES,
         n_evals_scale: float = 1.0) -> dict:
    lane_cap = lanes_per_cyc * C
    flow_cap = C - SETUP_FLOW
    folds = min_folds(g) * serve_scale
    omf = g * serve_scale
    spill = max(0.0, folds + omf - flow_cap)
    lanes = (hash_lanes(k) * n_evals_scale + idx + setup + VLEN * spill
             + (TAIL_LANES if tail else 0))
    loads = g * loads_per_gr + SETUP_LOAD + (TAIL_LOAD if tail else 0)
    stores = BASE_STORES + (TAIL_STORE if tail else 0)
    over = {"lane": lanes - lane_cap, "load": loads - 2 * C,
            "store": stores - 2 * C}
    return dict(lanes=lanes, loads=loads, over=over,
                feasible=all(v <= 1e-9 for v in over.values()),
                over_cyc=max(over["lane"] / lanes_per_cyc, over["load"] / 2,
                             over["store"] / 2))


def best_over_g(C, k, tail, **kw):
    return min((cell(C, k, g, tail=tail, **kw) | {"g": g}
                for g in range(TOTAL_GR + 1)), key=lambda c: c["over_cyc"])


TARGETS = (("904 with-idx", 904, True), ("889 no-idx", 889, False))


def bisect(f, lo, hi, tol=1e-6):
    """smallest x in [lo,hi] with f(x) True (f monotone increasing in x)."""
    if not f(hi):
        return None
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if f(mid):
            hi = mid
        else:
            lo = mid
    return hi


def premise_table():
    print("=" * 78)
    print("PREMISE LEDGER — required violation magnitude (k=11 held)")
    print("=" * 78)
    for label, C, tail in TARGETS:
        base = best_over_g(C, 11, tail)
        print(f"\n--- {label}: at k=11, best g={base['g']}, "
              f"overrun {base['over_cyc']:+.1f} cyc "
              f"(lane {base['over']['lane']:+.0f} lanes, "
              f"load {base['over']['load']:+.0f} slots)")
        free_serve = best_over_g(C, 11, tail, serve_scale=0.0)
        print(f"    P5 serving=FREE      -> overrun {free_serve['over_cyc']:+.1f} cyc"
              f" (g={free_serve['g']})   [P5-A's fantasy row]")

        # P1: hash census leak (x = ops/round removed)
        x = bisect(lambda x: best_over_g(C, 11 - x, tail)["feasible"], 0.0, 5.0)
        kk = 11 - x if x is not None else None
        print(f"    P1 hash: need k <= {kk:.2f} ops/round"
              f"  => leak {hash_lanes(11)-hash_lanes(kk):,.0f} lanes"
              f" ({(11-kk):.2f} ops/round, "
              f"{(hash_lanes(11)-hash_lanes(kk))/hash_lanes(11)*100:.1f}% of hash)")

        # P2: index floor
        ix = bisect(lambda cut: best_over_g(C, 11, tail,
                                            idx=IDX_FLOOR - cut)["feasible"],
                    0.0, IDX_FLOOR)
        print(f"    P2 idx:  need idx floor cut by "
              f"{'IMPOSSIBLE (even idx=0 fails)' if ix is None else f'{ix:,.0f} lanes ({ix/IDX_FLOOR*100:.0f}% of 6,608)'}")

        # P3: loads per gathered group-round (contiguity)
        lp = None
        for x in [8, 6, 4, 2, 1, 0.5, 0.25, 0]:
            if best_over_g(C, 11, tail, loads_per_gr=x)["feasible"]:
                lp = x
        print(f"    P3 loads/gr: need <= "
              f"{'IMPOSSIBLE (even 0 loads fails)' if lp is None else lp}")

        # P4: lane-ops per cycle
        lc = None
        for x in [60, 62, 64, 66, 68, 70, 72, 80]:
            if best_over_g(C, 11, tail, lanes_per_cyc=x)["feasible"]:
                lc = x
                break
        print(f"    P4 slots: need >= {lc} lane-ops/cycle "
              f"(hardware says 60 = 12 alu + 6 valu x 8)")

        # P5: serving scale
        ss = bisect(lambda s: best_over_g(C, 11, tail,
                                          serve_scale=1 - s)["feasible"],
                    0.0, 1.0)
        print(f"    P5 serving: need cost scaled to "
              f"{'IMPOSSIBLE (free serving still fails)' if ss is None else f'{(1-ss)*100:.0f}% of 2^d-1'}")

        # P6: number of hash evaluations
        ne = bisect(lambda cut: best_over_g(C, 11, tail,
                                            n_evals_scale=1 - cut)["feasible"],
                    0.0, 1.0)
        print(f"    P6 evals: need {'IMPOSSIBLE' if ne is None else f'{ne*100:.1f}% fewer hash evaluations ({ne*4096:.0f} of 4,096)'}")

        # P7: setup
        st = bisect(lambda cut: best_over_g(C, 11, tail,
                                            setup=SETUP_LANES - cut)["feasible"],
                    0.0, SETUP_LANES)
        print(f"    P7 setup: need {'IMPOSSIBLE (setup=0 still fails)' if st is None else f'{st:,.0f} lanes cut'} (setup is only {SETUP_LANES})")


# ---------------------------------------------------------------------------
# GAMBLING ARITHMETIC
#
# Instance law (problem.py): tree 2047 nodes, values uniform [0,2^30);
# indices all start at 0; 256 walkers x 16 rounds; idx_{r+1} = 2 idx_r + 1
# + (val&1), wrap to 0 when idx >= 2047  =>  level(r) = r mod 11, so every
# walker is at level r mod 11 in round r, uniform over that level's 2^d
# nodes (direction bits are hash bits).
LEVEL_ROUNDS = {d: 0 for d in range(11)}
for r in range(16):
    LEVEL_ROUNDS[r % 11] += 1
WALKERS = 256
EVALS = WALKERS * 16                      # 4,096 hash evaluations / instance


def gamble_table():
    print("\n" + "=" * 78)
    print("GAMBLING ARITHMETIC (one validation instance = 4,096 hash evals,")
    print("256 walkers, level(r) = r mod 11, node uniform in level)")
    print("=" * 78)

    print("\n[G1] PARTIAL-TABLE SERVING: serve s of 2^d nodes at level d;")
    print("     gamble that no walker-round lands on an unserved node.")
    print(f"{'d':>3}{'nodes':>7}{'rounds':>7}{'walker-rounds':>14}"
          f"{'drop m':>8}{'p(pass)':>12}{'folds saved/gr':>15}{'cyc saved':>10}")
    for d in range(11):
        n = 2 ** d
        rr = LEVEL_ROUNDS[d]
        W = WALKERS * rr
        n_gr = (64 if d <= 4 else 32)
        for m in (1, max(1, n // 64), max(1, n // 8)):
            p = (1 - m / n) ** W
            cyc = m * n_gr * VLEN / LANES_PER_CYC
            print(f"{d:>3}{n:>7}{rr:>7}{W:>14}{m:>8}{p:>12.3e}{m:>15}{cyc:>10.1f}")
        if d >= 6:
            break

    print("\n[G2] eps-APPROXIMATE HASH: a k-op form that differs from myhash")
    print("     on a fraction eps of the 2^32 input domain. Fails an instance")
    print("     iff any of its 4,096 evaluations hits a bad input.")
    print(f"{'eps':>12}{'bad inputs':>14}{'p(1 inst)':>12}{'p(8 inst)':>12}"
          f"{'E[subs] 1i':>12}{'E[subs] 8i':>12}")
    for eps in (1e-2, 3e-3, 1e-3, 3e-4, 1e-4, 1e-5, 1e-6, 1e-7, 1e-8):
        p1 = (1 - eps) ** EVALS
        p8 = (1 - eps) ** (8 * EVALS)
        print(f"{eps:>12.0e}{eps*2**32:>14,.0f}{p1:>12.4f}{p8:>12.4f}"
              f"{(1/p1 if p1 > 0 else float('inf')):>12.1f}"
              f"{(1/p8 if p8 > 0 else float('inf')):>12.1f}")
    print("     eps needed for p(1 inst)=0.5 :", f"{1-0.5**(1/EVALS):.3e}")
    print("     eps needed for p(1 inst)=0.99:", f"{1-0.99**(1/EVALS):.3e}")
    print("     eps needed for p(8 inst)=0.99:", f"{1-0.99**(1/(8*EVALS)):.3e}")
    print("     eps at which a 32-probe MITM meet still matches w.p. 0.9:",
          f"{1-0.9**(1/32):.3e}")
    print("     eps at which a 10M-vector verify still passes w.p. 0.9:",
          f"{1-0.9**(1/10_000_000):.3e}")

    print("\n[G3] CONTIGUITY GAMBLE: gamble that all 8 lanes of a group-round")
    print("     share a parent (vload instead of 8 loads).")
    for gr in (1, 5, 10, 50):
        # 8 lanes in same parent at level d: all 8 walkers equal in top d-1
        # bits.  Measured natural contiguity (P5-C) = 0.003 per group-round.
        p = 0.003 ** gr
        print(f"     {gr:>3} group-rounds gambled: p = {p:.3e}, "
              f"saves {gr*7*0.5:.1f} load-cycles")

    print("\n[G4] SKIPPED WRAP / HAZARD / TRUNCATED COLUMNS: the wrap"
          " (idx>=2047) and\n     level schedule are DETERMINISTIC (all walkers"
          " start at idx 0 and\n     advance in lockstep), so these are not"
          " gambles at all — they are\n     already-banked static facts."
          "  p = 1, saving already in the census.")


def submission_fit():
    print("\n" + "=" * 78)
    print("SUBMISSION-COUNT FIT")
    print("=" * 78)
    for subs, who in ((71, "saifalharthi no-idx 889"),
                      (3, "saifalharthi with-idx 904"),
                      (138, "josusanmartin no-idx 923"),
                      (696, "anboto1 no-idx 955")):
        p = 1 / subs
        eps1 = 1 - p ** (1 / EVALS)
        print(f"  {who:<32} {subs:>4} subs -> implied p={p:.4f}, "
              f"eps={eps1:.3e} (1 instance)")
    print("  NB: a gamble needs a CONSISTENT p across both boards; 71 subs"
          " (p=1.4%) then\n      3 subs (p=33%) on the ported kernel is a"
          " 24x inconsistency unless the\n      instance is reused across a"
          " time window or the port was luck.")


if __name__ == "__main__":
    premise_table()
    gamble_table()
    submission_fit()
