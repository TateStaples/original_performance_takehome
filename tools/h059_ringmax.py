"""H-059 pre-screen: what would NON-BORROWED parity rings be worth?

H-045/H-048 fund parity rings by BORROWING dead 8-word windows from other
blocks' registers -- an order-fragile mechanism that tops out at 40 of the
64 possible (epoch, group) rings.  The stated motivation for freeing scratch
is to fund the rest with REAL allocation.

This bounds that spend by relaxation: hand every unfunded (epoch, group) a
PRIVATE, never-shared 24-word triple out of an unbounded scratch space and
count bundles.  No borrow can beat a private allocation, so the number is an
upper bound on the whole "non-borrowed rings" class -- measurable without
building the allocator.

Usage: python3 tools/h059_ringmax.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402
import h059_oracle as O  # noqa: E402
from run_variant import BASE_KWARGS  # noqa: E402
from dev import KernelBuilder  # noqa: E402

FRESH_BASE = 4000  # far outside the real 1536-word machine
ROUNDS, PERIOD, N_GROUPS = 16, 11, 32


def funded_keys(base: dict[str, Any]) -> set[tuple[int, int]]:
    import dev
    old = dev.SCRATCH_SIZE
    dev.SCRATCH_SIZE = 100000
    try:
        kb = KernelBuilder()
        kb.build_kernel_scheduled(*O.SHAPE, **base)
        return set(kb._h048_layout["parity_ring_map"])
    finally:
        dev.SCRATCH_SIZE = old


def main() -> None:
    import f37_lib as F
    order, _ = F.load_point(os.path.join(REPO_ROOT, "tools",
                                         "h057_best_plan_1006.json"))
    base = dict(BASE_KWARGS, **dict(H.MIX, emission_plan=order,
                                    debug_compares=False))
    nb, sc = O.build(base)
    print(json.dumps({"case": "mainline(1006)", "bundles": nb, "scratch": sc,
                      "rings": len(funded_keys(base))}))

    # ring-free reference
    nofree = {k: v for k, v in base.items()
              if k not in ("parity_ring", "parity_ring_plan")}
    nb0, _ = O.build(nofree)
    print(json.dumps({"case": "no rings", "bundles": nb0}))

    # all 64 rings: keep the structural + mined ones, privately fund the rest
    have = funded_keys(base)
    extra = []
    k = 0
    for e in (0, 1):
        for g in range(N_GROUPS):
            if (e, g) in have:
                continue
            extra.append(((e, g), tuple(FRESH_BASE + 8 * (k + i)
                                        for i in range(3))))
            k += 3
    full = dict(base, parity_ring_plan=tuple(base["parity_ring_plan"]) + tuple(extra))
    nb1, sc1 = O.build(full, scratch_limit=100000)
    print(json.dumps({"case": "all-64 rings (private words)", "bundles": nb1,
                      "scratch": sc1, "extra_rings": len(extra),
                      "extra_words": k * 8}))

    # every ring privately funded (drop the borrow mechanism entirely)
    allplan = []
    k = 0
    for e in (0, 1):
        for g in range(N_GROUPS):
            allplan.append(((e, g), tuple(FRESH_BASE + 8 * (k + i)
                                          for i in range(3))))
            k += 3
    # structural slices off (parity_ring must stay truthy for the plan)
    allp = dict(base, parity_ring=((0, 0),), parity_ring_plan=tuple(
        p for p in allplan if p[0] not in funded_keys(
            dict(base, parity_ring=((0, 0),), parity_ring_plan=()))))
    nb2, sc2 = O.build(allp, scratch_limit=100000)
    print(json.dumps({"case": "one slice + private rest", "bundles": nb2,
                      "scratch": sc2}))


if __name__ == "__main__":
    main()
