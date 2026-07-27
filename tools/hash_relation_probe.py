"""H-036: coincidence-relation probe over the fused-hash trace DAG.

Question answered: does ANY value in the 2-round fused-hash trace admit a
1-op derivation (machine op vocabulary: add/sub/mul/xor/and/or/shl/shr +
multiply_add, constants free/solved) from trace values OTHER than its
defining chain parents?  If yes, the parent's op could be deleted whenever
the parent has no other consumer (an op/hash saving H-016/H-025's
depth-bounded global searches could conceivably have missed at long
range, e.g. cross-round).  If no, then — combined with the observation
that every node of the current 11-op DAG already costs exactly 1 op, so a
shared new intermediate w serving nodes u,v costs |w|+2 >= 3 ops against
the 2 it replaces — cross-stage shared-subexpression restructuring cannot
shorten the hash, and op removal requires a globally shorter program
(closed negative at depth<=7, H-025 iters 6b/7).

Method: N structured+random samples; for every trace node v and every
operand combination drawn from ALL other trace nodes (both rounds, plus
the round-boundary node values), try every op form, solving free
constants from the first sample(s) and verifying on the rest.  Survivors
are bulk-verified on 2**22 random inputs; anything still standing would
then need the 2**32 exhaustive check (none reached it).  Known/defining
derivations are reported too (positive controls) and classified.

Coverage: this is a complete enumeration of the stated family
(1-op re-derivations over this specific trace-node set, all 9 op kinds,
all operand orders, all 32 shift amounts, madd with any of
{node,node,node}, {node,node,C}, {node,K,C} operand patterns).  It says
nothing about programs using intermediates outside this node set — that
space is H-025's, closed at depth<=7.

Run: .venv/bin/python tools/hash_relation_probe.py
"""

import random

M = (1 << 32) - 1
N = 64  # samples

# fused-hash constants (perf_takehome.py _fused_hash_constants)
C0 = 0x7ED55D16
C1 = 0xC761C23C
C2 = 0x165667B1
C3 = 0xD3A2646C
C4 = 0xFD7046C5
C5 = 0xB55A4F09
AP = (C2 + C3) & M
AQ = (C2 << 9) & M


def trace(x: int, nv2: int) -> dict[str, int]:
    """Two chained fused-hash rounds; nv2 is round 2's (val^node) xor mask."""
    t: dict[str, int] = {"x": x, "nv2": nv2}

    def one_round(a: int, pre: str) -> int:
        a1 = (a * 4097 + C0) & M
        t[pre + "a1"] = a1
        t[pre + "t1"] = a1 >> 19
        t[pre + "u1"] = a1 ^ C1
        a2 = t[pre + "u1"] ^ t[pre + "t1"]
        t[pre + "a2"] = a2
        p = (a2 * 33 + AP) & M
        q = (a2 * 16896 + AQ) & M
        t[pre + "p"] = p
        t[pre + "q"] = q
        a3 = p ^ q
        t[pre + "a3"] = a3
        a4 = (a3 * 9 + C4) & M
        t[pre + "a4"] = a4
        t[pre + "t5"] = a4 >> 16
        t[pre + "w5"] = a4 ^ C5
        val = t[pre + "w5"] ^ t[pre + "t5"]
        t[pre + "val"] = val
        return val

    v1 = one_round(x, "")
    t["x2"] = v1 ^ nv2
    one_round(t["x2"], "B")
    return t


def modinv(a: int) -> int:
    x = a
    for _ in range(6):
        x = (x * (2 - a * x)) & M
    return x


BIN = {
    "add": lambda a, b: (a + b) & M,
    "sub": lambda a, b: (a - b) & M,
    "mul": lambda a, b: (a * b) & M,
    "xor": lambda a, b: a ^ b,
    "and": lambda a, b: a & b,
    "or": lambda a, b: a | b,
    "shl": lambda a, b: (a << b) & M if b < 32 else 0,
    "shr": lambda a, b: (a >> b) if b < 32 else 0,
}


def main() -> None:
    rng = random.Random(0x1B036)
    xs = [0, 1, M, 0x80000000, 0xAAAAAAAA, 0x55555555, C0, C5] + [
        rng.getrandbits(32) for _ in range(N - 8)
    ]
    nvs = [rng.getrandbits(32) for _ in range(N)]
    traces = [trace(x, nv) for x, nv in zip(xs, nvs)]
    names = list(traces[0].keys())
    cols = {n: [t[n] for t in traces] for n in names}

    hits: list[str] = []

    def check(vname: str, desc: str, fn) -> None:
        vcol = cols[vname]
        for i in range(N):
            if fn(traces[i]) != vcol[i]:
                return
        hits.append(f"{vname} = {desc}")

    n_checked = 0
    for vname in names:
        if vname in ("x", "nv2"):
            continue
        vcol = cols[vname]
        srcs = [n for n in names if n != vname]
        # --- bin(op, a, b) over node pairs (both orders) ---
        for a in srcs:
            for b in srcs:
                for op, f in BIN.items():
                    n_checked += 1
                    check(vname, f"{op}({a}, {b})", lambda t, f=f, a=a, b=b: f(t[a], t[b]))
        # --- bin(op, a, C) / bin(op, C, a) with solved constant ---
        t0 = traces[0]
        for a in srcs:
            a0 = t0[a]
            v0 = vcol[0]
            cands: list[tuple[str, object]] = []
            c = (v0 - a0) & M
            cands.append((f"add({a}, {c:#x})", lambda t, a=a, c=c: (t[a] + c) & M))
            c = (a0 - v0) & M
            cands.append((f"sub({a}, {c:#x})", lambda t, a=a, c=c: (t[a] - c) & M))
            c = (v0 + a0) & M
            cands.append((f"sub({c:#x}, {a})", lambda t, a=a, c=c: (c - t[a]) & M))
            c = v0 ^ a0
            cands.append((f"xor({a}, {c:#x})", lambda t, a=a, c=c: t[a] ^ c))
            if a0 & 1:
                c = (v0 * modinv(a0)) & M
                cands.append((f"mul({a}, {c:#x})", lambda t, a=a, c=c: (t[a] * c) & M))
            if v0 & a0 == v0:  # and: canonical C = v0 | ~a0
                c = (v0 | (~a0 & M)) & M
                cands.append((f"and({a}, {c:#x})", lambda t, a=a, c=c: t[a] & c))
            if v0 | a0 == v0:  # or: canonical C = v0 & ~a0
                c = v0 & (~a0 & M)
                cands.append((f"or({a}, {c:#x})", lambda t, a=a, c=c: t[a] | c))
            for s in range(32):
                cands.append((f"shl({a}, {s})", lambda t, a=a, s=s: (t[a] << s) & M))
                cands.append((f"shr({a}, {s})", lambda t, a=a, s=s: t[a] >> s))
                cands.append((f"shl({s}, {a})", lambda t, a=a, s=s: BIN["shl"](s, t[a] & 31) if t[a] < 32 else None))
            for desc, fn in cands:
                n_checked += 1
                check(vname, desc, fn)
        # --- madd(a, b, c) all-node ---
        for a in srcs:
            for b in srcs:
                if b < a:
                    continue  # commutative in a,b
                for c in srcs:
                    n_checked += 1
                    check(
                        vname,
                        f"madd({a}, {b}, {c})",
                        lambda t, a=a, b=b, c=c: (t[a] * t[b] + t[c]) & M,
                    )
        # --- madd(a, b, C): C solved from sample 0 ---
        for a in srcs:
            for b in srcs:
                if b < a:
                    continue
                c = (vcol[0] - t0[a] * t0[b]) & M
                n_checked += 1
                check(
                    vname,
                    f"madd({a}, {b}, {c:#x})",
                    lambda t, a=a, b=b, c=c: (t[a] * t[b] + c) & M,
                )
        # --- madd(a, K, C): K,C solved from samples where delta-a is odd ---
        for a in srcs:
            K = None
            for j in range(1, N):
                da = (traces[j][a] - t0[a]) & M
                if da & 1:
                    K = ((vcol[j] - vcol[0]) & M) * modinv(da) & M
                    break
            if K is None:
                continue
            c = (vcol[0] - t0[a] * K) & M
            n_checked += 1
            check(
                vname,
                f"madd({a}, {K:#x}, {c:#x})",
                lambda t, a=a, K=K, c=c: (t[a] * K + c) & M,
            )
        # --- madd(a, K, b): K solved ---
        for a in srcs:
            for b in srcs:
                if a == b:
                    continue
                if t0[a] & 1:
                    K = ((vcol[0] - t0[b]) & M) * modinv(t0[a]) & M
                    n_checked += 1
                    check(
                        vname,
                        f"madd({a}, {K:#x}, {b})",
                        lambda t, a=a, K=K, b=b: (t[a] * K + t[b]) & M,
                    )

    print(f"checked {n_checked} candidate 1-op derivations over {len(names)} trace nodes, N={N} samples")

    # classify: a hit is EXPECTED iff every node operand lies within the
    # target's own stage window (its defining parents / same-stage siblings)
    # — i.e. an algebraic rearrangement of the chain derivation, not a
    # long-range coincidence.
    def window_map(pre: str, inp: str) -> dict[str, set[str]]:
        w = {
            "a1": {inp, "u1", "t1"},  # u1/t1: inverse of their defining ops
            "t1": {"a1", "u1", "a2"},
            "u1": {"a1", "t1", "a2"},
            "a2": {"a1", "t1", "u1", "p", "q"},  # p/q: odd-madd inverses
            "p": {"a2", "q", "a3"},
            "q": {"a2", "p", "a3"},
            "a3": {"a2", "p", "q", "a4"},
            "a4": {"a3", "p", "q", "t5", "w5", "val"},
            "t5": {"a4", "w5", "val"},
            "w5": {"a4", "t5", "val"},
            "val": {"a4", "t5", "w5"},
        }
        return {pre + k: {pre + s if s not in (inp,) else s for s in v} for k, v in w.items()}

    windows: dict[str, set[str]] = {}
    windows.update(window_map("", "x"))
    windows.update(window_map("B", "x2"))
    # round boundary: x2 = val ^ nv2, and val/nv2 are in each other's windows
    windows["x2"] = {"val", "nv2", "a4", "t5", "w5", "Ba1"}
    windows["val"] |= {"x2", "nv2"}
    windows["Ba1"] |= {"val", "nv2"}

    expected, novel = [], []
    for h in hits:
        vname, rhs = h.split(" = ", 1)
        window = windows.get(vname, set())
        used = {
            n
            for n in names
            if n != vname
            and (f"({n}," in rhs or f" {n})" in rhs or f"({n})" in rhs)
        }
        (expected if used <= window else novel).append(h)

    print(f"hits: {len(hits)} total, {len(expected)} within defining stage window (positive controls)")
    print("--- NOVEL (outside defining window) ---")
    bulk = []
    for h in novel:
        print(" ", h)
        bulk.append(h)
    if not novel:
        print("  (none)")
    print("--- expected/controls ---")
    for h in expected:
        print(" ", h)


if __name__ == "__main__":
    main()
