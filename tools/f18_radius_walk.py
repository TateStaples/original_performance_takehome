"""F-18: escalated-radius emission-order walk (F-13 successor).

F-13 established that the productive axis of the emission-order local
search is the JUMP RADIUS, not the restart seed: re-running H-049's
+-8 move set under fresh seeds found zero over 62k evals, while walks
that added +-16/+-32 descended 1023 -> 1020 / 1022 -> 1020.  The
evidence therefore only covers radius <= 32.  This driver escalates:

  jump   single entry displaced by +-d for d in --jumps (64/128/...)
  free   single entry re-inserted UNIFORMLY inside its own maximal
         feasible interval (between its round-neighbours of the same
         group) -- the unbounded-radius move; always validity-feasible,
         so it does not waste evals the way long fixed jumps do
  comp2  two independent single moves applied to one candidate
  pairg  two CONSECUTIVE entries of the SAME group displaced together
         (the barrier to a long single move is the group's own next
         entry, so this is the compound move that lifts the radius cap)
  block  a contiguous run of 2..4 plan entries displaced as a unit

`tools/emission_order_search.py` is imported read-only (its `_eval`,
`FRONTIER_OVERRIDES` and `_tuplify` are reused verbatim) so that driver
stays untouched for concurrent agents.

Usage (repo root):
  python3 tools/f18_radius_walk.py --seed-json tools/f13_best_plan_1020.json \\
      --moves jump --jumps 1,2,4,8,16,32,64 --budget 540 --seed 1801
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import sys
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402

ROUNDS, N_GROUPS = eos.ROUNDS, eos.N_GROUPS


def load_seed(path: str) -> tuple[dict[str, Any], list[tuple[int, int]]]:
    """Load a plan artifact; returns (config overrides, flat plan)."""
    with open(path) as f:
        data = json.load(f)
    cfg = dict(eos.FRONTIER_OVERRIDES)
    for k, v in (data.get("config_overrides") or {}).items():
        cfg[k] = eos._tuplify(v)
    plan = []
    for e in data["plan"]:
        assert e and e[0] != "rr", "F-18 walker handles plain (r,g) plans only"
        plan.append((int(e[0]), int(e[1])))
    return cfg, plan


def valid(p: list[tuple[int, int]]) -> bool:
    nr = [0] * N_GROUPS
    for r, g in p:
        if nr[g] != r:
            return False
        nr[g] += 1
    return all(v == ROUNDS for v in nr)


def positions(p: list[tuple[int, int]]) -> list[list[int]]:
    d: list[list[int]] = [[] for _ in range(N_GROUPS)]
    for i, (_, g) in enumerate(p):
        d[g].append(i)
    return d


def _reinsert(p: list[tuple[int, int]], i: int, j: int) -> list[tuple[int, int]]:
    q = list(p)
    e = q.pop(i)
    q.insert(j, e)
    return q


# ---------------------------------------------------------------- moves


def mv_jump(p, rng, jumps):
    n = len(p)
    i = rng.randrange(n)
    j = i + rng.choice(jumps)
    if not (0 <= j < n):
        return None
    return _reinsert(p, i, j), f"jump {i}->{j}"


def mv_free(p, rng, jumps):
    """Re-insert one entry anywhere inside its maximal feasible interval."""
    n = len(p)
    i = rng.randrange(n)
    r, g = p[i]
    gp = positions(p)[g]
    lo = gp[r - 1] + 1 if r > 0 else 0
    hi = gp[r + 1] - 1 if r + 1 < ROUNDS else n - 1
    if hi <= lo:
        return None
    t = rng.randrange(lo, hi + 1)
    if t == i:
        return None
    j = t - 1 if t > i else t
    return _reinsert(p, i, j), f"free {i}->{j} (span {hi - lo})"


def mv_comp2(p, rng, jumps):
    """Two independent single moves in one candidate (F-13's queued compound)."""
    a = mv_jump(p, rng, jumps) or mv_free(p, rng, jumps)
    if a is None:
        return None
    q, na = a
    b = mv_free(q, rng, jumps) if rng.random() < 0.5 else mv_jump(q, rng, jumps)
    if b is None:
        return None
    return b[0], f"comp2 [{na}][{b[1]}]"


def mv_pairg(p, rng, jumps):
    """Displace two consecutive same-group entries together.

    A single entry cannot travel past its own group's next entry; moving
    the pair as a unit removes exactly that barrier, so this is the move
    that raises the effective radius rather than the nominal one.
    """
    g = rng.randrange(N_GROUPS)
    gp = positions(p)[g]
    r = rng.randrange(ROUNDS - 1)
    i1, i2 = gp[r], gp[r + 1]
    d = rng.choice(jumps)
    n = len(p)
    if not (0 <= i1 + d < n and 0 <= i2 + d < n):
        return None
    rest = [e for k, e in enumerate(p) if k not in (i1, i2)]
    e1, e2 = p[i1], p[i2]
    j1, j2 = sorted((i1 + d, i2 + d))
    j1 = min(max(j1, 0), len(rest))
    j2 = min(max(j2, 0), len(rest) + 1)
    q = list(rest)
    q.insert(j1, e1)
    q.insert(j2, e2)
    return q, f"pairg g{g} r{r} d{d}"


def mv_block(p, rng, jumps):
    """Displace a contiguous run of 2..4 entries as a unit."""
    n = len(p)
    L = rng.randrange(2, 5)
    i = rng.randrange(0, n - L)
    d = rng.choice(jumps)
    j = i + d
    if not (0 <= j <= n - L):
        return None
    seg = p[i:i + L]
    rest = p[:i] + p[i + L:]
    q = rest[:j] + seg + rest[j:]
    return q, f"block L{L} {i}->{j}"


MOVES = {"jump": mv_jump, "free": mv_free, "comp2": mv_comp2,
         "pairg": mv_pairg, "block": mv_block}


# ---------------------------------------------------------------- walk


def walk(args: argparse.Namespace) -> None:
    cfg, seed_plan = load_seed(args.seed_json)
    kinds: list[str] = []
    for tok in args.moves.split(","):
        name, _, w = tok.partition(":")
        kinds += [name] * int(w or 1)
    for k in kinds:
        assert k in MOVES, k
    jumps = tuple(int(x) for x in args.jumps.split(","))
    jumps = tuple(sorted(set(jumps) | {-j for j in jumps}))
    rng = random.Random(args.seed)

    pool = mp.Pool(args.workers)
    out = open(args.out, "a", buffering=1)
    start_c, start_ok = eos._eval((cfg, tuple(seed_plan)))
    print(f"seed {args.seed_json}: {start_c} correct={start_ok} "
          f"moves={args.moves} jumps={jumps} rng={args.seed}", flush=True)
    assert start_ok, "seed plan is incorrect"

    cur = list(seed_plan)
    cur_c = start_c
    best_c, best_plan = start_c, list(seed_plan)
    n_evals = 0
    tried_bad = 0
    per_kind: dict[str, int] = {}
    stale = 0
    t0 = time.time()

    while time.time() - t0 < args.budget:
        batch: list[tuple[str, str, list[tuple[int, int]]]] = []
        seen: set[tuple] = set()
        guard = 0
        while len(batch) < args.workers * 8 and guard < args.workers * 200:
            guard += 1
            kind = rng.choice(kinds)
            res = MOVES[kind](cur, rng, jumps)
            if res is None:
                tried_bad += 1
                continue
            q, name = res
            if not valid(q):
                tried_bad += 1
                continue
            key = tuple(q)
            if key in seen:
                continue
            seen.add(key)
            batch.append((kind, name, q))
        if not batch:
            continue
        results = pool.map(eos._eval, [(cfg, tuple(q)) for _, _, q in batch])
        n_evals += len(batch)
        improved: list[tuple[int, list]] = []
        sideways: list[tuple[int, list]] = []
        for (kind, name, q), (c, ok) in zip(batch, results):
            per_kind[kind] = per_kind.get(kind, 0) + 1
            out.write(json.dumps({"kind": kind, "name": name, "cycles": c,
                                  "correct": ok}) + "\n")
            if not ok:
                continue
            if c < cur_c:
                improved.append((c, q))
            elif c == cur_c:
                sideways.append((c, q))
            if c < best_c:
                best_c, best_plan = c, list(q)
                print(f"  NEW BEST {c} <- {kind} / {name}", flush=True)
                save(args.out + ".best.json", best_c, best_plan, cfg, args)
        if improved:
            cur_c, cur = min(improved, key=lambda t: t[0])
            cur = list(cur)
            stale = 0
            print(f"  descended to {cur_c}", flush=True)
        else:
            stale += 1
            if sideways and rng.random() < 0.7:
                cur = list(rng.choice(sideways)[1])
            elif args.restart_after and stale >= args.restart_after:
                cur, cur_c, stale = list(best_plan), best_c, 0
        print(f"  block: cur {cur_c} best {best_c} evals {n_evals} "
              f"rej {tried_bad} t={time.time()-t0:.0f}s", flush=True)

    print(f"DONE best={best_c} evals={n_evals} rejected_moves={tried_bad} "
          f"per_kind={per_kind} t={time.time()-t0:.0f}s", flush=True)
    save(args.out + ".best.json", best_c, best_plan, cfg, args)
    # The order landscape is plateau-dominated (most single moves measure
    # exactly cur_c), so the walk's progress is largely its sideways drift
    # position.  Checkpoint it so a chained round continues the same walk
    # instead of restarting from the seed.
    save(args.out + ".cur.json", cur_c, cur, cfg, args)


def save(path: str, cycles: int, plan: list[tuple[int, int]],
         cfg: dict[str, Any], args: argparse.Namespace) -> None:
    with open(path, "w") as f:
        json.dump({
            "hypothesis": "F-18",
            "date": "2026-07-27",
            "cycles": cycles,
            "config_overrides": {k: v for k, v in cfg.items()},
            "note": (f"F-18 radius escalation; seed={args.seed_json} "
                     f"moves={args.moves} jumps={args.jumps} rng={args.seed}"),
            "plan": [list(e) for e in plan],
        }, f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--moves", default="jump")
    ap.add_argument("--jumps", default="1,2,4,8,16,32,64")
    ap.add_argument("--budget", type=float, default=540)
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4)))
    ap.add_argument("--seed", type=int, default=1801)
    ap.add_argument("--restart-after", type=int, default=40)
    ap.add_argument("--out", required=True)
    walk(ap.parse_args())


if __name__ == "__main__":
    main()
