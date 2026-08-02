#!/usr/bin/env python3
"""P5-I3 mission 1: REALIZABILITY filter on sec.9's differential-count identity.

Sec.9 (STATE.md) gives, for s1+s2 >= 32, u = 31-s1, t = s1+s2-31 (so s2 = u+t):
    M = 2^(32-t)*(q-1) + 2^(33-s2)*n_1,     N = M  or  2^32 - M,
    q  = K2 mod 2^t   (odd),
    n_1 = #{c_lo < 2^u : bit_u(K2*c_lo + C2) = 1}   in [0, 2^u].
Since N = N_myhash is KNOWN, (q, n_1) is pinned down (two branches for the
K2_t sign, plus the n_1 = 2^u boundary case).  The pair dies with no solver
if the required n_1 is not realizable by any K2 == q (mod 2^t).

REALIZABILITY.  Only k := K2 mod 2^(u+1) and C := C2 mod 2^(u+1) matter.
Let  n1(C) = #{c < 2^u : bit_u(k c + C) = 1}.
  (a) n1(C+1) - n1(C) in {-1,0,+1}   (sliding a half-circle interval)
  (b) n1(C) + n1(C + 2^u) = 2^u      (the two intervals partition Z_2^(u+1))
=> the achievable set is exactly the contiguous range [m(k,u), 2^u - m(k,u)],
   m(k,u) := min_C n1(C).
DESCENT LEMMA (proved):  m(u,k) >= 2 * m(u-1, k mod 2^u).
   Proof: split c = 2c' and c = 2c'+1.  With C = 2C'+C_0 and k+C = 2E+f,
   bit_u(k(2c')+C)   = bit_{u-1}(k c' + C')  and
   bit_u(k(2c'+1)+C) = bit_{u-1}(k c' + E),  so n1(C) is a SUM of two
   level-(u-1) counts with modulus k mod 2^u.  Both are >= m(u-1,k mod 2^u).
Iterating:  m(u,k) >= 2^(u-j) * m(j, k mod 2^(j+1))  for every j <= u.
m(j,.) is brute-forced exactly, so the bound is rigorous.
"""
import argparse
import bisect
import random
from functools import lru_cache

N_MYHASH = 2172911616          # = 2^18 * 8289   (STATE.md sec 9)
NP_MYHASH = 2011299840         # = 2^17 * 15345  (mirror, sec 10; unused here)


# ---------------------------------------------------------------- m(k,u) ---
def m_exact(k, u):
    """min_C #{c<2^u : bit_u(k c + C)=1}, exact.  O(2^u log 2^u)."""
    M = 1 << (u + 1)
    half = 1 << u
    S = sorted((k * c) % M for c in range(half))
    n = len(S)
    best = n
    for s in S:                       # min attained at a window edge
        for C in (s, (s + 1) % M):
            hi = C + half
            if hi <= M:
                cnt = bisect.bisect_left(S, hi) - bisect.bisect_left(S, C)
            else:
                cnt = (n - bisect.bisect_left(S, C)) + bisect.bisect_left(S, hi - M)
            best = min(best, cnt)
    return best


@lru_cache(maxsize=None)
def mtab(j):
    """tuple over odd k in [1,2^(j+1)) -> m(j,k); index (k-1)//2."""
    return tuple(m_exact(k, j) for k in range(1, 1 << (j + 1), 2))


def m_of(j, k):
    return mtab(j)[((k % (1 << (j + 1))) - 1) // 2]


# ------------------------------------------------- rigorous lower bound ----
def lower_bound_m(u, t, q, jmax=12):
    """LB on m(k,u) valid for EVERY k == q (mod 2^min(t,u+1)).
    Returns (LB, j_used).  LB = 0 means some admissible k may hit m = 0."""
    j = min(u, jmax)
    lvl = j + 1                                   # we look at k mod 2^lvl
    if t >= lvl:
        reach = [q % (1 << lvl)]                  # k mod 2^lvl fully pinned
    else:
        step = 1 << t
        r0 = q % step
        reach = list(range(r0 if r0 else step, 1 << lvl, step))
        reach = [r for r in reach if r % 2 == 1]
    best = min(m_of(j, r) for r in reach)
    return best * (1 << (u - j)), j


# --------------------------------------------------- per-pair decision -----
def branch_candidates(s1, s2, N):
    """(q, n_1) candidates for one N-branch; [] if arithmetically impossible."""
    u, t = 31 - s1, s1 + s2 - 31
    assert s2 == u + t
    shift = 33 - s2
    if shift < 0 or (N & ((1 << shift) - 1)):
        return []                                  # 2^(33-s2) does not divide N
    Nt = N >> shift
    out = []
    n1 = Nt & ((1 << u) - 1)
    Q = Nt >> u
    if 0 <= Q <= (1 << (t - 1)) - 1:
        out.append((2 * Q + 1, n1))
    if n1 == 0 and Q >= 1 and Q - 1 <= (1 << (t - 1)) - 1:
        out.append((2 * Q - 1, 1 << u))            # boundary n_1 = 2^u
    return out


def decide_pair(s1, s2, N=N_MYHASH, jmax=12):
    u = 31 - s1
    rows = []
    alive = False
    for tag, Nv in (("N", N), ("2^32-N", (1 << 32) - N)):
        for q, n1 in branch_candidates(s1, s2, Nv):
            LB, j = lower_bound_m(u, s1 + s2 - 31, q, jmax)
            ok = LB <= n1 <= (1 << u) - LB
            rows.append((tag, q, n1, LB, j, ok))
            alive = alive or ok
    return alive, rows


# --------------------------------------------------------------- guards ----
def scaled_M(w, k2, c2, s1, s2):
    u = w - 1 - s1
    t = s1 + s2 - (w - 1)
    q = k2 % (1 << t)
    msk = (1 << w) - 1
    n1 = sum(1 for cl in range(1 << u) if (((k2 * cl + c2) & msk) >> u) & 1)
    return (1 << (w - t)) * (q - 1) + (1 << (w + 1 - s2)) * n1, q, n1


def guard_formula(w=12, trials=4, seed=11):
    """EXACT-FORMULA guard: N must equal M or 2^w - M with M from (q,n_1)."""
    import numpy as np
    rng = random.Random(seed)
    mask = (1 << w) - 1
    x = np.arange(1 << w, dtype=np.uint64)
    bad = tested = 0
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            if s1 + s2 - (w - 1) < 1:
                continue
            for _ in range(trials):
                P = [rng.getrandbits(w) | 1, rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w), rng.getrandbits(w),
                     rng.getrandbits(w) | 1, rng.getrandbits(w)]
                k1, c1, m1, k2, c2, m2, k3, c3 = P

                def out0(xv):
                    b = (xv * np.uint64(k1) + np.uint64(c1)) & np.uint64(mask)
                    c = b ^ np.uint64(m1) ^ (b >> np.uint64(s1))
                    e = (c * np.uint64(k2) + np.uint64(c2)) & np.uint64(mask)
                    wv = e ^ np.uint64(m2) ^ (e >> np.uint64(s2))
                    o = (wv * np.uint64(k3) + np.uint64(c3)) & np.uint64(mask)
                    return (o & np.uint64(1)).astype(np.uint8)

                N = int((out0(x) ^ out0(x ^ np.uint64(1 << (w - 1)))).sum())
                M, q, n1 = scaled_M(w, k2, c2, s1, s2)
                tested += 1
                if N != M and N != (1 << w) - M:
                    bad += 1
                    print("FORMULA-VIOLATION w=%d (s1,s2)=(%d,%d) N=%d M=%d q=%d n1=%d P=%s"
                          % (w, s1, s2, N, M, q, n1, P))
    print("GUARD-FORMULA w=%d trials=%d tested=%d VIOLATIONS=%d" % (w, trials, tested, bad))
    return bad


def guard_descent(jmax=9):
    """DESCENT-LEMMA guard: m(u,k) >= 2^(u-j) m(j, k mod 2^(j+1))."""
    bad = tested = 0
    for u in range(2, jmax + 1):
        for k in range(1, 1 << (u + 1), 2):
            mu = m_exact(k, u)
            for j in range(1, u):
                if mu < (1 << (u - j)) * m_of(j, k):
                    bad += 1
                    print("DESCENT-VIOLATION u=%d k=%d j=%d" % (u, k, j))
                tested += 1
    print("GUARD-DESCENT tested=%d VIOLATIONS=%d" % (tested, bad))
    return bad


def guard_range():
    """RANGE guard: achievable n1 set == contiguous [m, 2^u-m]."""
    bad = 0
    for u in range(1, 9):
        M = 1 << (u + 1)
        for k in range(1, M, 2):
            S = [(k * c) % M for c in range(1 << u)]
            ach = set()
            for C in range(M):
                ach.add(sum(1 for z in S if ((z + C) % M) >> u))
            m = min(ach)
            if ach != set(range(m, (1 << u) - m + 1)):
                bad += 1
                print("RANGE-VIOLATION u=%d k=%d" % (u, k))
    print("GUARD-RANGE VIOLATIONS=%d" % bad)
    return bad


SURVIVORS = {
    8: [24, 25], 9: [23, 24, 25], 10: [22, 23, 24, 25], 11: list(range(21, 26)),
    12: list(range(20, 26)), 13: list(range(19, 26)), 14: list(range(18, 25)),
    15: list(range(17, 26)), 16: list(range(16, 26)), 17: list(range(15, 25)),
    18: list(range(15, 25)), 19: list(range(15, 25)), 20: list(range(15, 26)),
    21: list(range(15, 25)), 22: list(range(15, 25)), 23: list(range(15, 26)),
    24: list(range(15, 26)), 25: list(range(15, 27)), 26: list(range(15, 28)),
    27: list(range(15, 29)), 28: list(range(15, 25)) + [26, 27, 28],
    29: [15, 16, 19, 20, 21, 22, 23, 26, 27, 28],
    30: [15, 17, 19, 20, 21, 22, 23, 27, 28],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--guards", action="store_true")
    ap.add_argument("--guard-w", type=int, default=12)
    ap.add_argument("--jmax", type=int, default=12)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.guards:
        guard_range()
        guard_descent()
        guard_formula(w=a.guard_w)
        return
    pairs = [(s1, s2) for s1 in sorted(SURVIVORS) for s2 in SURVIVORS[s1]]
    print("survivors in =", len(pairs))
    dead, live = [], []
    for s1, s2 in pairs:
        alive, rows = decide_pair(s1, s2, jmax=a.jmax)
        (live if alive else dead).append((s1, s2))
        if a.verbose or alive:
            u, t = 31 - s1, s1 + s2 - 31
            print("(%2d,%2d) u=%2d t=%2d %s" % (s1, s2, u, t, "ALIVE" if alive else "DEAD"))
            for tag, q, n1, LB, j, ok in rows:
                print("        %-7s q=%-10d n1=%-10d LB=%-10d 2^u-LB=%-10d j=%d %s"
                      % (tag, q, n1, LB, (1 << u) - LB, j, "ok" if ok else "kill"))
    print("KILLED  = %d" % len(dead))
    print("SURVIVE = %d" % len(live))
    print("killed pairs:", dead)
    print("surviving pairs:", live)


if __name__ == "__main__":
    main()
