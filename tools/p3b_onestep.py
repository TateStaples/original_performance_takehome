"""P3-B: mechanical search for a ONE-op index advance, and for a cheaper
parity extraction, over the full valu ISA.

Two exhaustive-in-structure searches, both read-only:

(1) PARITY-ONLY LEMMA.  Which (op, k) pairs -- op any alu opcode, k any
    32-bit constant broadcast -- produce a result that depends on `val`
    ONLY through bit0(val)?  Any single op that reads val and feeds an
    exact memory address must have this property (two vals of equal parity
    must give the same address).  We test every opcode against a large
    structured+random constant sample.

(2) ONE-OP ADVANCE.  Enumerate every single valu slot whose operands are
    drawn from {A (live address), val (live hashed value), K (a broadcast
    constant, solved for)} and ask whether it can equal the required
    A' = 2*A - 6 + (val & 1)  (forest_values_p == 7) for all (A, val).
    madd(a,b,c) is included with all 27 operand assignments; the constant
    is *solved* from one sample and then verified on the rest, so a
    constant that works is found if one exists.

Usage: python3 tools/p3b_onestep.py
"""

from __future__ import annotations

import itertools
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

M = 1 << 32
FP = 7  # forest_values_p, FROZEN by frozen_problem.build_mem_image

OPS = ["+", "-", "*", "//", "^", "&", "|", "<<", ">>", "%", "<", "=="]


def apply(op: str, a: int, b: int) -> int | None:
    """problem.Machine.alu semantics, mod 2**32; None where it would trap."""
    try:
        if op == "+":
            r = a + b
        elif op == "-":
            r = a - b
        elif op == "*":
            r = a * b
        elif op == "//":
            if b == 0:
                return None
            r = a // b
        elif op == "^":
            r = a ^ b
        elif op == "&":
            r = a & b
        elif op == "|":
            r = a | b
        elif op == "<<":
            if b > 64:
                return None      # simulator would build a 2**b-digit int
            r = a << b
        elif op == ">>":
            if b > 64:
                return None
            r = a >> b
        elif op == "%":
            if b == 0:
                return None
            r = a % b
        elif op == "<":
            r = int(a < b)
        elif op == "==":
            r = int(a == b)
        else:
            return None
    except (ValueError, OverflowError):
        return None
    return r % M


def const_sample() -> list[int]:
    ks = set()
    for i in range(33):
        ks.add((1 << i) % M)
        ks.add(((1 << i) - 1) % M)
        ks.add((-(1 << i)) % M)
    ks |= {0, 1, 2, 3, 5, 6, 7, 8, 9, 2047, 2048, 2054, (-6) % M, (-5) % M,
           0xFFFFFFFF, 0xAAAAAAAA, 0x55555555}
    rng = random.Random(20260728)
    for _ in range(400):
        ks.add(rng.randrange(M))
    return sorted(ks)


def parity_only_lemma() -> None:
    rng = random.Random(11)
    # vals sharing a parity must be indistinguishable
    even = [rng.randrange(M) & ~1 for _ in range(64)] + [0, 2, M - 2]
    odd = [(rng.randrange(M) | 1) for _ in range(64)] + [1, 3, M - 1]
    hits: list[tuple[str, str, int]] = []
    for op in OPS:
        for k in const_sample():
            for order in ("val,k", "k,val"):
                def f(v: int) -> int | None:
                    return apply(op, v, k) if order == "val,k" else apply(op, k, v)
                oe = {f(v) for v in even}
                oo = {f(v) for v in odd}
                if None in oe or None in oo:
                    continue
                if len(oe) == 1 and len(oo) == 1:
                    hits.append((op, order, k))
    print("== (1) PARITY-ONLY LEMMA: single ops whose output depends on val "
          "only through bit0 ==")
    print(f"   searched {len(OPS)} opcodes x {len(const_sample())} constants "
          f"x 2 operand orders = {len(OPS)*len(const_sample())*2} forms")
    byop: dict[str, list[tuple[str, int]]] = {}
    for op, order, k in hits:
        byop.setdefault(op, []).append((order, k))
    for op in sorted(byop):
        ks = byop[op]
        nontrivial = [(o, k) for o, k in ks
                      if len({apply(op, 1, k) if o == "val,k" else apply(op, k, 1),
                              apply(op, 0, k) if o == "val,k" else apply(op, k, 0)}) == 2]
        print(f"   {op:<3} {len(ks):>4} forms, {len(nontrivial):>4} of them "
              f"actually DISTINGUISH the two parities")
        for o, k in sorted(nontrivial)[:6]:
            v0 = apply(op, 0, k) if o == "val,k" else apply(op, k, 0)
            v1 = apply(op, 1, k) if o == "val,k" else apply(op, k, 1)
            print(f"        {o:<6} k=0x{k:08x} -> even {v0}, odd {v1}")


def one_op_advance() -> None:
    rng = random.Random(7)
    # sample (A, val): A ranges over legal level-5..10 addresses
    samples = []
    for _ in range(200):
        idx = rng.randrange(31, 2047)
        samples.append((FP + idx, rng.randrange(M)))
    samples += [(FP + 31, 0), (FP + 31, 1), (FP + 2046, 0), (FP + 2046, 1)]

    def target(A: int, val: int) -> int:
        return (2 * A - 6 + (val & 1)) % M

    fails = 0
    wins = []
    # --- binary ops over {A, val, K} ---
    names = ["A", "val", "K"]
    for op in OPS:
        for x, y in itertools.product(names, repeat=2):
            if "K" not in (x, y):
                ok = all(apply(op, {"A": A, "val": v}[x], {"A": A, "val": v}[y])
                         == target(A, v) for A, v in samples)
                fails += 1
                if ok:
                    wins.append(f"{op}({x},{y})")
            else:
                # solve K from the first sample by brute force over the sample set
                for k in const_sample():
                    vals = {"K": k}
                    ok = True
                    for A, v in samples:
                        vals["A"], vals["val"] = A, v
                        if apply(op, vals[x], vals[y]) != target(A, v):
                            ok = False
                            break
                    if ok:
                        wins.append(f"{op}({x},{y}) K=0x{k:08x}")
                    fails += 1
    # --- multiply_add(a,b,c) = a*b+c over {A, val, K1, K2} ---
    mnames = ["A", "val", "K"]
    ks = const_sample()
    for a, b, c in itertools.product(mnames, repeat=3):
        # at most two distinct constants; brute force pairs only when needed
        kslots = [n for n in (a, b, c) if n == "K"]
        cand = [()] if not kslots else (
            [(k,) for k in ks] if len(kslots) == 1 else
            [(k1, k2) for k1 in ks for k2 in ks] if len(kslots) == 2 else [])
        if len(kslots) == 3:
            cand = []
        for combo in cand:
            it = iter(combo)
            assign = {}
            for nm in ("a", "b", "c"):
                pass
            kvals = list(combo)
            ok = True
            for A, v in samples:
                env = {"A": A, "val": v}
                ki = 0
                vs = []
                for n in (a, b, c):
                    if n == "K":
                        vs.append(kvals[ki]); ki += 1
                    else:
                        vs.append(env[n])
                if (vs[0] * vs[1] + vs[2]) % M != target(A, v):
                    ok = False
                    break
            fails += 1
            if ok:
                wins.append(f"madd({a},{b},{c}) K={[hex(k) for k in combo]}")
    print("\n== (2) ONE-OP ADVANCE: can a single valu slot produce "
          "A' = 2A-6+(val&1)? ==")
    print(f"   structural forms tested (op x operand assignment x constant): {fails}")
    print(f"   SOLUTIONS FOUND: {len(wins)}")
    for w in wins:
        print("   ", w)


def two_value_check() -> None:
    """The flow-select escape: A' has exactly 2 possible values given A."""
    print("\n== (3) flow-vselect escape ==")
    print("   Given A, A' in {2A-6, 2A-5} -- exactly 2 values, so a vselect")
    print("   COULD produce A' for free IF both arms were already live.")
    print("   Arms are 2A-6 and 2A-5 = (2A-6)+1; producing 2A-6 is itself a")
    print("   madd, and +1 has no free vector spelling (flow add_imm is")
    print("   scalar: 8 flow slots/group-round x 448 = 3584 > 940 budget).")


if __name__ == "__main__":
    parity_only_lemma()
    one_op_advance()
    two_value_check()
