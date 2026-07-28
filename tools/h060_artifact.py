"""H-060: write + verify the drop-in artifact for the planned-partition point.

Same JSON shape as tools/h057_best_plan_1006.json (cycles / params.mix /
plan), with `vec_partition_plan` added to the mix as a flat 4,357-entry
list of "a"/"v" spellings indexed by `_sched_vec` emission site.

Usage:
  python3 tools/h060_artifact.py --plan SCRATCH/h060_min.json \
      --out tools/h060_best_plan_1005.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    with open(args.plan) as f:
        spelling = list(json.load(f)["plan"])

    with open(C.PLAN_PATH) as f:
        src = json.load(f)
    mix = dict(src["params"]["mix"])
    mix["vec_partition_plan"] = spelling

    cfg = C.frontier(vec_partition_plan=tuple(enumerate(spelling)))
    kb, prog = C.build(cfg)
    cen = C.slot_census(prog)
    fl = C.floors(prog)
    print(f"bundles {len(prog)}  scratch {kb.scratch_next_addr}")
    print("census", cen)
    print("floors", fl)

    results = {}
    for seed in (None, 1, 2, 3, 7, 42, 99):
        cyc, ok = C.measure(cfg, seed=seed)
        results[str(seed)] = [cyc, bool(ok)]
        print(f"  seed {seed}: {cyc} correct={ok}")
    cyc, ok = C.measure(dict(cfg, debug_compares=True))
    results["debug_compares"] = [cyc, bool(ok)]
    print(f"  debug_compares: {cyc} correct={ok}")

    out = {
        "cycles": len(prog),
        "params": {
            "hypothesis": "H-060",
            "organization": "H-057 1006 order + offline-searched per-site "
                            "alu/valu partition (vec_partition_plan)",
            "note": args.note,
            "verification": results,
            "mix": mix,
        },
        "plan": [list(e) if not (isinstance(e, tuple) and e and e[0] == "rr")
                 else ["rr", [list(p) for p in e[1]]]
                 for e in src["plan"]],
    }
    out["plan"] = src["plan"]
    with open(args.out, "w") as f:
        json.dump(out, f)
    print("wrote", args.out)


if __name__ == "__main__":
    main()
