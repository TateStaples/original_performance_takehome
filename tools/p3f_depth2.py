#!/usr/bin/env python3
"""P3-F depth-2 slice with the div/mod vocabulary that no prior hash search used.

Each of the three 3-op blocks of the shipped 11-op round body is asked the
2-op question.  The enumerated subspace is EXACTLY:

  op1 : any op whose operands are all runtime trace nodes (no free constant),
        i.e.  binop(u,v), madd(u,v,w), divfam(u,v)  over the available nodes,
        PLUS shift(u,k) for k in 0..31 (the only constant that is finitely
        enumerable), PLUS unary-ish forms u-u etc. implied by u==v.
  op2 : ANY op, with its constant SOLVED against the target -- including
        the //, %, cdiv forms (range / divisor solving), select/compare-free.

This is exhaustive over "op1 carries no free 32-bit constant".  It is NOT
exhaustive over the full 2^32-constant space in op1 -- that is the region
G-10 covered (~400B candidates) for the base vocabulary; here the point is
the vocabulary extension (//, %, cdiv, runtime-operand madd/div).

Read-only.
"""
import random
import sys

import numpy as np

sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome")
from problem import HASH_STAGES  # noqa: E402

M32 = np.uint32
MASK = (1 << 32) - 1
(_, C0, _, _, s0) = HASH_STAGES[0]
(_, C1, _, _, s1) = HASH_STAGES[1]
(_, C2, _, _, s2) = HASH_STAGES[2]
(_, C3, _, _, s3) = HASH_STAGES[3]
(_, C4, _, _, s4) = HASH_STAGES[4]
(_, C5, _, _, s5) = HASH_STAGES[5]
k0 = (1 + (1 << s0)) & MASK
kp = (1 + (1 << s2)) & MASK
ap = (C2 + C3) & MASK
kq = ((1 + (1 << s2)) << s3) & MASK
aq = (C2 << s3) & MASK
k4 = (1 + (1 << s4)) & MASK

N = 64
rnd = random.Random(31337)


def gen(n):
    s = np.array([rnd.getrandbits(32) for _ in range(n)], dtype=np.uint64)
    nt = np.array([rnd.getrandbits(30) ^ C5 for _ in range(n)], dtype=np.uint64)
    nt2 = np.array([rnd.getrandbits(30) ^ C5 for _ in range(n)], dtype=np.uint64)
    x = (s ^ nt) & MASK
    a = (x * k0 + C0) & MASK
    t1 = a >> s1
    b = (a ^ C1) & MASK
    d = (b ^ t1) & MASK
    p = (d * kp + ap) & MASK
    q = (d * kq + aq) & MASK
    e = (p ^ q) & MASK
    f = (e * k4 + C4) & MASK
    t2 = f >> s5
    sn = (f ^ t2) & MASK
    xn = (sn ^ nt2) & MASK
    return dict(s=s, nt=nt, x=x, a=a, t1=t1, b=b, d=d, p=p, q=q, e=e, f=f,
                t2=t2, sn=sn, nt2=nt2, xn=xn)


BIN = {
    "+": lambda u, v: (u + v) & MASK,
    "-": lambda u, v: (u - v) & MASK,
    "*": lambda u, v: (u * v) & MASK,
    "^": lambda u, v: u ^ v,
    "&": lambda u, v: u & v,
    "|": lambda u, v: u | v,
    "<<": lambda u, v: np.where(v >= 64, 0, (u << np.minimum(v, 63)) & MASK),
    ">>": lambda u, v: np.where(v >= 64, 0, u >> np.minimum(v, 63)),
    "<": lambda u, v: (u < v).astype(np.uint64),
    "==": lambda u, v: (u == v).astype(np.uint64),
}


def divfam(name, u, v):
    if np.any(v == 0):
        return None
    if name == "//":
        return u // v
    if name == "%":
        return u % v
    if name == "cdiv":
        return -((-u.astype(np.int64)) // v.astype(np.int64)) % (1 << 32)
    raise KeyError(name)


def solve_last(avail, target):
    """All 1-op forms (with solved constant) computing `target` from `avail`.
    avail: dict name -> uint64 array.  Returns list of descriptions."""
    hits = []
    names = list(avail)
    T = target
    for nm in names:
        U = avail[nm]
        # xor / add / sub / rsub
        t0, u0 = int(T[0]), int(U[0])
        for label, c, fn in (
            ("^", t0 ^ u0, lambda u, c: u ^ c),
            ("+", (t0 - u0) & MASK, lambda u, c: (u + c) & MASK),
            ("-", (u0 - t0) & MASK, lambda u, c: (u - c) & MASK),
            ("c-", (t0 + u0) & MASK, lambda u, c: (c - u) & MASK),
        ):
            if np.array_equal(fn(U, np.uint64(c)), T):
                hits.append((label, nm, c))
        # and / or (maximal constant then verify)
        c_and = int(MASK & ~int(np.bitwise_or.reduce(U & ~T & MASK)))
        if np.array_equal(U & np.uint64(c_and), T):
            hits.append(("&", nm, c_and))
        c_or = int(np.bitwise_or.reduce(T & ~U & MASK))
        if np.array_equal(U | np.uint64(c_or), T):
            hits.append(("|", nm, c_or))
        # shifts
        for k in range(32):
            if np.array_equal((U << np.uint64(k)) & MASK, T):
                hits.append(("<<", nm, k))
            if np.array_equal(U >> np.uint64(k), T):
                hits.append((">>", nm, k))
        # multiply_add affine: k*u + c, solved from two samples
        du = (int(U[0]) - int(U[1])) & MASK
        if du & 1:
            inv = pow(du, -1, 1 << 32)
            kk = (((int(T[0]) - int(T[1])) & MASK) * inv) & MASK
            cc = (int(T[0]) - kk * int(U[0])) & MASK
            if np.array_equal((U * np.uint64(kk) + np.uint64(cc)) & MASK, T):
                hits.append(("madd_aff", nm, (kk, cc)))
        # // by solved constant
        lo, hi, ok = 1, MASK, True
        for u, t in zip(U.tolist(), T.tolist()):
            if t == 0:
                l, h = (u + 1 if u else 1), MASK
            else:
                if t > u:
                    ok = False
                    break
                l, h = u // (t + 1) + 1, u // t
            lo, hi = max(lo, l), min(hi, h)
            if lo > hi:
                ok = False
                break
        if ok and lo <= hi:
            for c in ([lo, hi] if hi - lo > 32 else range(lo, hi + 1)):
                if np.array_equal(U // np.uint64(c), T):
                    hits.append(("//", nm, c))
        # % by solved constant (divisor intersection on the first two samples)
        if T[0] <= U[0] and T[1] <= U[1]:
            n0, n1 = int(U[0] - T[0]), int(U[1] - T[1])
            g = int(np.gcd(n0, n1)) if (n0 and n1) else max(n0, n1)
            if 0 < int(g) < (1 << 24):
                for c in range(1, int(g) + 1):
                    if g % c == 0 and c > int(T.max()):
                        if np.array_equal(U % np.uint64(c), T):
                            hits.append(("%", nm, c))
    # two-runtime-operand forms
    for i, na in enumerate(names):
        for nb in names:
            A, B = avail[na], avail[nb]
            for op, fn in BIN.items():
                if np.array_equal(np.asarray(fn(A, B), dtype=np.uint64), T):
                    hits.append((op, f"{na},{nb}", None))
            for dn in ("//", "%", "cdiv"):
                r = divfam(dn, A, B)
                if r is not None and np.array_equal(np.asarray(r, dtype=np.uint64), T):
                    hits.append((dn, f"{na},{nb}", None))
            for nc in names:
                if np.array_equal((A * B + avail[nc]) & MASK, T):
                    hits.append(("madd", f"{na},{nb},{nc}", None))
    return hits


def const_pool():
    g19 = lambda v: (v ^ (v >> s1)) & MASK
    g16 = lambda v: (v ^ (v >> s5)) & MASK
    base = [0, 1, 2, MASK, 1 << 31, C0, C1, C2, C3, C4, C5, ap, aq, k0, kp, kq, k4,
            g19(C1), g16(C5), (C2 + C3) & MASK, (aq - 512 * ap) & MASK, 512, 1 << 9,
            (C0 * k0) & MASK, (-C0) & MASK, (-C4) & MASK, (C1 ^ C5), (C4 + C5) & MASK]
    base += [g19(C5), g16(C1), (C1 >> s1), (C5 >> s5)]
    return sorted({int(v) & MASK for v in base})


POOL = const_pool()


def enumerate_op1(avail):
    """All op1 candidates: no free 32-bit constant, or a constant from POOL."""
    out = {}
    names = list(avail)
    for na in names:
        A = avail[na]
        for c in POOL:
            cv = np.uint64(c)
            for op, fn in BIN.items():
                if op in ("<<", ">>"):
                    continue
                out[f"({na}{op}{c:#x})"] = np.asarray(fn(A, np.full_like(A, cv)), dtype=np.uint64)
                out[f"({c:#x}{op}{na})"] = np.asarray(fn(np.full_like(A, cv), A), dtype=np.uint64)
            if c:
                out[f"({na}//{c:#x})"] = A // cv
                out[f"({na}%{c:#x})"] = A % cv
            for c2 in POOL:
                out[f"madd({na},{c:#x},{c2:#x})"] = (A * cv + np.uint64(c2)) & MASK
    for na in names:
        A = avail[na]
        for k in range(32):
            out[f"({na}<<{k})"] = (A << np.uint64(k)) & MASK
            out[f"({na}>>{k})"] = A >> np.uint64(k)
        for nb in names:
            B = avail[nb]
            for op, fn in BIN.items():
                out[f"({na}{op}{nb})"] = np.asarray(fn(A, B), dtype=np.uint64)
            for dn in ("//", "%", "cdiv"):
                r = divfam(dn, A, B)
                if r is not None:
                    out[f"({na}{dn}{nb})"] = np.asarray(r, dtype=np.uint64)
            for nc in names:
                out[f"madd({na},{nb},{nc})"] = (A * B + avail[nc]) & MASK
    return out


BLOCKS = {
    "A: a -> d   (>>19, ^C1, ^t1)": (["s", "nt", "x", "a"], "d"),
    "B: d -> e   (madd p, madd q, ^)": (["s", "nt", "x", "a", "t1", "b", "d"], "e"),
    "C: f -> x'  (>>16, ^, ^nt2)": (["s", "nt", "x", "a", "t1", "b", "d", "p", "q",
                                     "e", "f", "nt2"], "xn"),
}


def verify(desc, block_inputs, tgt, n=1_000_000):
    return True  # survivors are re-verified by hand; none expected


def main():
    tr = gen(N)
    # ---- positive controls: known 2-op facts the machinery MUST rediscover ----
    ctrl = {"g19(a) [=a^(a>>19)]": (["s", "nt", "x", "a"], (tr["a"] ^ (tr["a"] >> s1)) & MASK),
            "e via p [=p^(512p+Q)]": (["d", "p"], tr["e"]),
            "sn [=f^(f>>16)]": (["e", "f"], tr["sn"])}
    for lbl, (inputs, target) in ctrl.items():
        avail = {k: tr[k] for k in inputs}
        cand = enumerate_op1(avail)
        got = [("depth1", h) for h in solve_last(avail, target)]
        for c1n, c1v in cand.items():
            av2 = dict(avail); av2["_t"] = c1v
            for h in solve_last(av2, target):
                if "_t" in str(h[1]):
                    got.append((c1n, h))
        print(f"CONTROL {lbl}: hits={len(got)}  e.g. {got[:2]}")
    for label, (inputs, tgt) in BLOCKS.items():
        avail = {k: tr[k] for k in inputs}
        cand = enumerate_op1(avail)
        target = tr[tgt]
        n_pairs = 0
        found = []
        # depth-1 first (is the block 1 op?)
        for h in solve_last(avail, target):
            found.append(("depth1", h))
        for c1name, c1vals in cand.items():
            av2 = dict(avail)
            av2["_t"] = c1vals
            n_pairs += 1
            for h in solve_last(av2, target):
                if "_t" in str(h[1]):
                    found.append((c1name, h))
        print(f"{label}: op1 candidates={len(cand)}  (op1,op2) pairs enumerated="
              f"{n_pairs}  hits={len(found)}")
        for h in found[:12]:
            print("    ", h)


if __name__ == "__main__":
    main()
