#!/usr/bin/env python3
"""P5-C: frame-2 measurements on real walks (unseeded myhash dynamics).

1. Natural contiguity (NO sorting): per gathered level, P(a group's 8 lanes
   fit an 8-word / 16-word unaligned window), expected exploitable group-rounds.
2. Sorted-children lemma spot-check: from a sorted-by-node walker order, one
   round of branching yields exactly <=2 sorted runs after a stable partition
   by the new parity bit (i.e. maintenance = 2-run merge, not a sort).
3. Post-sort window stats: after sorting walkers by level-a ancestor, the
   distinct-ancestor count per 8-lane group ("straddle") at deeper levels.
"""
import random, sys
sys.path.insert(0, "/Users/tatestaples/Code/original_performance_takehome")
from problem import myhash

TRIALS = 400
B, H = 256, 10

def walk_positions(trials=TRIALS):
    """positions[trial][round][walker] = level-local position (0..2^level-1)"""
    out = []
    for _ in range(trials):
        vals = [random.randint(0, 2**30 - 1) for _ in range(B)]
        tree = {}
        pos = [0] * B          # level-local position; level = r mod 11
        rows = []
        for r in range(16):
            lvl = r % 11
            rows.append((lvl, pos[:]))
            newpos = []
            for i in range(B):
                idx = (1 << lvl) - 1 + pos[i]
                nv = tree.setdefault(idx, random.randint(0, 2**30 - 1))
                vals[i] = myhash(vals[i] ^ nv)
                b = 0 if vals[i] % 2 == 0 else 1
                newpos.append((pos[i] << 1) | b if lvl < 10 else 0)
            pos = newpos
        out.append(rows)
    return out

data = walk_positions()

print("=== 1. natural contiguity per gathered level (static lane binding) ===")
print("level  P(win<=8)  P(win<=16)  E[gr/32 win8]  E[gr win16]")
GATHERED = [4, 5, 6, 7, 8, 9, 10]   # L4 partially gathered; L5-10 gathered
for lvl in GATHERED:
    n8 = n16 = tot = 0
    for rows in data:
        for l, pos in rows:
            if l != lvl:
                continue
            for g in range(32):
                lanes = pos[g * 8:(g + 1) * 8]
                span = max(lanes) - min(lanes) + 1
                tot += 1
                if span <= 8: n8 += 1
                if span <= 16: n16 += 1
    print(f"L{lvl:<4} {n8/tot:9.4f}  {n16/tot:9.4f}  {32*n8/tot:9.2f}  {32*n16/tot:9.2f}")

print()
print("=== 2. sorted-children lemma: runs after stable partition by new bit ===")
bad = 0
checks = 0
for rows in data[:100]:
    for (l1, p1), (l2, p2) in zip(rows, rows[1:]):
        if l2 != l1 + 1:
            continue
        order = sorted(range(B), key=lambda i: p1[i])          # sorted by parent
        child = [p2[i] for i in order]
        bits = [c & 1 for c in child]
        part = [c for c, b in zip(child, bits) if b == 0] + \
               [c for c, b in zip(child, bits) if b == 1]
        runs = 1 + sum(1 for a, b2 in zip(part, part[1:]) if b2 < a)
        checks += 1
        if runs > 2:
            bad += 1
print(f"transitions checked: {checks}, cases with >2 runs: {bad}")

print()
print("=== 3. post-sort straddle: sort by level-a ancestor, groups at level d ===")
print("a  d  E[#distinct ancestors per group]  P(group pure)")
for a in (2, 3, 4):
    for d in range(a + 1, min(a + 4, 11)):
        tot = pure = 0
        acc = 0.0
        for rows in data[:100]:
            posd = next(p for l, p in rows if l == d)
            anc = sorted(p >> (d - a) for p in posd)            # sorted by ancestor
            for g in range(32):
                lanes = anc[g * 8:(g + 1) * 8]
                k = len(set(lanes))
                tot += 1
                acc += k
                pure += (k == 1)
        print(f"{a}  {d}   {acc/tot:6.3f}                         {pure/tot:6.3f}")
