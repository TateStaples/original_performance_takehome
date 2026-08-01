"""P4-B: measured width of the lane-uniform candidate set at level d.

Question (Phase-4 charter, target (a)): the routing law says serving level d
costs 2^d - 1 two-way selects because the select tree must range over all 2^d
nodes.  A group has only 8 lanes, so at most 8 distinct nodes are actually
needed; and if the group's 8 lanes shared an ancestor k levels up, the
*lane-uniform* candidate set would collapse to the 2^k descendants of that
ancestor (which are CONTIGUOUS in memory: the depth-k descendants of node v
are exactly [2^k*v + 2^k - 1, 2^k*v + 2^(k+1) - 2]).

This tool measures, over the real (unseeded-random) problem instance:
  * #distinct nodes occupied by a group's 8 lanes at level d   (the "8" bound)
  * #distinct ancestors k levels up, k = 1,2,3                 (the sharing)
  * the reachable-set width  = sum over distinct ancestors of 2^k, capped 2^d
    (the width a select tree would need if narrowing used the ancestor set)

Read-only.  Usage:  python3 tools/p4b_width.py [--trials 8]
"""
from __future__ import annotations

import argparse
import random
import sys
from collections import Counter

sys.path.insert(0, ".")
from problem import myhash                            # noqa: E402

HEIGHT, ROUNDS, BATCH, VLEN = 10, 16, 256, 8
PERIOD = HEIGHT + 1
N_NODES = 2 ** PERIOD - 1
N_GROUPS = BATCH // VLEN


def anc(v: int, k: int) -> int:
    for _ in range(k):
        v = (v - 1) // 2
    return v


def run_trial(rng: random.Random):
    """returns idx_hist[round] = list of 256 node indices at that round."""
    node = [rng.randint(0, 2 ** 30 - 1) for _ in range(N_NODES)]
    val = [rng.randint(0, 2 ** 30 - 1) for _ in range(BATCH)]
    idx = [0] * BATCH
    hist = []
    for r in range(ROUNDS):
        hist.append(list(idx))                        # position at round r
        for b in range(BATCH):
            v = myhash(val[b] ^ node[idx[b]])
            val[b] = v
            j = 2 * idx[b] + (1 if v % 2 == 0 else 2)
            idx[b] = 0 if j >= N_NODES else j
    return hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=8)
    a = ap.parse_args()

    # stats[(d, k)] -> Counter of reachable width ; also distinct-at-d
    dist_at_d: dict[int, Counter] = {}
    width: dict[tuple[int, int], Counter] = {}
    uniform: dict[tuple[int, int], int] = {}
    n_gr: dict[int, int] = {}

    for t in range(a.trials):
        hist = run_trial(random.Random(1000 + t))
        for r in range(ROUNDS):
            d = r % PERIOD
            if d == 0:
                continue
            for g in range(N_GROUPS):
                lanes = hist[r][g * VLEN:(g + 1) * VLEN]
                dist_at_d.setdefault(d, Counter())[len(set(lanes))] += 1
                n_gr[d] = n_gr.get(d, 0) + 1
                for k in range(1, 4):
                    if k > d:
                        continue
                    ancs = {anc(v, k) for v in lanes}
                    w = min(len(ancs) * (1 << k), 1 << d)
                    width.setdefault((d, k), Counter())[w] += 1
                    if len(ancs) == 1:
                        uniform[(d, k)] = uniform.get((d, k), 0) + 1

    print(f"trials={a.trials}  group-rounds sampled per level = "
          f"{n_gr.get(5)} (L5-L10), {n_gr.get(1)} (L1-L4)\n")
    print("distinct nodes occupied by a group's 8 lanes at level d:")
    print(f"{'d':>3}{'2^d':>6}   histogram(#distinct -> count)")
    for d in sorted(dist_at_d):
        h = dict(sorted(dist_at_d[d].items()))
        print(f"{d:>3}{1 << d:>6}   {h}")

    print("\nreachable-set width via the ancestor-set narrowing")
    print("(width = #distinct ancestors at level d-k, times 2^k, capped 2^d)")
    print(f"{'d':>3}{'k':>3}{'2^d':>6}{'min':>6}{'mean':>8}{'max':>6}"
          f"{'  lane-uniform (all 8 share)':>28}")
    for (d, k) in sorted(width):
        c = width[(d, k)]
        tot = sum(c.values())
        mean = sum(w * n for w, n in c.items()) / tot
        print(f"{d:>3}{k:>3}{1 << d:>6}{min(c):>6}{mean:>8.2f}{max(c):>6}"
              f"{uniform.get((d, k), 0):>12} / {tot}")

    print("\nNOTE: walkers are i.i.d. so ANY static lane->walker assignment"
          " gives the same distribution; and the data is unseeded random"
          " (tests/submission_tests.py:32), so the instruction stream cannot"
          " depend on it.")


if __name__ == "__main__":
    main()
