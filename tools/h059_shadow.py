"""H-059: the SHADOW PRICE OF SCRATCH at the 1006 stream.

The hypothesis is that freeing scratch words changes which serving/retention
strategies are affordable.  Rather than enumerate strategies one at a time,
this asks the dual question directly: with the 1536-word limit REMOVED
(tool-side monkeypatch of dev.SCRATCH_SIZE; the built programs are not
runnable and are scored only by schedule length, a valid upper bound), is
there ANY reachable configuration that improves?

If every direction is neutral-or-worse under unbounded scratch, the shadow
price of a scratch word is <= 0 and the whole scratch/parallelism trade has
nothing to buy, regardless of how cheaply the words are freed.

Usage: python3 tools/h059_shadow.py
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

# Every knob whose cost is (or was claimed to be) SCRATCH, plus the serving
# knobs H-041/H-047 rejected on scratch grounds.
PROBES: list[tuple[str, dict[str, Any]]] = [
    ("temp pool 24", {"temp_and_cond_pool_sizes": (24, 4)}),
    ("temp pool 32", {"temp_and_cond_pool_sizes": (32, 4)}),
    ("cond pool 6", {"temp_and_cond_pool_sizes": (16, 6)}),
    ("cond pool 8", {"temp_and_cond_pool_sizes": (16, 8)}),
    ("both 32/8", {"temp_and_cond_pool_sizes": (32, 8)}),
    ("coloring uncapped", {"temp_pool_coloring": True,
                           "temp_pool_coloring_uncapped": True}),
    ("prime L5,6,7", {"c5_primed_gather_levels": (5, 6, 7)}),
    ("prime L5,6,7,8", {"c5_primed_gather_levels": (5, 6, 7, 8)}),
    ("prime L4,5,6", {"c5_primed_gather_levels": (4, 5, 6)}),
    ("flow_consts", {"flow_consts": True}),
    ("idx_boundary_select", {"idx_boundary_select": True}),
    ("bcast_alu_copies", {"bcast_alu_copies": True}),
    ("bcast_via_mem", {"bcast_via_mem": True}),
    ("l4_gmin (0,0) serve-all", {"l4_gmin": (0, 0)}),
    ("l4_gmin (16,16)", {"l4_gmin": (16, 16)}),
    ("l4_gmin (32,32) gather-all", {"l4_gmin": (32, 32)}),
    ("tournament (1,2)", {"tournament_levels": (1, 2)}),
    ("tournament (1,2,3,4)", {"tournament_levels": (1, 2, 3, 4)}),
]


def main() -> None:
    import f37_lib as F
    order, _ = F.load_point(os.path.join(REPO_ROOT, "tools",
                                         "h057_best_plan_1006.json"))
    base = dict(BASE_KWARGS, **dict(H.MIX, emission_plan=order,
                                    debug_compares=False))
    nb, sc = O.build(base)
    print(json.dumps({"case": "base", "bundles": nb, "scratch": sc,
                      "delta": 0}))
    for name, ov in PROBES:
        try:
            n2, s2 = O.build(dict(base, **ov), scratch_limit=1000000)
            print(json.dumps({"case": name, "bundles": n2, "scratch": s2,
                              "delta": n2 - nb,
                              "over_budget": max(0, s2 - 1536)}))
        except Exception as exc:
            print(json.dumps({"case": name,
                              "error": f"{type(exc).__name__}: {exc}"[:110]}))


if __name__ == "__main__":
    main()
