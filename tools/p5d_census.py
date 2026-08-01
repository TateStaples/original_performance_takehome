#!/usr/bin/env python3
"""P5-D mission 1: exact census of n-op DAG shapes for hash equivalents,
classified by MITM-searchability.

Shape model
-----------
An n-op program: op p (p=1..n) produces t_p; t_0 = x (the input).
Each op reads a nonempty SET S_p of runtime slots from {x, t_1..t_{p-1}},
|S_p| in {1,2,3} (3 = madd with three runtime operands; remaining operand
slots are constants, whose values the census abstracts away).
Output = t_n. Validity: every t_p (p<n) is read by some later op, and x is
read at least once.

Op-type classification (syntactic, per position p >= 2):
  A      : S_p == {t_{p-1}}                      (unary-invertible chain link
                                                  candidate: op w/ constant)
  Bvalid : S_p == {t_{p-2}, t_{p-1}} AND op p-1 is A
           (the 2-op xorshift-macro pattern sigma: t=shr(v); v^t)
  join2  : |S_p| == 2, t_{p-1} in S_p, not Bvalid
           (binary op joining the running value with ONE older live value r)
  other  : anything else (violation)
Op 1 always reads {x} (type A by convention).

"Violation" = op not A and not Bvalid.  lv = position of LAST violation
(0 if none).  The suffix after lv is (syntactically) chain-expressible.

Coverage classes (what each searcher family can decompose):
  P5B      : lv <= 3.  [<=3-op full-shape DAG prefix][solved meet][chain<=6]
             == global_mitm kf3full (P5-B, REGION CLOSED negative).
  P5D_join : lv == 4 and op_4 is join2.  [<=3-op DAG][join g(m,r)][meet][chain]
             == fanout_mitm (this strain). NEW coverage.
  KF4C     : lv <= 4 and ops 2..4 each read t_{p-1} (chained spine).
             == global_mitm kf4chained (driver grinding, 2/4096 done).
  UNCOV    : everything else (lv >= 5, or lv == 4 with op_4 reading
             neither pattern, e.g. madd with two older operands, or a
             2-set not containing t_3).

NOTE the classification is SYNTACTIC: algebraic rewrites (xor commuting with
shr, etc.) let the chain links cover some syntactically-violating shapes, so
covered counts are LOWER bounds and UNCOV is an UPPER bound on the true gap.

DP over positions with state (u, w, xr, prevA, lvcls, spine):
  u     = number of currently-unreferenced temps among t_1..t_{p-1}
          (t_{p-1} is always unreferenced at time p)
  w     = is t_{p-2} unreferenced (p>=3; the B pattern needs to know)
  xr    = has x been read
  prevA = was op p-1 type A
  lvcls = NONE(<=3 incl 0) | EQ4_JOIN | EQ4_OTHER_SPINE | EQ4_OTHER_NOSPINE
          | GE5_JOIN | GE5_OTHER   (last-violation bucket; EQ4_OTHER split by
          whether op_4 reads t_3 so KF4C attribution is exact)
  spine = ops 2..min(p-1,4) all read their immediate predecessor
Validated against brute-force enumeration for n <= 6.
"""
from math import comb
from functools import lru_cache
import sys

# lvcls encoding
LV_LE3, LV_EQ4_JOIN, LV_EQ4_OTH_T3, LV_EQ4_OTH_NOT3, LV_GE5_JOIN, LV_GE5_OTH = range(6)


def census(n, max_arity=3):
    """Exact DP count. Returns dict lvcls_final -> {spine: count}."""
    # state: (p, u, w, xr, prevA, lvcls, spine) -> count
    # p advances 2..n (op1 fixed: reads {x})
    from collections import defaultdict
    states = defaultdict(int)
    # after op1: u=1 (t1 unref), xr=True, prevA=True, lv=NONE, spine trivially True
    # w at p=2 refers to t_0 = x -> treat "t_{p-2}" as x at p=2 (special-cased below)
    states[(1, None, True, True, LV_LE3, True)] = 1
    for p in range(2, n + 1):
        new = defaultdict(int)
        for (u, w, xr, prevA, lvcls, spine), cnt in states.items():
            # slots: x (1) + temps t_1..t_{p-1} (p-1 of them)
            # unref temps: u total, incl t_{p-1} (specific), and t_{p-2} iff w
            # p==2: t_{p-2} is x -> b2 merges with a; treat w-slot as absent
            has_t2slot = p >= 3
            u_other = u - 1 - (1 if (has_t2slot and w) else 0)
            ref_other = (p - 1) - u - (1 if (has_t2slot and not w) else 0)
            if u_other < 0 or ref_other < 0:
                continue
            for a in (0, 1):
                for b1 in (0, 1):
                    for b2 in ((0, 1) if has_t2slot else (0,)):
                        for k2 in range(0, u_other + 1):
                            for k3 in range(0, ref_other + 1):
                                s = a + b1 + b2 + k2 + k3
                                if s < 1 or s > max_arity:
                                    continue
                                ways = comb(u_other, k2) * comb(ref_other, k3)
                                if ways == 0:
                                    continue
                                # classify op p
                                isA = (b1 == 1 and s == 1)
                                isB = False
                                if has_t2slot:
                                    isB = (b1 == 1 and b2 == 1 and s == 2 and prevA)
                                else:
                                    # p==2: B pattern = {x, t_1} with op1=A(x)
                                    isB = (b1 == 1 and a == 1 and s == 2 and prevA)
                                reads_prev = (b1 == 1)
                                isJoin = (s == 2 and b1 == 1 and not isB)
                                # spine: ops 2..4 must read t_{p-1}
                                spine2 = spine and (reads_prev if p <= 4 else True)
                                # violation?
                                if isA or isB:
                                    lv2 = lvcls
                                else:
                                    if p <= 3:
                                        lv2 = LV_LE3
                                    elif p == 4:
                                        if isJoin:
                                            lv2 = LV_EQ4_JOIN
                                        elif reads_prev:
                                            lv2 = LV_EQ4_OTH_T3
                                        else:
                                            lv2 = LV_EQ4_OTH_NOT3
                                    else:
                                        lv2 = LV_GE5_JOIN if isJoin else LV_GE5_OTH
                                u2 = u - (b1 + (b2 if (has_t2slot and w) else 0) + k2) + 1
                                w2 = not reads_prev
                                xr2 = xr or (a == 1)
                                new[(u2, w2, xr2, isA, lv2, spine2)] += cnt * ways
        states = new
    out = defaultdict(int)
    for (u, w, xr, prevA, lvcls, spine), cnt in states.items():
        # after op n: t_n is the output (needn't be read); all t_1..t_{n-1}
        # must be referenced => unref set must be exactly {t_n} => u == 1
        if u == 1 and xr:
            out[(lvcls, spine)] += cnt
    return out


# ---- brute-force validation for small n ----
def brute(n, max_arity=3):
    from collections import defaultdict
    results = defaultdict(int)

    def rec(p, sets):
        if p == n + 1:
            # validity
            read = set()
            for S in sets:
                read |= S
            if 0 not in read:  # x = slot 0
                return
            for t in range(1, n):  # t_1..t_{n-1} = slots 1..n-1
                if t not in read:
                    return
            # classify
            lv = 0
            lvtype = None
            prevA = [False] * (n + 1)
            prevA[1] = True  # op1 = {x}
            for q in range(2, n + 1):
                S = sets[q - 1]
                isA = (S == {q - 1})
                isB = (S == {q - 2, q - 1}) and prevA[q - 1]
                prevA[q] = isA
                if not (isA or isB):
                    lv = q
                    lvtype = ('join' if (len(S) == 2 and (q - 1) in S) else 'oth',
                              (q - 1) in S)
            spine = all((q - 1) in sets[q - 1] for q in range(2, min(4, n) + 1))
            if lv <= 3:
                cls = LV_LE3
            elif lv == 4:
                if lvtype[0] == 'join':
                    cls = LV_EQ4_JOIN
                elif lvtype[1]:
                    cls = LV_EQ4_OTH_T3
                else:
                    cls = LV_EQ4_OTH_NOT3
            else:
                cls = LV_GE5_JOIN if lvtype[0] == 'join' else LV_GE5_OTH
            results[(cls, spine)] += 1
            return
        slots = list(range(0, p))  # 0 = x, i = t_i
        from itertools import combinations
        for s in range(1, max_arity + 1):
            for S in combinations(slots, s):
                sets.append(set(S))
                rec(p + 1, sets)
                sets.pop()

    rec(2, [{0}])  # op1 reads {x}
    return results


def report(n):
    r = census(n)
    tot = sum(r.values())
    p5b = sum(c for (cls, sp), c in r.items() if cls == LV_LE3)
    p5d_new = sum(c for (cls, sp), c in r.items() if cls == LV_EQ4_JOIN)
    kf4c = sum(c for (cls, sp), c in r.items()
               if sp and cls in (LV_LE3, LV_EQ4_JOIN, LV_EQ4_OTH_T3))
    kf4c_only = sum(c for (cls, sp), c in r.items()
                    if sp and cls == LV_EQ4_OTH_T3)
    eq4_uncov = sum(c for (cls, sp), c in r.items()
                    if (cls == LV_EQ4_OTH_NOT3) or (cls == LV_EQ4_OTH_T3 and not sp))
    ge5_join = sum(c for (cls, sp), c in r.items() if cls == LV_GE5_JOIN)
    ge5_oth = sum(c for (cls, sp), c in r.items() if cls == LV_GE5_OTH)
    print(f"n = {n} ops (single input x):")
    print(f"  TOTAL valid wiring shapes:                {tot:>18,}")
    print(f"  P5-B covered (lv<=3, kf3full+chain):      {p5b:>18,}  ({100*p5b/tot:.2f}%)")
    print(f"  P5-D NEW (join at 4 = kf3+join+chain):    {p5d_new:>18,}  ({100*p5d_new/tot:.2f}%)")
    print(f"  kf4chained would ALSO add (spine,lv=4,t3):{kf4c_only:>18,}  ({100*kf4c_only/tot:.2f}%)")
    print(f"      (kf4c total incl overlap w/ above:    {kf4c:>18,})")
    print(f"  lv=4 other (uncov by all):                {eq4_uncov:>18,}  ({100*eq4_uncov/tot:.2f}%)")
    print(f"  lv>=5 JOIN-type (deep single-r fanout):   {ge5_join:>18,}  ({100*ge5_join/tot:.2f}%)")
    print(f"  lv>=5 OTHER (deep multi/madd fanout):     {ge5_oth:>18,}  ({100*ge5_oth/tot:.2f}%)")
    uncov = tot - p5b - p5d_new - kf4c_only
    print(f"  => UNCOVERED after P5-B+P5-D+kf4c:        {uncov:>18,}  ({100*uncov/tot:.2f}%)")
    return tot, p5b, p5d_new, uncov


if __name__ == "__main__":
    if "--validate" in sys.argv:
        for n in (3, 4, 5, 6):
            b = brute(n)
            d = census(n)
            ok = dict(b) == {k: v for k, v in d.items() if v}
            print(f"validate n={n}: brute total={sum(b.values())} dp total={sum(d.values())} "
                  f"per-class match: {'PASS' if ok else 'FAIL'}")
            if not ok:
                print("  brute:", dict(sorted(b.items())))
                print("  dp:   ", dict(sorted((k, v) for k, v in d.items() if v)))
                sys.exit(1)
        sys.exit(0)
    for n in (9, 10, 11):
        report(n)
        print()
