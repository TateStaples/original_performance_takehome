#!/usr/bin/env python3
"""P5-L part 1: exact GF(2)/arithmetic computations for the 2-round
composite mechanism accounting.

1. Validate the fused 11-op myhash == problem.py HASH_STAGES semantics.
2. GF(2) matrix product of the two sigma layers: L19*L16 = I ^ S16 ^ S19
   (S^35 = 0); functional verification; rank/invertibility.
3. Verify the 4-op implementation of the merged layer and state the
   support-offset lower bound (proof in STATE.md).
4. Commutation obstruction, quantified:
   - mult-by-K is GF(2)-linear iff K is a power of two (witnesses);
   - for K = 2^s+1 (4097, 33, 9): exact fraction of v where K*v acts
     carry-free (= xor-shift analogue), via Fibonacci-chain DP;
   - explicit failing affinity triples for the natural conjugate
     g(w) = K*sigma_s(inv(K)*w)  [witness => g not affine].
5. Runtime XOR<->ADD lemma (P3-F lemma, runtime form): for y fixed,
   (v ^ y) == v + f(y) for all v  iff  y in {0, 2^31}.
"""
import random
import sys

sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome")
import numpy as np
from problem import myhash as myhash_ref

MASK = (1 << 32) - 1
C0, K0 = 0x7ED55D16, 4097
C1 = 0xC761C23C
KP, AP = 33, 0xE9F8CC1D
KQ, AQ = 16896, 0xACCF6200
K4, C4 = 9, 0xFD7046C5
C5 = 0xB55A4F09


def myhash_fused(v):
    v = (v * K0 + C0) & MASK
    v = (v ^ C1) ^ (v >> 19)
    v = ((v * KP + AP) & MASK) ^ ((v * KQ + AQ) & MASK)
    v = (v * K4 + C4) & MASK
    return ((v ^ C5) ^ (v >> 16)) & MASK


def check1():
    rng = random.Random(1)
    for _ in range(100_000):
        v = rng.getrandbits(32)
        assert myhash_fused(v) == myhash_ref(v), v
    for v in (0, 1, MASK, 1 << 31):
        assert myhash_fused(v) == myhash_ref(v)
    print("[1] fused 11-op myhash == problem.py myhash on 100k randoms + corners: PASS")


# --- GF(2) machinery -------------------------------------------------------
def shift_down_matrix(s):
    """Matrix of v -> v >> s on GF(2)^32, bit i of output = bit i+s of input.
    Row = output bit, col = input bit."""
    M = np.zeros((32, 32), dtype=np.uint8)
    for i in range(32 - s):
        M[i, i + s] = 1
    return M


def apply_mat(M, v):
    bits = np.array([(v >> j) & 1 for j in range(32)], dtype=np.uint8)
    out = (M @ bits) % 2
    return int(sum(int(b) << i for i, b in enumerate(out)))


def gf2_rank(M):
    M = M.copy() % 2
    r = 0
    for c in range(32):
        piv = None
        for i in range(r, 32):
            if M[i, c]:
                piv = i
                break
        if piv is None:
            continue
        M[[r, piv]] = M[[piv, r]]
        for i in range(32):
            if i != r and M[i, c]:
                M[i] ^= M[r]
        r += 1
    return r


def sigma(v, s):
    return (v ^ (v >> s)) & MASK


def check2():
    I = np.eye(32, dtype=np.uint8)
    S16, S19 = shift_down_matrix(16), shift_down_matrix(19)
    L16, L19 = (I + S16) % 2, (I + S19) % 2
    P = (L19 @ L16) % 2
    expected = (I + S16 + S19 + (S19 @ S16)) % 2
    assert np.array_equal(P, expected)
    S35 = (S19 @ S16) % 2
    assert not S35.any(), "S^35 should be 0 (35 >= 32)"
    assert np.array_equal(P, (I + S16 + S19) % 2)
    rng = random.Random(2)
    for _ in range(10_000):
        v = rng.getrandbits(32)
        direct = sigma(sigma(v, 16), 19)
        assert apply_mat(P, v) == direct
        assert direct == v ^ (v >> 16) ^ (v >> 19)
        # the 4-op merged implementation: t = v ^ (v>>3); out = v ^ (t>>16)
        t = v ^ (v >> 3)
        assert (v ^ (t >> 16)) == direct
    print("[2] L19*L16 == I ^ S16 ^ S19 (S^35=0): PASS; functional 10k: PASS")
    print(f"    rank(P) over GF(2) = {gf2_rank(P)} (32 = bijective)")
    print("    4-op merged impl (shr3,xor2,shr16,xor2) == sigma19(sigma16(v)): PASS")


# --- commutation obstruction ----------------------------------------------
def modinv(k):
    return pow(k, -1, 1 << 32)


def check4():
    # (i) mult-by-K GF(2)-linear iff K power of 2: witness for each real K.
    for K in (4097, 33, 9, 16896):
        found = None
        rng = random.Random(K)
        for _ in range(1000):
            x, y = rng.getrandbits(32), rng.getrandbits(32)
            if (K * (x ^ y)) & MASK != ((K * x) ^ (K * y)) & MASK:
                found = (x, y)
                break
        assert found, K
        print(f"[4i] K={K}: GF(2)-linearity witness x={found[0]:#x} y={found[1]:#x} "
              f"(K*(x^y) != Kx^Ky)")
    # (ii) linear-action fraction for K = 2^s + 1: K*v mod 2^32 equals the
    # xor-analogue v ^ (v<<s) iff the add a=v, b=(v<<s)&MASK is carry-free
    # OR the sole carry wraps out: a&b in {0, 2^31} (2*(2^31) == 0 mod 2^32
    # -- the same 2^31 exception as the P3-F lemma).
    # Exact count: residue chains mod s; a&b==0 <=> no two adjacent ones in
    # any chain -> product of Fibonacci(len+2). a&b==2^31 <=> the single
    # adjacency (31-s, 31) is set with its lower neighbor 0, all other
    # chains adjacency-free.
    def fib(n):
        a, b = 0, 1
        for _ in range(n):
            a, b = b, a + b
        return a

    def count_no_adj(chain_len):
        return fib(chain_len + 2)

    def count_top_pair_only(chain_bits):
        # chain containing bit 31: patterns with v[31]=v[31-s]=1, no OTHER
        # adjacency in this chain. Bits below 31-s form a no-adjacent-ones
        # string whose TOP bit (neighbor of 31-s) is 0.
        m = len(chain_bits) - 2  # bits below the top pair
        if m == 0:
            return 1
        # strings of length m, no two adjacent ones, last bit 0:
        # = count_no_adj(m-1) (drop the forced 0)
        return count_no_adj(m - 1)

    for K, s in ((4097, 12), (33, 5), (9, 3)):
        A = 1
        B = 1
        for r in range(s):
            chain = list(range(r, 32, s))
            A *= count_no_adj(len(chain))
            if 31 in chain:
                B *= count_top_pair_only(chain)
            else:
                B *= count_no_adj(len(chain))
        total = A + B
        frac = total / 2**32
        # validate the condition equivalence + estimate on randoms
        rng = random.Random(s)
        hits = 0
        N = 200_000
        for _ in range(N):
            v = rng.getrandbits(32)
            cond = (v & ((v << s) & MASK)) in (0, 1 << 31)
            lin = ((K * v) & MASK) == (v ^ ((v << s) & MASK))
            assert cond == lin, (v, K, s)
            hits += lin
        print(f"[4ii] K={K}=2^{s}+1: K*v acts GF(2)-linearly on exactly "
              f"{total} / 2^32 inputs = {frac:.4%} (sampled {hits/N:.4%})")
    # (iii) natural-conjugate affinity failure witnesses:
    # g(w) = K*sigma_s(inv(K)*w). If madd_K commuted through sigma_s with the
    # NATURAL candidate K''=K, B would equal g and must be affine.
    # Affine test: g(x)^g(y)^g(z)^g(x^y^z) == 0 for all x,y,z.
    for K, s in ((4097, 16), (9, 16), (4097, 19), (33, 19)):
        ki = modinv(K)
        def g(w):
            return (K * sigma((ki * w) & MASK, s)) & MASK
        rng = random.Random(100 * K + s)
        fails = 0
        witness = None
        N = 50_000
        for _ in range(N):
            x, y, z = (rng.getrandbits(32) for _ in range(3))
            if g(x) ^ g(y) ^ g(z) ^ g(x ^ y ^ z):
                fails += 1
                if witness is None:
                    witness = (x, y, z)
        print(f"[4iii] K={K},s={s}: natural conjugate non-affine; "
              f"failing triples {fails}/{N} = {fails/N:.2%}; "
              f"witness {tuple(hex(t) for t in witness)}")


def check5():
    # runtime XOR<->ADD lemma: (v ^ y) == v + f(y) mod 2^32 for all v
    # iff y in {0, 2^31}.  Proof: v=0 forces f(y)=y; v=y forces y+y==0.
    for y in (0, 1 << 31):
        f = y  # v=0 forces this
        rng = random.Random(y + 7)
        for _ in range(20_000):
            v = rng.getrandbits(32)
            assert (v ^ y) == (v + f) & MASK
    rng = random.Random(9)
    for _ in range(1000):
        y = rng.getrandbits(30)  # node values are uniform in [0, 2^30)
        if y == 0:
            continue
        f = y  # forced by v=0
        # find violating v (v=y works: (y^y)=0 vs y+y=2y != 0 unless 2y==0)
        assert (y ^ y) != (y + f) & MASK or y == 0
    print("[5] runtime XOR<->ADD lemma: y in {0,2^31} commute exactly; every "
          "y in [1,2^30) has violation v=y (2y != 0 mod 2^32): PASS")


if __name__ == "__main__":
    check1()
    check2()
    check4()
    check5()
    print("ALL PASS")
