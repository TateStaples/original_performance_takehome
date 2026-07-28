"""H-047: serving-mix change under joint plan re-search.

Wrapper around tools/emission_order_search.py (NOT modified): patches its
module-global FRONTIER_OVERRIDES with a candidate mix config, then reuses
its Runner/local machinery. All artifacts namespaced h047_*.

Subcommands:
    sweep   — grid of mix candidates evaluated at a FIXED emission plan
              (the committed h049 winner) + the default diagonal order.
    local   — emission-plan local search for ONE candidate config
              (seeded from the h049 plan), budgeted.
    eval    — single config x plan measurement (JSON line out).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
from run_variant import measure  # noqa: E402

H049_PLAN = os.path.join(REPO_ROOT, "tools", "h049_best_plan.json")

# The 1023 mainline-equivalent frontier config (H-049 winner).
BASELINE: dict[str, Any] = dict(eos.FRONTIER_OVERRIDES)


def parse_overrides(items: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    spec_env = {"frozenset": frozenset, "set": set, "range": range,
                "__builtins__": {}}
    for item in items:
        key, _, val = item.partition("=")
        try:
            out[key] = eval(val, dict(spec_env))  # noqa: S307 — trusted CLI args
        except Exception:
            if "," in val:
                out[key] = tuple(ast.literal_eval(t.strip()) for t in val.split(","))
            else:
                out[key] = val
    return out


def eval_one(overrides: dict[str, Any], plan_path: str | None, seed: int) -> tuple[int, bool]:
    over = dict(BASELINE, **overrides)
    if plan_path:
        over["emission_plan"] = eos.load_plan(plan_path)
    try:
        return measure(over, seed=seed)
    except Exception as e:  # crash-prone set-form specs (P-17)
        print(f"  CRASH: {type(e).__name__}: {e}", flush=True)
        return (-1, False)


def cmd_eval(args: argparse.Namespace) -> None:
    overrides = parse_overrides(args.set)
    cycles, correct = eval_one(overrides, None if args.no_plan else args.plan, args.seed)
    print(json.dumps({"overrides": {k: repr(v) for k, v in overrides.items()},
                      "plan": None if args.no_plan else args.plan,
                      "seed": args.seed, "cycles": cycles, "correct": bool(correct)}))


def cmd_sweep(args: argparse.Namespace) -> None:
    """Grid over l4_gmin (and optional extra flag sets) at fixed plan(s)."""
    import multiprocessing as mp
    candidates: list[tuple[str, dict[str, Any]]] = []
    if args.grid == "gmin":
        for e0 in range(args.e0_lo, args.e0_hi + 1):
            for e1 in range(args.e1_lo, args.e1_hi + 1):
                candidates.append((f"gmin({e0},{e1})", {"l4_gmin": (e0, e1)}))
    elif args.grid == "file":
        with open(args.grid_file) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                name, spec = line.split("\t")
                spec_env = {"frozenset": frozenset, "set": set, "range": range,
                            "__builtins__": {}}
                candidates.append((name, eval(spec, spec_env)))  # noqa: S307 — trusted local grid files
    else:
        raise SystemExit(f"unknown grid {args.grid}")

    plan = None if args.no_plan else eos.load_plan(args.plan)
    jobs = []
    for name, over in candidates:
        full = dict(BASELINE, **over)
        if plan is not None:
            full["emission_plan"] = plan
        jobs.append((name, full))

    with mp.Pool(args.workers) as pool:
        results = pool.map(_run_job, [(name, over, args.seed) for name, over in jobs])
    with open(args.out, "a", buffering=1) as f:
        for name, c, ok in results:
            rec = {"name": name, "cycles": c, "correct": ok, "plan": args.plan if plan is not None else None}
            f.write(json.dumps(rec) + "\n")
            print(f"{name:>28}  {c:>5}  {'ok' if ok else 'BAD'}", flush=True)


def _run_job(job: tuple[str, dict[str, Any], int]) -> tuple[str, int, bool]:
    name, over, seed = job
    try:
        c, ok = measure(over, seed=seed)
    except Exception:
        return (name, -1, False)
    return (name, c, bool(ok))


def cmd_local(args: argparse.Namespace) -> None:
    """Emission-plan local search for one candidate mix config."""
    overrides = parse_overrides(args.set)
    eos.FRONTIER_OVERRIDES = dict(BASELINE, **overrides)
    eos.FRONTIER_OVERRIDES.pop("emission_plan", None)
    print(f"h047 local: overrides={overrides} budget={args.budget}s window={args.window}",
          flush=True)
    eos.local(args.budget, args.workers, args.out, args.seed_json, args.window)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("one")
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--plan", default=H049_PLAN)
    p.add_argument("--no-plan", action="store_true")
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("sweep")
    p.add_argument("--grid", default="gmin")
    p.add_argument("--grid-file", default=None)
    p.add_argument("--e0-lo", type=int, default=5)
    p.add_argument("--e0-hi", type=int, default=10)
    p.add_argument("--e1-lo", type=int, default=26)
    p.add_argument("--e1-hi", type=int, default=31)
    p.add_argument("--plan", default=H049_PLAN)
    p.add_argument("--no-plan", action="store_true")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    p.add_argument("--out", default=os.path.join(REPO_ROOT, "tools", "h047_sweep.jsonl"))
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("local")
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--budget", type=float, default=1200)
    p.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) // 2))
    p.add_argument("--seed-json", default=H049_PLAN)
    p.add_argument("--window", default="both")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_local)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
