"""F-37 phase A: measure every single displacement whose SOURCE round is in
a given band (default 12-15) at a seed plan, and dump the map as JSONL.

This is f18_exhaust1 re-run through the composable (src, anchor) move
coordinates so the pair search can index straight into it.  Output records:
{"s": src, "a": anchor, "cycles": c, "correct": bool}

Usage (repo root):
  python3 tools/f37_single.py --seed-json tools/h057_best_plan_1006.json \
      --rounds 12,13,14,15 --out SCRATCH/f37/single_r1215.jsonl
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
import f37_lib as F  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rounds", default="12,13,14,15")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    order, mix = F.load_point(args.seed_json)
    plan = list(order)
    rounds = None if args.rounds == "all" else [int(x) for x in args.rounds.split(",")]
    moves = F.enumerate_moves(plan, rounds)
    base_c, base_ok = eos._eval((mix, order))
    print(f"base {base_c} correct={base_ok}; moves {len(moves)}", flush=True)

    pool = mp.Pool(args.workers)
    out = open(args.out, "w", buffering=1)
    t0 = time.time()
    B = args.workers * 32
    best = base_c
    for k in range(0, len(moves), B):
        chunk = moves[k:k + B]
        cand = [(m, F.apply_moves(plan, [m])) for m in chunk]
        res = pool.map(eos._eval, [(mix, q) for _, q in cand])
        for (m, _), (c, ok) in zip(cand, res):
            out.write(json.dumps({"s": m[0], "a": m[1], "cycles": c,
                                  "correct": ok}) + "\n")
            if ok and c < best:
                best = c
                print(f"  BETTER {c} at {m}", flush=True)
        print(f"  {k + len(chunk)}/{len(moves)} best {best} "
              f"t={time.time() - t0:.0f}s", flush=True)
    print(f"DONE best={best} t={time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
