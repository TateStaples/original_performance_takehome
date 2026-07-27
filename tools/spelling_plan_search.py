"""H-042 offline joint selection x scheduling search over flow_spelling_plan.

Derives a `flow_spelling_plan` for dev.py's build_kernel_scheduled: per
emit_any race site, force one of the semantically-equivalent encodings
instead of the greedy earliest-retire race. Correct by construction (all
encodings compute the same values); only cycles move.

Move set per sweep, regenerated from the current best plan's schedule:
  - reverse flips: flow-WON race -> each non-flow spelling (the moves
    that actually pay: they return a ramp/drain flow slot the greedy
    took myopically);
  - forward flips: flow-LOST race -> flow spelling (pays only on
    flow-uncongested configs);
  - drop moves (escape stale forcings);
  - with H042_AUX=1, all non-flow (alu/valu) races too.
Objective = exact bundle count from a full rebuild (~0.1 s). After the
greedy fixpoint, an optional sideways plateau walk (H042_WALK seconds)
samples equal-cycle plans for further descents.

PLANS ARE CONFIG-SPECIFIC MEASUREMENT ARTIFACTS (same class as
parity_ring_plan): re-derive after ANY flag/emission-order change.

Usage (repo root):
  python tools/spelling_plan_search.py [flag=value ...]  # overrides on BASE_KWARGS
  env: H042_BUDGET (greedy secs, default 480), H042_WALK (walk secs, 0),
       H042_WALK_SEED, H042_SEED_PLAN (e.g. '{354: 1}'), H042_AUX=1
Writes h042_plan.json next to itself; prints the plan tuple.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from dev import KernelBuilder, ListScheduler
from run_variant import BASE_KWARGS, SHAPE, parse_value

RACE_LOG: list[dict[str, Any]] = []
LOGGING = False

_orig_emit_any = ListScheduler.emit_any


def logging_emit_any(self, encodings):
    encodings = list(encodings)
    is_race = len(encodings) > 1
    is_flow_site = is_race and any(
        all(e == "flow" for e, *_ in enc) for enc in encodings
    )
    site_idx = None
    encodings_run = encodings
    if is_race:
        if is_flow_site:
            site_idx = self.flow_site_idx
            self.flow_site_idx += 1
        else:
            site_idx = -(self.aux_site_idx + 1)
            self.aux_site_idx += 1
        forced = self.flow_site_plan.get(site_idx)
        if forced is not None:
            encodings_run = [encodings[forced]]

    trials = []
    for encoding in encodings_run:
        trial_occupancy: dict[str, dict[int, int]] = {}
        trial_last_write: dict[int, int] = {}
        trial_last_read: dict[int, int] = {}
        placements: list[int] = []
        retire = -1
        for engine, slot, reads, writes in encoding:
            cycle = self.ready(reads, writes)
            for addr in reads:
                t = trial_last_write.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
            for addr in writes:
                t = trial_last_write.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
                t = trial_last_read.get(addr, -1)
                if t > cycle:
                    cycle = t
            cycle = self.find_free(engine, cycle, trial_occupancy.setdefault(engine, {}))
            trial_occupancy[engine][cycle] = trial_occupancy[engine].get(cycle, 0) + 1
            placements.append(cycle)
            if cycle > retire:
                retire = cycle
            for addr in reads:
                if trial_last_read.get(addr, -1) < cycle:
                    trial_last_read[addr] = cycle
            for addr in writes:
                trial_last_write[addr] = cycle
        trials.append((retire, encoding, placements))
    best_idx = min(range(len(trials)), key=lambda i: trials[i][0])
    retire, encoding, placements = trials[best_idx]
    for (engine, slot, reads, writes), cycle in zip(encoding, placements):
        self.put(engine, slot, cycle, reads, writes)

    if is_race and LOGGING:
        shapes = tuple(tuple(sorted({e for e, *_ in enc})) for enc in encodings)
        fidx = next((i for i, s in enumerate(shapes) if s == ("flow",)), None)
        chosen_global = (
            self.flow_site_plan[site_idx]
            if site_idx in self.flow_site_plan else best_idx
        )
        RACE_LOG.append({
            "site": site_idx,
            "tag": self.tag,
            "shapes": shapes,
            "flow_idx": fidx,
            "chosen": chosen_global,
            "retire": retire,
            "dest": tuple(sorted({a for _, _, _, ws in encoding for a in ws})),
            "trace_pos": len(self.trace) if self.trace is not None else -1,
            "forced": site_idx in self.flow_site_plan,
        })
    return retire


ListScheduler.emit_any = logging_emit_any


def build(kwargs, plan, logging=False, trace=False):
    global LOGGING
    RACE_LOG.clear()
    LOGGING = logging
    kb = KernelBuilder()
    if trace:
        kb.sched_trace = []
    kb.build_kernel_scheduled(
        SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"],
        flow_spelling_plan=tuple(sorted(plan.items())), **kwargs
    )
    LOGGING = False
    return kb


def candidates_from_log(kb, n_cycles):
    """flow-lost sites whose flow spelling fits before the dest's first
    consumer (RAW) / next writer (WAW). Returns [(site, flow_idx, slack)]."""
    out = []
    for r in RACE_LOG:
        if r["forced"] or r["flow_idx"] is None or r["chosen"] == r["flow_idx"]:
            continue
        dest = set(r["dest"])
        deadline = n_cycles + 50
        for entry in kb.sched_trace[r["trace_pos"]:]:
            cyc, _eng, _tag, _slot, reads, writes, _mr, _mw = entry
            if dest & set(reads) or dest & set(writes):
                deadline = cyc - 1
                break
        out.append((r["site"], r["flow_idx"], deadline - r["retire"]))
    return out


def main() -> None:
    overrides: dict[str, Any] = {}
    for item in sys.argv[1:]:
        key, _, text = item.partition("=")
        overrides[key.strip()] = parse_value(text.strip())
    kwargs = dict(BASE_KWARGS, **overrides)

    budget = float(os.environ.get("H042_BUDGET", "480"))
    plan: dict[int, int] = {}
    if "H042_SEED_PLAN" in os.environ:
        plan = dict(eval(os.environ["H042_SEED_PLAN"]))
    kb = build(kwargs, plan)
    best = len(kb.instrs)
    print(f"start: {best} bundles (plan size {len(plan)})", flush=True)

    t0 = time.time()
    improved = True
    sweep = 0
    while improved and time.time() - t0 < budget:
        improved = False
        sweep += 1
        # regenerate the move set from the CURRENT best plan's schedule
        kb = build(kwargs, plan, logging=True, trace=True)
        n_cycles = len(kb.instrs)
        moves: list[tuple[int, int, str]] = []
        # reverse flips first (they are what pays): flow-won -> each alt;
        # aux (non-flow) races: every non-chosen alt
        for r in RACE_LOG:
            if r["forced"]:
                continue
            if r["flow_idx"] is not None and r["chosen"] == r["flow_idx"]:
                for i in range(len(r["shapes"])):
                    if i != r["flow_idx"]:
                        moves.append((r["site"], i, "rev"))
            elif r["flow_idx"] is None and os.environ.get("H042_AUX"):
                for i in range(len(r["shapes"])):
                    if i != r["chosen"]:
                        moves.append((r["site"], i, "aux"))
        # forward flips: flow-lost with any slack -> flow
        for site, fidx, slack in candidates_from_log(kb, n_cycles):
            moves.append((site, fidx, f"fwd(slack {slack})"))
        # un-plan moves: drop existing plan entries (escape stale forcings)
        for site in list(plan):
            moves.append((site, -1, "drop"))
        for site, alt, kind in moves:
            if time.time() - t0 > budget:
                break
            trial = dict(plan)
            if alt < 0:
                trial.pop(site, None)
            else:
                trial[site] = alt
            n = len(build(kwargs, trial).instrs)
            if n < best:
                best, plan, improved = n, trial, True
                print(f"  sweep {sweep}: {kind} site {site} -> {best}", flush=True)
        print(f"  sweep {sweep} done: best {best}, plan size {len(plan)}, t={time.time()-t0:.0f}s", flush=True)

    # plateau walk: random sideways-or-better moves from the fixpoint,
    # tracking the global best; move set regenerated every 40 accepted moves
    import random as _random
    _random.seed(int(os.environ.get("H042_WALK_SEED", "0")))
    walk_budget = float(os.environ.get("H042_WALK", "0"))
    if walk_budget > 0:
        t1 = time.time()
        cur_plan, cur_n = dict(plan), best
        stale = 0
        while time.time() - t1 < walk_budget:
            kb = build(kwargs, cur_plan, logging=True, trace=True)
            n_cycles = len(kb.instrs)
            moves = []
            for r in RACE_LOG:
                if r["forced"]:
                    continue
                if r["flow_idx"] is None and not os.environ.get("H042_AUX"):
                    continue
                for i in range(len(r["shapes"])):
                    if i != r["chosen"]:
                        moves.append((r["site"], i))
            for site in list(cur_plan):
                moves.append((site, -1))
            accepted = 0
            tries = 0
            while accepted < 40 and tries < 400 and time.time() - t1 < walk_budget:
                site, alt = moves[_random.randrange(len(moves))]
                trial = dict(cur_plan)
                if alt < 0:
                    trial.pop(site, None)
                else:
                    trial[site] = alt
                n = len(build(kwargs, trial).instrs)
                tries += 1
                if n <= cur_n:
                    cur_plan, cur_n = trial, n
                    accepted += 1
                    if n < best:
                        best, plan = n, dict(trial)
                        print(f"  walk: NEW BEST {best} (plan size {len(trial)}, t={time.time()-t0:.0f}s)", flush=True)
            print(f"  walk block: cur {cur_n}, best {best}, accepted {accepted}/{tries}", flush=True)

    print(f"\nFINAL: {best} bundles, plan size {len(plan)}")
    print("plan =", tuple(sorted(plan.items())))
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "h042_plan.json"), "w") as f:
        json.dump({"kwargs_overrides": {k: repr(v) for k, v in overrides.items()},
                   "cycles": best, "plan": sorted(plan.items())}, f, indent=1)


if __name__ == "__main__":
    main()
