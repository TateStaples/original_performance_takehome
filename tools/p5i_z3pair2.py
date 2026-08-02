#!/usr/bin/env python3
"""P5-I2: width-TRUNCATED fixed-shift z3 decision for one sandwich9 (s1,s2).

Same question as tools/p5i_z3pair.py, same soundness contract, but the
low-k rungs are encoded at the exact minimal bit-widths implied by the
cone of `out mod 2^k` instead of at 32 bits everywhere.

Cone (exact, see research/strains/p5i/STATE.md sec 5):
    out mod 2^k   needs K3,C3 mod 2^k and w mod 2^k
    w   mod 2^k   needs M2 mod 2^k, e mod 2^k and e bits s2..s2+k-1
    e   mod 2^We  needs K2,C2 mod 2^We and c mod 2^We,  We = min(32, s2+k)
    c   mod 2^We  needs M1 mod 2^We, b mod 2^We and b bits s1..s1+We-1
    b   mod 2^Wb  needs K1,C1 mod 2^Wb,                 Wb = min(32, s1+s2+k)
and Wb - s1 == We exactly when Wb < 32, so LShR at the truncated width
zero-fills only positions >= We, which are discarded.  Truncation is
therefore EXACT, not a relaxation: the encoded formula is satisfiable iff
the 32-bit formula restricted to `out mod 2^k` on those samples is.
=> UNSAT here is still an exact refutation of the pair.

Unknown bits at rung k: 2*Wb + 3*We + 3*k  (vs 256 at full width).

Usage:
  python3 tools/p5i_z3pair2.py S1 S2 [--timeout SEC] [--ks 8,16,32]
                                     [--nrand 16] [--selftest]
"""
import argparse
import random
import sys
import time

import z3

from p5i_z3pair import M32, myhash, sandwich_py, battery


def encode_rung(s1, s2, k, xs, tgt):
    """Fresh solver for the `out mod 2^k` constraint on samples xs."""
    Wb = min(32, s1 + s2 + k)
    We = min(32, s2 + k)
    Ww = k
    K1, C1 = z3.BitVecs(f"K1_{k} C1_{k}", Wb)
    M1, K2, C2 = z3.BitVecs(f"M1_{k} K2_{k} C2_{k}", We)
    M2, K3, C3 = z3.BitVecs(f"M2_{k} K3_{k} C3_{k}", Ww)
    s = z3.Solver()
    for K in (K1, K2, K3):
        s.add(z3.Extract(0, 0, K) == 1)  # odd-K lemma (sound)
    for x in xs:
        b = z3.BitVecVal(x & ((1 << Wb) - 1), Wb) * K1 + C1
        c = z3.Extract(We - 1, 0, b) ^ M1 ^ z3.Extract(We - 1, 0, z3.LShR(b, s1))
        e = c * K2 + C2
        w = (z3.Extract(Ww - 1, 0, e) ^ M2
             ^ z3.Extract(Ww - 1, 0, z3.LShR(e, s2)))
        out = w * K3 + C3
        s.add(out == z3.BitVecVal(tgt[x] & ((1 << k) - 1), Ww))
    return s, (Wb, We, Ww)


def decide_pair2(s1, s2, target_fn, rung_timeout_s, ks=(8, 16, 32),
                 nrand=16, max_iters=6, verbose=True):
    """(verdict, detail); verdict in REFUTED / FOUND / OPEN / GAVE_UP."""
    rng = random.Random(0x5150 + s1 * 37 + s2)
    xs = battery(rng, nrand)
    tgt = {x: target_fn(x) for x in xs}
    t_all = time.time()

    for it in range(max_iters):
        for k in ks:
            s, widths = encode_rung(s1, s2, k, xs, tgt)
            s.set("timeout", rung_timeout_s * 1000)
            t0 = time.time()
            res = s.check()
            dt = time.time() - t0
            if verbose:
                print(f"    rung k={k} W={widths} n={len(xs)}: {res} ({dt:.1f}s)",
                      flush=True)
            if res == z3.unsat:
                return ("REFUTED", f"rung=k{k} iter={it} n={len(xs)} "
                                   f"solve={dt:.1f}s total={time.time()-t_all:.1f}s")
            if res == z3.unknown:
                return ("OPEN", f"rung=k{k} iter={it} n={len(xs)} "
                                f"timeout={rung_timeout_s}s "
                                f"reason={s.reason_unknown()}")
            last = (s, k)
        # SAT through the top rung (k must end at 32): verify outside z3.
        s, k = last
        assert k == 32, "top rung must be 32 for FOUND to be meaningful"
        m = s.model()
        names = [f"K1_32", f"C1_32", f"M1_32", f"K2_32", f"C2_32",
                 f"M2_32", f"K3_32", f"C3_32"]
        env = {d.name(): m[d].as_long() for d in m.decls()}
        P = [env[n] & M32 for n in names]
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
                             f"total={time.time()-t_all:.1f}s")
        xs = xs + [cex]
        tgt[cex] = target_fn(cex)
    return ("GAVE_UP", f"{max_iters} CEGIS iters")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("s1", type=int)
    ap.add_argument("s2", type=int)
    ap.add_argument("--timeout", type=int, default=25)
    ap.add_argument("--ks", default="8,16,32")
    ap.add_argument("--nrand", type=int, default=16)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    ks = tuple(int(t) for t in a.ks.split(","))

    if a.selftest:
        # (1) TRUNCATION GUARD: pinned constants, symbolic truncated circuit
        # must reproduce sandwich_py(...) mod 2^k on random inputs.
        rngE = random.Random(99)
        ok = True
        for k in ks:
            Wb = min(32, a.s1 + a.s2 + k)
            We = min(32, a.s2 + k)
            PE = [rngE.getrandbits(32) | 1, rngE.getrandbits(32),
                  rngE.getrandbits(32), rngE.getrandbits(32) | 1,
                  rngE.getrandbits(32), rngE.getrandbits(32),
                  rngE.getrandbits(32) | 1, rngE.getrandbits(32)]
            xs = [rngE.getrandbits(32) for _ in range(48)]
            tgt = {x: sandwich_py(PE, a.s1, a.s2, x) for x in xs}
            s, _ = encode_rung(a.s1, a.s2, k, xs, tgt)
            # pin the truncated unknowns to the planted values
            trunc = [PE[0] & ((1 << Wb) - 1), PE[1] & ((1 << Wb) - 1),
                     PE[2] & ((1 << We) - 1), PE[3] & ((1 << We) - 1),
                     PE[4] & ((1 << We) - 1), PE[5] & ((1 << k) - 1),
                     PE[6] & ((1 << k) - 1), PE[7] & ((1 << k) - 1)]
            names = [f"K1_{k}", f"C1_{k}", f"M1_{k}", f"K2_{k}", f"C2_{k}",
                     f"M2_{k}", f"K3_{k}", f"C3_{k}"]
            widths = [Wb, Wb, We, We, We, k, k, k]
            for n, w, v in zip(names, widths, trunc):
                s.add(z3.BitVec(n, w) == v)
            r = s.check()
            print(f"SELFTEST-TRUNC k={k} pair=({a.s1},{a.s2}): planted "
                  f"constants are {r} (want sat)")
            ok = ok and (r == z3.sat)
        assert ok
        # (2) planted-target end-to-end (FOUND expected only if z3 can solve)
        rng = random.Random(1234)
        P = [rng.getrandbits(32) | 1, rng.getrandbits(32), rng.getrandbits(32),
             rng.getrandbits(32) | 1, rng.getrandbits(32), rng.getrandbits(32),
             rng.getrandbits(32) | 1, rng.getrandbits(32)]
        target = lambda x: sandwich_py(P, a.s1, a.s2, x)  # noqa: E731
        v, d = decide_pair2(a.s1, a.s2, target, a.timeout, ks, a.nrand,
                            verbose=not a.quiet)
        print(f"SELFTEST-PLANTED pair=({a.s1},{a.s2}) verdict={v} {d}")
        print("  (REFUTED here would be a FATAL encoding bug; OPEN/FOUND ok)")
        sys.exit(1 if v == "REFUTED" else 0)

    v, d = decide_pair2(a.s1, a.s2, myhash, a.timeout, ks, a.nrand,
                        verbose=not a.quiet)
    print(f"CHECKPOINT2 pair=({a.s1},{a.s2}) verdict={v} {d}", flush=True)


if __name__ == "__main__":
    main()
