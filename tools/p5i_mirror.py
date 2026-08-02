#!/usr/bin/env python3
"""P5-I2: MIRROR of the top-bit differential-count theorem, obtained by
running the same argument on sandwich9^{-1}.

sandwich^{-1} = A1' o T1 o A2' o T2 o A3'  where A' are madds with odd
multipliers (K'=K^{-1}) and T_i = sigma_i^{-1} is the GF(2)-affine
multi-term xorshift  T(y) = (y^M) ^ ((y^M)>>s) ^ ((y^M)>>2s) ^ ...
When s1 >= 16 and s2 >= 16 each T has exactly TWO terms on 32 bits, so:
    w* = w ^ 2^31                         (K3' odd)
    e* = e ^ 2^31 ^ 2^(31-s2)             (T2, two terms, exact XOR)
    c* = c + 2^31 + sg*K2'*2^u2,  u2 = 31-s2
    x_0 = c_0 ^ c_{s1} ^ const            (T1, two terms)
    D(y) = c*_{s1} ^ c_{s1}               (u2 >= 1 so c*_0 = c_0)
which is literally the forward structure with (observed bit, low shift)
= (s1, u2) instead of (s2, u).  t = s1 - u2 = s1+s2-31 is the same.
Hence, with N' := #{y : g_0(y) != g_0(y ^ 2^31)}, g = sandwich^{-1}:

        N'  ==  0   (mod 2^(33 - s1))            for 16<=s1,s2<=30.

General w: N' == 0 mod 2^(w+1-s1) for s1,s2 > (w-1)/2, s1+s2 >= w.
"""
import argparse
import random

import numpy as np


def sand(P, s1, s2, x, w):
    mask = (1 << w) - 1
    k1, c1, m1, k2, c2, m2, k3, c3 = [p & mask for p in P]
    b = (x * np.uint64(k1) + np.uint64(c1)) & np.uint64(mask)
    c = b ^ np.uint64(m1) ^ (b >> np.uint64(s1))
    e = (c * np.uint64(k2) + np.uint64(c2)) & np.uint64(mask)
    wv = e ^ np.uint64(m2) ^ (e >> np.uint64(s2))
    return (wv * np.uint64(k3) + np.uint64(c3)) & np.uint64(mask)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=14)
    ap.add_argument("--trials", type=int, default=6)
    a = ap.parse_args()
    w, mask = a.w, (1 << a.w) - 1
    x = np.arange(1 << w, dtype=np.uint64)
    rng = random.Random(23)
    bad = tested = 0
    vals = {}
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            if s1 + s2 < w:
                continue
            if not (2 * s1 > w - 1 and 2 * s2 > w - 1):
                continue  # two-term regime only
            for _ in range(a.trials):
                P = [rng.getrandbits(w) | 1, rng.getrandbits(w),
                     rng.getrandbits(w), rng.getrandbits(w) | 1,
                     rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w)]
                y = sand(P, s1, s2, x, w)          # y[x] = sandwich(x)
                inv = np.zeros(1 << w, dtype=np.uint64)
                inv[y] = x                          # exact inverse table
                assert len(np.unique(y)) == (1 << w), "not bijective"
                g0 = (inv & np.uint64(1)).astype(np.uint8)
                yy = np.arange(1 << w, dtype=np.uint64)
                Np = int((g0 ^ g0[(yy ^ np.uint64(1 << (w - 1)))]).sum())
                tested += 1
                mod = 1 << (w + 1 - s1)
                if Np % mod != 0:
                    bad += 1
                    if bad <= 8:
                        print(f"  VIOLATION s1={s1} s2={s2} N'={Np} "
                              f"rem={Np % mod}")
                vals.setdefault(s1, set()).add(Np)
    print(f"w={w}: {tested} trials in the two-term regime, VIOLATIONS={bad}")
    from math import gcd
    for s1 in sorted(vals):
        g = 0
        for n in vals[s1]:
            g = gcd(g, n)
        v = (g & -g).bit_length() - 1 if g else 99
        print(f"  s1={s1}: predicted valuation >= {w+1-s1}, observed {v}")


if __name__ == "__main__":
    main()
