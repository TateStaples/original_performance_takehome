"""H-059 pre-screen: what is FREED SCRATCH actually worth?

Before paying cycles to free words (the liveness trade), bound what any
amount of extra scratch could buy.  Three relaxations, each measured as
BUNDLE COUNT (the built schedule length; these programs are deliberately
not runnable, they allocate outside the 1536-word machine):

  temp=inf     every temp_slot() gets a private never-reused vector
               (dominates ANY temp-pool enlargement)
  cond=N       cond/tm/tmM pools grown to N (they are the WAW serialisers
               for the tournament fold conditions)
  both         the two together

Usage: python3 tools/h059_oracle.py [--order PLAN.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402
from run_variant import BASE_KWARGS  # noqa: E402
from dev import KernelBuilder  # noqa: E402

SHAPE = (256, 16, 10)  # batch_size, rounds, forest_height


def build(overrides: dict[str, Any], virtual_temps: bool = False,
          scratch_limit: int | None = None) -> tuple[int, int]:
    """(bundle count, scratch_next_addr) for one configuration.

    `scratch_limit` raises dev's SCRATCH_SIZE assert for RELAXATION runs
    (tool-side monkeypatch only; the resulting program is not runnable and
    is never measured for correctness -- only its schedule length, which is
    a valid upper bound on what any amount of scratch could buy).
    """
    import dev
    old = dev.SCRATCH_SIZE
    if scratch_limit is not None:
        dev.SCRATCH_SIZE = scratch_limit
    try:
        kb = KernelBuilder()
        if virtual_temps:
            kb._temp_alloc_mode = "virtual"
        kb.build_kernel_scheduled(*SHAPE, **overrides)
        return len(kb.instrs), kb.scratch_next_addr
    finally:
        dev.SCRATCH_SIZE = old


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", default=os.path.join(REPO_ROOT, "tools",
                                                    "h057_best_plan_1006.json"))
    args = ap.parse_args()
    import f37_lib as F
    order, _ = F.load_point(args.order)

    base = dict(BASE_KWARGS, **dict(H.MIX, emission_plan=order,
                                    debug_compares=False))
    nb, sc = build(base)
    print(json.dumps({"case": "mainline(1006)", "bundles": nb, "scratch": sc}))

    nb0, sc0 = build(dict(base), virtual_temps=True)
    print(json.dumps({"case": "temp=inf", "bundles": nb0, "scratch": sc0}))

    for n in (4, 6, 8, 12, 16, 32):
        try:
            nb1, sc1 = build(dict(base, temp_and_cond_pool_sizes=(16, n)),
                             scratch_limit=100000)
            print(json.dumps({"case": f"cond={n}", "bundles": nb1,
                              "scratch": sc1}))
        except Exception as exc:
            print(json.dumps({"case": f"cond={n}",
                              "error": f"{type(exc).__name__}: {exc}"[:120]}))
    for n in (20, 24, 32, 48):
        try:
            nb1, sc1 = build(dict(base, temp_and_cond_pool_sizes=(n, 4)),
                             scratch_limit=100000)
            print(json.dumps({"case": f"temp={n}", "bundles": nb1,
                              "scratch": sc1}))
        except Exception as exc:
            print(json.dumps({"case": f"temp={n}",
                              "error": f"{type(exc).__name__}: {exc}"[:120]}))
    try:
        nb2, sc2 = build(dict(base, temp_and_cond_pool_sizes=(48, 32)),
                         virtual_temps=True, scratch_limit=100000)
        print(json.dumps({"case": "temp=inf+cond=16", "bundles": nb2,
                          "scratch": sc2}))
    except Exception as exc:
        print(json.dumps({"case": "both", "error": str(exc)[:120]}))


if __name__ == "__main__":
    main()
