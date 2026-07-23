"""
H-006 measurement: gather-address distribution of the reference walk at the
graded shape (forest_height=10, batch=256, rounds=16), over many random
problem instances.

Per round r (tree level = r mod 11) and per group (8 walkers = 1 vector):
  a) distinct tree nodes the group's 8 walkers hit (vselect-routable
     duplication: 8 - distinct loads could be deduped IF input-dependent
     routing existed);
  b) how often the 8 addresses form a contiguous run IN LANE ORDER
     (addr[i] == addr[0] + i -- the only pattern a single vload serves),
     and how often they are a contiguous SET (any permutation);
  c) cross-GROUP duplication: distinct nodes over all 256 walkers vs the
     level's structural maximum (2^level distinct nodes exist, period).

Everything here is INPUT-DEPENDENT except the structural maximum; the
kernel is built before data exists, so only structural facts are usable.
This script quantifies how much an input-dependent scheme would even have
to win, to bound the hypothesis honestly.

Usage (repo root): python tools/measure_gather_dist.py [n_seeds]
"""

import os
import random
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from problem import Tree, Input, myhash, VLEN

FOREST_HEIGHT, BATCH_SIZE, ROUNDS = 10, 256, 16
N_NODES = 2 ** (FOREST_HEIGHT + 1) - 1
PERIOD = FOREST_HEIGHT + 1
N_GROUPS = BATCH_SIZE // VLEN


def walk_stats(seed):
    random.seed(seed)
    t = Tree.generate(FOREST_HEIGHT)
    inp = Input.generate(t, BATCH_SIZE, ROUNDS)
    idx = list(inp.indices)
    val = list(inp.values)
    per_round = []
    for r in range(ROUNDS):
        # addresses THIS round's gather would need (node values at idx)
        groups = [idx[g * VLEN:(g + 1) * VLEN] for g in range(N_GROUPS)]
        g_distinct = [len(set(gr)) for gr in groups]
        g_contig_lane = [all(gr[i] == gr[0] + i for i in range(VLEN))
                         for gr in groups]
        g_contig_set = [len(set(gr)) == VLEN
                        and max(gr) - min(gr) == VLEN - 1 for gr in groups]
        all_distinct = len(set(idx))
        per_round.append((g_distinct, g_contig_lane, g_contig_set,
                          all_distinct))
        for i in range(BATCH_SIZE):
            v = myhash(val[i] ^ t.values[idx[i]])
            nx = 2 * idx[i] + (1 if v % 2 == 0 else 2)
            idx[i] = 0 if nx >= N_NODES else nx
            val[i] = v
    return per_round


def main():
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    acc = defaultdict(lambda: [0.0, 0, 0, 0.0, 0])  # r -> sums
    for s in range(n_seeds):
        for r, (gd, gcl, gcs, ad) in enumerate(walk_stats(1000 + s)):
            a = acc[r]
            a[0] += sum(gd) / len(gd)
            a[1] += sum(gcl)
            a[2] += sum(gcs)
            a[3] += ad
            a[4] += 1
    print(f"graded shape fh={FOREST_HEIGHT} bs={BATCH_SIZE} r={ROUNDS}, "
          f"{n_seeds} seeds; {N_GROUPS} groups x {VLEN} walkers")
    print(f"{'round':>5} {'level':>5} {'2^lvl':>6} {'avg distinct/grp':>17} "
          f"{'dup/grp':>8} {'contig-lane':>12} {'contig-set':>11} "
          f"{'distinct/256':>13}")
    for r in sorted(acc):
        a = acc[r]
        n = a[4]
        lvl = r % PERIOD
        print(f"{r:>5} {lvl:>5} {2**lvl:>6} {a[0]/n:>17.3f} "
              f"{VLEN - a[0]/n:>8.3f} {a[1]/(n*N_GROUPS):>11.2%} "
              f"{a[2]/(n*N_GROUPS):>10.2%} {a[3]/n:>13.1f}")


if __name__ == "__main__":
    main()
