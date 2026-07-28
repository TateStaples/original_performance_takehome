#!/usr/bin/env python3
"""P3-F part 2: lower-bound work for the round body `myhash(val ^ node_val)`.

A. O1 revisited WITH full node-table freedom (does a transformed table help?).
B. Exact dependency / change-set facts about the target.
C. BARRIER witnesses: explicit short programs proving that each of the three
   proposed invariant families cannot yield a bound above a small constant.
D. Rigorous depth-1 refutations: per-stage minimum op counts.

Read-only.
"""
import random
import sys

sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome")
from problem import HASH_STAGES, myhash  # noqa: E402

MASK = (1 << 32) - 1
(_, C0, _, _, s0) = HASH_STAGES[0]
(_, C1, _, _, s1) = HASH_STAGES[1]
(_, C2, _, _, s2) = HASH_STAGES[2]
(_, C3, _, _, s3) = HASH_STAGES[3]
(_, C4, _, _, s4) = HASH_STAGES[4]
(_, C5, _, _, s5) = HASH_STAGES[5]
k0, kp, kq, k4 = 4097, 33, 16896, 9
ap, aq = (C2 + C3) & MASK, (C2 << s3) & MASK


def g(v, sh):
    return (v ^ (v >> sh)) & MASK


def target(s, nt):
    """carried-state round body (c5_prexor basis): s -> s'."""
    x = s ^ nt
    a = (x * k0 + C0) & MASK
    d = (a ^ C1 ^ (a >> s1)) & MASK
    e = (((d * kp + ap) & MASK) ^ ((d * kq + aq) & MASK)) & MASK
    f = (e * k4 + C4) & MASK
    return (f ^ (f >> s5)) & MASK


# ---------------------------------------------------------------- A
def sectionA():
    print("=" * 72)
    print("A. O1 with FULL node-table freedom (coordinator's secondary ask)")
    print("=" * 72)
    print("""
Setup.  The round boundary is
    f = 9e + C4          (the last madd)
    s' = f ^ (f>>16)     (= g16(f))
    x  = s' ^ C5 ^ nv    (the fold-in; true val = s' ^ C5)
Because g16 is a GF(2)-linear involution,
    x = g16(f) ^ K   with K = C5 ^ nv
      = g16(f ^ M)   with M = g16(K) = g16(C5 ^ nv).
M is EXACTLY the entry a transformed node table would hold, and the table is
already maximally free: T(nv) := g16(C5 ^ nv) is computable at setup.  So the
transform freedom is fully used, and M is then UNIQUELY DETERMINED by nv --
there is no residual choice left to exploit.
Deleting the fold-in op means folding `^M` into the only additive slot that
touches f, namely the madd addend:  need  (9e + C4) ^ M == 9e + A  for all e.
9 is odd so e -> 9e+C4 is onto Z/2^32; by the XOR<->ADD lemma this forces
M in {0, 2^31}.  Both legs of the madd are checked below (multiplier slot too).
""")
    good = [nv for nv in (0, 1 << 31) for nv in [
        (C5 ^ ((v ^ (v >> s5)) & MASK)) for v in [nv]]]
    # solve directly: M = g16(C5^nv) in {0, 2^31}  <=>  C5^nv in {g16^-1(0), g16^-1(2^31)}
    sols = sorted({(C5 ^ g(0, s5)) & MASK, (C5 ^ g(1 << 31, s5)) & MASK})
    print(f"  M in {{0, 2^31}}  <=>  node_val in {[hex(v) for v in sols]}")
    print(f"  node values are drawn from randint(0, 2**30-1)  (problem.py:449)")
    for v in sols:
        print(f"    {v:#010x} = {v}   in range [0,2^30)? {v < (1 << 30)}   "
              f"(2^30 = {1 << 30})")
    print("    ^^ CORRECTION to the first P3-F report: 0x355ACF09 IS < 2^30, so a")
    print("       single node COULD carry it (probability 2^-30).  It is still")
    print("       unusable: the kernel is built from (forest_height, n_nodes,")
    print("       batch_size, rounds) ONLY (tests/submission_tests.py:24-26), so the")
    print("       emitted op stream cannot be specialised on a runtime node VALUE,")
    print("       and it would save 1 op on 1 node of 2^(h+1)-1 in any case.")
    # verify the M in {0,2^31} case really would work (positive control)
    rnd = random.Random(5)
    for M in (0, 1 << 31):
        A = (C4 + M) & MASK
        ok = all((((9 * e + C4) & MASK) ^ M) == ((9 * e + A) & MASK)
                 for e in [rnd.getrandbits(32) for _ in range(20000)])
        print(f"  control: M={M:#010x} absorbable into the addend? {ok}")
    # and that a per-node MULTIPLIER slot does not help either
    print("""  multiplier slot: need e*B + A == (9e+C4)^M for all e; LHS is Z-affine
  in e, so the same lemma applies verbatim.  No help.
  => O1 STANDS.  A transformed node table cannot remove the fold-in for any
     level, because the required table entry is forced, not chosen.""")


# ---------------------------------------------------------------- B
def sectionB():
    print("=" * 72)
    print("B. exact change-sets of the target (empirical, 4000 random s per bit)")
    print("=" * 72)
    rnd = random.Random(77)
    nt = rnd.getrandbits(30) ^ C5
    changed = {}
    for j in range(32):
        acc = 0
        for _ in range(4000):
            s = rnd.getrandbits(32)
            acc |= target(s, nt) ^ target(s ^ (1 << j), nt)
        changed[j] = acc
    lo = {j: (changed[j] & -changed[j]).bit_length() - 1 for j in range(32)}
    print("  perturb s at bit j -> lowest output bit that can change:")
    print("   ", {j: lo[j] for j in range(32)})
    print(f"  j=31 -> lowest changed output bit {lo[31]} "
          f"=> a NET DOWNWARD DISPLACEMENT OF {31 - lo[31]} is required")
    full = all(changed[j] == MASK for j in range(32))
    print(f"  every perturbation reaches every output bit: {full}")


# ---------------------------------------------------------------- C
def sectionC():
    print("=" * 72)
    print("C. BARRIER witnesses -- why each proposed invariant family caps out")
    print("=" * 72)
    rnd = random.Random(9)

    # C1: downward reach / bit-dependency  (coordinator's line 3)
    #   one op `s % C` already makes output bit 0 depend on ALL 32 bits of s.
    Cc = 0xB3A7F001  # odd, non-power-of-two
    dep = 0
    for j in range(32):
        # targeted witnesses: match C's prefix above bit j, vary the low bits
        found = False
        for _ in range(4000):
            r = rnd.getrandbits(j + 1) if j >= 0 else 0
            sv = (Cc & ~((1 << (j + 1)) - 1)) | r
            if int(sv < Cc) != int((sv ^ (1 << j)) < Cc):
                found = True
                break
        if found:
            dep |= 1 << j
    print(f"  reach barrier: out = (s < {Cc:#x}); bit 0 of the output depends on "
          f"{bin(dep).count('1')}/32 input bits after ONE op")
    print("   => any lower bound of the form 'bit i needs input bit j' is <= 1 op.")
    # even in the shift-only fragment, ONE op (s>>31) already achieves
    # displacement 31, which is the maximum the target demands (section B).
    print("   => even restricted to shifts, one `>>31` realises the maximum")
    print("      downward displacement the target needs, so the bound is <= 1.")

    # C2: GF(2) algebraic degree  (coordinator's line 1, degree variant)
    #   one op `s*s` already has near-maximal degree.
    def gf2_degree_bit(fn, bit, nvars=32, trials=1):
        # Moebius transform over a random 12-variable restriction (exact on it)
        k = 12
        idx = sorted(random.Random(bit).sample(range(nvars), k))
        best = 0
        for _ in range(trials):
            base = random.Random(bit * 31 + 7).getrandbits(32)
            tbl = []
            for m in range(1 << k):
                v = base
                for b, i in enumerate(idx):
                    v = (v & ~(1 << i)) | (((m >> b) & 1) << i)
                tbl.append((fn(v) >> bit) & 1)
            # Moebius
            for b in range(k):
                st = 1 << b
                for m in range(1 << k):
                    if m & st:
                        tbl[m] ^= tbl[m ^ st]
            for m in range(1 << k):
                if tbl[m]:
                    best = max(best, bin(m).count("1"))
        return best

    d_sq = max(gf2_degree_bit(lambda v: (v * v) & MASK, b) for b in (20, 31))
    d_tg = max(gf2_degree_bit(lambda v: target(v, 0x12345678), b) for b in (20, 31))
    print(f"  degree barrier (exact on a random 12-var restriction):")
    print(f"    deg(one op  s*s )  >= {d_sq} of 12")
    print(f"    deg(the target  )  >= {d_tg} of 12")
    print("   => the target's degree is already reached by a ONE-op program,")
    print("      so degree/2-adic-filtration counting cannot bound above ~1.")

    # C3: counting
    nprog = 10 * (14 * (10 + 3) ** 3 * 2 ** 32)
    print(f"  counting barrier: #10-op programs <~ (14*13^3*2^32)^10 ~ 2^{510}")
    print(f"    #functions (Z/2^32)^2 -> Z/2^32 = 2^(32*2^64).")
    print("   => counting proves *almost every* function needs many ops and")
    print("      says NOTHING about a named one.  Non-constructive by design.")


# ---------------------------------------------------------------- D
def solve1(avail, T, samples):
    """All 1-op forms with a SOLVED constant computing T from `avail`.
    avail: dict name -> list of values (parallel to T)."""
    hits = []
    names = list(avail)
    for nm in names:
        U = avail[nm]
        u0, t0 = U[0], T[0]
        for lab, c, fn in (("^", u0 ^ t0, lambda u, c: u ^ c),
                           ("+", (t0 - u0) & MASK, lambda u, c: (u + c) & MASK),
                           ("-", (u0 - t0) & MASK, lambda u, c: (u - c) & MASK),
                           ("c-", (t0 + u0) & MASK, lambda u, c: (c - u) & MASK)):
            if all(fn(u, c) == t for u, t in zip(U, T)):
                hits.append((lab, nm, c))
        c_and = MASK & ~(0 if not U else
                         eval("0") | __import__("functools").reduce(
                             lambda x, y: x | y, [(u & ~t) & MASK for u, t in zip(U, T)]))
        if all((u & c_and) == t for u, t in zip(U, T)):
            hits.append(("&", nm, c_and))
        c_or = __import__("functools").reduce(
            lambda x, y: x | y, [(t & ~u) & MASK for u, t in zip(U, T)])
        if all((u | c_or) == t for u, t in zip(U, T)):
            hits.append(("|", nm, c_or))
        for k in range(32):
            if all(((u << k) & MASK) == t for u, t in zip(U, T)):
                hits.append(("<<", nm, k))
            if all((u >> k) == t for u, t in zip(U, T)):
                hits.append((">>", nm, k))
        for i1 in range(len(U)):
            for i2 in range(i1 + 1, len(U)):
                du = (U[i1] - U[i2]) & MASK
                if du & 1:
                    inv = pow(du, -1, 1 << 32)
                    kk = (((T[i1] - T[i2]) & MASK) * inv) & MASK
                    cc = (T[i1] - kk * U[i1]) & MASK
                    if all(((u * kk + cc) & MASK) == t for u, t in zip(U, T)):
                        hits.append(("madd_affine", nm, (kk, cc)))
                    break
            else:
                continue
            break
        # madd(u,u,c) = u^2 + c ; madd(u,c,u') handled by the pair loop
        cc = (T[0] - U[0] * U[0]) & MASK
        if all(((u * u + cc) & MASK) == t for u, t in zip(U, T)):
            hits.append(("sqr+c", nm, cc))
        # // and % with solved constants
        lo, hi, ok = 1, MASK, True
        for u, t in zip(U, T):
            if t == 0:
                l, h = (u + 1 if u else 1), MASK
            elif t > u:
                ok = False
                break
            else:
                l, h = u // (t + 1) + 1, u // t
            lo, hi = max(lo, l), min(hi, h)
            if lo > hi:
                ok = False
                break
        if ok and lo <= hi:
            for c in ([lo, hi] if hi - lo > 64 else range(lo, hi + 1)):
                if all((u // c) == t for u, t in zip(U, T)):
                    hits.append(("//", nm, c))
    for na in names:
        for nb in names:
            A, B = avail[na], avail[nb]
            for lab, fn in (("^", lambda p, q: p ^ q), ("+", lambda p, q: (p + q) & MASK),
                            ("-", lambda p, q: (p - q) & MASK), ("*", lambda p, q: (p * q) & MASK),
                            ("&", lambda p, q: p & q), ("|", lambda p, q: p | q),
                            ("<<", lambda p, q: (p << q) & MASK if q < 64 else 0),
                            (">>", lambda p, q: p >> q if q < 64 else 0),
                            ("<", lambda p, q: int(p < q)), ("==", lambda p, q: int(p == q))):
                if all(fn(p, q) == t for p, q, t in zip(A, B, T)):
                    hits.append((lab, f"{na},{nb}", None))
            if all(q and (p // q) == t for p, q, t in zip(A, B, T)):
                hits.append(("//", f"{na},{nb}", None))
            if all(q and (p % q) == t for p, q, t in zip(A, B, T)):
                hits.append(("%", f"{na},{nb}", None))
            for nc in names:
                Cv = avail[nc]
                if all(((p * q + r) & MASK) == t for p, q, r, t in zip(A, B, Cv, T)):
                    hits.append(("madd", f"{na},{nb},{nc}", None))
            # madd(u, const, v) : constant multiplier solved
            for i1 in range(len(A)):
                for i2 in range(i1 + 1, len(A)):
                    if (A[i1] - A[i2]) & 1:
                        inv = pow((A[i1] - A[i2]) & MASK, -1, 1 << 32)
                        kk = ((((T[i1] - B[i1]) - (T[i2] - B[i2])) & MASK) * inv) & MASK
                        if all(((p * kk + q) & MASK) == t for p, q, t in zip(A, B, T)):
                            hits.append(("madd_kconst", f"{na},{nb}", kk))
                        break
                else:
                    continue
                break
    return hits


def sectionD():
    print("=" * 72)
    print("D. rigorous depth-1 refutations (stage-local minima)")
    print("=" * 72)
    rnd = random.Random(2024)
    S = [rnd.getrandbits(32) for _ in range(40)]
    NT = [rnd.getrandbits(30) ^ C5 for _ in range(40)]
    tests = {
        "stage2 body  a -> g19(a)^C1": (
            {"a": S}, [(v ^ C1 ^ (v >> s1)) & MASK for v in S]),
        "stage2 shiftless a -> g19(a)": (
            {"a": S}, [g(v, s1) for v in S]),
        "stage6 body  f -> g16(f)": (
            {"f": S}, [g(v, s5) for v in S]),
        "stage4 join  d -> (33d+ap)^(16896d+aq)": (
            {"d": S}, [(((v * kp + ap) & MASK) ^ ((v * kq + aq) & MASK)) & MASK for v in S]),
        "fold-in      (s,nt) -> s^nt  [POSITIVE CONTROL]": (
            {"s": S, "nt": NT}, [(p ^ q) & MASK for p, q in zip(S, NT)]),
        "stage1       x -> 4097x+C0  [POSITIVE CONTROL]": (
            {"x": S}, [(v * k0 + C0) & MASK for v in S]),
        "WHOLE ROUND  (s,nt) -> s'": (
            {"s": S, "nt": NT}, [target(p, q) for p, q in zip(S, NT)]),
    }
    for lbl, (avail, T) in tests.items():
        h = solve1(avail, T, S)
        print(f"  {lbl:52s} 1-op forms: {len(h)}  {h[:2]}")

    print("\n  same questions with FULL availability (every earlier trace value):")
    X = [(p ^ q) & MASK for p, q in zip(S, NT)]
    A = [(v * k0 + C0) & MASK for v in X]
    T1 = [v >> s1 for v in A]
    B = [(v ^ C1) & MASK for v in A]
    D = [(p ^ q) & MASK for p, q in zip(B, T1)]
    P = [(v * kp + ap) & MASK for v in D]
    Q = [(v * kq + aq) & MASK for v in D]
    E = [(p ^ q) & MASK for p, q in zip(P, Q)]
    F = [(v * k4 + C4) & MASK for v in E]
    T2 = [v >> s5 for v in F]
    SN = [(p ^ q) & MASK for p, q in zip(F, T2)]
    full = dict(s=S, nt=NT, x=X, a=A, t1=T1, b=B, d=D, p=P, q=Q, e=E, f=F, t2=T2)
    checks = [("stage2 out d  from {s,nt,x,a}", ["s", "nt", "x", "a"], D),
              ("stage4 out e  from {s,nt,x,a,t1,b,d,p}", ["s", "nt", "x", "a", "t1", "b", "d", "p"], E),
              ("stage6 out s' from all of {..,e,f}", ["s", "nt", "x", "a", "t1", "b", "d", "p", "q", "e", "f"], SN)]
    for lbl, keys, T in checks:
        h = solve1({k: full[k] for k in keys}, T, S)
        h = [z for z in h if True]
        print(f"    {lbl:46s} 1-op forms: {len(h)}  {h[:2]}")


if __name__ == "__main__":
    sectionA()
    sectionB()
    sectionC()
    sectionD()
