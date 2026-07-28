"""H-047: single-sweep spelling fixpoint check (flow + aux moves) for a
candidate config x emission-plan artifact. Reports any improving single flip."""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import spelling_plan_search as sps  # noqa: E402
import emission_order_search as eos  # noqa: E402
from run_variant import BASE_KWARGS  # noqa: E402
from h047_search import BASELINE, parse_overrides  # noqa: E402


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[])
    ap.add_argument("--plan", required=True)
    args = ap.parse_args()

    kwargs = dict(BASE_KWARGS)
    kwargs.update(BASELINE)
    kwargs.update(parse_overrides(args.set))
    kwargs["debug_compares"] = False
    kwargs["emission_plan"] = eos.load_plan(args.plan)
    kwargs.pop("flow_spelling_plan", None)

    plan: dict[int, int] = {}
    kb = sps.build(kwargs, plan, logging=True, trace=True)
    best = n_cycles = len(kb.instrs)
    print("start bundles:", best, flush=True)
    moves = []
    for r in sps.RACE_LOG:
        if r["forced"]:
            continue
        if r["flow_idx"] is not None and r["chosen"] == r["flow_idx"]:
            for i in range(len(r["shapes"])):
                if i != r["flow_idx"]:
                    moves.append((r["site"], i, "rev"))
        elif r["flow_idx"] is None:
            for i in range(len(r["shapes"])):
                if i != r["chosen"]:
                    moves.append((r["site"], i, "aux"))
    for site, fidx, slack in sps.candidates_from_log(kb, n_cycles):
        moves.append((site, fidx, f"fwd{slack}"))
    print("moves:", len(moves), flush=True)
    t0 = time.time()
    wins = []
    for site, alt, kind in moves:
        trial = dict(plan)
        trial[site] = alt
        n = len(sps.build(kwargs, trial).instrs)
        if n < best:
            wins.append((site, alt, kind, n))
            print("  WIN", site, alt, kind, n, flush=True)
    print(json.dumps({"n_moves": len(moves), "wins": wins,
                      "secs": round(time.time() - t0, 1)}))


if __name__ == "__main__":
    main()
