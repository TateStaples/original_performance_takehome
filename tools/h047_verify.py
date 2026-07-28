"""H-047 finalist verification: multi-seed + debug_compares on a candidate
config x emission-plan artifact."""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
from run_variant import measure  # noqa: E402
from h047_search import BASELINE, parse_overrides  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--plan", required=True)
    ap.add_argument("--seeds", default="1,2,3,7,42,99")
    args = ap.parse_args()

    over = dict(BASELINE, **parse_overrides(args.set))
    over["emission_plan"] = eos.load_plan(args.plan)

    results = []
    for seed in [int(s) for s in args.seeds.split(",")]:
        c, ok = measure(dict(over), seed=seed)
        results.append({"seed": seed, "cycles": c, "correct": bool(ok)})
        print(json.dumps(results[-1]), flush=True)
    c, ok = measure(dict(over), seed=None)
    print(json.dumps({"seed": None, "cycles": c, "correct": bool(ok)}), flush=True)
    c, ok = measure(dict(over, debug_compares=True), seed=1)
    print(json.dumps({"seed": 1, "debug_compares": True, "cycles": c,
                      "correct": bool(ok)}), flush=True)


if __name__ == "__main__":
    main()
