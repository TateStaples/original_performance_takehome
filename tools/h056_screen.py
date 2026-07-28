"""H-056 organization pre-screen: LB + census + chain ceiling per candidate.

The standing pre-screen stack (G-25 backtrack_sched, G-26 free_slot_oracle,
G-28 lag-zeroing) applied to a *config* rather than to the mainline stream,
so an organization candidate can be costed WITHOUT an emission-order walk.

For each candidate config it reports, from one in-process capture (~4 s):
  * realized cycles of the greedy build (the capture's own schedule),
  * per-engine slot census and floors, the critical-path bound, and the
    combined any-packing LB (`lb_total`) -- this is the number H-056 gates
    on: only candidates with LB <= 1006 earn an order walk,
  * the two energetic staircase bounds (release / tail), which are also
    valid for ANY packing of the stream,
  * the fungible bound (perfect valu/alu respelling),
  * the all-lags-zero greedy (G-28's chain-shortening ceiling), optional.

Usage (repo root):
  python3 tools/h056_screen.py --cfg '{"skew": [4, 3]}' --name mainline
  python3 tools/h056_screen.py --cfg-file cands.json      # {name: overrides}
Options: --lags-zero (chain ceiling), --regret (full regret profile, slow),
         --plan FILE (emission_plan from an emission_order_search .best.json).
Prints one JSON line per candidate to stdout.

Read-only w.r.t. the shared pre-screens: this module IMPORTS
backtrack_sched/free_slot_oracle and never edits them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import backtrack_sched as bs  # noqa: E402
from run_variant import measure  # noqa: E402


def _tuplify(v: Any) -> Any:
    return tuple(_tuplify(x) for x in v) if isinstance(v, list) else v


def load_plan(path: str) -> tuple[Any, ...]:
    with open(path) as f:
        data = json.load(f)
    plan = []
    for e in data["plan"]:
        if e[0] == "rr":
            plan.append(("rr", tuple(tuple(p) for p in e[1])))
        else:
            plan.append(tuple(e))
    return tuple(plan)


def screen(name: str, overrides: dict[str, Any], lags_zero: bool = False,
           regret: bool = False, verify: bool = True) -> dict[str, Any]:
    """Capture `overrides` and return the bound stack. Never mutates the
    caller's dict; H51_OVERRIDES is restored on exit."""
    t0 = time.time()
    out: dict[str, Any] = {"name": name}
    saved = dict(bs.H51_OVERRIDES)
    try:
        bs.H51_OVERRIDES.clear()
        bs.H51_OVERRIDES.update(overrides)
        try:
            data = bs.capture()
        except Exception as exc:  # organization candidates can assert
            out["error"] = f"{type(exc).__name__}: {exc}"
            out["secs"] = round(time.time() - t0, 1)
            return out
    finally:
        bs.H51_OVERRIDES.clear()
        bs.H51_OVERRIDES.update(saved)

    ops = data["ops"]
    preds, floors = bs.build_model(ops, data["pair_writes"])
    lb = bs.lb_total(ops, preds, floors)
    counts: dict[str, int] = defaultdict(int)
    for op in ops:
        counts[op[0]] += 1

    out.update({
        "realized": data["n_cycles"],
        "ops": len(ops),
        "census": {e: counts[e] for e in sorted(counts)},
        "floors": lb["engine"],
        "cp": lb["cp"],
        "LB": lb["lb"],
    })

    # energetic staircase bounds (valid for any packing)
    est = bs.ests(ops, preds, floors)
    h = bs.tails(ops, preds)
    for label, key in (("stair_release", est), ("stair_tail", h)):
        best_v, best_at = 0, None
        for e in bs.ENGINES:
            vals = sorted((key[i] for i in range(len(ops)) if ops[i][0] == e),
                          reverse=True)
            for cnt, t in enumerate(vals, 1):
                v = t + -(-cnt // bs.SLOT_LIMITS[e])
                if v > best_v:
                    best_v, best_at = v, (e, t, cnt)
        out[label] = best_v
        out[label + "_at"] = best_at
    out["LB_energetic"] = max(out["LB"], out["stair_release"], out["stair_tail"])
    out["fungible"] = bs.fungible_lb(ops)

    # offline greedy must reproduce the capture (model soundness check)
    place, nonempty = bs.greedy_schedule(ops, preds, floors)
    out["offline_greedy"] = nonempty
    out["model_exact"] = all(place[i] == ops[i][9] for i in range(len(ops)))

    if lags_zero:
        zero_preds = [[(j, 0) for j, _ in p] for p in preds]
        _, nz = bs.greedy_schedule(ops, zero_preds, floors)
        out["all_lags_zero"] = nz

    if regret:
        F, _, _ = bs.regret_profile(ops, preds, floors, [op[9] for op in ops])
        jumps = []
        prev = lb["lb"]
        for c, v in enumerate(F):
            if v > prev:
                jumps.append([c, v - prev])
                prev = v
        out["regret_total"] = data["n_cycles"] - lb["lb"]
        out["regret_jumps"] = jumps
        band = {"ramp": 0, "mid": 0, "drain": 0}
        n = data["n_cycles"]
        for c, d in jumps:
            band["ramp" if c < 100 else ("drain" if c > n - 80 else "mid")] += d
        out["regret_bands"] = band

    if verify:
        try:
            cyc, ok = measure(overrides, seed=1)
            out["measure"] = [cyc, bool(ok)]
        except Exception as exc:
            out["measure_error"] = f"{type(exc).__name__}: {exc}"

    out["secs"] = round(time.time() - t0, 1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg", default=None, help="JSON overrides dict")
    ap.add_argument("--cfg-file", default=None, help="JSON {name: overrides}")
    ap.add_argument("--name", default="cand")
    ap.add_argument("--plan", default=None,
                    help="emission_plan JSON (adds emission_plan to every cfg)")
    ap.add_argument("--lags-zero", action="store_true")
    ap.add_argument("--regret", action="store_true")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cands: dict[str, dict[str, Any]]
    if args.cfg_file:
        with open(args.cfg_file) as f:
            cands = {k: {kk: _tuplify(vv) for kk, vv in v.items()}
                     for k, v in json.load(f).items()}
    else:
        cands = {args.name: {k: _tuplify(v)
                             for k, v in json.loads(args.cfg or "{}").items()}}

    plan = load_plan(args.plan) if args.plan else None
    sink = open(args.out, "a", buffering=1) if args.out else None
    for name, over in cands.items():
        if plan is not None and "emission_plan" not in over:
            over = dict(over, emission_plan=plan)
        rec = screen(name, over, lags_zero=args.lags_zero, regret=args.regret,
                     verify=not args.no_verify)
        line = json.dumps(rec, default=str)
        print(line, flush=True)
        if sink:
            sink.write(line + "\n")


if __name__ == "__main__":
    main()
