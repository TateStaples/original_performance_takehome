"""H-059: the full F-25 chain at one windowed point.

Every Phase-1 relief only paid through the whole chain (re-mine rings FROM
EMPTY -> re-slide l4_gmin -> re-walk the emission order), so a bare
structural change measured without it is measured wrong.  This runs that
chain at a `group_window` point: the ring plan is re-mined from empty into
the words the windowing actually freed, l4_gmin is re-slid under the
resulting relief, and the rolling-window diagonal is re-walked with rings
and gmin inside the objective.

Usage: python3 tools/h059_chain.py --w 24 --budget 600
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_alias as A  # noqa: E402
import h059_curve as H  # noqa: E402
import h059_oracle as O  # noqa: E402
from run_variant import measure  # noqa: E402
from problem import SCRATCH_SIZE  # noqa: E402

RING_ORDERS = {
    "e0-asc": [(0, g) for g in range(32)],
    "e1-asc": [(1, g) for g in range(32)],
    "e0-desc": [(0, g) for g in reversed(range(32))],
    "e1-desc": [(1, g) for g in reversed(range(32))],
    "e0-late": [(0, g) for g in list(range(16, 32)) + list(range(16))],
    "e1-late": [(1, g) for g in list(range(16, 32)) + list(range(16))],
}


def mine_rings(top: int, order: str) -> tuple:
    """Fill the freed words with 24-word rings, in `order`."""
    out, a = [], top
    for k in RING_ORDERS[order]:
        if a + 24 > SCRATCH_SIZE:
            break
        out.append((k, (a, a + 8, a + 16)))
        a += 24
    return tuple(out)


def evaluate(w: int, lags, ring_order: str | None, gmin) -> tuple[int, bool]:
    plan = H.rolling_plan_lags(w, lags, "zip")
    cfg: dict[str, Any] = dict(A.base_mix(), emission_plan=plan,
                               group_window=w, l4_gmin=gmin)
    if ring_order is not None:
        try:
            _, top = O.build(dict(A.base_mix(), emission_plan=plan,
                                  group_window=w, l4_gmin=gmin))
        except Exception:
            return (10 ** 6, False)
        cfg["parity_ring"] = True
        cfg["parity_ring_plan"] = mine_rings(top, ring_order)
    try:
        c, ok = measure(cfg, seed=1)
    except Exception:
        return (10 ** 6, False)
    return (c, bool(ok))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, default=24)
    ap.add_argument("--budget", type=float, default=600.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    w = args.w
    lags = sorted(A.BEST_LAGS[w])
    rng = random.Random(11)
    t0 = time.time()

    # leg 1: ring plan from empty
    best = (10 ** 6, None, None)
    for ro in list(RING_ORDERS) + [None]:
        c, ok = evaluate(w, lags, ro, (6, 31))
        if ok and c < best[0]:
            best = (c, ro, (6, 31))
    print(json.dumps({"leg": "rings", "cycles": best[0], "order": best[1]}),
          flush=True)

    # leg 2: gmin slide under the ring relief
    ro = best[1]
    for g0 in range(3, 12):
        for g1 in range(27, 33):
            c, ok = evaluate(w, lags, ro, (g0, g1))
            if ok and c < best[0]:
                best = (c, ro, (g0, g1))
    print(json.dumps({"leg": "gmin", "cycles": best[0], "gmin": best[2]}),
          flush=True)

    # leg 3: re-walk the rolling diagonal with rings+gmin inside the objective
    cur = best[0]
    cur_lags = list(lags)
    gmin = best[2]
    cache: dict[tuple, int] = {}
    while time.time() - t0 < args.budget:
        b = list(cur_lags)
        for _ in range(rng.choice([1, 1, 1, 2, 3])):
            i = rng.randrange(w)
            b[i] = max(0, b[i] + rng.choice([-3, -2, -1, 1, 2, 3]))
        b = sorted(x - min(b) for x in b)
        key = tuple(b)
        if key in cache:
            continue
        c, ok = evaluate(w, b, ro, gmin)
        cache[key] = c
        if ok and c < cur:
            cur, cur_lags = c, b
            print(json.dumps({"leg": "walk", "cycles": c, "lags": b}),
                  flush=True)
    res = {"w": w, "cycles": cur, "lags": cur_lags, "ring_order": ro,
           "gmin": list(gmin), "walk_evals": len(cache)}
    print(json.dumps(res), flush=True)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(res, f)


if __name__ == "__main__":
    main()
