#!/usr/bin/env python3
"""P6-D: can any of the 323 free-parity shapes be pushed BACK into the
forced-odd class (which keeps p5i sec.12's 113-alive verdict instead of the
extension's 290)?

(a) CHAIN-T6b (proved).  If shr-B's input slot E is a DAG cut and E is reached
    from the K2 madd's OUTPUT by single-input ops only (xorc / madd), then
    F: x -> E is bijective and F = g o madd_K2 o h with h = (x->c) bijective
    (T6a) and g the chain.  If any chain madd were even, g would not be
    injective and F could not be bijective; so g is bijective, hence
    madd_K2 = g^-1 o F o h^-1 is bijective, hence K2 is ODD.
    (p5i3_transfer's T6b was the special case chain = identity.)

(b) XOR-JOIN case (the 73 bucket): E = xor2(bypass, e).  Cut still gives F
    bijective, but that no longer forces K2 odd on its face.  This script
    SEARCHES for an even-K2 witness (a constant set making x -> E bijective at
    small width).  A witness = the bucket is genuinely free-parity; no witness
    = a lead, not a theorem.
"""
import json
import random
import sys

sys.path.insert(0, "tools")
import p5i3_transfer as T
import p6d_extend as X


def chain_forced_odd(ops, b_idx, k2_idx):
    e_slot = ops[b_idx][1]
    if not T.is_cut(ops, e_slot):
        return False
    s = e_slot
    while s != k2_idx + 1:
        if s == 0:
            return False
        op = ops[s - 1]
        if op[0] not in ("xorc", "madd"):
            return False
        s = op[1]
    return True


def eval_slot(ops, consts, shifts, w, x, slot):
    mask = (1 << w) - 1
    slots = [x]
    ci = si = 0
    for op in ops:
        if op[0] == "madd":
            K, C = consts[ci]; ci += 1
            slots.append((slots[op[1]] * K + C) & mask)
        elif op[0] == "xorc":
            C = consts[ci][1]; ci += 1
            slots.append(slots[op[1]] ^ C)
        elif op[0] == "shr":
            slots.append(slots[op[1]] >> shifts[si]); si += 1
        else:
            slots.append(slots[op[1]] ^ slots[op[2]])
    return slots[slot]


def even_k2_bijection_witness(ops, b_idx, k2_idx, w=10, tries=4000, seed=0):
    """search for constants with EVEN K2 making x -> shrB's input bijective."""
    rng = random.Random(seed)
    e_slot = ops[b_idx][1]
    nc = sum(1 for o in ops if o[0] in ("madd", "xorc"))
    ck2 = sum(1 for k, o in enumerate(ops)
              if k < k2_idx and o[0] in ("madd", "xorc"))
    N = 1 << w
    for _ in range(tries):
        consts = [[rng.getrandbits(w) | 1, rng.getrandbits(w)]
                  for _ in range(nc)]
        v = rng.randint(1, w - 2)
        consts[ck2][0] = (((rng.getrandbits(max(1, w - v)) | 1) << v) % N) or (1 << v)
        s1 = rng.randint(1, w - 2)
        s2 = rng.randint(1, w - 2)
        if s1 + s2 < w - 1:
            continue
        img = {eval_slot(ops, consts, [0, 0][:0] + _sh(ops, b_idx, s1, s2),
                         w, x, e_slot) for x in range(N)}
        if len(img) == N:
            return (consts, s1, s2, v)
    return None


def _sh(ops, b_idx, s1, s2):
    shrs = [k for k, o in enumerate(ops) if o[0] == "shr"]
    out = [0, 0]
    out[shrs.index(b_idx)] = s2
    out[1 - shrs.index(b_idx)] = s1
    return out


def main():
    q = json.load(open("tools/p5k_queue.json"))
    ent = [e for e in q["entries"]
           if e["status"] in ("QUEUED", "SCREEN-TIMEOUT")]
    n_chain = n_xorjoin = n_nocut = 0
    xorjoin = []
    for e in ent:
        ops = [tuple(o) for o in e["ops"]]
        r = X.extended_transfer(ops)
        if not r:
            continue
        a_idx, b_idx, c, k2, modes = r
        e_slot = ops[b_idx][1]
        if chain_forced_odd(ops, b_idx, k2):
            n_chain += 1
        elif T.is_cut(ops, e_slot):
            n_xorjoin += 1
            xorjoin.append(e)
        else:
            n_nocut += 1
    print("extended-transfer shapes: chain-forced-odd=%d  xor-join-cut=%d  "
          "no-cut=%d" % (n_chain, n_xorjoin, n_nocut))
    rng = random.Random(3)
    for e in rng.sample(xorjoin, min(4, len(xorjoin))):
        ops = [tuple(o) for o in e["ops"]]
        a_idx, b_idx, c, k2, modes = X.extended_transfer(ops)
        wit = even_k2_bijection_witness(ops, b_idx, k2, w=10, tries=3000,
                                        seed=e["rank"])
        print("rank=%-5d even-K2 bijective witness: %s   ops=%s"
              % (e["rank"], "FOUND v=%d s=(%d,%d)" % (wit[3], wit[1], wit[2])
                 if wit else "none in 3000 tries", e["ops"]))


if __name__ == "__main__":
    main()
