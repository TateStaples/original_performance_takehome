#!/usr/bin/env python3
"""P5-L2: close the dir1 commutation query ANALYTICALLY (z3 timed out).

dir1 asks: do there exist an odd K'', constants C'', C and a GF(2)-AFFINE
map B with

    (D1)   K * sigma_s(v) + C  ==  B(K''*v + C'')      for all v in Z_2^32

(sigma_s(v) = v ^ (v>>s); + and * are mod 2^32).  If yes, a madd could be
pulled back through a sigma, enabling madd*madd fusion across the sigma.

TOP-BIT LEMMA (proved here, then validated numerically)
-------------------------------------------------------
Assume (D1).  Put e := sigma_s(2^31) = 2^31 ^ 2^(31-s), a := 2^(31-s).
 1. v ^ 2^31 = v + 2^31, and K'' odd => (K''(v^2^31)+C'') = u ^ 2^31 where
    u = K''v + C''.  So the top-bit flip on v is a top-bit flip on u.
 2. B affine => B(u ^ 2^31) = B(u) ^ D for the CONSTANT D := Bm*2^31.
 3. sigma_s linear and bijective => with w := sigma_s(v) ranging over all of
    Z_2^32, (D1) forces
        (L)   K*(w ^ e) + C == (K*w + C) ^ D        for all w.
    *** K'', C'' and B have been eliminated: only (K, s, C, D) remain. ***
 4. For w with bit (31-s) clear, w ^ e = w + e, so K*(w^e) = K*w + E with
        E := K*e mod 2^32 = (K*2^(31-s)) ^ 2^31.
    So with X := K*w + C -- which ranges over a set T0 of size 2^31, since
    w |-> K*w+C is a bijection and {w : w_(31-s)=0} has size 2^31 --
        (L0)  X + E == X ^ D        for every X in T0.
 5. Carry analysis of (L0).  Writing c_i for the carry into bit i of X+E:
    D_i = E_i ^ c_i, so the whole carry word is c = D ^ E, and c_0 = 0.
    The recurrence c_{i+1} = maj(X_i, E_i, c_i) gives, per position:
        E_i=1,c_i=1 -> c_{i+1} must be 1, X_i free
        E_i=0,c_i=0 -> c_{i+1} must be 0, X_i free
        E_i=1,c_i=0 -> X_i = c_{i+1}  (forced)
        E_i=0,c_i=1 -> X_i = c_{i+1}  (forced)
    So X_i is free exactly when E_i = c_i, i.e. when D_i = 0; bit 31 is
    always free (c_32 is discarded).  Hence the solution set of (L0) is
    empty or a coset of dimension 32 - popcount(D & 0x7fffffff).
 6. |T0| = 2^31 forces popcount(D & 0x7fffffff) <= 1.  The lowest set bit of
    E is j = 31-s (K odd), so all carries below j vanish, c_j = 0 and
    D_j = E_j ^ c_j = 1.  Therefore D & 0x7fffffff == 2^j exactly, i.e.
    D in {2^j, 2^j + 2^31}, and in both cases c = D ^ E has c_i = E_i for
    every i in [j+1, 30].
 7. Feasibility of that carry chain: at position j, E_j=1, c_j=0 => forced
    and c_{j+1} = X_j.  For i in [j+1, 30] we need E_i = c_i, and the
    recurrence with E_i = c_i propagates c_{i+1} = c_i.  So the chain is
    consistent only if E_i is CONSTANT on [j+1, 30] and equal to c_{j+1};
    since c_{j+1} may be 0 or 1 this means E's bits j+1..30 are all equal.
    Both uniform cases are checked exactly below (feasible_chain()).
 8. Net predicate: (D1) is possible only if E's bits j+1..30 are all 0 or
    all 1, i.e. exactly     K == +1 (mod 2^s)  or  K == -1 (mod 2^s).
    (Both branches are checked exactly by feasible_chain(); the closed form
    is only the human-readable summary.  An earlier draft omitted the -1
    branch and was caught by the exhaustive width-6 search below.)

Positive controls: K = +-1 mod 2^s satisfies the predicate, and those K
really do admit affine B (width-6/7 exhaustive search finds solutions
exactly at K = +-1 mod 2^(n-1), the degenerate-multiplier family that also
produced P5-L's dir2 K=1 positive control at 0x7fffffff) -- the lemma is
necessary, not sufficient, and it is not vacuous.

Subcommands:
  lemma      -- symbolic/exact predicate for the two OPEN dir1 queries
  scan32     -- brute-force confirmation at the REAL width 32: scan all
                2^32 values of C (D is forced by w=0) and show none works
  exhaust    -- fully exhaustive dir1 search at small width n over ALL odd
                K'', ALL C'', ALL C, testing affinity of B directly; the
                empirical law is compared to the lemma predicate
"""
import sys
import time

import numpy as np


# ---------------------------------------------------------------- lemma ----
def feasible_chain(E, D, nbits=32):
    """Is the carry chain c = D ^ E consistent with X + E == X ^ D having
    ANY solution?  Returns (feasible, dimension)."""
    c = D ^ E
    if c & 1:
        return False, 0            # c_0 must be 0
    dim = 0
    for i in range(nbits):
        Ei = (E >> i) & 1
        ci = (c >> i) & 1
        cn = (c >> (i + 1)) & 1 if i + 1 < nbits else None
        if Ei == ci:
            dim += 1               # X_i free
            if cn is not None and cn != Ei:
                return False, 0    # c_{i+1} pinned to Ei, mismatch
        else:
            if cn is None:
                dim += 1           # X_31 = c_32, unconstrained
            # else X_i forced to c_{i+1}
    return True, dim


def lemma(K, s, nbits=32, verbose=True):
    top = 1 << (nbits - 1)
    a = 1 << (nbits - 1 - s)
    E = ((K * a) & ((1 << nbits) - 1)) ^ top
    j = nbits - 1 - s
    assert E & ((1 << j) - 1) == 0 and (E >> j) & 1 == 1, "j must be lsb(E)"
    if verbose:
        print(f"  K={K} s={s} width={nbits}: "
              f"e=sigma_s(2^{nbits-1})={(top ^ a):#x}"
              f"  E=K*e={E:#x}  lsb(E)=j={j}")
    ok_any = False
    for D in (1 << j, (1 << j) | top):
        feas, dim = feasible_chain(E, D, nbits)
        need = nbits - 1  # |T0| = 2^(nbits-1)
        good = feas and dim >= need
        if verbose:
            print(f"    D={D:#x}: carry chain c={D ^ E:#x} -> "
                  f"{'FEASIBLE' if good else 'INFEASIBLE'} "
                  f"(dim={dim if feas else '-'} need>={need})")
        ok_any |= good
    closed = (K % (1 << s) == 1) or (K % (1 << s) == (1 << s) - 1)
    if verbose:
        print(f"    closed form K == +-1 (mod 2^{s})? {closed}"
              f"  (agrees: {closed == ok_any})   ==>  dir1 "
              f"{'POSSIBLE (not excluded)' if ok_any else 'IMPOSSIBLE (UNSAT)'}")
    return ok_any


# --------------------------------------------------------------- scan32 ----
def scan32(K, s, chunk_bits=24):
    """Independent width-32 confirmation.  (L) at w=0 forces D = C ^ (C+E).
    Then test (L) at a handful of other w with bit (31-s) clear.  If no C
    survives, dir1 is UNSAT for this (K,s)."""
    M32 = np.uint32
    a = np.uint32(1 << (31 - s))
    e = np.uint32((1 << 31) ^ (1 << (31 - s)))
    E = np.uint32((K * int(e)) & 0xFFFFFFFF)
    # probe w values with bit (31-s) clear (so w^e == w+e)
    probes = [1, 2, 3, 7, 0x1234, 0xDEADBEE, 0x7FFFFFFF, 0x55555555]
    probes = [w for w in probes if not ((w >> (31 - s)) & 1)]
    Kw = [np.uint32((K * w) & 0xFFFFFFFF) for w in probes]
    lhs = [np.uint32((K * ((w ^ int(e)) & 0xFFFFFFFF)) & 0xFFFFFFFF)
           for w in probes]
    survivors = 0
    t0 = time.time()
    step = 1 << chunk_bits
    with np.errstate(over="ignore"):
        for base in range(0, 1 << 32, step):
            C = (np.arange(step, dtype=np.uint32) + np.uint32(base))
            D = C ^ (C + E)
            alive = np.ones(step, dtype=bool)
            for kw, lh in zip(Kw, lhs):
                alive &= ((lh + C) == ((kw + C) ^ D))
                if not alive.any():
                    break
            survivors += int(alive.sum())
    print(f"  scan32 K={K} s={s}: E={int(E):#x} probes={[hex(w) for w in probes]}"
          f" -> {survivors} surviving C out of 2^32 "
          f"({time.time()-t0:.0f}s)")
    return survivors


# -------------------------------------------------------------- exhaust ----
def dir1_exhaustive(n, K, s):
    """Exhaustive small-width dir1: does ANY (odd K'', C'', C, affine B)
    satisfy K*sigma_s(v)+C == B(K''v+C'')?  We search B = Phi o A^{-1}
    directly: B(u) = K*sigma_s(J*u - d) + C with J = K''^{-1} odd (free)
    and d = J*C'' (free), and test B for GF(2)-affinity exactly."""
    M = (1 << n) - 1
    K &= M
    if K % 2 == 0:
        return None
    us = np.arange(1 << n, dtype=np.int64)
    Cs = np.arange(1 << n, dtype=np.int64)
    bitmasks = [((us >> i) & 1).astype(bool) for i in range(n)]
    found = []
    for J in range(1, 1 << n, 2):
        Ju = (J * us) & M
        for d in range(1 << n):
            arg = (Ju - d) & M
            P = (K * ((arg ^ (arg >> s)) & M)) & M
            # cheap necessary filter: B(0)^B(1)^B(2)^B(3) == 0
            B0 = (P[0] + Cs) & M
            B1 = (P[1] + Cs) & M
            B2 = (P[2] + Cs) & M
            B3 = (P[3] + Cs) & M
            cand = np.nonzero((B0 ^ B1 ^ B2 ^ B3) == 0)[0]
            for c in cand:
                B = (P + int(c)) & M
                pred = np.full(1 << n, B[0], dtype=np.int64)
                for i in range(n):
                    pred[bitmasks[i]] ^= (B[1 << i] ^ B[0])
                if np.array_equal(pred, B):
                    found.append((J, d, int(c)))
    return found


def run_exhaust(n, s):
    print(f"[exhaust] width n={n}, shift s={s}: all odd K, all odd K'', "
          f"all C'', all C")
    print(f"  {'K':>4} {'K%2^s':>6} {'pred':>5} {'#solutions':>11}")
    mism = 0
    for K in range(1, 1 << n, 2):
        sols = dir1_exhaustive(n, K, s)
        pred = lemma(K, s, nbits=n, verbose=False)
        flag = ""
        if bool(sols) and not pred:
            flag = "  <<< LEMMA VIOLATED"
            mism += 1
        print(f"  {K:>4} {K % (1 << s):>6} {str(pred):>5} {len(sols):>11}{flag}")
    print(f"  mismatches (solutions where lemma says impossible): {mism}")
    return mism


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("lemma", "all"):
        print("[lemma] the two OPEN dir1 queries (P5-L sec 3.3):")
        lemma(4097, 16)
        lemma(33, 19)
        print("[lemma] controls (K=1 must be POSSIBLE; K=9/K=3 shown too):")
        lemma(1, 16)
        lemma(1, 19)
        lemma(65537, 16)   # 65537 == 1 mod 2^16 -> predicate true
        lemma(9, 16)
        lemma(3, 19)
    if which in ("exhaust", "all"):
        run_exhaust(6, 2)
        run_exhaust(6, 3)
        run_exhaust(8, 3)
    if which in ("scan32", "all"):
        scan32(4097, 16)
        scan32(33, 19)
        scan32(1, 16)      # control: must have survivors
        scan32(65537, 16)  # control: K == 1 mod 2^16
