"""H-047: per-candidate stream-floor measurement.

Wrapper around tools/backtrack_sched.py (NOT modified): captures the op
stream of a candidate mix config (BASELINE 1023 config + overrides +
optional emission plan), then reports the H-051 bounds:
  - engine slot floors (per-engine ceil(slots/cap))
  - dependency critical path
  - lb_total (max of the above)
  - energetic staircase bounds (release/tail) = provable floor for ANY
    packing of this stream
  - final cycles + regret

Usage:
    python3 tools/h047_floor.py --name cand --set 'l4_gmin=(7,30)' [--no-plan]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import backtrack_sched as bts  # noqa: E402
import emission_order_search as eos  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

from h047_search import BASELINE, H049_PLAN, parse_overrides  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--plan", default=H049_PLAN)
    ap.add_argument("--no-plan", action="store_true")
    args = ap.parse_args()

    overrides = dict(BASELINE, **parse_overrides(args.set))
    if not args.no_plan:
        overrides["emission_plan"] = eos.load_plan(args.plan)
    # capture() composes BASE_KWARGS + H51_OVERRIDES + overrides; neutralize
    # the stale H51 layer (it pins flow_spelling_plan=((354,1),) which is
    # order-specific to the OLD 1031 order).
    bts.H51_OVERRIDES = {}
    overrides.setdefault("flow_spelling_plan", ())

    data = bts.capture(overrides)
    ops = data["ops"]
    preds, floors = bts.build_model(ops, data["pair_writes"])
    lb = bts.lb_total(ops, preds, floors)
    place = [op[9] for op in ops]
    total = max(place) + 1

    est = bts.ests(ops, preds, floors)
    h = bts.tails(ops, preds)
    stair = {}
    for sname, key in (("release", est), ("tail", h)):
        best_v, best_at = 0, None
        for e in bts.ENGINES:
            vals = sorted((key[i] for i in range(len(ops)) if ops[i][0] == e),
                          reverse=True)
            for cnt, t in enumerate(vals, 1):
                v = t + -(-cnt // SLOT_LIMITS[e])
                if v > best_v:
                    best_v, best_at = v, (e, t, cnt)
        stair[sname] = {"bound": best_v, "at": best_at}

    slots = {}
    for e in bts.ENGINES:
        n = sum(1 for op in ops if op[0] == e)
        slots[e] = {"slots": n, "floor": -(-n // SLOT_LIMITS[e])}

    out = {
        "name": args.name,
        "captured_cycles": data["n_cycles"],
        "total_cycles": total,
        "lb_total": lb,
        "staircase": stair,
        "floor_any_packing": max(lb["lb"], stair["release"]["bound"],
                                 stair["tail"]["bound"]),
        "regret": total - max(lb["lb"], stair["release"]["bound"],
                              stair["tail"]["bound"]),
        "engine_slots": slots,
    }
    print(json.dumps(out, default=str))


if __name__ == "__main__":
    main()
