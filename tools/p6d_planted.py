#!/usr/bin/env python3
"""P6-D SELFTEST-PLANTED for the EXTENDED (any-parity) filter -- the analogue of
tools/p5i3_planted.py.

Plant random constants (K2 of a random 2-adic valuation) at scaled width w,
brute-force the TRUE differential count N over all 2^w inputs, then run the
width-w extended filter on that N.  A solution exists by construction, so the
filter MUST return ALIVE; a DEAD verdict is a soundness violation.

Also reports TEETH: over every legal N at width w, what fraction the extended
filter kills (non-vacuity), split by odd-only vs any-parity.
"""
import argparse
import random
import sys

sys.path.insert(0, "tools")
import p5i3_arith as AR
import p6d_algebra as ALG

SAND9 = ALG.SAND9


def branch_candidates_w(w, s1, s2, N, v):
    u, t = w - 1 - s1, s1 + s2 - (w - 1)
    if v >= t or v < 0:
        return []
    shift = w + 1 - s2 + v
    if shift < 0 or (N & ((1 << shift) - 1)):
        return []
    Nt = N >> shift
    out = []
    n1 = Nt & ((1 << u) - 1)
    Q = Nt >> u
    if 0 <= Q <= (1 << (t - v - 1)) - 1:
        out.append((2 * Q + 1, n1))
    if n1 == 0 and Q >= 1 and Q - 1 <= (1 << (t - v - 1)) - 1:
        out.append((2 * Q - 1, 1 << u))
    return out


def alive_w(w, s1, s2, N, odd_only=False, jmax=12):
    u, t = w - 1 - s1, s1 + s2 - (w - 1)
    for v in range(0, 1 if odd_only else t):
        for Nv in (N, (1 << w) - N):
            for qp, n1 in branch_candidates_w(w, s1, s2, Nv, v):
                LB, _ = AR.lower_bound_m(u, t - v, qp, jmax)
                if LB <= n1 <= (1 << u) - LB:
                    return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=14)
    ap.add_argument("--trials", type=int, default=4)
    ap.add_argument("--parity", default="even")
    a = ap.parse_args()
    import numpy as np
    w = a.w
    rng = random.Random(11)
    xs = np.arange(1 << w, dtype=np.uint64)
    ops = SAND9
    ck2 = 1                                  # madd #2 of sandwich9
    bad = tested = 0
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            t, u = s1 + s2 - (w - 1), w - 1 - s1
            if t < 1 or u < 1 or s2 > w - 2:
                continue
            for _ in range(a.trials):
                consts = [[rng.getrandbits(w) | 1, rng.getrandbits(w)]
                          for _ in range(3)]
                if a.parity == "even":
                    v = rng.randint(1, w - 2)
                    K2 = ((rng.getrandbits(max(1, w - v)) | 1) << v) % (1 << w)
                    consts[ck2][0] = K2 or (1 << v)
                o0 = ALG.eval_np(ops, consts, [s1, s2], w, xs) & np.uint64(1)
                o1 = ALG.eval_np(ops, consts, [s1, s2], w,
                                 xs ^ np.uint64(1 << (w - 1))) & np.uint64(1)
                N = int((o0 ^ o1).sum())
                tested += 1
                if not alive_w(w, s1, s2, N):
                    bad += 1
                    print("  PLANTED-VIOLATION s=(%d,%d) v=%d K2=%d N=%d"
                          % (s1, s2, ALG.v2(consts[ck2][0]), consts[ck2][0], N))
    print("SELFTEST-PLANTED-EXT parity=%s w=%d trials=%d VIOLATIONS=%d"
          % (a.parity, w, tested, bad))

    # ---- teeth: fraction of legal N values killed, odd-only vs any-parity ---
    for odd_only in (True, False):
        dead = tot = 0
        for s1 in range(1, w - 1):
            for s2 in range(1, w - 1):
                t, u = s1 + s2 - (w - 1), w - 1 - s1
                if t < 1 or u < 1 or s2 > w - 2:
                    continue
                step = 1 << (w + 1 - s2)
                for N in range(0, (1 << w) + 1, step):
                    tot += 1
                    if not alive_w(w, s1, s2, N, odd_only=odd_only):
                        dead += 1
        print("TEETH w=%d %-10s DEAD %d / %d = %.3f"
              % (w, "odd-only" if odd_only else "any-parity", dead, tot,
                 dead / tot))


if __name__ == "__main__":
    main()
