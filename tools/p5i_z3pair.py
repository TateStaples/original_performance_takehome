#!/usr/bin/env python3
"""P5-I: fixed-shift z3 decision for one sandwich9 (s1,s2) pair.

For survivors of the window-theorem refutation (s1+s2>=31; see
tools/p5i_proto.py) the bit-serial lift has no early constraint, so the
remaining exact tool is per-pair constraint solving with BOTH shifts fixed
(the free-shift whole problem timed out at 424s and 10,800s in P5-D).

Soundness:
  - UNSAT on a battery of necessary conditions (sample equalities, low-bit
    masked equalities, odd-K lemma) => the pair admits NO constants: exact.
    Odd-K lemma: myhash is bijective; a composition on a finite set is
    bijective only if every factor is; madd with even K is non-injective.
  - SAT => constants verified OUTSIDE z3 (2^20 sweep + 10^7 random);
    mismatch => CEGIS iterate with the counterexample.
  - unknown => OPEN (never counted as closed).
  - Encoding guarded by --selftest: planted sandwich9 target with the same
    shifts must come back FOUND+verified (catches encoding bugs that would
    otherwise fabricate UNSATs).

Usage:
  python3 tools/p5i_z3pair.py S1 S2 [--timeout SEC_PER_RUNG] [--selftest]
Prints one CHECKPOINT line (append to research/strains/p5i/STATE.md).
"""
import argparse
import random
import sys
import time

import z3

M32 = (1 << 32) - 1

HASH_STAGES = [
    ("+", 0x7ED55D16, "+", "<<", 12),
    ("^", 0xC761C23C, "^", ">>", 19),
    ("+", 0x165667B1, "+", "<<", 5),
    ("+", 0xD3A2646C, "^", "<<", 9),
    ("+", 0xFD7046C5, "+", "<<", 3),
    ("^", 0xB55A4F09, "^", ">>", 16),
]
BINOPS = {
    "+": lambda x, y: (x + y) & M32,
    "^": lambda x, y: x ^ y,
    "<<": lambda x, y: (x << y) & M32,
    ">>": lambda x, y: x >> y,
}


def myhash(v):
    for op1, val1, op2, op3, val3 in HASH_STAGES:
        v = BINOPS[op2](BINOPS[op1](v, val1) & M32, BINOPS[op3](v, val3) & M32) & M32
    return v


def sandwich_py(P, s1, s2, x):
    k1, c1, m1, k2, c2, m2, k3, c3 = P
    b = (x * k1 + c1) & M32
    c = b ^ m1 ^ (b >> s1)
    e = (c * k2 + c2) & M32
    w = e ^ m2 ^ (e >> s2)
    return (w * k3 + c3) & M32


def battery(rng, n_random):
    xs = [0, 1, M32, 1 << 31, 0x4E005510, 0xCE005510]  # edges + universal witness pair
    xs += [rng.getrandbits(32) for _ in range(n_random)]
    # structured congruent pairs (top-bit differentials constrain hard)
    for _ in range(4):
        x = rng.getrandbits(32)
        xs += [x, x ^ (1 << 31), x ^ (1 << 30)]
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def decide_pair(s1, s2, target_fn, rung_timeout_s, max_iters=6, verbose=True):
    """Returns (verdict, detail). verdict in REFUTED / FOUND / OPEN / GAVE_UP."""
    K1, C1, M1 = z3.BitVecs("K1 C1 M1", 32)
    K2, C2, M2 = z3.BitVecs("K2 C2 M2", 32)
    K3, C3 = z3.BitVecs("K3 C3", 32)
    unk = [K1, C1, M1, K2, C2, M2, K3, C3]

    def sym(xv):
        b = xv * K1 + C1
        c = b ^ M1 ^ z3.LShR(b, s1)
        e = c * K2 + C2
        w = e ^ M2 ^ z3.LShR(e, s2)
        return w * K3 + C3

    s = z3.Solver()
    s.set("timeout", rung_timeout_s * 1000)
    for K in (K1, K2, K3):
        s.add(z3.Extract(0, 0, K) == 1)  # odd-K lemma (sound)

    rng = random.Random(0x5150 + s1 * 37 + s2)
    xs = battery(rng, 16)
    tgt = {x: target_fn(x) for x in xs}

    # UNSAT ladder: masked low-k equalities, cheap rungs first.
    rungs = [(8, xs), (16, xs), (32, xs)]
    t_all = time.time()
    for it in range(max_iters):
        for k, sub in rungs:
            mask = z3.BitVecVal((1 << k) - 1, 32)
            for x in sub:
                s.add((sym(z3.BitVecVal(x, 32)) ^ z3.BitVecVal(tgt[x], 32)) & mask == 0)
            t0 = time.time()
            res = s.check()
            dt = time.time() - t0
            if verbose:
                print(f"    rung k={k} n={len(sub)}: {res} ({dt:.1f}s)", flush=True)
            if res == z3.unsat:
                return ("REFUTED", f"rung=k{k} iter={it} solve={dt:.1f}s "
                                   f"total={time.time() - t_all:.1f}s")
            if res == z3.unknown:
                return ("OPEN", f"rung=k{k} iter={it} timeout={rung_timeout_s}s "
                               f"reason={s.reason_unknown()}")
        # SAT at full width: extract + verify outside z3
        m = s.model()
        P = [m.eval(u, model_completion=True).as_long() for u in unk]
        cex = None
        for v in range(1 << 20):
            if sandwich_py(P, s1, s2, v) != target_fn(v):
                cex = v
                break
        if cex is None:
            r2 = random.Random(0xF00D)
            for _ in range(10_000_000):
                v = r2.getrandbits(32)
                if sandwich_py(P, s1, s2, v) != target_fn(v):
                    cex = v
                    break
        if cex is None:
            return ("FOUND", f"P={[hex(p) for p in P]} VERIFIED 2^20+10M "
                             f"total={time.time() - t_all:.1f}s")
        xs = [cex]
        tgt[cex] = target_fn(cex)
        rungs = [(32, xs)]
    return ("GAVE_UP", f"{max_iters} CEGIS iters")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("s1", type=int)
    ap.add_argument("s2", type=int)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.s1 <= 31 and 1 <= a.s2 <= 31

    if a.selftest:
        # 1) ENCODING GUARD: pin unknowns to planted constants; symbolic
        # circuit must agree with the Python evaluator on random inputs
        # (UNSAT of disagreement). Decisive against false-UNSAT encodings.
        rngE = random.Random(99)
        K1, C1, M1 = z3.BitVecs("K1 C1 M1", 32)
        K2, C2, M2 = z3.BitVecs("K2 C2 M2", 32)
        K3, C3 = z3.BitVecs("K3 C3", 32)
        PE = [rngE.getrandbits(32) | 1, rngE.getrandbits(32), rngE.getrandbits(32),
              rngE.getrandbits(32) | 1, rngE.getrandbits(32), rngE.getrandbits(32),
              rngE.getrandbits(32) | 1, rngE.getrandbits(32)]
        se = z3.Solver()
        for u, val in zip([K1, C1, M1, K2, C2, M2, K3, C3], PE):
            se.add(u == val)
        bad = z3.BoolVal(False)
        for _ in range(64):
            x = rngE.getrandbits(32)
            b = z3.BitVecVal(x, 32) * K1 + C1
            c = b ^ M1 ^ z3.LShR(b, a.s1)
            e = c * K2 + C2
            w = e ^ M2 ^ z3.LShR(e, a.s2)
            out = w * K3 + C3
            bad = z3.Or(bad, out != z3.BitVecVal(sandwich_py(PE, a.s1, a.s2, x), 32))
        se.add(bad)
        r = se.check()
        print(f"SELFTEST-ENCODING pair=({a.s1},{a.s2}): disagreement is {r} "
              "(want unsat)")
        assert r == z3.unsat
        rng = random.Random(1234)
        P = [rng.getrandbits(32) | 1, rng.getrandbits(32), rng.getrandbits(32),
             rng.getrandbits(32) | 1, rng.getrandbits(32), rng.getrandbits(32),
             rng.getrandbits(32) | 1, rng.getrandbits(32)]
        # reorder to (k1,c1,m1,k2,c2,m2,k3,c3) layout used by sandwich_py
        P = [P[0], P[1], P[2], P[3], P[4], P[5], P[6], P[7]]
        target = lambda x: sandwich_py(P, a.s1, a.s2, x)  # noqa: E731
        v, d = decide_pair(a.s1, a.s2, target, a.timeout, verbose=not a.quiet)
        print(f"SELFTEST pair=({a.s1},{a.s2}) verdict={v} {d}")
        print(f"  planted={[hex(p) for p in P]}")
        sys.exit(0 if v == "FOUND" else 1)

    v, d = decide_pair(a.s1, a.s2, myhash, a.timeout, verbose=not a.quiet)
    print(f"CHECKPOINT pair=({a.s1},{a.s2}) verdict={v} {d}", flush=True)


if __name__ == "__main__":
    main()
