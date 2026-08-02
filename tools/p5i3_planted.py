#!/usr/bin/env python3
"""P5-I3 SELFTEST-PLANTED for the realizability filter (mission 1).

For random constants in the scaled model of width w, compute the TRUE
differential count N by brute force, then feed N to the width-w analogue of
the realizability decision procedure.  A solution EXISTS by construction, so
the procedure must return ALIVE.  Any DEAD is a fabricated refutation.
"""
import argparse, random, sys
import numpy as np
sys.path.insert(0, '/Users/tatestaples/Code/original_performance_takehome/tools')
from p5i3_arith import m_of, m_exact, mtab

def branch_cands(w, s1, s2, N):
    u, t = w - 1 - s1, s1 + s2 - (w - 1)
    shift = w + 1 - s2
    if shift < 0 or (N & ((1 << shift) - 1)):
        return []
    Nt = N >> shift
    out = []
    n1 = Nt & ((1 << u) - 1); Q = Nt >> u
    if 0 <= Q <= (1 << (t - 1)) - 1:
        out.append((2 * Q + 1, n1))
    if n1 == 0 and Q >= 1:
        out.append((2 * Q - 1, 1 << u))
    return out

def lb(u, t, q, jmax):
    j = min(u, jmax); lvl = j + 1
    if t >= lvl:
        reach = [q % (1 << lvl)]
    else:
        step = 1 << t; r0 = q % step
        reach = list(range(r0, 1 << lvl, step))
    return min(m_of(j, r) for r in reach) * (1 << (u - j))

def decide(w, s1, s2, N, jmax=10):
    u, t = w - 1 - s1, s1 + s2 - (w - 1)
    rows = []
    for tag, Nv in (("N", N), ("2^w-N", (1 << w) - N)):
        for q, n1 in branch_cands(w, s1, s2, Nv):
            L = lb(u, t, q, jmax)
            rows.append((tag, q, n1, L, L <= n1 <= (1 << u) - L))
    return any(r[-1] for r in rows), rows

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=14)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--seed", type=int, default=101)
    ap.add_argument("--jmax", type=int, default=10)
    a = ap.parse_args()
    w = a.w; mask = (1 << w) - 1
    x = np.arange(1 << w, dtype=np.uint64)
    rng = random.Random(a.seed)
    bad = tested = 0
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            if s1 + s2 - (w - 1) < 1:
                continue
            for _ in range(a.trials):
                P = [rng.getrandbits(w) | 1, rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w)]
                k1, c1, m1, k2, c2, m2, k3, c3 = P
                def out0(xv):
                    b = (xv * np.uint64(k1) + np.uint64(c1)) & np.uint64(mask)
                    c = b ^ np.uint64(m1) ^ (b >> np.uint64(s1))
                    e = (c * np.uint64(k2) + np.uint64(c2)) & np.uint64(mask)
                    wv = e ^ np.uint64(m2) ^ (e >> np.uint64(s2))
                    return ((((wv * np.uint64(k3) + np.uint64(c3)) & np.uint64(mask))) & np.uint64(1)).astype(np.uint8)
                N = int((out0(x) ^ out0(x ^ np.uint64(1 << (w - 1)))).sum())
                alive, rows = decide(w, s1, s2, N, a.jmax)
                tested += 1
                if not alive:
                    bad += 1
                    print("PLANTED-VIOLATION w=%d (s1,s2)=(%d,%d) N=%d K2=%d C2=%d rows=%s"
                          % (w, s1, s2, N, k2, c2, rows))
    print("SELFTEST-PLANTED w=%d tested=%d VIOLATIONS=%d" % (w, tested, bad))

main()
