"""H-054 shared config/harness: the floor-990 target board (F-17).

The H-047 winner config (strain frontier 1022) plus helpers to build its op
stream under arbitrary flow-spelling policies and to measure engine floors.
Wrapper only: emission_order_search.py / backtrack_sched.py untouched.
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, measure  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

PLAN_1022 = os.path.join(REPO_ROOT, "tools", "h047_best_plan_1022.json")

# H-047 landed frontier (dev flags, all default OFF) == mainline 1022.
FRONTIER: dict[str, Any] = {
    "parity_ring": True,
    "l4_gmin": (7, 30),
    "parity_ring_plan": (((0, 5), (193, 201, 601)), ((0, 6), (609, 617, 625)),
                         ((0, 15), (185, 1225, 1233)), ((0, 16), (193, 201, 1297))),
    "c5_primed_gather_levels": (5, 6),
    "mem_prime_region_hazards": True,
    "mem_prime_dead_reg_staging": True,
    "flow_spelling_plan": (),
}


def frontier_kwargs(**extra: Any) -> dict[str, Any]:
    kw = dict(BASE_KWARGS)
    kw.update(FRONTIER)
    kw["emission_plan"] = eos.load_plan(PLAN_1022)
    kw["debug_compares"] = False
    kw.update(extra)
    return kw


def slot_stats(kb) -> dict[str, dict[str, int]]:
    counts: Counter[str] = Counter()
    for bundle in kb.instrs:
        for engine, ops in bundle.items():
            if engine == "debug":
                continue
            counts[engine] += len(ops) if isinstance(ops, list) else 1
    return {e: {"slots": n, "floor": -(-n // SLOT_LIMITS[e])}
            for e, n in sorted(counts.items())}


def max_floor(kb) -> int:
    return max(v["floor"] for v in slot_stats(kb).values())


def measure_frontier(extra: dict[str, Any] | None = None, seed: int | None = 1):
    over = dict(FRONTIER)
    over["emission_plan"] = eos.load_plan(PLAN_1022)
    if extra:
        over.update(extra)
    return measure(over, seed=seed)
