#!/usr/bin/env python3
"""P6-D step 1: for the 73 'even-K parity branch not constant' shapes, find
WHICH parity assignment breaks the abstract analysis and what state it lands in.
Read-only diagnostic."""
import json
import sys
from collections import Counter

sys.path.insert(0, "tools")
import p5i3_transfer as T


def diag(e):
    ops = [tuple(o) for o in e["ops"]]
    shrs = [k for k, o in enumerate(ops) if o[0] == "shr"]
    madds = [k for k, o in enumerate(ops) if o[0] == "madd"]
    out = []
    for a_idx, b_idx in ((shrs[0], shrs[1]), (shrs[1], shrs[0])):
        ok, c = T.analyse(ops, a_idx, b_idx)
        if not ok or c is None:
            continue
        e_slot = ops[b_idx][1]
        if not T.bijective_cone(ops, c):
            continue
        if not T.is_cut(ops, e_slot):
            continue
        k2_madd = next((k for k in madds if k + 1 == e_slot), None)
        others = [k for k in madds if k != k2_madd]
        for m in range(1 << len(others)):
            ev = frozenset(o for i, o in enumerate(others) if (m >> i) & 1)
            ok2, _ = T.analyse(ops, a_idx, b_idx, ev)
            if ok2:
                continue
            st = T._final_state(ops, a_idx, b_idx, ev)
            d = T.d0(st)
            if d is None or d[1] != 0:
                # where is the even madd? relative to structure
                pos = []
                for k in sorted(ev):
                    slot = k + 1
                    if T.bijective_cone(ops, c) and _in_cone(ops, c, slot):
                        pos.append("in-c-cone")
                    elif slot == e_slot or _in_cone(ops, e_slot, slot):
                        pos.append("pre-shrB")
                    else:
                        pos.append("post-shrB/bypass")
                out.append((a_idx, b_idx, k2_madd, tuple(sorted(ev)),
                            tuple(pos), st))
    return out


def _in_cone(ops, slot, target):
    """is `target` slot inside the cone feeding `slot`?"""
    if slot == target:
        return True
    if slot == 0:
        return False
    return any(_in_cone(ops, a, target) for a in ops[slot - 1][1:])


def main():
    q = json.load(open("tools/p5k_queue.json"))
    rows = []
    for e in q["entries"]:
        ops = [tuple(o) for o in e["ops"]]
        if sum(1 for o in ops if o[0] == "shr") != 2:
            continue
        why = set()
        if T.shape_transfers(ops, why):
            continue
        if "even-K parity branch not constant" not in why:
            continue
        rows.append(e)
    print("even-bucket shapes:", len(rows))
    cnt = Counter()
    for e in rows:
        for (a, b, k2, ev, pos, st) in diag(e):
            key = (len(ev), pos, st if not isinstance(st, tuple) else st[0])
            cnt[key] += 1
    for k, n in cnt.most_common(20):
        print("  %-60s %d" % (str(k), n))
    # one worked example
    e = rows[0]
    print("\nexample rank", e["rank"], e["ops"])
    for r in diag(e)[:6]:
        print("   ", r)


if __name__ == "__main__":
    main()
