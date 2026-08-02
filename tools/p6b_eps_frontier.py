#!/usr/bin/env python3
"""P6-B sub-audit 2: the eps-REFUTATION FRONTIER for sandwich9.

Every exact refutation of a (s1,s2) sandwich9 pair in research/strains/p5i/
STATE.md is a statement "myhash has property X; every sandwich9 lacks it".
An eps-approximate sandwich9 g (differing from myhash on E = eps*2^32 inputs)
still lacks X exactly -- so the refutation survives iff myhash is FARTHER
than E from the nearest X-satisfying function, measured in Hamming distance
on inputs.  This script computes, per refutation class, the exact
    E_min(class) = min #input-errors needed to satisfy X
and hence  eps_crit = E_min / 2^32:  the pair stays refuted for eps < eps_crit
and RE-OPENS for eps >= eps_crit.

Classes (p5i STATE.md sections):
  sec 1  window theorem   (435 pairs, s1+s2 <= 30): out_0 constant on the
         cosets of 2^(min(s1+s2,31)+1).  E_min = sum over cosets of
         min(#0,#1) -- monotone non-increasing in s1+s2, so the WEAKEST case
         is s1+s2 = 30 (cosets = {x, x^2^31}) and E_min = N_myhash/2.
  sec 2  row-31 (30 pairs): out_0 must FLIP under x -> x^2^31 for all x;
         E_min = #non-flipping pairs = (2^32 - N_myhash)/2.
  sec 3  row-32 (12 pairs (19,13)..(30,2), plus (31,1) and (18,14)):
         the order-(32-m) iterated xor-derivative table P_m must be CONSTANT;
         E_min = min(popcount(P_m), 2^m - popcount(P_m)) since the cosets are
         disjoint and one input flip repairs exactly one table entry.
  sec 9  differential count (68 pairs, s2 <= 14): N_g == 0 mod 2^(33-s2) for
         every sandwich9; one input error moves N by exactly +-2, so
         E_min = ceil(dist(N_myhash, 2^(33-s2)Z) / 2).
  sec 12 realizability (136 pairs): handled by p6b_eps_realizability.py.
  sec 5  z3 sample-UNSAT (207 pairs): NOT a full-domain argument -- see the
         probabilistic bound printed at the end.

Read-only; prints a table.  ~2^32 numpy myhash evaluations (few minutes).
"""
import sys
import numpy as np

M32 = np.uint32(0xFFFFFFFF)
TWO32 = 1 << 32


def myhash_np(v):
    v = v.astype(np.uint32)
    v = (v + np.uint32(0x7ED55D16)) + (v << np.uint32(12))
    v = (v ^ np.uint32(0xC761C23C)) ^ (v >> np.uint32(19))
    v = (v + np.uint32(0x165667B1)) + (v << np.uint32(5))
    v = (v + np.uint32(0xD3A2646C)) ^ (v << np.uint32(9))
    v = (v + np.uint32(0xFD7046C5)) + (v << np.uint32(3))
    v = (v ^ np.uint32(0xB55A4F09)) ^ (v >> np.uint32(16))
    return v


def sweep():
    """One pass over 2^32: returns (N_myhash, P30_packed_uint64).

    P30[r] = XOR over the 4 x with x == r (mod 2^30) of bit0(myhash(x)).
    N = #{x : bit0(myhash(x)) != bit0(myhash(x ^ 2^31))}.
    """
    CH = 1 << 24
    nflip = 0
    words = []
    for base in range(0, 1 << 30, CH):
        r = np.arange(CH, dtype=np.uint32) + np.uint32(base)
        h = [myhash_np(r ^ np.uint32(o)) & np.uint32(1)
             for o in (0, 1 << 30, 1 << 31, (1 << 30) | (1 << 31))]
        # N contribution: pairs (r, r^2^31) and (r+2^30, r+2^30+2^31)
        nflip += int((h[0] ^ h[2]).sum()) + int((h[1] ^ h[3]).sum())
        p = (h[0] ^ h[1] ^ h[2] ^ h[3]).astype(np.uint8)
        words.append(np.packbits(p, bitorder='little').view(np.uint64))
    N = 2 * nflip  # each unordered pair counted twice over the full domain
    return N, np.concatenate(words)


def popcount_bits(w):
    return int(np.bitwise_count(w).sum())


def main():
    print("P6-B eps-refutation frontier for sandwich9 (read-only)\n")
    print("sweeping 2^32 ...", flush=True)
    N, P30 = sweep()
    assert N == 2172911616, f"N mismatch vs p5i sec 9: {N}"
    print(f"N_myhash = {N} = 2^{(N & -N).bit_length()-1} * "
          f"{N >> ((N & -N).bit_length()-1)}  (matches p5i sec 9)\n")

    # ---- sec 1 / sec 2 -------------------------------------------------
    e_sec1 = N // 2
    e_sec2 = (TWO32 - N) // 2
    print("sec 1 (window, 435 pairs, s1+s2<=30): "
          f"E_min = N/2 = {e_sec1}  eps_crit = {e_sec1/TWO32:.4f}")
    print("sec 2 (row-31, 30 pairs):             "
          f"E_min = (2^32-N)/2 = {e_sec2}  eps_crit = {e_sec2/TWO32:.4f}")
    print("sec 3 edge pair (31,1) [H constant]:  "
          f"E_min = min(N,2^32-N)/2 = {min(e_sec1,e_sec2)}  "
          f"eps_crit = {min(e_sec1,e_sec2)/TWO32:.4f}\n")

    # ---- sec 3 row-32: fold P30 down ----------------------------------
    print("sec 3 (row-32 recursion): pair (s1, 32-s1) needs P_{s1} CONSTANT")
    print(f"{'m=s1':>5} {'pair':>9} {'2^m':>12} {'ones':>12} "
          f"{'E_min':>12} {'eps_crit':>11}")
    tabs = {}
    cur = P30
    for m in range(30, 17, -1):
        ones = popcount_bits(cur)
        emin = min(ones, (1 << m) - ones)
        tabs[m] = (ones, emin)
        if 19 <= m <= 30:
            print(f"{m:>5} {'(%d,%d)'%(m,32-m):>9} {1<<m:>12} {ones:>12} "
                  f"{emin:>12} {emin/TWO32:>11.3e}")
        if m > 18:
            half = cur.size // 2
            cur = cur[:half] ^ cur[half:]
    o18, e18 = tabs[18]
    print(f"  (18,14) const-branch via P_19: E_min = {tabs[19][1]} "
          f"eps_crit = {tabs[19][1]/TWO32:.3e}; "
          f"P_18 ones = {o18} (0 => perfect symmetry kills the anti branch, "
          f"E_min for that branch = {e18})")
    print()

    # ---- sec 9 ---------------------------------------------------------
    print("sec 9 (top-bit differential count): N_g == 0 mod 2^(33-s2)")
    print(f"{'s2':>4} {'mod=2^(33-s2)':>14} {'dist(N,mod Z)':>14} "
          f"{'E_min':>12} {'eps_crit':>11}")
    for s2 in range(1, 15):
        m = 1 << (33 - s2)
        r = N % m
        dist = min(r, m - r)
        emin = (dist + 1) // 2
        print(f"{s2:>4} {m:>14} {dist:>14} {emin:>12} {emin/TWO32:>11.3e}")
    print()

    # ---- sec 5 z3 sample-UNSAT ----------------------------------------
    nsamp = 34
    print("sec 5 (z3, 207 pairs): sample-UNSAT over n=34 fixed inputs, rung "
          "k=8.  An eps-form escapes a given pair's UNSAT only if one of the "
          "34 samples lies in its error set.")
    for eps in (1e-6, 1e-5, 1e-4, 1e-3, 3.3e-3):
        p = 1 - (1 - eps) ** nsamp
        print(f"   eps={eps:<8.1e} P(escape one pair) = {p:.3e}   "
              f"E[pairs escaping of 207] = {207*p:.4f}")


if __name__ == "__main__":
    sys.exit(main())
