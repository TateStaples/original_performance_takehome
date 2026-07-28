"""F-18: EXHAUSTIVE single-entry displacement scan of an emission plan.

The F-13/F-18 walks sample the move space, so a zero result is only
probabilistic.  This driver enumerates EVERY valid single-entry
reinsertion -- each of the 512 entries moved to every position inside
its maximal feasible interval (bounded only by its own group's
round-neighbours, i.e. UNBOUNDED radius) -- and measures all of them.
A zero over the full enumeration proves the plan is a strict 1-move
local optimum at any radius, which is the exact claim the sampled walks
cannot make.

Chunked via --start/--stop so a scan fits inside one wall-clock window.

Usage (repo root):
  python3 tools/f18_exhaust1.py --seed-json tools/f13_best_plan_1020.json \\
      --out SCRATCH/ex.jsonl --start 0 --stop 16000
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
from f18_radius_walk import ROUNDS, load_seed, positions, valid  # noqa: E402


def enumerate_moves(plan: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """All (i, j) single-entry reinsertions that keep the plan valid."""
    n = len(plan)
    pos = positions(plan)
    out: list[tuple[int, int]] = []
    for i, (r, g) in enumerate(plan):
        gp = pos[g]
        lo = gp[r - 1] + 1 if r > 0 else 0
        hi = gp[r + 1] - 1 if r + 1 < ROUNDS else n - 1
        for t in range(lo, hi + 1):
            if t == i:
                continue
            j = t - 1 if t > i else t
            if j != i:
                out.append((i, j))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10 ** 9)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4)))
    ap.add_argument("--count-only", action="store_true")
    args = ap.parse_args()

    cfg, plan = load_seed(args.seed_json)
    moves = enumerate_moves(plan)
    print(f"total single-entry moves: {len(moves)}", flush=True)
    if args.count_only:
        return
    base_c, base_ok = eos._eval((cfg, tuple(plan)))
    print(f"base {base_c} correct={base_ok}", flush=True)

    chunk = moves[args.start:args.stop]
    pool = mp.Pool(args.workers)
    out = open(args.out, "a", buffering=1)
    best = (base_c, None)
    t0 = time.time()
    B = args.workers * 32
    for k in range(0, len(chunk), B):
        cand = []
        for (i, j) in chunk[k:k + B]:
            q = list(plan)
            q.insert(j, q.pop(i))
            assert valid(q)
            cand.append(((i, j), tuple(q)))
        res = pool.map(eos._eval, [(cfg, q) for _, q in cand])
        for ((i, j), q), (c, ok) in zip(cand, res):
            out.write(json.dumps({"i": i, "j": j, "cycles": c, "correct": ok}) + "\n")
            if ok and c < best[0]:
                best = (c, (i, j))
                print(f"  BETTER {c} at move {i}->{j}", flush=True)
                with open(args.out + ".best.json", "w") as f:
                    json.dump({"hypothesis": "F-18-exhaust1", "cycles": c,
                               "config_overrides": cfg, "note": f"move {i}->{j}",
                               "plan": [list(e) for e in q]}, f)
        print(f"  scanned {args.start + k + len(cand)}/{len(moves)} "
              f"best {best[0]} t={time.time()-t0:.0f}s", flush=True)
    print(f"DONE best={best} scanned={len(chunk)} t={time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
