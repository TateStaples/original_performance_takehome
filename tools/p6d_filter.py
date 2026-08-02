#!/usr/bin/env python3
"""P6-D: the EXTENDED (any-parity) realizability filter + the queue mass sweep.

Per-(s1,s2) verdict, from p6d_algebra.THEOREM P6D-1 / COROLLARY P6D-3:
a shape whose shr-B multiplier K2 has 2-adic valuation v realises myhash's
bit-0 top differential count N only if, for that v,
    2^(33-s2+v) | N,   Ntilde = N >> (33-s2+v),
    n_1 = Ntilde mod 2^u,  Q = Ntilde >> u,  q' = 2Q+1 < 2^(t-v)   (odd),
    n_1 realizable for some odd k == q' (mod 2^(t-v))  -- p5i sec.12's
    sliding-window/descent theory, verbatim, with t -> t-v.
v >= t gives M = 0, i.e. N in {0,2^32}: impossible.  The pair is ALIVE iff some
v in 0..t-1 and some N-branch survives; v = 0 IS p5i sec.12's filter exactly.

If the shape forces K2 odd (T6b: shr-B's input slot is a DAG cut AND that slot
is the K2 madd's own output => out = G(F(x)), F bijective => K2 odd) only v = 0
is admissible.  Otherwise the union over v is the sound verdict.
"""
import json
import sys
from collections import defaultdict

sys.path.insert(0, "tools")
import p5i3_arith as AR
import p5i3_transfer as T
import p6d_extend as X

N_MYHASH = AR.N_MYHASH
W = 32


def branch_candidates_v(s1, s2, N, v):
    u, t = 31 - s1, s1 + s2 - 31
    if v >= t or v < 0:
        return []
    shift = 33 - s2 + v
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


def alive_at_v(s1, s2, v, N=N_MYHASH, jmax=12):
    u, t = 31 - s1, s1 + s2 - 31
    for Nv in (N, (1 << 32) - N):
        for qp, n1 in branch_candidates_v(s1, s2, Nv, v):
            LB, _ = AR.lower_bound_m(u, t - v, qp, jmax)
            if LB <= n1 <= (1 << u) - LB:
                return True
    return False


def alive_ext(s1, s2, odd_only=False, N=N_MYHASH, jmax=12):
    t = s1 + s2 - 31
    for v in range(0, 1 if odd_only else t):
        if alive_at_v(s1, s2, v, N, jmax):
            return True
    return False


def grids(jmax=12):
    """(odd_alive, ext_alive) over 1<=s1,s2<=30, t>=1 (the 435-pair region)."""
    oddA, extA = set(), set()
    for s1 in range(1, 31):
        for s2 in range(1, 31):
            if s1 + s2 - 31 < 1:
                continue
            if alive_ext(s1, s2, odd_only=True, jmax=jmax):
                oddA.add((s1, s2))
            if alive_ext(s1, s2, odd_only=False, jmax=jmax):
                extA.add((s1, s2))
    return oddA, extA


# ------------------------------------------------------- window theorem ----
def window_kills(ops):
    """#(s1,s2) in [1,31]^2 killed free by P6-C's window theorem."""
    n = 0
    for s1 in range(1, 32):
        for s2 in range(1, 32):
            if max_path_shift(ops, s1, s2) <= 30:
                n += 1
    return n


def max_path_shift(ops, s1, s2):
    L = [0]
    si = 0
    sh = [s1, s2]
    for op in ops:
        if op[0] == "shr":
            L.append(L[op[1]] + sh[si]); si += 1
        elif op[0] in ("madd", "xorc"):
            L.append(L[op[1]])
        else:
            L.append(max(L[op[1]], L[op[2]]))
    return L[-1]


def k2_forced_odd(ops, b_idx, k2_idx):
    """CHAIN-T6b (p6d_forced.py): shr-B's input slot E is a DAG cut AND E is
    reached from the K2 madd's output by single-input (xorc/madd) ops only.
    Then F: x->E bijective = g o madd_K2 o h with h bijective (T6a) and g the
    chain; an even chain madd would make g non-injective, so g is bijective and
    madd_K2 = g^-1 o F o h^-1 is bijective => K2 ODD.  p5i3_transfer's T6b is
    the chain-length-0 case."""
    e_slot = ops[b_idx][1]
    if not T.is_cut(ops, e_slot):
        return False
    s = e_slot
    while s != k2_idx + 1:
        if s == 0 or ops[s - 1][0] not in ("xorc", "madd"):
            return False
        s = ops[s - 1][1]
    return True


def main():
    oddA, extA = grids()
    print("ODD-only alive over the 435-pair t>=1 grid : %d" % len(oddA))
    print("ANY-PARITY alive (union over v)            : %d" % len(extA))
    print("new-open caused by even branches           : %d"
          % len(extA - oddA))
    byv = defaultdict(int)
    for (s1, s2) in sorted(extA - oddA):
        for v in range(1, s1 + s2 - 31):
            if alive_at_v(s1, s2, v):
                byv[v] += 1
                break
    print("  first v that saves them:", dict(sorted(byv.items())))
    print("  even-only-alive pairs:", sorted(extA - oddA))
    # v=0 must reproduce p5i3_arith exactly
    mism = [(s1, s2) for s1 in range(1, 31) for s2 in range(1, 31)
            if s1 + s2 >= 32 and
            (AR.decide_pair(s1, s2)[0] != ((s1, s2) in oddA))]
    print("CONTROL v=0 vs p5i3_arith.decide_pair mismatches:", len(mism))

    q = json.load(open("tools/p5k_queue.json"))
    # P6-C's instance universe: the 2,988 open shapes (QUEUED + SCREEN-TIMEOUT)
    ent = [e for e in q["entries"]
           if e["status"] in ("QUEUED", "SCREEN-TIMEOUT")]
    print("queue entries:", len(q["entries"]), " open:", len(ent),
          " statuses:", dict((s, sum(1 for e in q["entries"]
                                     if e["status"] == s))
                             for s in set(e["status"] for e in q["entries"])))

    tot = win = new_dc = new_r31 = 0
    n_forced = n_free = 0
    per = []
    for e in ent:
        ops = [tuple(o) for o in e["ops"]]
        tot += 961
        w = window_kills(ops)
        win += w
        r = X.extended_transfer(ops)
        if not r:
            per.append((e["rank"], w, 0, 0))
            continue
        a_idx, b_idx, c, k2, modes = r
        forced = k2_forced_odd(ops, b_idx, k2)
        n_forced += forced
        n_free += (not forced)
        alive = oddA if forced else extA
        dc = 435 - len(alive)               # t>=1, s1,s2<=30 region
        r31 = 30                            # row s1+s2=31 (sec.2 recursion)
        new_dc += dc
        new_r31 += r31
        per.append((e["rank"], w, dc, r31))
    print("\nSHAPES: extended-transfer forced-odd=%d free-parity=%d"
          % (n_forced, n_free))
    print("instances total                 %10d" % tot)
    print("window-theorem kills            %10d  = %.4f" % (win, win / tot))
    print("+ diffcount(ext) kills          %10d" % new_dc)
    print("+ row-31 kills (sec.2, if it transfers) %d" % new_r31)
    print("NEW TOTAL (window+diffcount)    %10d  = %.4f"
          % (win + new_dc, (win + new_dc) / tot))
    print("NEW TOTAL (+row-31)             %10d  = %.4f"
          % (win + new_dc + new_r31, (win + new_dc + new_r31) / tot))
    print("residual after window only      %10d" % (tot - win))
    print("residual after extension        %10d" % (tot - win - new_dc - new_r31))


if __name__ == "__main__":
    main()
