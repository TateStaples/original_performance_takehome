#!/usr/bin/env python3
"""P5-I3 mission 1: realizability of n_1 = #{c<2^u : bit_u(K2*c+C2)=1}.

m(k,u) := min over C of that count.  Achievable set of n_1 for fixed k is
exactly the contiguous range [m, 2^u - m]  (proved: n1(C+1)-n1(C) in {-1,0,1}
and n1(C)+n1(C+2^u) = 2^u).
"""
import sys

def counts_all_C(k, u):
    """exact n1(C) for every C in [0,2^(u+1))  -- brute force, u small."""
    M = 1 << (u + 1)
    S = [(k * c) % M for c in range(1 << u)]
    res = []
    for C in range(M):
        res.append(sum(1 for z in S if ((z + C) % M) >> u))
    return res

def m_brute(k, u):
    return min(counts_all_C(k, u))

def m_fast(k, u):
    """min_C #{c<2^u : bit_u(kc+C)=1} without looping over all C.
    n1(C) = |B xor P(C_lo)| or its complement (see derivation);
    equivalently slide the half-circle interval over S with a sorted scan."""
    M = 1 << (u + 1)
    S = sorted((k * c) % M for c in range(1 << u))
    # count of S in [C, C+2^u) for every C: sliding window over doubled list
    n = len(S)
    best = n
    # events: use two pointers over C = each element position (min occurs at some C = s or s - 2^u + ... )
    # simpler: window count changes only at C = s or C = s+2^u+1 ; evaluate at C = s for all s in S and s+1
    import bisect
    half = 1 << u
    for s in S:
        for C in (s, (s + 1) % M):
            hi = C + half
            if hi <= M:
                cnt = bisect.bisect_left(S, hi) - bisect.bisect_left(S, C)
            else:
                cnt = (n - bisect.bisect_left(S, C)) + bisect.bisect_left(S, hi - M)
            if cnt < best:
                best = cnt
    return best

if __name__ == '__main__':
    # sanity: m_fast == m_brute for u<=8, all odd k
    bad = 0
    for u in range(1, 9):
        for k in range(1, 1 << (u + 1), 2):
            a, b = m_brute(k, u), m_fast(k, u)
            if a != b:
                bad += 1
                print('MISMATCH', u, k, a, b)
    print('m_fast selftest done, mismatches =', bad)
    for u in range(1, 8):
        row = [(k, m_fast(k, u)) for k in range(1, 1 << (u + 1), 2)]
        print('u=%2d  2^u=%5d  zeros@k=%s' % (u, 1 << u, [k for k, m in row if m == 0]))
        print('      m:', ' '.join('%d:%d' % kv for kv in row))
