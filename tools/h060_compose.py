"""H-060 step 4: does the searched per-site partition COMPOSE with the
standing chain?

A `vec_partition_plan` is indexed by EMISSION-ORDER site number, exactly
like `flow_spelling_plan`'s negative keys. Every step of the standing chain
(re-mine rings -> re-slide l4_gmin -> re-walk the order) changes which op is
emitted at which site index, so a plan mined at one stream is applied to a
DIFFERENT op at every index on the next. This tool measures the transfer
directly: take single-displacement order perturbations in the productive
r12-15 window and compare (race) vs (stale plan) at each.

Usage: python3 tools/h060_compose.py --plan FILE [--n 120] [--workers N]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import f37_lib as F  # noqa: E402
import h060_common as C  # noqa: E402

_PLAN: tuple[tuple[int, str], ...] = ()


def _init(plan: Any) -> None:
    global _PLAN
    _PLAN = tuple((int(i), str(v)) for i, v in plan)


def _eval(arg: tuple[int, Any]) -> tuple[int, int, int]:
    idx, order = arg
    out = []
    for pl in ((), _PLAN):
        try:
            _, prog = C.build(C.frontier(emission_plan=order,
                                         vec_partition_plan=pl))
            out.append(len(prog))
        except Exception:
            out.append(10 ** 6)
    return idx, out[0], out[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--n", type=int, default=120)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 1))
    ap.add_argument("--seed", type=int, default=5)
    args = ap.parse_args()

    with open(args.plan) as f:
        plan = list(enumerate(json.load(f)["plan"]))

    base_order = C.frontier()["emission_plan"]
    moves = F.enumerate_moves(base_order, rounds=range(12, 16))
    rng = random.Random(args.seed)
    rng.shuffle(moves)
    cands: list[tuple[int, Any]] = []
    for m in moves:
        o = F.apply_moves(base_order, [m])
        if o is None or o == tuple(base_order):
            continue
        cands.append((len(cands), o))
        if len(cands) >= args.n:
            break
    print(f"{len(cands)} single-move order perturbations (r12-15 window)")

    with mp.Pool(args.workers, initializer=_init, initargs=(plan,)) as pool:
        res = sorted(pool.map(_eval, cands))

    ok = [(r, p) for _i, r, p in res if r < 10 ** 6 and p < 10 ** 6]
    print(f"evaluated {len(ok)}/{len(res)} (rest tripped config asserts)")
    br = min(r for r, _ in ok)
    bp = min(p for _, p in ok)
    wins = sum(1 for r, p in ok if p < r)
    print(f"race over perturbations : best {br}, mean {sum(r for r,_ in ok)/len(ok):.1f}")
    print(f"stale plan over the same: best {bp}, mean {sum(p for _,p in ok)/len(ok):.1f}")
    print(f"plan beats race at {wins}/{len(ok)} perturbed orders")
    d = sorted(p - r for r, p in ok)
    print("plan-minus-race deltas: min %d  p25 %d  median %d  p75 %d  max %d"
          % (d[0], d[len(d)//4], d[len(d)//2], d[3*len(d)//4], d[-1]))


if __name__ == "__main__":
    main()
