#!/usr/bin/env python3
"""P6-B sub-audit 2b: does p5i sec-12's REALIZABILITY filter survive eps?

sec 12 kills a pair by pinning (q, n_1) from the EXACT value N_myhash and
showing no odd K2 can realize that n_1.  An eps-approximate sandwich9 g has
   |N_g - N_myhash| <= 2*E,    E = eps * 2^32
(one wrong input flips out_0 at x, hence flips the differential D at both x
and x^2^31, moving N by exactly +-2).  g still obeys the sec-9 congruence
2^(33-s2) | N_g exactly.  So the pair stays refuted at eps iff EVERY
multiple of 2^(33-s2) in [N-2E, N+2E] is unrealizable (both N-branches).

Reuses tools/p5i3_arith.decide_pair(s1,s2,N) verbatim (read-only import).
"""
import sys
sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome/tools")
from p5i3_arith import N_MYHASH, decide_pair, SURVIVORS  # noqa: E402

TWO32 = 1 << 32
# sec 12.4's DEAD list is exactly SURVIVORS minus these 71 ALIVE pairs.
ALIVE_EXACT = None  # computed below at eps = 0


def pair_dead_at(s1, s2, eps, cand_cap=20000):
    """True if every admissible N_g within 2*eps*2^32 of N_myhash is dead."""
    mod = 1 << (33 - s2)
    E2 = int(2 * eps * TWO32)
    lo, hi = N_MYHASH - E2, N_MYHASH + E2
    base = (N_MYHASH // mod) * mod
    assert base == N_MYHASH or True
    n = 0
    d = 0
    while True:
        cands = []
        for sgn in ((0,) if d == 0 else (-1, 1)):
            v = base + sgn * d * mod
            if lo <= v <= hi and 0 <= v <= TWO32:
                cands.append(v)
        if not cands and d > 0:
            # both directions out of window -> done
            if base - d * mod < lo and base + d * mod > hi:
                break
        for v in cands:
            alive, _ = decide_pair(s1, s2, N=v)
            if alive:
                return False, n
            n += 1
            if n > cand_cap:
                return None, n           # inconclusive (budget)
        d += 1
    return True, n


def main():
    pairs = [(s1, s2) for s1 in sorted(SURVIVORS) for s2 in SURVIVORS[s1]]
    print("sec-11 survivors in =", len(pairs))
    dead0 = [p for p in pairs if not decide_pair(*p)[0]]
    print("exact (eps=0) sec-12 kills =", len(dead0), "(expect 136)")
    for eps in (1e-6, 1e-5, 1e-4, 1e-3):
        still, reopen, unk = [], [], []
        for (s1, s2) in dead0:
            r, n = pair_dead_at(s1, s2, eps)
            (still if r is True else (reopen if r is False else unk)).append((s1, s2))
        print(f"eps={eps:.0e}: sec-12 kills still valid = {len(still):3d} / "
              f"{len(dead0)}   re-opened = {len(reopen):3d}   inconclusive = {len(unk)}")
        if still:
            print("   still-refuted pairs:", still)


if __name__ == "__main__":
    main()
