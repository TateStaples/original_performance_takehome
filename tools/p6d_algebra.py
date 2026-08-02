#!/usr/bin/env python3
"""P6-D: the ANY-PARITY differential-count theorem (extends p5i sec.9), and its
numeric guard.

Setting (p5i/STATE.md sec.9 notation, word width w; w=32 in production):
  perturbation x -> x ^ 2^(w-1);  u = w-1-s1 >= 1;  t = s1+s2-(w-1) >= 1;
  s2 = u+t <= w-2;  c = the value feeding the single madd (K2,C2) that reaches
  shr B;  x -> c a bijection (T6a);  e = K2*c + C2.

  c* - c = 2^(w-1) + sg*2^u,  sg = 1-2*c_u                 (exact, any K2)
  e* - e = K2*2^(w-1) + sg*K2*2^u   -- the first term is 2^(w-1) (K2 odd) or 0
        (K2 even) and in EITHER case touches only bit w-1, invisible at bit
        s2 <= w-2.  So, for any K2,
  D = bit_{s2}(e*) ^ bit_{s2}(e) = K2_t ^ [A+q >= 2^t]   (c_u=0)
                                 = K2_t ^ [A <  q]       (c_u=1)
  with A = bits u..u+t-1 of e, q = K2 mod 2^t, K2_t = bit t of K2.
  Sec.9 assumed K2 ODD (forced there by transfer condition T6b: shr-B's input
  slot is a DAG cut).  Nothing above uses the parity; only the COUNT does.

THEOREM P6D-1 (unified count).  Let v := v2(K2), k := K2 >> v (odd),
C' := C2 >> v, and M := #{c : D ^ K2_t = 1}.  Then N = M or 2^w - M by K2_t and
    v >= t :  q = 0, D = K2_t is CONSTANT, so M = 0 and N in {0, 2^w};
    v <  t :  M = 2^(w-t+v) * (q'-1)  +  2^(w+1-s2+v) * n_1,
              q' := k mod 2^(t-v)  (ODD),
              n_1 := #{c_lo < 2^u : bit_u(k*c_lo + C') = 1}  in [0, 2^u].
v = 0 reproduces sec.9 verbatim.  So sec.9's identity is the v=0 slice of a
one-parameter family: **substituting (t, q, C2) -> (t-v, q', C2>>v) and scaling
by 2^v is the whole even-K2 correction.**

Proof.  Write C2 = 2^v C' + r, 0 <= r < 2^v.  Then e = 2^v*s + r with
s := (k c + C') mod 2^(w-v), so bit_j(e) = bit_{j-v}(s) for j >= v.
(1) REDUCTION.  Split A = A_lo + 2^v*A_hi, A_lo := bits u..u+v-1 of e < 2^v,
    A_hi := bits u+v..u+t-1 of e, and q = 2^v q' with q' odd.  Because
    A_lo < 2^v and A_hi + q' is an integer,
       A + q >= 2^t  <=>  A_hi + q' >= 2^(t-v),      A < q  <=>  A_hi < q'.
    So D is the sec.9 differential with the window (t, q) replaced by
    (t-v, q') read at bit offset u+v instead of u.
(2) LOW BIT.  Split c = c_hi*2^(u+1) + c_u*2^u + c_lo.  The c_hi term
    2^(u+v+1) k c_hi is divisible by 2^(u+v+1); the c_u term is 2^(u+v) k c_u
    whose bit u+v is c_u (k odd) and which carries nothing below bit u+v.  So
       bit_{u+v}(e) = g(c_lo) ^ c_u,  g(c_lo) := bit_{u+v}(K2 c_lo + C2)
                                               = bit_u(k c_lo + C')
    (the last equality from e = 2^v(kc+C')+r with r < 2^v).
    **This is where the earlier naive guess fails**: bit u+v of A DOES depend on
    c_u even for even K2 -- the c_u term survives at offset u+v, not at u.
(3) HIGH BITS.  bits u+v+1..u+t-1 of e are (k c_hi + carry) mod 2^(t-v-1),
    EXACTLY uniform over c_hi (k odd; needs w-u-1 >= t-v-1, true as s2<=w-2),
    with 2^(w-u-1)/2^(t-v-1) = 2^(w-s2+v) values of c_hi per residue.
(4) COUNT.  With A_hi = (g ^ c_u) + 2V, V uniform on [0,2^(t-v-1)), the sec.9
    computation runs verbatim at parameter (t-v, q'):
       alpha(p) = #{V : p+2V+q' >= 2^(t-v)} = (q'-1)/2 + p,
       beta(p)  = #{V : p+2V < q'}          = alpha(p^1)   (q' odd),
       M = 2^(w-s2+v) * sum_{c_lo} [alpha(g) + beta(g^1)]
         = 2^(w-s2+v) * [2^u (q'-1) + 2 n_1]
         = 2^(w-t+v)(q'-1) + 2^(w+1-s2+v) n_1.                            QED

COROLLARY P6D-2 (sec.9's divisibility needs T6a but NOT T6b).
  v2(M) >= min(w-t+v, w+1-s2+v) = w+1-s2+v >= w+1-s2  (u >= 1),  so
        N == 0  (mod 2^(w+1-s2))   for EVERY K2, of either parity.
Hence the s2 <= 14 mass kill (33-s2 > v2(N_myhash) = 18) transfers to every
shape satisfying T1-T5 + T6a, cut or no cut.

COROLLARY P6D-3 (the even branches, at w=32, N_myhash = 2^18*A).
  2^(33-s2+v) | N forces v <= s2-15 (so s2 >= 16 for any even branch), and then
        Ntilde_v = A * 2^(s2-15-v) = Ntilde_0 / 2^v,
        n_1 = Ntilde_v mod 2^u,  Q = Ntilde_v >> u,  q' = 2Q+1  (< 2^(t-v)),
  which is p5i sec.12's arithmetic with t -> t-v.  The sec.12 realizability
  filter therefore applies branch-by-branch with LB = lower_bound_m(u, t-v, q').
  A pair is ALIVE iff SOME v in 0..min(t-1, s2-15) and some N-branch survives.
"""
import argparse
import json
import random
import sys

sys.path.insert(0, "tools")

SAND9 = [("madd", 0), ("shr", 1), ("xor2", 1, 2), ("madd", 3), ("shr", 4),
         ("xor2", 4, 5), ("madd", 6)]


def v2(n):
    return (n & -n).bit_length() - 1 if n else 999


def predicted_M(w, K2, C2, s1, s2):
    """THEOREM P6D-1, any parity."""
    u = w - 1 - s1
    t = s1 + s2 - (w - 1)
    v = v2(K2)
    if v >= t:
        return 0
    k = K2 >> v
    Cp = C2 >> v
    qp = k % (1 << (t - v))
    msk = (1 << w) - 1
    n1 = sum(1 for cl in range(1 << u)
             if (((k * cl + Cp) & msk) >> u) & 1)
    return (1 << (w - t + v)) * (qp - 1) + (1 << (w + 1 - s2 + v)) * n1


def eval_np(ops, consts, shifts, w, xs):
    import numpy as np
    mask = np.uint64((1 << w) - 1)
    slots = [xs]
    ci = si = 0
    for op in ops:
        if op[0] == "madd":
            K, C = consts[ci]; ci += 1
            slots.append((slots[op[1]] * np.uint64(K) + np.uint64(C)) & mask)
        elif op[0] == "xorc":
            C = consts[ci][1]; ci += 1
            slots.append(slots[op[1]] ^ np.uint64(C))
        elif op[0] == "shr":
            slots.append(slots[op[1]] >> np.uint64(shifts[si])); si += 1
        else:
            slots.append(slots[op[1]] ^ slots[op[2]])
    return slots[-1]


def const_index(ops, op_idx):
    return sum(1 for k, o in enumerate(ops) if k < op_idx
               and o[0] in ("madd", "xorc"))


def guard(ops, a_idx, b_idx, k2_idx, w=14, trials=3, seed=1, verbose=False,
          parity="even"):
    """brute force N over all 2^w inputs; check P6D-1 (FORM) and P6D-2 (DIV)."""
    import numpy as np
    rng = random.Random(seed)
    xs = np.arange(1 << w, dtype=np.uint64)
    shrs = [k for k, o in enumerate(ops) if o[0] == "shr"]
    order = (shrs.index(a_idx), shrs.index(b_idx))
    nc = sum(1 for o in ops if o[0] in ("madd", "xorc"))
    ck2 = const_index(ops, k2_idx)
    bad_div = bad_form = tested = 0
    vseen = set()
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            t = s1 + s2 - (w - 1)
            u = w - 1 - s1
            if parity == "t0":
                if t != 0 or u < 1 or s2 > w - 2:
                    continue
            elif t < 1 or u < 1 or s2 > w - 2:
                continue
            shifts = [0, 0]
            shifts[order[0]] = s1
            shifts[order[1]] = s2
            for _ in range(trials):
                consts = [[rng.getrandbits(w) | 1, rng.getrandbits(w)]
                          for _ in range(nc)]
                if parity == "mixed":
                    # EVERY madd/xorc constant gets a random 2-adic valuation:
                    # tests the whole parity split, not just K2's.
                    for cc in consts:
                        vv = rng.choice([0, 0, 1, 2, rng.randint(1, w - 2)])
                        cc[0] = (cc[0] << vv) % (1 << w) or (1 << vv)
                elif parity == "even":
                    v = rng.randint(1, w - 2)
                    K2 = ((rng.getrandbits(max(1, w - v)) | 1) << v) % (1 << w)
                    if K2 == 0:
                        K2 = 1 << v
                elif parity == "odd":
                    K2 = rng.getrandbits(w) | 1
                elif parity == "t0":
                    # row-31 control: ANY parity; P6D-1 with t=0 predicts M=0,
                    # i.e. a CONSTANT differential, N in {0, 2^w} (sec.2 says
                    # N = 2^w for odd K2; N = 0 is the new even-K2 case).
                    vv = rng.randint(0, w - 2)
                    K2 = ((rng.getrandbits(max(1, w - vv)) | 1) << vv) % (1 << w)
                    K2 = K2 or (1 << vv)
                if parity != "mixed":
                    consts[ck2][0] = K2
                K2 = consts[ck2][0]
                vseen.add(v2(K2))
                o0 = eval_np(ops, consts, shifts, w, xs) & np.uint64(1)
                o1 = eval_np(ops, consts, shifts, w,
                             xs ^ np.uint64(1 << (w - 1))) & np.uint64(1)
                N = int((o0 ^ o1).sum())
                M = predicted_M(w, K2, consts[ck2][1], s1, s2)
                tested += 1
                if N % (1 << (w + 1 - s2)):
                    bad_div += 1
                    if verbose:
                        print("  DIV-VIOL s=(%d,%d) v=%d N=%d"
                              % (s1, s2, v2(K2), N))
                ok_form = N in (M, (1 << w) - M)
                if parity == "mixed":
                    # an even madd elsewhere may make the whole bit-0
                    # differential CONSTANT: N in {0, 2^w} is then legal too.
                    ok_form = ok_form or N in (0, 1 << w)
                if not ok_form:
                    bad_form += 1
                    if verbose:
                        print("  FORM-VIOL s=(%d,%d) K2=%d(v=%d) C2=%d N=%d M=%d"
                              % (s1, s2, K2, v2(K2), consts[ck2][1], N, M))
    return bad_div, bad_form, tested, sorted(vseen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=14)
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--parity", default="even")
    ap.add_argument("--shapes", default="sand9")
    ap.add_argument("--limit", type=int, default=6)
    a = ap.parse_args()
    import p5i3_transfer as T
    import p6d_extend as X
    todo = []
    if "sand9" in a.shapes:
        todo.append((328, SAND9))
    if "queue" in a.shapes:
        q = json.load(open("tools/p5k_queue.json"))
        cut, evn = [], []
        for e in q["entries"]:
            ops = [tuple(o) for o in e["ops"]]
            if sum(1 for o in ops if o[0] == "shr") != 2:
                continue
            why = set()
            if T.shape_transfers(ops, why):
                continue
            if "shrB-input-not-a-cut" in why:
                cut.append((e["rank"], ops))
            elif "even-K parity branch not constant" in why:
                evn.append((e["rank"], ops))
        rng = random.Random(7)
        todo += rng.sample(cut, min(a.limit, len(cut)))
        todo += rng.sample(evn, min(a.limit, len(evn)))
    for rank, ops in todo:
        r = X.extended_transfer([tuple(o) for o in ops])
        if not r:
            print("rank=%d NO-EXT-TRANSFER" % rank)
            continue
        a_idx, b_idx, c_slot, k2_idx, modes = r
        bd, bf, n, vs = guard(ops, a_idx, b_idx, k2_idx, w=a.w,
                              trials=a.trials, seed=rank, verbose=True,
                              parity=a.parity)
        print("GUARD-%s rank=%-5d w=%d tested=%d DIV-VIOL=%d FORM-VIOL=%d "
              "v2seen=%s ops=%s"
              % (a.parity.upper(), rank, a.w, n, bd, bf, vs, ops))


if __name__ == "__main__":
    main()
