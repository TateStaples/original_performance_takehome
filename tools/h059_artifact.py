"""H-059: write a drop-in plan artifact for a windowed configuration.

Same JSON shape as tools/h057_best_plan_1006.json (cycles / params.mix /
plan) so tools/f37_bounds.py and tools/h056_screen.py can read it directly.

Usage:
  python3 tools/h059_artifact.py --w 24 --gmin 7,30 --ring e1-desc \
      --out tools/h059_best_plan_1050.json
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

import h059_alias as A  # noqa: E402
import h059_chain as C  # noqa: E402
import h059_curve as H  # noqa: E402
import h059_oracle as O  # noqa: E402
from run_variant import measure  # noqa: E402


def build_mix(w: int, lags, ring: str | None, gmin) -> dict[str, Any]:
    plan = H.rolling_plan_lags(w, lags, "zip")
    mix: dict[str, Any] = {
        "group_window": w,
        "lazy_val_loads": True,
        "l4_gmin": list(gmin),
        "c5_primed_gather_levels": [5, 6],
        "mem_prime_region_hazards": True,
        "mem_prime_dead_reg_staging": True,
        "flow_spelling_plan": [],
    }
    if ring:
        _, top = O.build(dict(A.base_mix(), emission_plan=plan,
                              group_window=w, l4_gmin=tuple(gmin)))
        mix["parity_ring"] = True
        mix["parity_ring_plan"] = [[list(k), list(v)]
                                   for k, v in C.mine_rings(top, ring)]
    return mix, plan


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, required=True)
    ap.add_argument("--gmin", default="6,31")
    ap.add_argument("--ring", default=None)
    ap.add_argument("--lags", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="")
    args = ap.parse_args()
    gmin = tuple(int(x) for x in args.gmin.split(","))
    lags = ([int(x) for x in args.lags.split(",")] if args.lags
            else sorted(A.BEST_LAGS[args.w]))
    mix, plan = build_mix(args.w, lags, args.ring, gmin)
    cfg = dict(A.base_mix())
    cfg.update({k: (tuple(v) if isinstance(v, list) else v)
                for k, v in mix.items()})
    cfg["parity_ring_plan"] = tuple(
        (tuple(k), tuple(v)) for k, v in mix.get("parity_ring_plan", []))
    if not mix.get("parity_ring"):
        cfg.pop("parity_ring_plan", None)
    cfg["emission_plan"] = plan
    cyc, ok = measure(cfg, seed=1)
    with open(args.out, "w") as f:
        json.dump({"cycles": cyc, "params": {
            "hypothesis": "H-059", "window": args.w, "lags": lags,
            "ring_order": args.ring, "correct_seed1": bool(ok),
            "note": args.note, "mix": mix}, "plan": [list(e) for e in plan]},
            f)
    print(json.dumps({"out": args.out, "cycles": cyc, "correct": bool(ok)}))


if __name__ == "__main__":
    main()
