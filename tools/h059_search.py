"""H-059: per-window-size search over the base diagonal.

The trade curve's cycle leg is only meaningful if each window size W is
given its OWN best organization -- a diagonal tuned for 32 live groups is
not the right diagonal for 16.  This walks the per-group lag vector inside
one window (seeded from the structured staircases) at fixed W.

Usage:
  python3 tools/h059_search.py --w 16 --budget 120
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402


def search(w: int, budget: float, seed: int = 7, verbose: bool = True
           ) -> dict:
    rng = random.Random(seed)
    t0 = time.time()
    cache: dict[tuple, int] = {}

    def ev(b, iv) -> int:
        key = (tuple(b), iv)
        if key not in cache:
            c, ok = H.eval_lags(w, b, iv)
            cache[key] = c if ok else 10 ** 6
        return cache[key]

    seeds = []
    for nb in range(1, min(w, 9) + 1):
        if w % nb:
            continue
        per = w // nb
        for stag in range(0, 8):
            seeds.append([stag * (g // per) for g in range(w)])
    seeds.append([H.F24_LAGS[min(7, g * 8 // w)] for g in range(w)])
    best = None
    for iv in ("zip", "block"):
        for b in seeds:
            c = ev(b, iv)
            if best is None or c < best[0]:
                best = (c, list(b), iv)
    assert best is not None
    if verbose:
        print(f"  seed best w={w}: {best[0]} {best[2]} {best[1]}", flush=True)

    cur_c, cur_b, cur_iv = best
    while time.time() - t0 < budget:
        b = list(cur_b)
        for _ in range(rng.choice([1, 1, 1, 2, 3])):
            i = rng.randrange(w)
            b[i] = max(0, b[i] + rng.choice([-3, -2, -1, 1, 2, 3]))
        m = min(b)
        b = [x - m for x in b]
        c = ev(b, cur_iv)
        if c < cur_c:
            cur_c, cur_b = c, b
            if verbose:
                print(f"    -> {c} {b}", flush=True)
    return {"w": w, "cycles": cur_c, "interleave": cur_iv, "lags": cur_b,
            "evals": len(cache)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, action="append", default=[])
    ap.add_argument("--budget", type=float, default=90.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    ws = args.w or [32, 24, 20, 16, 14, 12, 8, 4]
    out = []
    for w in ws:
        r = search(w, args.budget, args.seed)
        print(json.dumps(r), flush=True)
        out.append(r)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
