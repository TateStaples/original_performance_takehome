#!/usr/bin/env python3
"""P5-I: exact decision machinery for sandwich9.

Shape (matches tools/p5d_sandwich9.py SANDWICH_9 and stoke.rs s9 exactly):
    b   = x*K1 + C1        (mod 2^32)
    c   = b ^ M1 ^ (b >> s1)
    e   = c*K2 + C2
    w   = e ^ M2 ^ (e >> s2)
    out = w*K3 + C3
K1,K2,K3 ODD (P5-H bijectivity lemma: composition bijective => every factor
bijective; even K madd is non-injective).  s1,s2 in 1..31 (s=0 degenerates
sigma to a constant, non-bijective).  961 (s1,s2) pairs.

WINDOW THEOREM (the exact refutation weapon):
  For ANY constants, out_0 is a function of x mod 2^(min(s1+s2,31)+1).
  Proof chain: madd is bit-triangular (out bits 0..m depend on in bits
  0..m); c_i = b_i ^ M1_i ^ b_{i+s1} so c mod 2^(s2+1) needs b only up to
  bit min(s1+s2,31); w_0 = e_0 ^ M2_0 ^ e_{s2} needs e mod 2^(s2+1);
  out_0 = w_0 ^ C3_0 since K3 odd (no carry at bit 0).
  COROLLARY: if s1+s2 <= 30 and there exist x ≡ x' (mod 2^(s1+s2+1)) with
  myhash(x)_0 != myhash(x')_0, the pair (s1,s2) admits NO constants: a
  single witness pair is an exact, machine-checkable refutation certificate.
  A witness with x' = x + 2^31 refutes ALL pairs with s1+s2 <= 30 at once
  (2^31 is a multiple of every 2^(L+1), L<=30).

For s1+s2 >= 31 the window is the full word: no bit-level constraint exists
until ALL of (K1,C1) [64 bits] plus the M1/K2/C2 windows are fixed, so the
briefed lift-and-prune has its first prune only after ~2^80+ states: the
explicit-set (and affine) lift is dead on arrival for exactly the surviving
pairs.  Those go to fixed-shift z3 (tools/p5i_z3pair.py).

This file: (1) verifies myhash == P5-D's fused form, (2) numerically
validates the window theorem against random constants (guards the
derivation), (3) demonstrates the survivor cone (out_0 depends on K1 bit
31), (4) finds the universal witness + per-L witnesses, (5) prints the
961-pair classification.
"""
import random
import sys

M32 = (1 << 32) - 1

HASH_STAGES = [  # verbatim from problem.py:472-479
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
    """Ground truth, transcribed from problem.py:482-502."""
    for op1, val1, op2, op3, val3 in HASH_STAGES:
        v = BINOPS[op2](BINOPS[op1](v, val1) & M32, BINOPS[op3](v, val3) & M32) & M32
    return v


C0f, C1f = 0x7ED55D16, 0xC761C23C
KPf, APf = 33, 0xE9F8CC1D
KQf, AQf = 16896, 0xACCF6200
K4f, C4f = 9, 0xFD7046C5
C5f = 0xB55A4F09


def myhash_fused(v):
    """P5-D's fused 11-op form (tools/p5d_cegis.py) -- cross-check."""
    v = (v * 4097 + C0f) & M32
    v = (v ^ C1f) ^ (v >> 19)
    p = (v * KPf + APf) & M32
    q = (v * KQf + AQf) & M32
    v = p ^ q
    v = (v * K4f + C4f) & M32
    return ((v ^ C5f) ^ (v >> 16)) & M32


def sandwich(k1, c1, m1, s1, k2, c2, m2, s2, k3, c3, x):
    b = (x * k1 + c1) & M32
    c = b ^ m1 ^ (b >> s1)
    e = (c * k2 + c2) & M32
    w = e ^ m2 ^ (e >> s2)
    return (w * k3 + c3) & M32


def rand_params(rng, s1, s2):
    k1 = rng.getrandbits(32) | 1
    k2 = rng.getrandbits(32) | 1
    k3 = rng.getrandbits(32) | 1
    return (k1, rng.getrandbits(32), rng.getrandbits(32), s1,
            k2, rng.getrandbits(32), rng.getrandbits(32), s2,
            k3, rng.getrandbits(32))


def main():
    rng = random.Random(0x9517)

    # (1) ground truth agreement
    for i in range(100_000):
        x = rng.getrandbits(32)
        assert myhash(x) == myhash_fused(x), hex(x)
    for x in (0, 1, M32, 1 << 31, 0xDEADBEEF):
        assert myhash(x) == myhash_fused(x)
    print("[1] myhash(problem.py) == myhash_fused(p5d): 100k+edges AGREE")

    # (2) window theorem numeric validation: out_0 must be invariant under
    # x -> x + t*2^(L+1) for any constants when L = s1+s2 <= 30.
    trials = 0
    for _ in range(4000):
        s1 = rng.randrange(1, 31)
        s2 = rng.randrange(1, 31)
        L = s1 + s2
        if L > 30:
            continue
        p = rand_params(rng, s1, s2)
        x = rng.getrandbits(32)
        t = rng.getrandbits(32) | 1
        x2 = (x + ((t << (L + 1)) & M32)) & M32
        a = sandwich(*p, x) & 1
        b = sandwich(*p, x2) & 1
        assert a == b, f"WINDOW THEOREM VIOLATED at s1={s1} s2={s2}"
        trials += 1
    # edge pairs
    for (s1, s2) in [(1, 29), (29, 1), (1, 1), (15, 15), (14, 16), (16, 14)]:
        for _ in range(500):
            p = rand_params(rng, s1, s2)
            x = rng.getrandbits(32)
            t = rng.getrandbits(32) | 1
            x2 = (x + ((t << (s1 + s2 + 1)) & M32)) & M32
            assert (sandwich(*p, x) & 1) == (sandwich(*p, x2) & 1)
            trials += 1
    print(f"[2] window theorem holds on {trials} random-constant trials "
          "(incl. edge pairs): out_0 = f(x mod 2^(s1+s2+1)) for L<=30")

    # (2b) sharpness: for a survivor pair the invariance must FAIL for
    # generic constants (window genuinely full) -- else our classification
    # would be too coarse.
    for (s1, s2) in [(16, 15), (15, 16), (19, 16), (31, 31)]:
        broken = False
        for _ in range(200):
            p = rand_params(rng, s1, s2)
            x = rng.getrandbits(32)
            x2 = (x + (1 << 31)) & M32
            if (sandwich(*p, x) & 1) != (sandwich(*p, x2) & 1):
                broken = True
                break
        assert broken, f"survivor ({s1},{s2}) unexpectedly windowed"
    print("[2b] sharpness: survivor pairs (L>=31) DO see x_31 at out_0 "
          "(generic constants) -- classification is exact, not conservative")

    # (3) survivor cone demo: out_0 depends on K1 bit 31 for L>=31.
    s1, s2 = 16, 15
    p = list(rand_params(rng, s1, s2))
    dep = False
    for _ in range(200):
        x = rng.getrandbits(32)
        q = p.copy()
        q[0] ^= 1 << 31  # flip K1 top bit
        if (sandwich(*p, x) & 1) != (sandwich(*q, x) & 1):
            dep = True
            break
    print(f"[3] survivor cone: out_0 depends on K1 bit31 at (16,15): {dep} "
          "(first lift constraint needs ALL 64 bits of K1,C1)")

    # (4) universal witness: x' = x + 2^31, myhash bit0 differs
    uni = None
    for _ in range(256):
        x = rng.getrandbits(32)
        x2 = (x + (1 << 31)) & M32
        if (myhash(x) ^ myhash(x2)) & 1:
            uni = (x, x2)
            break
    assert uni, "no universal witness found (?!)"
    print(f"[4] UNIVERSAL WITNESS: x=0x{uni[0]:08X} x'=0x{uni[1]:08X} "
          f"(x'-x=2^31): myhash bit0 = {myhash(uni[0]) & 1} vs {myhash(uni[1]) & 1}"
          " -> refutes ALL 435 pairs with s1+s2<=30 exactly")

    # per-L witnesses (independent redundancy)
    perl = {}
    for L in range(2, 31):
        for _ in range(512):
            x = rng.getrandbits(32)
            t = rng.getrandbits(32) | 1
            x2 = (x + ((t << (L + 1)) & M32)) & M32
            if x2 != x and (myhash(x) ^ myhash(x2)) & 1:
                perl[L] = (x, x2)
                break
    assert set(perl) == set(range(2, 31)), sorted(set(range(2, 31)) - set(perl))
    print("[4b] independent per-L witnesses found for every L in 2..30:")
    for L in range(2, 31):
        x, x2 = perl[L]
        print(f"    L={L:2d}: x=0x{x:08X} x'=0x{x2:08X}  "
              f"(x'-x = 0x{(x2 - x) & M32:08X}, multiple of 2^{L + 1})")

    # (5) ROW s1+s2=31 DIFFERENTIAL KILL.
    # THEOREM: for s1+s2=31, s1,s2<=30, any odd K2 and ANY other constants:
    #   sandwich(x ^ 2^31)_0 ^ sandwich(x)_0 = 1 for ALL x.
    # Proof: b* = b ^ 2^31 exactly (K1 odd); c* = c ^ 2^31 ^ 2^u exactly
    # (u = 31-s1 = s2 here, 1<=u<=30); e* = e + sg1*2^31 + sg2*K2*2^u with
    # sg in {+-1}; bit 0 of e unchanged (u>=1), bit s2: the 2^31 term never
    # reaches bit s2<=30, and K2*2^u mod 2^(s2+1) = 2^s2 (K2 odd, u=s2), so
    # e_s2 always flips; w_0 = e_0^M2_0^e_s2 flips; out_0 = w_0^C3_0 (K3
    # odd) flips.  myhash has witnesses with UNCHANGED bit 0 under x^2^31
    # => the whole row is refuted by one witness.
    for _ in range(3000):
        s1 = rng.randrange(1, 31)  # 1..30
        s2 = 31 - s1
        p = rand_params(rng, s1, s2)
        x = rng.getrandbits(32)
        d = (sandwich(*p, x) ^ sandwich(*p, x ^ (1 << 31))) & 1
        assert d == 1, f"ROW-31 THEOREM VIOLATED at s1={s1}"
    row31_wit = None
    for _ in range(256):
        x = rng.getrandbits(32)
        if not ((myhash(x) ^ myhash(x ^ (1 << 31))) & 1):
            row31_wit = x
            break
    assert row31_wit is not None
    print(f"[5] ROW-31 DIFFERENTIAL KILL: validated on 3000 random-constant "
          f"trials (delta out_0 == 1 always); myhash witness x=0x{row31_wit:08X} "
          f"has myhash(x)_0 == myhash(x^2^31)_0 -> all 30 pairs with "
          "s1+s2=31 REFUTED EXACTLY")

    # (6) classification of the 961 pairs
    refuted = [(a, b) for a in range(1, 32) for b in range(1, 32) if a + b <= 30]
    row31 = [(a, 31 - a) for a in range(1, 31)]
    surv = [(a, b) for a in range(1, 32) for b in range(1, 32) if a + b >= 32]
    assert len(refuted) + len(row31) + len(surv) == 961
    print(f"[6] PAIR CLASSIFICATION: {len(refuted)} REFUTED (window witness, "
          f"s1+s2<=30) + {len(row31)} REFUTED (row-31 differential) = "
          f"{len(refuted) + len(row31)} exact; {len(surv)} SURVIVORS "
          "(s1+s2>=32) -> fixed-shift z3 (p5i_z3pair.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
