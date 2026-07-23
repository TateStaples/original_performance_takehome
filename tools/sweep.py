"""
Background parameter sweep for the research loop's `sweep` strain (H-005).

Runs build_kernel_scheduled variants (via tools/run_variant.measure) over a
priority-ordered grid, appending one JSON file per config to
research/strains/sweep/results/. Restart-safe: configs already present in
the results dir (by config hash) are skipped, so the driver can relaunch
this after every iteration and it resumes where it left off.

Each result file: {"config": {...}, "cycles": N, "correct": bool,
"baseline": 1140}. The driver harvests winners (correct && cycles < best)
and puts them through the full grader accept gate.

Usage: python tools/sweep.py [--limit N] [--phase 1]
"""

import argparse
import hashlib
import itertools
import json
import os
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(TOOLS)
RESULTS = os.path.join(REPO_ROOT, "research", "strains", "sweep", "results")
sys.path.insert(0, TOOLS)

from run_variant import measure  # noqa: E402


def config_key(cfg):
    return hashlib.sha1(
        json.dumps({k: repr(v) for k, v in sorted(cfg.items())}).encode()
    ).hexdigest()[:16]


def phase1_grid():
    """Priority-ordered configs: cheap high-signal dimensions first.
    Yields override dicts (relative to run_variant.BASE_KWARGS)."""
    # 1. skew shapes around the (4,3) optimum, incl. asymmetric lag lists.
    for blocks, lag in itertools.product((2, 4, 8), (1, 2, 3, 4, 5)):
        yield {"skew": (blocks, lag)}
    for lags in ([0, 2, 5, 8], [0, 3, 5, 8], [0, 2, 4, 7], [0, 3, 7, 10],
                 [0, 1, 3, 6], [0, 4, 7, 9], [0, 2, 6, 9], [0, 3, 6, 8]):
        yield {"skew": lags}
    # 2. l4_gmin grid (which groups get the L4 tournament, per epoch).
    for a, b in itertools.product(range(14, 31, 2), range(18, 33, 2)):
        yield {"l4_gmin": (a, b)}
    # 3. pool sizes.
    for tp, cp in itertools.product(range(13, 22), (3, 4, 5, 6)):
        yield {"pool_sizes": (tp, cp)}
    # 4. cross products of the best-known regions (coarse).
    for skew, gmin in itertools.product(
        ((4, 2), (4, 3), (4, 4), (8, 2)),
        ((18, 24), (20, 26), (22, 28), (24, 30)),
    ):
        yield {"skew": skew, "l4_gmin": gmin}
    # 5. tournament-level subsets (sanity: is (1,2,3) still right?).
    for tl in ((1,), (1, 2), (1, 2, 3)):
        for off in (True, False):
            yield {"tournament_levels": tl, "alu_offload": off}


PHASES = {1: phase1_grid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="stop after N new runs")
    ap.add_argument("--phase", type=int, default=1)
    args = ap.parse_args()

    os.makedirs(RESULTS, exist_ok=True)
    done = {f[:-5] for f in os.listdir(RESULTS) if f.endswith(".json")}
    ran = best = 0
    t0 = time.time()
    for cfg in PHASES[args.phase]():
        key = config_key(cfg)
        if key in done:
            continue
        try:
            cycles, correct = measure(cfg, seed=123)
        except Exception as e:  # a bad config must not kill the sweep
            cycles, correct = -1, False
            err = repr(e)
        else:
            err = None
        rec = {"config": {k: repr(v) for k, v in cfg.items()},
               "cycles": cycles, "correct": correct, "baseline": 1140}
        if err:
            rec["error"] = err
        with open(os.path.join(RESULTS, key + ".json"), "w") as f:
            json.dump(rec, f)
        ran += 1
        if correct and 0 < cycles < 1140:
            best += 1
            print(f"WINNER {cycles} {cfg}", flush=True)
        if args.limit and ran >= args.limit:
            break
    print(f"sweep: {ran} new runs, {best} beat baseline, "
          f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
