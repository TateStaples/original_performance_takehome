#!/usr/bin/env python3
"""P5-I3 mission 2: does STATE.md sec.9's top-bit differential-count theorem
transfer from sandwich9 to another p5k shape?

TRANSFER CONDITIONS (derived; each is checked syntactically below).
Let the perturbation be x -> x ^ 2^(w-1) and let the observed output bit be
bit 0.  Write A for the "first" shr (shift s1) and B for the "second" (s2).

 T1  the shape has EXACTLY 2 shr ops (a 3rd shr breaks every step below);
 T2  x reaches A's input through madd(odd K)/xorc/xor2-with-exact-branches
     only, and the perturbation there is EXACTLY the single bit 2^(w-1);
 T3  the value c feeding the middle madd carries the EXACT 2-bit xor flip
     {w-1, u}, u = w-1-s1 >= 1  (i.e. A's output is xored back onto an
     unshifted copy);
 T4  between c and B's input there is EXACTLY ONE madd (any number of xorc
     and any number of xor2 with branches whose flip is exact), so that
     e* - e = 2^(w-1) + sg*K2*2^u  EXACTLY (additive, 2 terms);
 T5  bit 0 of the output equals bit 0 of (B's output) xored with terms whose
     bit-0 differential is CONSTANT -- i.e. downstream of B only
     madd(odd K)/xorc/xor2-with-constant-differential ops occur (no 3rd shr);
 T6  c's slot is a DAG CUT, so x -> c is a bijection (P5-K filter K2's
     lemma: out = G(F(x)) with out bijective forces F bijective).  This is
     what makes the counting over c_hi/c_u/c_lo uniform.

Under T1-T6 the differential is bit-for-bit the sandwich9 one, so
    N == 0  (mod 2^(w+1-s2))   and   N = M or 2^w - M with
    M = 2^(w-t)*(q-1) + 2^(w+1-s2)*n_1,  t = s1+s2-(w-1), q = K2 mod 2^t.
Everything P5-I2 sec.9 and P5-I3 sec.12 conclude for sandwich9 then applies
verbatim to the shape, per (s1,s2).
"""
import argparse
import json
import random
from collections import defaultdict

# ---------------------------------------------------------------- states ---
# ('E', frozenset(symbols))  exact xor flip at the named bit positions
#                            symbols: 'H' = bit w-1, 'U' = bit u = w-1-s1
# ('S', F)                   e* - e = 2^(w-1) + sg*K*2^u exactly, then xored
#                            with the exact flips in F (F never contains bit0)
# ('D', c)                   delta_0 = c ^ D  (D = the sandwich differential)
# ('C', c)                   delta_0 = c (constant), other bits unknown
# 'TOP'                      unknown


def d0(state):
    """(const, coeff_of_D) of the bit-0 differential, or None if unknown."""
    k = state[0] if isinstance(state, tuple) else state
    if k == 'E':
        return (0, 0)          # 'H' is bit w-1, 'U' is bit u>=1: never bit 0
    if k == 'S':
        return (0, 0)
    if k == 'C':
        return (state[1], 0)
    if k == 'D':
        return (state[1], 1)
    return None


def analyse(ops, a_idx, b_idx, even=frozenset()):
    """abstract-interpret with shr op a_idx as A and b_idx as B.
    `even` = madd op indices whose K is EVEN.  returns (ok, K2-madd in-slot)."""
    st, c_slot, dup = _run(ops, a_idx, b_idx, even)
    if dup:
        return False, None
    ok = isinstance(st, tuple) and st[0] == 'D'
    return ok, c_slot


def is_cut(ops, slot):
    """slot is a DAG cut: deleting it disconnects slot 0 from the output."""
    n = len(ops)
    reach = {0}
    if slot == 0:
        return True
    for k, op in enumerate(ops):
        args = op[1:]
        if any(a in reach for a in args) and (k + 1) != slot:
            if slot in args:
                # the op reads the cut slot: it does not carry x past it
                args2 = [a for a in args if a != slot]
                if any(a in reach for a in args2):
                    reach.add(k + 1)
            else:
                reach.add(k + 1)
    return n not in reach



def bijective_cone(ops, slot, memo=None):
    """True if x -> slot is a bijection for EVERY constant choice (odd madd K).
    Allowed: x, madd, xorc, and the xorshift motif xor2(v, shr(v))."""
    if memo is None:
        memo = {}
    if slot in memo:
        return memo[slot]
    if slot == 0:
        return True
    op = ops[slot - 1]
    if op[0] in ('madd', 'xorc'):
        r = bijective_cone(ops, op[1], memo)
    elif op[0] == 'xor2':
        a, b = op[1], op[2]
        r = False
        for v, sh in ((a, b), (b, a)):
            if sh > 0 and ops[sh - 1][0] == 'shr' and ops[sh - 1][1] == v:
                r = bijective_cone(ops, v, memo)
                break
    else:
        r = False                       # a bare shr is never a bijection
    memo[slot] = r
    return r

def shape_transfers(ops, why=None):
    """returns (a_idx, b_idx, c_slot) if sec.9 transfers to this shape."""
    shrs = [k for k, o in enumerate(ops) if o[0] == 'shr']
    if len(shrs) != 2:
        return None
    madds = [k for k, o in enumerate(ops) if o[0] == 'madd']
    for a_idx, b_idx in ((shrs[0], shrs[1]), (shrs[1], shrs[0])):
        ok, c = analyse(ops, a_idx, b_idx)
        if not ok or c is None:
            if why is not None:
                why.add('no-sandwich-pattern')
            continue
        e_slot = ops[b_idx][1]            # value entering the second shr
        # T6a: x -> c must be a BIJECTION (the sec.9 count is a count over c;
        # without it the differential count is re-weighted -- verified to FAIL
        # numerically, see p5i3_guard_shape.py rank 2953).
        if not bijective_cone(ops, c):
            if why is not None:
                why.add('x->c not syntactically bijective')
            continue
        # T6b: e a DAG cut => out = G(F(x)) with F bijective => K2 odd.
        if not is_cut(ops, e_slot):
            if why is not None:
                why.add('shrB-input-not-a-cut')
            continue
        k2_madd = next(k for k in madds if k + 1 == e_slot) \
            if any(k + 1 == e_slot for k in madds) else None
        others = [k for k in madds if k != k2_madd]
        bad = False
        for m in range(1 << len(others)):
            ev = frozenset(o for i, o in enumerate(others) if (m >> i) & 1)
            ok2, _ = analyse(ops, a_idx, b_idx, ev)
            if ok2:
                continue
            # acceptable fallback: the differential is a CONSTANT (N in
            # {0, 2^w}), which is still == 0 mod 2^(w+1-s2) and != N_myhash
            st = _final_state(ops, a_idx, b_idx, ev)
            if d0(st) is None or d0(st)[1] != 0:
                bad = True
                break
        if bad:
            if why is not None:
                why.add('even-K parity branch not constant')
            continue
        return (a_idx, b_idx, c)
    return None


def _final_state(ops, a_idx, b_idx, ev):
    return _run(ops, a_idx, b_idx, ev)[0]


def _run(ops, a_idx, b_idx, even):
    """returns (final state, K2-madd input slot, duplicate-K2-madd flag).
    ZERO = ('E', empty): a value with NO differential at all; every op maps
    zero-difference inputs to a zero-difference output, for any constants."""
    ZERO = ('E', frozenset())
    st = {0: ('E', frozenset(['H']))}
    c_slot = None
    dup = False
    for k, op in enumerate(ops):
        out = k + 1
        kind = op[0]
        if kind in ('madd', 'xorc', 'shr'):
            s = st[op[1]]
            if s == ZERO:
                st[out] = ZERO
                continue
        if kind == 'madd':
            if k in even:
                # K even: K*2^(w-1) = 0 kills an exact top-bit flip; and bit 0
                # of K*v+C is the constant C_0, so delta_0 = 0 regardless.
                st[out] = ZERO if (s[0] == 'E' and s[1] == frozenset(['H'])) \
                    else ('C', 0)
            elif s[0] == 'E' and s[1] == frozenset(['H']):
                st[out] = ('E', frozenset(['H']))
            elif s[0] == 'E' and s[1] in (frozenset(['H', 'U']),
                                          frozenset(['U'])):
                # e* - e = [2^(w-1) +] sg*K2*2^u exactly.  The 2^(w-1) term is
                # invisible at every bit < w-1, so BOTH flip sets give the
                # identical differential at bit 0 and bit s2.
                if c_slot is not None:
                    dup = True
                c_slot = op[1]
                st[out] = ('S', frozenset())
            elif s[0] == 'E':
                st[out] = ('C', 0)
            elif s[0] in ('C', 'D'):
                st[out] = (s[0], s[1])
            else:
                st[out] = 'TOP'
        elif kind == 'xorc':
            st[out] = s
        elif kind == 'shr':
            if k == a_idx:
                if s[0] == 'E' and s[1] == frozenset(['H']):
                    st[out] = ('E', frozenset(['U']))
                elif s[0] in ('E', 'S'):
                    st[out] = ('C', 0)      # bit0 of result = bit s1 of input
                else:
                    st[out] = 'TOP'
            elif k == b_idx:
                if s[0] == 'S':
                    st[out] = ('D', 0)      # bit0 of result = delta_{s2}
                elif s[0] == 'E':
                    st[out] = ('C', 0)      # H != s2 (s2<=w-2); U==s2 is t=0
                else:
                    st[out] = 'TOP'
            else:
                st[out] = 'TOP'
        elif kind == 'xor2':
            sa, sb = st[op[1]], st[op[2]]
            if sa == ZERO:
                st[out] = sb
            elif sb == ZERO:
                st[out] = sa
            elif sa[0] == 'E' and sb[0] == 'E':
                st[out] = ('E', sa[1] ^ sb[1])
            elif sa[0] == 'S' and sb[0] == 'E':
                st[out] = ('S', sa[1] ^ sb[1])
            elif sb[0] == 'S' and sa[0] == 'E':
                st[out] = ('S', sb[1] ^ sa[1])
            else:
                da, db = d0(sa), d0(sb)
                if da is None or db is None:
                    st[out] = 'TOP'
                else:
                    st[out] = (('D', da[0] ^ db[0]) if (da[1] ^ db[1])
                               else ('C', da[0] ^ db[0]))
        else:
            st[out] = 'TOP'
    return st[len(ops)], c_slot, dup


# ------------------------------------------------------- numeric guard -----
def eval_shape(ops, consts, shifts, w, xs):
    """numpy evaluation of a shape.  consts: per-op (K,C) / C / unused."""
    import numpy as np
    mask = np.uint64((1 << w) - 1)
    slots = [xs]
    ci = 0
    si = 0
    for op in ops:
        if op[0] == 'madd':
            K, C = consts[ci]; ci += 1
            slots.append((slots[op[1]] * np.uint64(K) + np.uint64(C)) & mask)
        elif op[0] == 'xorc':
            C = consts[ci][1]; ci += 1
            slots.append(slots[op[1]] ^ np.uint64(C))
        elif op[0] == 'shr':
            s = shifts[si]; si += 1
            slots.append(slots[op[1]] >> np.uint64(s))
        elif op[0] == 'xor2':
            slots.append(slots[op[1]] ^ slots[op[2]])
    return slots[-1]


def guard_shape(ops, w=14, trials=3, seed=5, a_idx=None, b_idx=None):
    """N == 0 mod 2^(w+1-s2) for every legal (s1,s2) and random constants."""
    import numpy as np
    rng = random.Random(seed)
    xs = np.arange(1 << w, dtype=np.uint64)
    shrs = [k for k, o in enumerate(ops) if o[0] == 'shr']
    nmadd = sum(1 for o in ops if o[0] in ('madd', 'xorc'))
    bad = tested = 0
    order = shrs.index(a_idx), shrs.index(b_idx)
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            if s1 + s2 - (w - 1) < 1:
                continue
            shifts = [0, 0]
            shifts[order[0]] = s1
            shifts[order[1]] = s2
            for _ in range(trials):
                consts = [(rng.getrandbits(w) | 1, rng.getrandbits(w))
                          for _ in range(nmadd)]
                o0 = eval_shape(ops, consts, shifts, w, xs) & np.uint64(1)
                o1 = eval_shape(ops, consts, shifts, w,
                                xs ^ np.uint64(1 << (w - 1))) & np.uint64(1)
                N = int((o0 ^ o1).sum())
                tested += 1
                if N % (1 << (w + 1 - s2)):
                    bad += 1
                    print("  VIOLATION (s1,s2)=(%d,%d) N=%d mod=%d"
                          % (s1, s2, N, 1 << (w + 1 - s2)))
    return bad, tested


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--queue", default="tools/p5k_queue.json")
    ap.add_argument("--guard", type=int, default=0,
                    help="numerically guard this many transferred shapes at w=14")
    ap.add_argument("--w", type=int, default=14)
    a = ap.parse_args()
    q = json.load(open(a.queue))
    ent = q["entries"]
    stats = defaultdict(int)
    transferred = []
    for e in ent:
        ops = [tuple(o) for o in e["ops"]]
        nshr = sum(1 for o in ops if o[0] == 'shr')
        stats['nshr=%d' % nshr] += 1
        r = shape_transfers(ops)
        stats['transfer' if r else 'no-transfer'] += 1
        if r:
            transferred.append((e, r))
    print("queue entries:", len(ent))
    for k in sorted(stats):
        print("  %-14s %d" % (k, stats[k]))
    by_status = defaultdict(int)
    for e, r in transferred:
        by_status[e['status']] += 1
    print("transferred by status:", dict(by_status))
    if a.guard:
        rng = random.Random(0)
        pick = transferred[:1] + rng.sample(transferred, min(a.guard - 1,
                                                             len(transferred)))
        for e, (ai, bi, c) in pick[:a.guard]:
            bad, tested = guard_shape(e['ops'], w=a.w, a_idx=ai, b_idx=bi)
            print("GUARD rank=%d w=%d tested=%d VIOLATIONS=%d ops=%s"
                  % (e['rank'], a.w, tested, bad, e['ops']))


if __name__ == "__main__":
    main()
