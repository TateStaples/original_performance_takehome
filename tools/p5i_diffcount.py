#!/usr/bin/env python3
"""P5-I2: TOP-BIT DIFFERENTIAL COUNT theorem for sandwich9 -- scaled-model
numerical validation (and negative controls).

CLAIM.  Word width w.  sandwich(x) = K3*(sigma2(K2*sigma1(K1 x+C1)+C2))+C3
with sigma1 = ^M1^(>>s1), sigma2 = ^M2^(>>s2), K's odd.  Let
    N := #{ x in Z_2^w : out_0(x ^ 2^(w-1)) != out_0(x) }.
For 1 <= s1 <= w-2, 1 <= s2 <= w-2, s1+s2 >= w  (i.e. u := w-1-s1 >= 1 and
t := s1+s2-(w-1) >= 1):
        N  ==  0   (mod 2^(w+1-s2))
for EVERY choice of constants.

Derivation (see STATE.md sec 9):
  b* = b ^ 2^(w-1) exactly (K1 odd);  c* = c ^ 2^(w-1) ^ 2^u exactly;
  e* = e + 2^(w-1) + sg*K2*2^u, sg = +-1 from c_u;  out_0 = e_0^e_{s2}^const
  and e*_0 = e_0, so D(x) = e*_{s2} ^ e_{s2}
            = K2_t ^ [ A + q >= 2^t ]      (sg=+1)
            = K2_t ^ [ A     <  q  ]      (sg=-1)
  with A := bits u..u+t-1 of e, q := K2 mod 2^t (odd).
  Splitting c = c_hi*2^(u+1) + c_u*2^u + c_lo: for fixed (c_u, c_lo) the
  bits u+1..u+t-1 of e are EXACTLY uniform over c_hi (K2 odd), while bit u
  of e is fixed at g ^ c_u with g := bit_u(K2*c_lo + C2).  Counting the two
  sg-classes and using q odd gives
        M = 2^(w-t)*(q-1) + 2^(w+1-s2)*n_1,  n_1 := #{c_lo : g(c_lo)=1},
  and N = M or 2^w - M according to K2_t.  Both are divisible by
  2^(w+1-s2) (using s1 <= w-2 for the first term).  QED
"""
import argparse
import random

import numpy as np


def sandwich_bit0_diff_count(w, P, s1, s2):
    """Exact N over all 2^w inputs, brute force with numpy."""
    mask = (1 << w) - 1
    k1, c1, m1, k2, c2, m2, k3, c3 = [p & mask for p in P]
    x = np.arange(1 << w, dtype=np.uint64)

    def out0(xv):
        b = (xv * np.uint64(k1) + np.uint64(c1)) & np.uint64(mask)
        c = b ^ np.uint64(m1) ^ (b >> np.uint64(s1))
        e = (c * np.uint64(k2) + np.uint64(c2)) & np.uint64(mask)
        wv = e ^ np.uint64(m2) ^ (e >> np.uint64(s2))
        o = (wv * np.uint64(k3) + np.uint64(c3)) & np.uint64(mask)
        return (o & np.uint64(1)).astype(np.uint8)

    d = out0(x) ^ out0(x ^ np.uint64(1 << (w - 1)))
    return int(d.sum())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=16)
    ap.add_argument("--trials", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--control", action="store_true",
                    help="also test s1+s2 == w-1 (t=0) where the claim must "
                         "NOT be asserted, as a sharpness check")
    a = ap.parse_args()
    w = a.w
    rng = random.Random(a.seed)
    bad = 0
    tested = 0
    vals = {}
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            t = s1 + s2 - (w - 1)
            if t < 1:
                continue
            for _ in range(a.trials):
                P = [rng.getrandbits(w) | 1, rng.getrandbits(w),
                     rng.getrandbits(w), rng.getrandbits(w) | 1,
                     rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w)]
                N = sandwich_bit0_diff_count(w, P, s1, s2)
                tested += 1
                mod = 1 << (w + 1 - s2)
                if N % mod != 0:
                    bad += 1
                    if bad <= 8:
                        print(f"  VIOLATION s1={s1} s2={s2} N={N} "
                              f"mod 2^{w+1-s2}={N % mod} P={[hex(p) for p in P]}")
                vals.setdefault((s1, s2), set()).add(N)
    print(f"w={w}: {tested} (pair,constants) trials, VIOLATIONS={bad}")

    # SHARPNESS: is the modulus the largest one that always holds?  Report
    # the observed gcd-valuation per s2 vs the predicted w+1-s2.
    from math import gcd
    bys2 = {}
    for (s1, s2), ns in vals.items():
        g = 0
        for n in ns:
            g = gcd(g, n)
        bys2[s2] = gcd(bys2.get(s2, 0), g)
    for s2 in sorted(bys2):
        g = bys2[s2]
        v = (g & -g).bit_length() - 1 if g else 99
        print(f"  s2={s2}: predicted 2-adic valuation >= {w+1-s2}, "
              f"observed common valuation {v}")

    if a.control:
        # NEGATIVE CONTROL: t = 0 (s1+s2 = w-1).  Theory says D == 1 for all
        # x there, i.e. N == 2^w exactly -- a different, stronger statement.
        print("control t=0 (s1+s2=w-1): N should be exactly 2^w")
        for s1 in range(1, w - 2):
            s2 = w - 1 - s1
            if s2 < 1 or s2 > w - 2:
                continue
            P = [rng.getrandbits(w) | 1, rng.getrandbits(w),
                 rng.getrandbits(w), rng.getrandbits(w) | 1,
                 rng.getrandbits(w), rng.getrandbits(w),
                 rng.getrandbits(w) | 1, rng.getrandbits(w)]
            N = sandwich_bit0_diff_count(w, P, s1, s2)
            print(f"  s1={s1} s2={s2}: N={N} (2^w={1<<w}) "
                  f"{'OK' if N == (1 << w) else 'MISMATCH'}")


if __name__ == "__main__":
    main()
