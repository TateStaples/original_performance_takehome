"""H-047 probe: does forcing ALL flow-capable race sites onto flow lower a
candidate mix's engine floors? (The LP's serve-more prize requires the added
tournament selects to ride flow; greedy races put them on valu.)

For a config: build once with race logging (greedy), then rebuild with every
flow-capable site forced to its flow encoding. Report cycles + per-engine
slot counts/floors for both streams.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import spelling_plan_search as sps  # noqa: E402  (monkeypatches emit_any)
import emission_order_search as eos  # noqa: E402
from run_variant import BASE_KWARGS  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402
from h047_search import BASELINE, H049_PLAN, parse_overrides  # noqa: E402


def slot_stats(kb) -> dict[str, dict[str, int]]:
    counts: Counter[str] = Counter()
    for bundle in kb.instrs:
        for engine, ops in bundle.items():
            if engine == "debug":
                continue
            counts[engine] += len(ops) if isinstance(ops, list) else 1
    return {e: {"slots": n, "floor": -(-n // SLOT_LIMITS[e])}
            for e, n in sorted(counts.items())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--no-plan", action="store_true")
    args = ap.parse_args()

    kwargs = dict(BASE_KWARGS)
    kwargs.update(BASELINE)
    kwargs.update(parse_overrides(args.set))
    if not args.no_plan:
        kwargs["emission_plan"] = eos.load_plan(H049_PLAN)
    kwargs.pop("flow_spelling_plan", None)
    kwargs["debug_compares"] = False

    kb0 = sps.build(kwargs, {}, logging=True)
    log = list(sps.RACE_LOG)
    flow_sites = [r for r in log if r["site"] is not None and r["site"] >= 0
                  and r["flow_idx"] is not None]
    flow_lost = [r for r in flow_sites if r["chosen"] != r["flow_idx"]]
    plan = {r["site"]: r["flow_idx"] for r in flow_sites}

    kb1 = sps.build(kwargs, plan, logging=False)

    out = {
        "name": args.name,
        "n_flow_sites": len(flow_sites),
        "n_flow_lost_greedy": len(flow_lost),
        "greedy": {"cycles": len(kb0.instrs), "engines": slot_stats(kb0)},
        "all_flow": {"cycles": len(kb1.instrs), "engines": slot_stats(kb1)},
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()
