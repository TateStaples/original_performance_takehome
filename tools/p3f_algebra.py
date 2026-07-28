#!/usr/bin/env python3
"""P3-F: global 10-op question for the round body.

Part 1: bit-exact reconstruction + validation of the shipped 11-op round body.
Part 2: the XOR<->ADD dichotomy lemma and the three "op-removal" obstruction
        constants it produces (this is the exact algebraic reason the fold-in
        ^nv and the stage-1 ^C1 xor cannot be pushed into a neighbouring madd).
Part 3: extended-vocabulary 1-op probe over the two-round trace DAG, adding
        the three ISA ops that no prior hash search ever used as general ops:
        // (floor div), % (mod), cdiv (ceil div), by solved constants on
        either side, plus runtime-operand forms.

Read-only. Writes nothing.
"""
import random
import sys

sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome")
from problem import HASH_STAGES, myhash  # noqa: E402

M = (1 << 32) - 1
(o0, C0, _, _, s0) = HASH_STAGES[0]
(_, C1, _, _, s1) = HASH_STAGES[1]
(_, C2, _, _, s2) = HASH_STAGES[2]
(_, C3, _, _, s3) = HASH_STAGES[3]
(_, C4, _, _, s4) = HASH_STAGES[4]
(_, C5, _, _, s5) = HASH_STAGES[5]

k0 = (1 + (1 << s0)) & M          # 4097
kp = (1 + (1 << s2)) & M          # 33
ap = (C2 + C3) & M
kq = ((1 + (1 << s2)) << s3) & M  # 16896
aq = (C2 << s3) & M
k4 = (1 + (1 << s4)) & M          # 9


def round_body(s, nt):
    """The shipped 11 vector ops. s = carried state (true val ^ C5),
    nt = per-node precomputed table entry (= node_val ^ C5).
    Returns the next carried state."""
    ops = []
    x = (s ^ nt) & M;                       ops.append(("^", "x"))
    a = (x * k0 + C0) & M;                  ops.append(("madd", "a"))
    t1 = a >> s1;                           ops.append((">>", "t1"))
    b = (a ^ C1) & M;                       ops.append(("^", "b"))
    d = (b ^ t1) & M;                       ops.append(("^", "d"))
    p = (d * kp + ap) & M;                  ops.append(("madd", "p"))
    q = (d * kq + aq) & M;                  ops.append(("madd", "q"))
    e = (p ^ q) & M;                        ops.append(("^", "e"))
    f = (e * k4 + C4) & M;                  ops.append(("madd", "f"))
    t2 = f >> s5;                           ops.append((">>", "t2"))
    s2_ = (f ^ t2) & M;                     ops.append(("^", "s'"))
    return s2_, ops, dict(x=x, a=a, t1=t1, b=b, d=d, p=p, q=q, e=e, f=f, t2=t2, sn=s2_)


def ref_round(val, nv):
    return myhash((val ^ nv) & M)


# ---------------- Part 1: validation ----------------
def part1(n_random=1_000_000):
    edges = [0, 1, 2, 3, 2 ** 31, 2 ** 31 - 1, 2 ** 31 + 1, M, M - 1,
             0x80000000, 0x7FFFFFFF, 0xFFFF0000, 0x0000FFFF, 0xAAAAAAAA, 0x55555555]
    for sh in range(33):
        v = (1 << sh) & M
        edges += [v, (v - 1) & M, (v + 1) & M, (M ^ v)]
    cases = [(a, b) for a in edges for b in edges]
    rnd = random.Random(20260728)
    cases += [(rnd.getrandbits(32), rnd.getrandbits(30)) for _ in range(n_random)]
    bad = 0
    for (val, nv) in cases:
        s = (val ^ C5) & M
        nt = (nv ^ C5) & M
        got, _, _ = round_body(s, nt)
        want = (ref_round(val, nv) ^ C5) & M
        if got != want:
            bad += 1
            if bad < 4:
                print(f"  MISMATCH val={val:#010x} nv={nv:#010x} got={got:#010x} want={want:#010x}")
    print(f"[part1] 11-op round body vs myhash: {len(cases)} cases "
          f"({len(edges)}^2={len(edges)**2} edge pairs + {n_random} random), mismatches={bad}")
    return bad == 0


# ---------------- Part 2: the XOR<->ADD dichotomy ----------------
def part2():
    print("\n[part2] XOR<->ADD dichotomy and the obstruction constants")
    # Lemma: (exists c) forall y in Z_2^32: y ^ K == y + c (mod 2^32)  <=>  K in {0, 2^31}.
    # Proof: y=0 forces c=K.  Then y=K gives 0 == 2K (mod 2^32) <=> K in {0, 2^31}.
    # Numeric confirmation on the whole single-bit basis + randoms:
    fails = []
    for K in [0, 1 << 31] + [1 << j for j in range(31)] + [random.Random(7).getrandbits(32) for _ in range(200)]:
        ok = all(((y ^ K) & M) == ((y + K) & M) for y in
                 [0, 1, 2, 3, K, K ^ 1, M, 0x12345678, 0xDEADBEEF, 1 << 31])
        if ok != (K in (0, 1 << 31)):
            fails.append(K)
    print(f"  lemma numeric check: exceptions found = {len(fails)} (expect 0)")

    def g(v, sh):
        return (v ^ (v >> sh)) & M

    # g_s is an involution when 2*s >= 32.
    inv19 = all(g(g(v, 19), 19) == v for v in [random.Random(3).getrandbits(32) for _ in range(10000)])
    inv16 = all(g(g(v, 16), 16) == v for v in [random.Random(4).getrandbits(32) for _ in range(10000)])
    print(f"  g19 involution={inv19}  g16 involution={inv16}")

    # (O1) remove the fold-in `^nt`: needs (s^nt) to be s+const, i.e. nt in {0,2^31}
    #      for EVERY node -> node_val in {C5, C5^2^31}.  node values are uniform in [0,2^30).
    print(f"  O1 fold-in removal would require node_val in "
          f"{{{C5:#010x}, {(C5 ^ (1 << 31)):#010x}}}; node values are random in [0,2^30) -> impossible")

    # (O2) remove the `^C1` (stage-2 constant) by pushing it BACKWARD through g19
    #      into the stage-1 madd addend: needs K = g19^{-1}(C1) = g19(C1) in {0,2^31}
    K_back = g(C1, 19)
    print(f"  O2 backward push: g19^-1(C1={C1:#010x}) = {K_back:#010x} "
          f"-> in {{0,2^31}}? {K_back in (0, 1 << 31)}")

    # (O3) remove the `^C1` by pushing it FORWARD into the stage-3/4 madd
    #      addends: needs C1 itself in {0,2^31}
    print(f"  O3 forward push: C1 = {C1:#010x} -> in {{0,2^31}}? {C1 in (0, 1 << 31)}")

    # (O4) the already-exploited one: C5 elision works because the op AFTER it
    #      is the fold-in xor (xor-conjugation transports free through xorshifts).
    print(f"  O4 (already shipped, c5_prexor): C5={C5:#010x} elided because its consumer is a XOR")

    # Sanity: verify the identity that backs O2/O3 shape, g19(a^K) == g19(a)^g19(K)
    r = random.Random(11)
    lin = all(g((a ^ K) & M, 19) == (g(a, 19) ^ g(K, 19)) & M
              for a, K in [(r.getrandbits(32), r.getrandbits(32)) for _ in range(20000)])
    print(f"  g19 is GF(2)-linear (xor transports): {lin}")


# ---------------- Part 3: extended-vocabulary 1-op probe ----------------
def cdiv(a, b):
    if b == 0:
        return None
    return -((-a) // b)


def divisors(n, limit=1 << 32):
    if n == 0:
        return None  # every c works; handled by caller
    ds = set()
    i = 1
    while i * i <= n:
        if n % i == 0:
            ds.add(i)
            ds.add(n // i)
        i += 1
        if i > 3_000_000:
            return None  # give up on factorisation, treat as unresolved
    return {d for d in ds if d < limit}


def part3(n_samples=48, n_verify=200_000):
    print("\n[part3] extended-vocabulary 1-op probe (//, %, cdiv) over the 2-round trace DAG")
    rnd = random.Random(4242)
    samples = []
    structured = [0, 1, 2, M, M - 1, 1 << 31, (1 << 31) - 1, 0xAAAAAAAA, 0x55555555]
    for i in range(n_samples):
        if i < len(structured):
            s = structured[i]
        else:
            s = rnd.getrandbits(32)
        nt = rnd.getrandbits(30) ^ C5
        samples.append((s, nt))

    def trace(s, nt):
        s1v, _, d1 = round_body(s, nt)
        nt2 = rnd_nt2
        s2v, _, d2 = round_body(s1v, nt2)
        n = {"s": s, "nt": nt}
        for k, v in d1.items():
            n["r1_" + k] = v
        n["nt2"] = nt2
        for k, v in d2.items():
            n["r2_" + k] = v
        return n

    rnd_nt2 = rnd.getrandbits(30) ^ C5
    traces = [trace(s, nt) for (s, nt) in samples]
    names = list(traces[0].keys())
    cols = {nm: [t[nm] for t in traces] for nm in names}
    order = {nm: i for i, nm in enumerate(names)}

    hits = []
    tested = 0
    for tgt in names:
        T = cols[tgt]
        for src in names:
            if order[src] >= order[tgt]:
                continue
            U = cols[src]
            # ---- u // c  (c constant, c>=1) ----
            tested += 1
            lo, hi = 1, M
            feasible = True
            for u, t in zip(U, T):
                if t == 0:
                    l, h = (u + 1 if u > 0 else 1), M
                else:
                    if t > u:
                        feasible = False
                        break
                    l = u // (t + 1) + 1
                    h = u // t
                lo, hi = max(lo, l), min(hi, h)
                if lo > hi:
                    feasible = False
                    break
            if feasible and lo <= hi:
                # verify the full range endpoints then a sweep if small
                cand = [lo, hi] if hi - lo > 64 else list(range(lo, hi + 1))
                for c in cand:
                    if all((u // c) == t for u, t in zip(U, T)):
                        hits.append(("//", src, tgt, c))
            # ---- u % c ----
            tested += 1
            ds = None
            resolved = True
            for u, t in zip(U, T):
                if t > u:
                    resolved = False
                    break
                dd = divisors(u - t)
                if dd is None:
                    resolved = False
                    break
                dd = {c for c in dd if c > t}
                ds = dd if ds is None else (ds & dd)
                if not ds:
                    break
            if resolved and ds:
                for c in list(ds)[:4096]:
                    if all((u % c) == t for u, t in zip(U, T)):
                        hits.append(("%", src, tgt, c))
            # ---- cdiv(u, c) ----
            tested += 1
            lo, hi = 1, M
            feasible = True
            for u, t in zip(U, T):
                if t == 0:
                    if u != 0:
                        feasible = False
                        break
                    continue
                if t > u:
                    feasible = False
                    break
                l = (u + t - 1) // t if t else 1
                l = max(1, (u - 1) // t + 1 if t else 1)
                h = (u - 1) // (t - 1) if t > 1 else M
                lo, hi = max(lo, l), min(hi, h)
                if lo > hi:
                    feasible = False
                    break
            if feasible and lo <= hi:
                cand = [lo, hi] if hi - lo > 64 else list(range(lo, hi + 1))
                for c in cand:
                    if all(cdiv(u, c) == t for u, t in zip(U, T)):
                        hits.append(("cdiv", src, tgt, c))
            # ---- c // u , c % u  (constant on the left) ----
            tested += 2
            lo, hi = 0, M
            feasible = all(u != 0 for u in U)
            if feasible:
                for u, t in zip(U, T):
                    l, h = t * u, t * u + u - 1
                    lo, hi = max(lo, l), min(hi, h)
                    if lo > hi or lo > M:
                        feasible = False
                        break
                if feasible and lo <= min(hi, M):
                    for c in ([lo, min(hi, M)] if hi - lo > 64 else range(lo, min(hi, M) + 1)):
                        if all((c // u) == t for u, t in zip(U, T)):
                            hits.append(("c//u", src, tgt, c))
        # ---- two-runtime-operand div/mod forms ----
        for i, a in enumerate(names):
            if order[a] >= order[tgt]:
                continue
            for b in names:
                if order[b] >= order[tgt]:
                    continue
                A, B = cols[a], cols[b]
                tested += 3
                if all(x != 0 for x in B):
                    if all((u // v) == t for u, v, t in zip(A, B, T)):
                        hits.append(("u//v", f"{a},{b}", tgt, None))
                    if all((u % v) == t for u, v, t in zip(A, B, T)):
                        hits.append(("u%v", f"{a},{b}", tgt, None))
                    if all(cdiv(u, v) == t for u, v, t in zip(A, B, T)):
                        hits.append(("cdiv(u,v)", f"{a},{b}", tgt, None))
    print(f"  screened {tested} (op, source, target) questions on {n_samples} samples")
    print(f"  screen hits: {len(hits)}")
    # verify survivors on a big independent sample
    confirmed = []
    for (op, src, tgt, c) in hits:
        ok = True
        vr = random.Random(999)
        for _ in range(n_verify):
            s = vr.getrandbits(32)
            nt = vr.getrandbits(30) ^ C5
            t = trace(s, nt)
            u = None if "," in str(src) else t[src]
            if u is None:
                a, b = src.split(",")
                ua, ub = t[a], t[b]
                got = {"u//v": (ua // ub) if ub else None,
                       "u%v": (ua % ub) if ub else None,
                       "cdiv(u,v)": cdiv(ua, ub)}[op]
            else:
                got = {"//": u // c if c else None, "%": u % c if c else None,
                       "cdiv": cdiv(u, c), "c//u": (c // u) if u else None}[op]
            del s, nt
            if got != t[tgt]:
                ok = False
                break
        if ok:
            confirmed.append((op, src, tgt, c))
    print(f"  CONFIRMED on {n_verify} extra samples: {len(confirmed)}")
    for h in confirmed:
        print("   ", h)
    return confirmed


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1_000_000
    part1(n)
    part2()
    part3()
