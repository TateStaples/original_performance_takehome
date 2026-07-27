"""H-049 emission-order search over dev.py's `emission_plan` kwarg.

H-042 proved per-site spelling selection under the FIXED emission order is
exhausted at 1031; the residual modeled flow prize is emission-order-shaped
(flow bubbles anti-correlated with select readiness). This driver searches
the ORDER: candidate plans are full explicit emission sequences (see
`emission_plan` in dev.build_kernel_scheduled), evaluated by an exact
build + frozen-grader simulation (~0.17 s), so every point is both cycle-
exact AND correctness-checked (ring-borrow windows are liveness-timed and
can break under reorders -- `correct` is part of the objective, not an
afterthought).

Structured families (make_plan knobs):
  lags         per-block emission lag (skew phase), default (0,3,6,9)
  blocks       explicit group partition (uneven blocks supported)
  wave_order   per-step order of active waves: default(=r desc)/rev/rot:k
  group_order  within-wave group order: asc/rev/rot:k (rotates by k*step)
  interleave   block (wave-major) / zip (group-granular across waves)
  stage_rr     steps emitted as stage round-robin entries (scope step/wave)
  tail_df      last N steps flattened depth-first (group-contiguous drain)
Local search phase: window-restricted entry moves on the best flat plan.

Usage (repo root):
  python tools/emission_order_search.py phase1 [--budget S] [--workers N]
  python tools/emission_order_search.py local --seed-json FILE [--budget S]
Results stream to EOS_OUT (default scratchpad) as JSON lines.
"""
from __future__ import annotations

import itertools
import json
import multiprocessing as mp
import os
import random
import sys
import time
from typing import Any, Sequence

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from run_variant import measure  # noqa: E402

ROUNDS, N_GROUPS = 16, 32

# The H-042 frontier config MINUS flow_spelling_plan (site numbering is
# emission-order-specific; plans are re-derived per winning order).
FRONTIER_OVERRIDES: dict[str, Any] = {
    "parity_ring": True,
    "l4_gmin": (8, 30),
    "parity_ring_plan": (((0, 5), (193, 201, 601)), ((0, 6), (609, 617, 625)),
                          ((0, 15), (185, 1225, 1233)), ((0, 16), (193, 201, 1297))),
}


def default_blocks() -> list[list[int]]:
    return [list(range(b * 8, (b + 1) * 8)) for b in range(4)]


def make_plan(
    lags: Sequence[int] = (0, 3, 6, 9),
    blocks: Sequence[Sequence[int]] | None = None,
    wave_order: str = "default",
    group_order: str = "asc",
    interleave: str = "block",
    stage_rr: Sequence[int] = (),
    stage_rr_scope: str = "step",
    tail_df: int = 0,
    rounds: int = ROUNDS,
) -> tuple[Any, ...]:
    blocks = [list(b) for b in (blocks or default_blocks())]
    assert len(blocks) == len(lags)
    n_steps = rounds + max(lags)
    plan: list[Any] = []
    df_from = n_steps - tail_df
    emitted: dict[int, int] = {g: 0 for b in blocks for g in b}

    def order_groups(groups: list[int], step: int) -> list[int]:
        if group_order == "asc":
            return groups
        if group_order == "rev":
            return list(reversed(groups))
        if group_order.startswith("rot:"):
            k = int(group_order.split(":")[1]) * step % len(groups)
            return groups[k:] + groups[:k]
        raise ValueError(group_order)

    for step in range(n_steps):
        waves = []
        for (lag, grp) in zip(lags, blocks):
            r = step - lag
            if 0 <= r < rounds:
                waves.append((r, list(grp)))
        if not waves:
            continue
        if wave_order == "rev":
            waves = list(reversed(waves))
        elif wave_order.startswith("rot:"):
            k = int(wave_order.split(":")[1]) * step % len(waves)
            waves = waves[k:] + waves[:k]
        elif wave_order != "default":
            raise ValueError(wave_order)

        if step >= df_from:
            # depth-first drain: for each group still unfinished (in wave
            # order), emit ALL its remaining rounds contiguously.
            for r, grp in waves:
                for g in order_groups(grp, step):
                    while emitted[g] < rounds:
                        plan.append((emitted[g], g))
                        emitted[g] += 1
            continue

        step_pairs: list[tuple[int, int]]
        if interleave == "zip":
            cols = [[(r, g) for g in order_groups(grp, step)] for r, grp in waves]
            step_pairs = [p for tup in itertools.zip_longest(*cols) for p in tup if p]
        else:
            step_pairs = [(r, g) for r, grp in waves for g in order_groups(grp, step)]

        if step in stage_rr:
            if stage_rr_scope == "step":
                plan.append(("rr", tuple(step_pairs)))
            else:  # per-wave rr
                for r, grp in waves:
                    plan.append(("rr", tuple((r, g) for g in order_groups(grp, step))))
        else:
            plan.extend(step_pairs)
        for r, grp in waves:
            for g in grp:
                emitted[g] += 1

    # validity is asserted again inside dev.py; sanity-check here for speed
    nr = {g: 0 for g in range(N_GROUPS)}
    for entry in plan:
        members = entry[1] if entry and entry[0] == "rr" else (entry,)
        for r, g in members:
            assert nr[g] == r, f"plan invalid at {(r, g)}"
            nr[g] += 1
    assert all(v == rounds for v in nr.values())
    return tuple(plan)


def flatten(plan: tuple[Any, ...]) -> list[Any]:
    return list(plan)


def _eval(args: tuple[dict[str, Any], tuple[Any, ...]]) -> tuple[int, bool]:
    overrides, plan = args
    over = dict(overrides)
    if plan:
        over["emission_plan"] = plan
    try:
        cycles, correct = measure(over, seed=1)
    except Exception:
        return (-1, False)
    return (cycles, correct)


class Runner:
    def __init__(self, overrides: dict[str, Any], workers: int, out_path: str):
        self.overrides = overrides
        self.pool = mp.Pool(workers)
        self.out = open(out_path, "a", buffering=1)
        self.best: tuple[int, dict[str, Any] | None, tuple[Any, ...] | None] = (10**9, None, None)
        self.n_evals = 0

    def run_batch(self, named: list[tuple[str, dict[str, Any], tuple[Any, ...]]]) -> list[tuple[str, int, bool]]:
        results = self.pool.map(_eval, [(self.overrides, plan) for _, _, plan in named])
        out = []
        for (name, params, plan), (cycles, correct) in zip(named, results):
            self.n_evals += 1
            rec = {"name": name, "params": params, "cycles": cycles, "correct": correct}
            self.out.write(json.dumps(rec) + "\n")
            if correct and cycles < self.best[0]:
                self.best = (cycles, params, plan)
                print(f"  NEW BEST {cycles} <- {name} {params}", flush=True)
                if plan is not None:
                    with open(self.out.name + ".best.json", "w") as f:
                        json.dump({"cycles": cycles, "params": params,
                                   "plan": [list(e) if e[0] != "rr" else ["rr", [list(p) for p in e[1]]] for e in plan]}, f)
            out.append((name, cycles, correct))
        return out


def phase1(budget: float, workers: int, out_path: str) -> None:
    r = Runner(FRONTIER_OVERRIDES, workers, out_path)
    t0 = time.time()

    base = [("baseline(default order)", {}, make_plan())]
    print("baseline:", r.run_batch(base), flush=True)

    axes: list[tuple[str, list[dict[str, Any]]]] = [
        ("wave_order", [{"wave_order": w} for w in ("rev", "rot:1", "rot:2")]),
        ("group_order", [{"group_order": g} for g in ("rev", "rot:1", "rot:2", "rot:3", "rot:4")]),
        ("interleave", [{"interleave": "zip"},
                         {"interleave": "zip", "wave_order": "rev"}]),
        ("stage_rr_tail", [{"stage_rr": tuple(range(25 - n, 25))} for n in (1, 2, 3)]),
        ("stage_rr_tail_wave", [{"stage_rr": tuple(range(25 - n, 25)), "stage_rr_scope": "wave"} for n in (1, 2, 3)]),
        ("stage_rr_ramp", [{"stage_rr": tuple(range(0, n))} for n in (1, 2, 3)]),
        ("stage_rr_all", [{"stage_rr": tuple(range(25))},
                           {"stage_rr": tuple(range(25)), "stage_rr_scope": "wave"}]),
        ("tail_df", [{"tail_df": n} for n in (1, 2, 3, 4, 5)]),
        ("tail_df_rev", [{"tail_df": n, "group_order": "rev"} for n in (1, 2, 3)]),
        ("lags", [{"lags": l} for l in (
            (0, 2, 5, 8), (0, 3, 6, 8), (0, 3, 5, 8), (0, 4, 7, 10),
            (0, 2, 4, 6), (0, 3, 6, 10), (0, 4, 6, 9), (0, 3, 7, 9),
            (1, 4, 7, 10), (0, 2, 6, 9), (0, 3, 6, 11))]),
        ("blocks8", [{"lags": (0, 1, 2, 3, 4, 5, 6, 7),
                       "blocks": [list(range(b * 4, (b + 1) * 4)) for b in range(8)]},
                      {"lags": (0, 2, 4, 6, 8, 10, 12, 14),
                       "blocks": [list(range(b * 4, (b + 1) * 4)) for b in range(8)]}]),
        ("blocks13", [{"lags": tuple(2 * i for i in range(13)),
                        "blocks": [list(range((32 * i) // 13, (32 * (i + 1)) // 13)) for i in range(13)]}]),
        ("blocks2", [{"lags": (0, 6), "blocks": [list(range(16)), list(range(16, 32))]},
                      {"lags": (0, 8), "blocks": [list(range(16)), list(range(16, 32))]}]),
    ]

    winners: list[dict[str, Any]] = []
    for axis, variants in axes:
        if time.time() - t0 > budget:
            print("budget exhausted", flush=True)
            break
        named = []
        for v in variants:
            try:
                named.append((f"{axis}:{v}", v, make_plan(**v)))
            except (AssertionError, ValueError) as e:
                print(f"  skip {axis}:{v} ({e})", flush=True)
        res = r.run_batch(named)
        print(f"axis {axis}: {[(n.split(':',1)[1], c, ok) for n, c, ok in res]}", flush=True)
        base_cycles = r.best[0]
        for (name, cycles, ok), (_, v, _) in zip(res, named):
            if ok and cycles <= base_cycles + 1:
                winners.append(v)

    # compose pairs of near-winning axis settings
    print(f"\ncomposing {len(winners)} near-winners...", flush=True)
    comps = []
    for a, b in itertools.combinations(winners, 2):
        if set(a) & set(b):
            continue
        v = dict(a, **b)
        try:
            comps.append((f"comp:{v}", v, make_plan(**v)))
        except (AssertionError, ValueError):
            pass
    for i in range(0, len(comps), 64):
        if time.time() - t0 > budget:
            break
        r.run_batch(comps[i:i + 64])

    print(f"\nphase1 done: {r.n_evals} evals, best {r.best[0]} params {r.best[1]}", flush=True)
    if r.best[2] is not None:
        with open(out_path + ".best.json", "w") as f:
            json.dump({"cycles": r.best[0], "params": r.best[1],
                       "plan": [list(e) if e[0] != "rr" else ["rr", [list(p) for p in e[1]]] for e in r.best[2]]}, f)


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


def local(budget: float, workers: int, out_path: str, seed_json: str | None,
          window: str = "both") -> None:
    """Window-restricted local search: move single (r,g) entries earlier/
    later past K positions when validity allows; restricted to the ramp
    (first ~120 entries) and drain (last ~120 entries)."""
    r = Runner(FRONTIER_OVERRIDES, workers, out_path)
    plan = load_plan(seed_json) if seed_json else make_plan()
    start = _eval((FRONTIER_OVERRIDES, plan))
    print(f"local start: {start}", flush=True)
    best_c = start[0]
    r.best = (best_c, {"seed": seed_json}, plan)
    rng = random.Random(int(os.environ.get("EOS_SEED", "0")))
    t0 = time.time()

    def valid(p: list[Any]) -> bool:
        nr = {g: 0 for g in range(N_GROUPS)}
        for entry in p:
            members = entry[1] if entry and entry[0] == "rr" else (entry,)
            for rr_, gg_ in members:
                if nr[gg_] != rr_:
                    return False
                nr[gg_] += 1
        return all(v == ROUNDS for v in nr.values())

    cur = list(plan)
    cur_c = best_c
    n = len(cur)
    while time.time() - t0 < budget:
        batch = []
        for _ in range(workers * 8):
            p = list(cur)
            if window == "ramp":
                i = rng.randrange(0, min(120, n))
            elif window == "drain":
                i = rng.randrange(max(0, n - 120), n)
            elif window == "mid":
                i = rng.randrange(min(120, n // 3), max(n - 120, 2 * n // 3))
            elif window == "all":
                i = rng.randrange(0, n)
            else:
                i = (rng.randrange(0, min(120, n)) if rng.random() < 0.5
                     else rng.randrange(max(0, n - 120), n))
            j = i + rng.choice((-8, -4, -2, -1, 1, 2, 4, 8))
            if not (0 <= j < n):
                continue
            e = p.pop(i)
            p.insert(j, e)
            if valid(p):
                batch.append((f"move {i}->{j}", {"i": i, "j": j}, tuple(p)))
        if not batch:
            continue
        res = r.run_batch(batch)
        improved = [(c, plan_) for (name, c, ok), (_, _, plan_) in zip(res, batch)
                    if ok and c < cur_c]
        sideways = [(c, plan_) for (name, c, ok), (_, _, plan_) in zip(res, batch)
                    if ok and c == cur_c]
        if improved:
            cur_c, best_plan = min(improved, key=lambda t: t[0])
            cur = list(best_plan)
            print(f"  local: descended to {cur_c}", flush=True)
        elif sideways and rng.random() < 0.7:
            cur = list(rng.choice(sideways)[1])
        print(f"  local block: cur {cur_c}, best {r.best[0]}, evals {r.n_evals}, t={time.time()-t0:.0f}s", flush=True)
    if r.best[2] is not None:
        with open(out_path + ".best.json", "w") as f:
            json.dump({"cycles": r.best[0], "params": r.best[1],
                       "plan": [list(e) if e[0] != "rr" else ["rr", [list(p) for p in e[1]]] for e in r.best[2]]}, f)
    print(f"local done: best {r.best[0]}", flush=True)


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["phase1", "local"])
    ap.add_argument("--budget", type=float, default=1800)
    ap.add_argument("--workers", type=int, default=max(2, os.cpu_count() // 2))
    ap.add_argument("--seed-json", default=None)
    ap.add_argument("--window", default="both")
    ap.add_argument("--out", default=os.environ.get(
        "EOS_OUT", os.path.join(REPO_ROOT, "tools", "eos_results.jsonl")))
    args = ap.parse_args()
    if args.mode == "phase1":
        phase1(args.budget, args.workers, args.out)
    else:
        local(args.budget, args.workers, args.out, args.seed_json, args.window)


if __name__ == "__main__":
    main()
