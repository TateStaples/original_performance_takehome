"""
H-006 measurement: gather-address distribution of the reference walk at the
graded shape (forest_height=10, batch=256, rounds=16), over many random
problem instances.

Per round (tree level = round mod 11) and per group (8 walkers = 1 vector):
  a) distinct tree nodes the group's 8 walkers hit (vselect-routable
     duplication: 8 - distinct loads could be deduped IF input-dependent
     routing existed);
  b) how often the 8 addresses form a contiguous run IN LANE ORDER
     (addr[lane] == addr[0] + lane -- the only pattern a single vload serves),
     and how often they are a contiguous SET (any permutation);
  c) cross-GROUP duplication: distinct nodes over all 256 walkers vs the
     level's structural maximum (2^level distinct nodes exist, period).

Everything here is INPUT-DEPENDENT except the structural maximum; the
kernel is built before data exists, so only structural facts are usable.
This script quantifies how much an input-dependent scheme would even have
to win, to bound the hypothesis honestly.

Usage (repo root): python tools/measure_gather_dist.py [n_seeds]
"""

from __future__ import annotations

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


def walk_stats(seed: int) -> list[tuple[list[int], list[bool], list[bool], int]]:
    random.seed(seed)
    forest = Tree.generate(FOREST_HEIGHT)
    inp = Input.generate(forest, BATCH_SIZE, ROUNDS)
    idx = list(inp.indices)
    val = list(inp.values)
    per_round = []
    for round in range(ROUNDS):
        # addresses THIS round's gather would need (node values at idx)
        groups = [idx[group * VLEN:(group + 1) * VLEN] for group in range(N_GROUPS)]
        distinct_per_group = [len(set(group_indices)) for group_indices in groups]
        contig_lane_per_group = [all(group_indices[lane] == group_indices[0] + lane for lane in range(VLEN))
                         for group_indices in groups]
        contig_set_per_group = [len(set(group_indices)) == VLEN
                        and max(group_indices) - min(group_indices) == VLEN - 1 for group_indices in groups]
        distinct_across_batch = len(set(idx))
        per_round.append((distinct_per_group, contig_lane_per_group, contig_set_per_group,
                          distinct_across_batch))
        for batch_index in range(BATCH_SIZE):
            new_val = myhash(val[batch_index] ^ forest.values[idx[batch_index]])
            next_idx = 2 * idx[batch_index] + (1 if new_val % 2 == 0 else 2)
            idx[batch_index] = 0 if next_idx >= N_NODES else next_idx
            val[batch_index] = new_val
    return per_round


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    acc: defaultdict[int, list[float]] = defaultdict(lambda: [0.0, 0, 0, 0.0, 0])  # round -> sums
    for seed_offset in range(n_seeds):
        for round, (distinct_per_group, contig_lane_per_group, contig_set_per_group, distinct_across_batch) in enumerate(walk_stats(1000 + seed_offset)):
            round_totals = acc[round]
            round_totals[0] += sum(distinct_per_group) / len(distinct_per_group)
            round_totals[1] += sum(contig_lane_per_group)
            round_totals[2] += sum(contig_set_per_group)
            round_totals[3] += distinct_across_batch
            round_totals[4] += 1
    print(f"graded shape fh={FOREST_HEIGHT} bs={BATCH_SIZE} r={ROUNDS}, "
          f"{n_seeds} seeds; {N_GROUPS} groups x {VLEN} walkers")
    print(f"{'round':>5} {'level':>5} {'2^lvl':>6} {'avg distinct/grp':>17} "
          f"{'dup/grp':>8} {'contig-lane':>12} {'contig-set':>11} "
          f"{'distinct/256':>13}")
    for round in sorted(acc):
        round_totals = acc[round]
        sample_count = round_totals[4]
        level = round % PERIOD
        print(f"{round:>5} {level:>5} {2**level:>6} {round_totals[0]/sample_count:>17.3f} "
              f"{VLEN - round_totals[0]/sample_count:>8.3f} {round_totals[1]/(sample_count*N_GROUPS):>11.2%} "
              f"{round_totals[2]/(sample_count*N_GROUPS):>10.2%} {round_totals[3]/sample_count:>13.1f}")


if __name__ == "__main__":
    main()
