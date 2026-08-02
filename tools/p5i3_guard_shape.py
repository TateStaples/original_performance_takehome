#!/usr/bin/env python3
"""P5-I3 mission-2 guard: for shapes the sec.9 transfer analyser accepts,
verify NUMERICALLY at scaled width w that, for every legal (s1,s2) and random
odd-K constants,
   (i)  N == 0  (mod 2^(w+1-s2))                      [the divisibility]
   (ii) N in {M, 2^w - M},  M = 2^(w-t)(q-1) + 2^(w+1-s2) n_1   [the FORM,
        which is what licenses the P5-I3 sec.12 realizability filter]
"""
import json, random, sys
import numpy as np
sys.path.insert(0, '/Users/tatestaples/Code/original_performance_takehome/tools')
import p5i3_transfer as T

def run(ops, a_idx, b_idx, w=14, trials=3, seed=9, verbose=False):
    rng = random.Random(seed)
    mask = np.uint64((1 << w) - 1)
    xs = np.arange(1 << w, dtype=np.uint64)
    shrs = [k for k, o in enumerate(ops) if o[0] == 'shr']
    e_slot = ops[b_idx][1]
    bad_div = bad_form = tested = 0
    for s1 in range(1, w - 1):
        for s2 in range(1, w - 1):
            t = s1 + s2 - (w - 1)
            if t < 1:
                continue
            u = w - 1 - s1
            shift = {a_idx: s1, b_idx: s2}
            for _ in range(trials):
                cst = {}
                for k, o in enumerate(ops):
                    if o[0] == 'madd':
                        cst[k] = (rng.getrandbits(w) | 1, rng.getrandbits(w))
                    elif o[0] == 'xorc':
                        cst[k] = (None, rng.getrandbits(w))
                def ev(xv):
                    sl = [xv]
                    for k, o in enumerate(ops):
                        if o[0] == 'madd':
                            K, C = cst[k]
                            sl.append((sl[o[1]] * np.uint64(K) + np.uint64(C)) & mask)
                        elif o[0] == 'xorc':
                            sl.append(sl[o[1]] ^ np.uint64(cst[k][1]))
                        elif o[0] == 'shr':
                            sl.append(sl[o[1]] >> np.uint64(shift[k]))
                        else:
                            sl.append(sl[o[1]] ^ sl[o[2]])
                    return sl
                s0 = ev(xs); s1v = ev(xs ^ np.uint64(1 << (w - 1)))
                N = int(((s0[-1] ^ s1v[-1]) & np.uint64(1)).sum())
                tested += 1
                if N % (1 << (w + 1 - s2)):
                    bad_div += 1
                    print("  DIV-VIOLATION (s1,s2)=(%d,%d) N=%d" % (s1, s2, N))
                k2op = next(k for k, o in enumerate(ops)
                            if o[0] == 'madd' and k + 1 == e_slot)
                K2, C2 = cst[k2op]
                q = K2 % (1 << t)
                n1 = sum(1 for cl in range(1 << u)
                         if (((K2 * cl + C2) & ((1 << w) - 1)) >> u) & 1)
                M = (1 << (w - t)) * (q - 1) + (1 << (w + 1 - s2)) * n1
                if N != M and N != (1 << w) - M:
                    bad_form += 1
                    print("  FORM-VIOLATION (s1,s2)=(%d,%d) N=%d M=%d q=%d n1=%d"
                          % (s1, s2, N, M, q, n1))
    return bad_div, bad_form, tested

if __name__ == '__main__':
    tr = json.load(open('/private/tmp/claude-501/-Users-tatestaples-Code-original-performance-takehome/3c5b1f32-7f70-46d9-9d31-685ca3585579/scratchpad/tr.json'))
    picks = [r for r in tr if r[0] in (328, 200, 634, 1097, 905)]
    for rank, (ai, bi, c), ops in picks:
        ops = [tuple(o) for o in ops]
        bd, bf, n = run(ops, ai, bi, w=14, trials=3, seed=rank)
        print("GUARD rank=%-5d w=14 tested=%d DIV-VIOL=%d FORM-VIOL=%d  ops=%s"
              % (rank, n, bd, bf, ops))
