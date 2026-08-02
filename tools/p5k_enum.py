#!/usr/bin/env python3
"""P5-K: shape-level COMPLETENESS for the 9-op myhash question.

Enumerates ALL 9-op DAG shapes over the P5-D template vocabulary
  madd(i): t = v[i]*K + C   (K, C free 32-bit)
  shr(i) : t = v[i] >> s    (s free 1..31)
  xorc(i): t = v[i] ^ C     (C free)
  xor2(i,j): t = v[i] ^ v[j]
Slots: 0 = x; op k (0-based) produces slot k+1; output = slot n.
Validity: every slot 1..n-1 read by a later op (=> all ops on the output
cone; every slot reaches both x and out).

SOUND KILL FILTERS (each kills a shape only with a proof that NO constant
assignment can make it compute myhash, OR with an instance-preserving map
into a shape that stays in the enumeration / into the <=8-op family):

K1 (#shr >= 2)  -- MINIMUM-SHR THEOREM. myhash out bit0 depends on x bit31
   (witness 0x4E005510 / 0xCE005510) and D_{2^31} out0 is NONCONSTANT
   (witness 0x4679814A gives 0, 0x4E005510 gives 1).  In any shape with
   <= 1 shr: (a) shr shift s<=30 => out0 is a function of x mod 2^31
   (backward bit-cone: madd/xorc/xor2 are bit-triangular, only shr moves
   info downward, max displacement = s), refuted by witness A; (b) s=31 =>
   for ALL constants D_{2^31} out0 is CONSTANT (upstream of the shr the
   x^2^31 perturbation stays exactly at bit31 since x^2^31 = x+2^31 and
   madd(x+2^31)=madd(x)^ (K odd?2^31:0), xorc/xor2 exact; the shr turns it
   into a constant bit0 flip; downstream, bit0 of every slot flips by a
   constant: madd bit0 flip = K0 & argflip, xorc/xor2 exact xor of
   constant flips; bypass branches perturb only bit31 which cannot reach
   bit0 without a second shr), refuted by witness B. Numerically validated
   below (--selftest).

K2 (no shr at a DAG cut vertex, incl. the output op)  -- myhash is a
   bijection.  If every x->out path passes through slot v then (since
   every slot is reachable from x) no downstream op reads a pre-v slot, so
   out = G(v), v = F(x), and |range| = 2^32 forces both F and G bijective.
   If v is a shr output, range(F) <= 2^31: dead for every constant.

R-filters (instance-preserving reductions; killed shapes either reduce to
   <= 8 effective ops -- a strictly stronger find, tracked as the separate
   n=8 sub-question -- or map to a partner 9-op shape that remains
   enumerated):
R1 fanout-1 same-type unary chains madd->madd (compose to one madd),
   shr->shr (one shr or constant 0), xorc->xorc (one xorc): <=8-op family.
R2 fanout-1 xorc feeding shr or xor2: (v^C)>>s = (v>>s)^(C>>s) and
   (v^C)^b = (v^b)^C -- every instance is an instance of the partner shape
   with the xorc AFTER (same op count; partner enumerated). Canonical
   form: every fanout-1 xorc feeds a madd or is the final op.
R3 xor2(i,j) with producer(j)=xorc(i) (or sym., or both xorc of the same
   slot): output is a CONSTANT; constants fold into consumers: <=8-op.
R4 xor2(i,j) with producer(j)=xor2 containing i (or sym.): output equals
   the other xor2 argument: <=8-op.

DEDUPE: exact canonical linearization (lex-min topological order over
(typecode, mapped-args) keys, ties branched); xor2 args sorted.  An
adjacent-transposition local-min prune during DFS removes most
non-canonical linearizations early (sound: a violating sequence is
lex-greater than its swap, hence not canonical).
"""
import sys, os, json, time, random, argparse
from collections import Counter, defaultdict
from math import comb

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from p5d_cegis import myhash, eval_template_py, delete_ops, REAL_11, MASK  # noqa

TC = {"madd": 0, "shr": 1, "xorc": 2, "xor2": 3}
TN = {v: k for k, v in TC.items()}
UNARY = ("madd", "shr", "xorc")

WITNESS_A = 0x4E005510   # myhash(x)_0 != myhash(x^2^31)_0
WITNESS_B = 0x4679814A   # myhash(x)_0 == myhash(x^2^31)_0


# ---------------------------------------------------------------- theorem
def check_witnesses():
    da = (myhash(WITNESS_A) ^ myhash(WITNESS_A ^ 0x80000000)) & 1
    db = (myhash(WITNESS_B) ^ myhash(WITNESS_B ^ 0x80000000)) & 1
    return da == 1 and db == 0


def rand_consts(ops, rng):
    cs = []
    for op in ops:
        if op[0] == "madd":
            cs += [rng.getrandbits(32), rng.getrandbits(32)]
        elif op[0] == "shr":
            cs.append(rng.randrange(1, 32))
        elif op[0] == "xorc":
            cs.append(rng.getrandbits(32))
    return cs


def d31_constant(ops, consts, rng, npts=48):
    """Is D_{2^31} out0 constant over sampled x for these constants?"""
    d0 = None
    for _ in range(npts):
        x = rng.getrandbits(32)
        d = (eval_template_py(ops, 1, consts, (x,)) ^
             eval_template_py(ops, 1, consts, (x ^ 0x80000000,))) & 1
        if d0 is None:
            d0 = d
        elif d != d0:
            return False
    return True


# ---------------------------------------------------------------- DP counts
def dp_count(n=9, need_shr2=True, forbid_final_shr=True):
    """Exact count of VALID typed sequences (linearizations, pre-dedupe)."""
    states = {(0, 0): 1}   # (unread temps, min(shr,2)) -> count
    for k in range(1, n + 1):
        new = defaultdict(int)
        for (u, sc), cnt in states.items():
            rd = k - u          # readable already-read slots incl x
            for typ in ("madd", "shr", "xorc"):
                sc2 = min(2, sc + 1) if typ == "shr" else sc
                if k == n and typ == "shr" and forbid_final_shr:
                    continue
                if u:
                    new[(u, sc2)] += cnt * u          # read an unread slot
                new[(u + 1, sc2)] += cnt * rd         # read a read slot
            # xor2
            if u >= 2:
                new[(u - 1, sc)] += cnt * comb(u, 2)
            if u >= 1 and rd >= 1:
                new[(u, sc)] += cnt * u * rd
            if rd >= 2:
                new[(u + 1, sc)] += cnt * comb(rd, 2)
        states = dict(new)
    tot = 0
    for (u, sc), cnt in states.items():
        if u == 1 and (sc >= 2 or not need_shr2):
            tot += cnt
    return tot


def dp_count_stratum(n, m, s, c, x2, need_final_not_shr=True):
    """Valid typed sequences for a fixed op-type multiset."""
    states = {(0, 0, 0, 0, 0): 1}  # u, m,s,c,x used
    for k in range(1, n + 1):
        new = defaultdict(int)
        for (u, um, us, uc, ux), cnt in states.items():
            rd = k - u
            for typ, used, cap in (("madd", um, m), ("shr", us, s),
                                   ("xorc", uc, c)):
                if used >= cap:
                    continue
                if k == n and typ == "shr" and need_final_not_shr:
                    continue
                d = {"madd": (1, 0, 0), "shr": (0, 1, 0),
                     "xorc": (0, 0, 1)}[typ]
                key_add = (um + d[0], us + d[1], uc + d[2], ux)
                if u:
                    new[(u,) + key_add] += cnt * u
                new[(u + 1,) + key_add] += cnt * rd
            if ux < x2:
                key_add = (um, us, uc, ux + 1)
                if u >= 2:
                    new[(u - 1,) + key_add] += cnt * comb(u, 2)
                if u >= 1 and rd >= 1:
                    new[(u,) + key_add] += cnt * u * rd
                if rd >= 2:
                    new[(u + 1,) + key_add] += cnt * comb(rd, 2)
        states = dict(new)
    return sum(cnt for (u, um, us, uc, ux), cnt in states.items()
               if u == 1 and (um, us, uc, ux) == (m, s, c, x2))


def raw_count(n=9):
    p = 1
    for k in range(1, n + 1):
        p *= 3 * k + comb(k, 2)
    return p


# ------------------------------------------------------------- canonical
def canon(ops):
    """Exact lex-min topological linearization. Returns (key, canon_ops)."""
    n = len(ops)
    args_of = [tuple(op[1:]) for op in ops]
    typ_of = [op[0] for op in ops]
    best = [None]

    def rec(mapping, placed_mask, prefix):
        p = len(prefix)
        if p == n:
            t = tuple(prefix)
            if best[0] is None or t < best[0]:
                best[0] = t
            return
        cands = []
        for oi in range(n):
            if placed_mask & (1 << oi):
                continue
            ok = True
            for a in args_of[oi]:
                if a != 0 and not (placed_mask >> (a - 1)) & 1:
                    ok = False
                    break
            if ok:
                na = tuple(sorted(mapping[a] for a in args_of[oi]))
                cands.append(((TC[typ_of[oi]], na), oi))
        mink = min(k for k, _ in cands)
        for k, oi in cands:
            if k != mink:
                continue
            mapping[oi + 1] = p + 1
            rec(mapping, placed_mask | (1 << oi), prefix + [k])
            del mapping[oi + 1]

    rec({0: 0}, 0, [])
    key = best[0]
    cops = []
    for (tc, na) in key:
        cops.append((TN[tc],) + tuple(na))
    return key, cops


# ------------------------------------------------------------- kill checks
def final_kill(ops, n):
    """Post-completion kills. Returns reason string or None."""
    reads = Counter()
    for op in ops:
        for a in op[1:]:
            reads[a] += 1
    # R1/R2 fanout-1 patterns
    consumers = defaultdict(list)
    for k, op in enumerate(ops):
        for a in op[1:]:
            consumers[a].append(k)
    for v in range(1, n):
        if reads[v] == 1:
            pt = ops[v - 1][0]
            ct = ops[consumers[v][0]][0]
            if pt == ct and pt in UNARY:
                return "R1"
            if pt == "xorc" and ct in ("shr", "xor2"):
                return "R2"
    # K2: cut check per shr (and any final shr, pre-filtered anyway)
    if ops[n - 1][0] == "shr":
        return "K2-final"
    for v in range(1, n):
        if ops[v - 1][0] != "shr":
            continue
        # reachability 0 -> n avoiding v
        seen = {0}
        stack = [0]
        hit = False
        while stack:
            s0 = stack.pop()
            for k in consumers[s0]:
                t = k + 1
                if t == v or t in seen:
                    continue
                if t == n:
                    hit = True
                    break
                seen.add(t)
                stack.append(t)
            if hit:
                break
        if not hit:
            return "K2-cut"
    return None


def features(cops):
    n = len(cops)
    cnt = Counter(op[0] for op in cops)
    reads = Counter()
    for op in cops:
        for a in op[1:]:
            reads[a] += 1
    maxfan = max(reads.values())
    sigma = 0
    for op in cops:
        if op[0] == "xor2":
            i, j = op[1], op[2]
            for a, b in ((i, j), (j, i)):
                if b >= 1 and cops[b - 1][0] == "shr" and cops[b - 1][1] == a:
                    sigma += 1
                    break
    # max #shr on any x->out path
    best = [0] * (n + 1)
    for k, op in enumerate(cops):
        m = max(best[a] for a in op[1:])
        best[k + 1] = m + (1 if op[0] == "shr" else 0)
    twopath = best[n]
    return {"m": cnt["madd"], "s": cnt["shr"], "c": cnt["xorc"],
            "x2": cnt["xor2"], "maxfan": maxfan, "sigma": sigma,
            "shrpath": twopath}


def score(f):
    dm = 0 if f["m"] in (3, 4) else min(abs(f["m"] - 3), abs(f["m"] - 4))
    return (dm, f["s"] - 2, max(0, 2 - f["sigma"]),
            0 if f["shrpath"] >= 2 else 1, max(0, f["maxfan"] - 2),
            max(0, f["c"] - 2), max(0, f["x2"] - 3))


def stratum_score(m, s, c, x2):
    dm = 0 if m in (3, 4) else min(abs(m - 3), abs(m - 4))
    ds = s - 2
    dc = 0 if c in (1, 2) else min(abs(c - 1), abs(c - 2))
    dx = 0 if x2 in (2, 3) else min(abs(x2 - 2), abs(x2 - 3))
    return (dm + ds + dc + dx, dm, ds, dc, dx)


# ------------------------------------------------------------ enumeration
def enumerate_stratum(n, m, s, c, x2, cap=None, kills=True):
    """DFS over typed sequences of the multiset; canonical dedupe; kills.
    Returns (shapes dict key->(cops, feats), stats Counter, capped flag)."""
    rem = {"madd": m, "shr": s, "xorc": c, "xor2": x2}
    ops = []
    reads = [0] * (n + 1)
    stats = Counter()
    seen = {}
    capped = [False]

    def rec(t, u):
        if capped[0]:
            return
        if t == n:
            stats["complete"] += 1
            if u != 1:
                stats["invalid"] += 1
                return
            if kills:
                r = final_kill(ops, n)
                if r:
                    stats[r] += 1
                    return
            key, cops = canon(ops)
            if key in seen:
                stats["dup"] += 1
            else:
                seen[key] = (cops, features(cops))
                if cap and len(seen) > cap:
                    capped[0] = True
            return
        m_rem = n - t
        cap_args = rem["madd"] + rem["shr"] + rem["xorc"] + 2 * rem["xor2"]
        if cap_args < u + m_rem - 1:
            return
        prev = ops[t - 1] if t else None
        prevkey = (TC[prev[0]], tuple(sorted(prev[1:]))) if prev else None

        def place(op, du):
            for a in op[1:]:
                reads[a] += 1
            ops.append(op)
            rec(t + 1, u + du + 1)
            ops.pop()
            for a in op[1:]:
                reads[a] -= 1

        for typ in UNARY:
            if rem[typ] == 0:
                continue
            if kills and typ == "shr" and t == n - 1:
                continue
            rem[typ] -= 1
            for i in range(t + 1):
                op = (typ, i)
                if prev and i != t:  # independent of prev op
                    if prevkey > (TC[typ], (i,)):
                        continue
                place(op, -1 if (i >= 1 and reads[i] == 0) else 0)
            rem[typ] += 1
        if rem["xor2"]:
            rem["xor2"] -= 1
            for i in range(t + 1):
                for j in range(i + 1, t + 1):
                    if kills:
                        pj = ops[j - 1] if j >= 1 else None
                        pi = ops[i - 1] if i >= 1 else None
                        # R3
                        if pj and pj == ("xorc", i):
                            continue
                        if pi and pi == ("xorc", j):
                            continue
                        if (pi and pj and pi[0] == "xorc" and
                                pj[0] == "xorc" and pi[1] == pj[1]):
                            continue
                        # R4
                        if pj and pj[0] == "xor2" and i in pj[1:]:
                            continue
                        if pi and pi[0] == "xor2" and j in pi[1:]:
                            continue
                    op = ("xor2", i, j)
                    if prev and j != t:
                        if prevkey > (TC["xor2"], (i, j)):
                            continue
                    du = 0
                    if i >= 1 and reads[i] == 0:
                        du -= 1
                    if j >= 1 and reads[j] == 0:
                        du -= 1
                    place(op, du)
            rem["xor2"] += 1

    rec(0, 0)
    return seen, stats, capped[0]


def all_strata(n=9, min_shr=2, min_x2=1):
    out = []
    for m in range(0, n + 1):
        for s in range(min_shr, n + 1):
            for c in range(0, n + 1):
                x2 = n - m - s - c
                if x2 < min_x2:
                    continue
                out.append((m, s, c, x2))
    out.sort(key=lambda t: stratum_score(*t))
    return out


# ------------------------------------------------------------- normalize
def normalize(ops):
    """Rewrite to canonical form (R2 commutes xorc later; R1/R3/R4 merges
    reduce). Returns ('OK', canon_key, cops) or ('REDUCES', nops, None)."""
    nodes = {}  # id -> (type, args)
    for k, op in enumerate(ops):
        nodes[k + 1] = (op[0], tuple(op[1:]))
    out_id = len(ops)
    changed = True
    while changed:
        changed = False
        cons = defaultdict(list)
        for nid, (t, a) in nodes.items():
            for x in a:
                if x != 0:
                    cons[x].append(nid)
        for nid in list(nodes):
            t, a = nodes[nid]
            if t == "xorc" and len(cons[nid]) == 1 and nid != out_id:
                w = cons[nid][0]
                wt, wa = nodes[w]
                if wt == "shr":
                    nodes[nid] = ("shr", a)
                    nodes[w] = ("xorc", (nid,))
                    changed = True
                    break
                if wt == "xor2":
                    other = [z for z in wa if z != nid]
                    if len(other) == 1:
                        if other[0] == a[0]:
                            # xor2(v, xorc(v)) = constant: R3 degenerate
                            return ("REDUCES", len(nodes) - 1, None)
                        nodes[nid] = ("xor2", tuple(sorted((a[0], other[0]))))
                        nodes[w] = ("xorc", (nid,))
                        changed = True
                        break
                if wt == "xorc":
                    return ("REDUCES", len(nodes) - 1, None)
            if t in UNARY and len(cons[nid]) == 1 and nid != out_id:
                w = cons[nid][0]
                if nodes[w][0] == t and nodes[w][1] == (nid,):
                    return ("REDUCES", len(nodes) - 1, None)
            if t == "xor2":
                i, j = a
                for p, q in ((i, j), (j, i)):
                    if q != 0 and nodes[q][0] == "xorc" and \
                            nodes[q][1] == (p,):
                        return ("REDUCES", len(nodes) - 1, None)
                    if q != 0 and nodes[q][0] == "xor2" and \
                            p in nodes[q][1]:
                        return ("REDUCES", len(nodes) - 1, None)
                if i != 0 and j != 0 and nodes[i][0] == "xorc" and \
                        nodes[j][0] == "xorc" and nodes[i][1] == nodes[j][1]:
                    return ("REDUCES", len(nodes) - 1, None)
    # relinearize (nodes ids arbitrary but acyclic); topo order then canon
    order = []
    placed = {0}
    while len(order) < len(nodes):
        for nid in sorted(nodes):
            if nid in placed:
                continue
            if all(x in placed for x in nodes[nid][1]):
                order.append(nid)
                placed.add(nid)
    remap = {0: 0}
    lin = []
    for k, nid in enumerate(order):
        remap[nid] = k + 1
        t, a = nodes[nid]
        na = tuple(sorted(remap[x] for x in a))
        lin.append((t,) + na)
    key, cops = canon(lin)
    return ("OK", key, cops)


# ------------------------------------------------------------- selftest
def selftest():
    ok = True
    print("witnesses:", "PASS" if check_witnesses() else "FAIL")
    ok &= check_witnesses()
    # Theorem numeric: 1-shr shapes must have constant D_{2^31} out0
    rng = random.Random(1)
    n1 = 0
    for (m, s, c, x2) in all_strata(6, min_shr=1, min_x2=0):
        if s != 1:
            continue
        shapes, _, _ = enumerate_stratum(6, m, s, c, x2, cap=40, kills=False)
        for key, (cops, f) in list(shapes.items())[:8]:
            for _ in range(3):
                cs = rand_consts(cops, rng)
                if not d31_constant(cops, cs, rng):
                    print("THEOREM VIOLATION", cops, cs)
                    ok = False
                n1 += 1
    print(f"theorem T1 numeric: {n1} (shape,const) trials, all constant-D")
    # negative control: 2-shr shapes with real-form-like structure must
    # show NONconstant D for generic constants (proves the test has teeth)
    SWc = [("madd", 0), ("shr", 1), ("xor2", 1, 2), ("xorc", 3),
           ("madd", 4), ("shr", 5), ("xor2", 5, 6), ("xorc", 7),
           ("madd", 8)]
    nc = 0
    tot = 0
    for cops in (REAL_11, SWc):
        for _ in range(12):
            cs = rand_consts(cops, rng)
            # force odd multipliers and s1+s2>=32-ish real-like shifts
            ci = 0
            for op in cops:
                if op[0] == "madd":
                    cs[ci] |= 1
                    ci += 2
                elif op[0] == "shr":
                    cs[ci] = rng.randrange(14, 22)
                    ci += 1
                elif op[0] == "xorc":
                    ci += 1
            tot += 1
            if not d31_constant(cops, cs, rng):
                nc += 1
    print(f"negative control: {nc}/{tot} 2-shr real-like shapes show "
          f"NONconstant D (test has teeth: expect > 0)")
    ok &= nc > 0
    # dedupe validation at n=5: DFS+prune vs brute canon over all sequences
    for stratum in ((1, 2, 0, 2), (2, 2, 0, 1), (1, 2, 1, 1)):
        m, s, c, x2 = stratum
        fast, _, _ = enumerate_stratum(5, m, s, c, x2, kills=False)
        brute = set()
        # brute: raw DFS without adjacent prune = re-run with prev check off
        def rec(t, ops, reads, u, rem):
            if t == 5:
                if u == 1:
                    brute.add(canon(ops)[0])
                return
            for typ in UNARY:
                if rem[typ] == 0:
                    continue
                rem[typ] -= 1
                for i in range(t + 1):
                    du = -1 if (i >= 1 and reads[i] == 0) else 0
                    reads[i] += 1
                    rec(t + 1, ops + [(typ, i)], reads, u + du + 1, rem)
                    reads[i] -= 1
                rem[typ] += 1
            if rem["xor2"]:
                rem["xor2"] -= 1
                for i in range(t + 1):
                    for j in range(i + 1, t + 1):
                        du = sum(-1 for z in (i, j)
                                 if z >= 1 and reads[z] == 0)
                        reads[i] += 1
                        reads[j] += 1
                        rec(t + 1, ops + [("xor2", i, j)], reads,
                            u + du + 1, rem)
                        reads[i] -= 1
                        reads[j] -= 1
                rem["xor2"] += 1
        rec(0, [], [0] * 6, 0,
            {"madd": m, "shr": s, "xorc": c, "xor2": x2})
        match = set(fast.keys()) == brute
        print(f"dedupe n=5 {stratum}: DFS={len(fast)} brute={len(brute)} "
              f"{'PASS' if match else 'FAIL'}")
        ok &= match
    # sandwich9 must canonicalize into the enumeration
    SW = [("madd", 0), ("shr", 1), ("xorc", 1), ("xor2", 2, 3),
          ("madd", 4), ("shr", 5), ("xorc", 5), ("xor2", 6, 7),
          ("madd", 8)]
    st, key, cops = normalize(SW)
    print("sandwich9 normalize:", st, cops if st == "OK" else "")
    ok &= st == "OK"
    print("SELFTEST", "PASS" if ok else "FAIL")
    return ok


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dp", action="store_true")
    ap.add_argument("--strata", action="store_true")
    ap.add_argument("--enum-ranked", action="store_true")
    ap.add_argument("--n", type=int, default=9)
    ap.add_argument("--cap", type=int, default=200000)
    ap.add_argument("--max-strata", type=int, default=200)
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--map", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(0 if selftest() else 1)

    if args.dp:
        n = args.n
        print(f"n={n} raw typed sequences:            {raw_count(n):,}")
        v = dp_count(n, need_shr2=False, forbid_final_shr=False)
        print(f"n={n} VALID sequences (all live):      {v:,}")
        v2 = dp_count(n, need_shr2=True, forbid_final_shr=False)
        print(f"n={n} + K1 (#shr>=2):                  {v2:,}")
        v3 = dp_count(n, need_shr2=True, forbid_final_shr=True)
        print(f"n={n} + final-not-shr:                 {v3:,}")

    if args.strata:
        n = args.n
        tot = 0
        print("stratum (m,s,c,x2) | score | DP valid seqs")
        for st in all_strata(n):
            cnt = dp_count_stratum(n, *st)
            tot += cnt
            print(f"  {st}  {stratum_score(*st)}  {cnt:,}")
        print(f"TOTAL sequences over strata: {tot:,}")

    if args.enum_ranked:
        n = args.n
        t0 = time.time()
        allshapes = []
        totals = Counter()
        strata_report = []
        for st in all_strata(n)[:args.max_strata]:
            m, s, c, x2 = st
            t1 = time.time()
            shapes, stats, capped = enumerate_stratum(
                n, m, s, c, x2, cap=args.cap)
            dt = time.time() - t1
            totals.update(stats)
            totals["shapes"] += len(shapes)
            strata_report.append(
                {"stratum": st, "score": stratum_score(*st),
                 "shapes": len(shapes), "capped": capped,
                 "stats": dict(stats), "secs": round(dt, 1)})
            for key, (cops, f) in shapes.items():
                allshapes.append({"ops": [list(o) for o in cops],
                                  "stratum": list(st),
                                  "feat": f, "score": score(f)})
            print(f"[{time.time()-t0:7.1f}s] {st} shapes={len(shapes)}"
                  f"{' CAPPED' if capped else ''} stats={dict(stats)}",
                  flush=True)
        allshapes.sort(key=lambda e: (tuple(e["score"]),
                                      tuple(map(tuple, e["ops"]))))
        for r, e in enumerate(allshapes):
            e["rank"] = r
        out = args.out or f"/tmp/p5k_shapes_n{n}.json"
        with open(out, "w") as f:
            json.dump({"n": n, "strata": strata_report,
                       "totals": dict(totals),
                       "shapes": allshapes}, f)
        print(f"wrote {len(allshapes)} shapes -> {out}")

    if args.map:
        # ownership mapping: sandwich9 + the 28 deletion shapes
        SW = [("madd", 0), ("shr", 1), ("xorc", 1), ("xor2", 2, 3),
              ("madd", 4), ("shr", 5), ("xorc", 5), ("xor2", 6, 7),
              ("madd", 8)]
        st, key, cops = normalize(SW)
        print("SANDWICH9 ->", st, json.dumps([list(o) for o in cops]))
        UNSAT = [(0, 1), (0, 2), (0, 4), (0, 5), (0, 8), (0, 9), (1, 3),
                 (1, 4), (1, 5), (1, 7), (1, 8), (1, 9), (2, 8), (4, 8),
                 (5, 8), (7, 8)]
        TIMEOUT = [(0, 7), (2, 3), (2, 4), (2, 5), (2, 7), (2, 9), (4, 6),
                   (4, 7), (4, 9), (5, 7), (5, 9), (7, 9)]
        for name, dels in (("UNSAT(P5-D)", UNSAT), ("OPEN(P5-J)", TIMEOUT)):
            for (i, j) in dels:
                for new_ops, desc in delete_ops(REAL_11, 1, {i, j}):
                    if len(new_ops) != 9:
                        continue
                    stt = normalize(new_ops)
                    if stt[0] == "OK":
                        print(f"DEL{list((i,j))} {name} {desc} ->",
                              json.dumps([list(o) for o in stt[2]]))
                    else:
                        print(f"DEL{list((i,j))} {name} {desc} -> "
                              f"REDUCES to {stt[1]} ops")


if __name__ == "__main__":
    main()
