#!/usr/bin/env python3
"""P6-B sub-audit 3: MEASURED eps of every single-op deletion of the real
11-op fused myhash.

P5-D proved each deletion is exactly UNSAT (no constants reproduce myhash).
That says eps > 0; it does not say eps is LARGE.  This measures it: for each
of the 11 ops, delete it (the op becomes the identity on one of its inputs --
both wirings tried for binary ops), then hill-climb ALL 12 constants to
MINIMISE the number of disagreeing inputs on a fixed sample.  The resulting
min-disagreement fraction is a measured UPPER bound on that family's eps.

Reference form (rust_harness/src/bin/stoke.rs:378-395, REAL_CONSTS at :361):
  0 b  = madd(x , 4097 , 0x7ED55D16)
  1 t1 = shr (b , 19)
  2 t2 = xor(b , 0xC761C23C)
  3 cc = xor(t2, t1)
  4 p  = madd(cc, 33   , 0xE9F8CC1D)
  5 q  = madd(cc, 16896, 0xACCF6200)
  6 d  = xor(p , q)
  7 e  = madd(d , 9    , 0xFD7046C5)
  8 t2 = shr (e , 16)
  9 t0 = xor(e , 0xB55A4F09)
 10 out= xor(t0, t2)
"""
import numpy as np

U32 = np.uint32
M = np.uint32(0xFFFFFFFF)
REAL = [4097, 0x7ED55D16, 19, 0xC761C23C, 33, 0xE9F8CC1D, 16896, 0xACCF6200,
        9, 0xFD7046C5, 16, 0xB55A4F09]
# constant slots used by each op (for the hill-climb's active set)
SLOTS = {0: [0, 1], 1: [2], 2: [3], 3: [], 4: [4, 5], 5: [6, 7], 6: [],
         7: [8, 9], 8: [10], 9: [11], 10: []}


def myhash_np(v):
    v = v.astype(U32)
    v = (v + U32(0x7ED55D16)) + (v << U32(12))
    v = (v ^ U32(0xC761C23C)) ^ (v >> U32(19))
    v = (v + U32(0x165667B1)) + (v << U32(5))
    v = (v + U32(0xD3A2646C)) ^ (v << U32(9))
    v = (v + U32(0xFD7046C5)) + (v << U32(3))
    v = (v ^ U32(0xB55A4F09)) ^ (v >> U32(16))
    return v


def run(x, C, drop=None, wire=0):
    """Evaluate the 11-op form with constants C; op `drop` becomes identity
    on its operand `wire` (0 = first operand, 1 = second, binary ops only)."""
    def ident(op, a, b):
        return a if wire == 0 else b
    c = [U32(v & 0xFFFFFFFF) for v in C]
    sh19 = U32(c[2] & 31) if (c[2] & 63) < 32 else U32(0)
    sh16 = U32(c[10] & 31) if (c[10] & 63) < 32 else U32(0)
    b = x if drop == 0 else (x * c[0] + c[1]).astype(U32)
    t1 = b if drop == 1 else (b >> sh19)
    t2 = b if drop == 2 else (b ^ c[3])
    cc = (t2 if wire == 0 else t1) if drop == 3 else (t2 ^ t1)
    p = cc if drop == 4 else (cc * c[4] + c[5]).astype(U32)
    q = cc if drop == 5 else (cc * c[6] + c[7]).astype(U32)
    d = (p if wire == 0 else q) if drop == 6 else (p ^ q)
    e = d if drop == 7 else (d * c[8] + c[9]).astype(U32)
    u2 = e if drop == 8 else (e >> sh16)
    u0 = e if drop == 9 else (e ^ c[11])
    out = (u0 if wire == 0 else u2) if drop == 10 else (u0 ^ u2)
    return out.astype(U32)


def score(x, want, C, drop, wire):
    o = run(x, C, drop, wire)
    bad = int((o != want).sum())
    # tie-break: total hamming distance (gives the climb a gradient once the
    # per-input count saturates at 100%)
    ham = int(np.unpackbits((o ^ want).view(np.uint8)).sum())
    return bad, ham


def climb(x, want, drop, wire, rounds=3, seed=1):
    rng = np.random.default_rng(seed)
    best = None
    for r in range(rounds):
        C = list(REAL) if r == 0 else [int(rng.integers(0, 1 << 32)) for _ in REAL]
        if r == 2:
            C = list(REAL)
            for i in SLOTS.get(drop, []):
                C[i] = int(rng.integers(0, 1 << 32))
        cur = score(x, want, C, drop, wire)
        improved = True
        it = 0
        while improved and it < 8:
            improved = False
            it += 1
            for i in range(12):
                for bit in range(32):
                    C2 = list(C)
                    C2[i] ^= (1 << bit)
                    s = score(x, want, C2, drop, wire)
                    if s < cur:
                        cur, C = s, C2
                        improved = True
        if best is None or cur < best[0]:
            best = (cur, C)
    return best


def main():
    rng = np.random.default_rng(7)
    S = 4096
    x = rng.integers(0, 1 << 32, size=S, dtype=np.uint64).astype(U32)
    want = myhash_np(x)
    assert (run(x, REAL, None, 0) == want).all(), "reference 11-op form mismatch"
    print("reference 11-op form reproduces myhash on the sample: OK")
    print(f"sample S = {S} random inputs;  eps_hat = min-disagreements / S\n")
    print(f"{'drop':>4} {'wire':>4} {'bad':>6} {'eps_hat':>10} {'ham/32S':>9}")
    rows = []
    for drop in range(11):
        wires = (0, 1) if drop in (3, 6, 10) else (0,)
        for wire in wires:
            (bad, ham), C = climb(x, want, drop, wire)
            rows.append((drop, wire, bad, ham))
            print(f"{drop:>4} {wire:>4} {bad:>6} {bad/S:>10.5f} "
                  f"{ham/(32*S):>9.4f}")
    m = min(r[2] for r in rows)
    print(f"\nBEST over all 11 deletions: bad = {m}/{S}, eps_hat = {m/S:.5f}")
    print(f"target window ceiling eps = 3.3e-3 -> decades of gap = "
          f"{np.log10((m/S)/3.3e-3) if m else float('inf'):.2f}")


if __name__ == "__main__":
    main()
