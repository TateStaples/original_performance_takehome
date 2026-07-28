#!/usr/bin/env python3
"""F-39: re-test the PACKING axis at the 1006 stream.

Wrapper around tools/backtrack_sched.py (unmodified) that patches its
H51_OVERRIDES to the current 1006 mainline-equivalent dev config
(tools/h057_best_plan_1006.json: F-24 organization emission_plan +
re-mined 20-ring parity plan + l4_gmin (6,31)) and re-runs G-25's
measurement + search battery on THIS stream.

Usage:
    python3 tools/f39_pack.py measure
    python3 tools/f39_pack.py capture
    python3 tools/f39_pack.py validate
    python3 tools/f39_pack.py regret
    python3 tools/f39_pack.py bound
    python3 tools/f39_pack.py probe
    python3 tools/f39_pack.py disc1 --delays 1,2 [--start I --end J]
    python3 tools/f39_pack.py pairs --budget S
    python3 tools/f39_pack.py triples --budget S
    python3 tools/f39_pack.py verify
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import random
import sys
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import backtrack_sched as bs  # noqa: E402

PLAN_JSON = os.path.join(REPO_ROOT, "tools", "h057_best_plan_1006.json")
SCRATCH = bs.SCRATCH_DIR
CAPTURE_PATH = os.path.join(SCRATCH, "f39_capture.pkl")


def _tup(v):
    if isinstance(v, list):
        return tuple(_tup(x) for x in v)
    return v


def build_overrides() -> dict[str, Any]:
    with open(PLAN_JSON) as f:
        data = json.load(f)
    mix = data["params"]["mix"]
    over: dict[str, Any] = {k: _tup(v) for k, v in mix.items()}
    plan = []
    for e in data["plan"]:
        if e[0] == "rr":
            plan.append(("rr", tuple(tuple(p) for p in e[1])))
        else:
            plan.append(tuple(e))
    over["emission_plan"] = tuple(plan)
    return over


OVERRIDES = build_overrides()
bs.H51_OVERRIDES = OVERRIDES
bs.CAPTURE_PATH = CAPTURE_PATH


def load():
    with open(CAPTURE_PATH, "rb") as f:
        data = pickle.load(f)
    ops = data["ops"]
    preds, floors = bs.build_model(ops, data["pair_writes"])
    return data, ops, preds, floors


def energetic_bound(ops, preds, floors, lo=850, hi=1010) -> int:
    est = bs.ests(ops, preds, floors)
    h = bs.tails(ops, preds)

    def feasible(C: int) -> bool:
        for e in bs.ENGINES:
            cap = bs.SLOT_LIMITS[e]
            pts = [(est[i], C - 1 - h[i]) for i in range(len(ops))
                   if ops[i][0] == e]
            if not pts:
                continue
            if any(d < r for r, d in pts):
                return False
            t1s = sorted({r for r, _ in pts})
            for t1 in t1s:
                dls = sorted(d for r, d in pts if r >= t1)
                for k, t2 in enumerate(dls, 1):
                    if k > (t2 - t1 + 1) * cap:
                        return False
        return True

    while not feasible(hi):
        hi += 8
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def jump_cycles(ops, preds, floors, place):
    F, eng, cp = bs.regret_profile(ops, preds, floors, place)
    jumps = []
    prev = 0
    for c in range(len(F)):
        if F[c] > prev and c > 0:
            jumps.append(c)
        prev = max(prev, F[c])
    return jumps, F, eng, cp


def save_incumbent(tag, cycles, floors_map, place):
    p = os.path.join(SCRATCH, f"f39_incumbent_{tag}.pkl")
    with open(p, "wb") as f:
        pickle.dump({"cycles": cycles, "floors": floors_map, "place": place}, f)
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--delays", default="1,2")
    ap.add_argument("--budget", type=float, default=600.0)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--end", type=int, default=-1)
    ap.add_argument("--engines", default="valu,load,flow,alu,store")
    ap.add_argument("--radius", type=int, default=3)
    ap.add_argument("--trials", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.cmd == "measure":
        from run_variant import measure
        t0 = time.time()
        c, ok = measure(OVERRIDES)
        print(json.dumps({"cycles": c, "correct": ok,
                          "secs": round(time.time() - t0, 1)}))
        return

    if args.cmd == "capture":
        t0 = time.time()
        data = bs.capture()
        with open(CAPTURE_PATH, "wb") as f:
            pickle.dump(data, f)
        print(json.dumps({"ops": len(data["ops"]), "n_cycles": data["n_cycles"],
                          "span": data["span"],
                          "pair_writes": data["pair_writes"],
                          "secs": round(time.time() - t0, 1),
                          "path": CAPTURE_PATH}))
        return

    data, ops, preds, floors = load()
    place0 = [op[9] for op in ops]

    if args.cmd == "validate":
        place, nonempty = bs.greedy_schedule(ops, preds, floors)
        mism = [i for i in range(len(ops)) if place[i] != place0[i]]
        print(json.dumps({
            "ops": len(ops), "offline_cycles": nonempty,
            "captured_cycles": data["n_cycles"],
            "exact_match": not mism, "n_mismatch": len(mism),
            "first_mismatches": [(i, place0[i], place[i], ops[i][0],
                                  ops[i][1][0]) for i in mism[:8]],
        }, default=str))
        return

    if args.cmd == "bound":
        lb = bs.lb_total(ops, preds, floors)
        print("LB(total):", json.dumps(lb))
        est = bs.ests(ops, preds, floors)
        h = bs.tails(ops, preds)
        for name, key in (("release(est)", est), ("tail(h)", h)):
            best_v, best_at = 0, None
            for e in bs.ENGINES:
                vals = sorted((key[i] for i in range(len(ops))
                               if ops[i][0] == e), reverse=True)
                for cnt, t in enumerate(vals, 1):
                    v = t + -(-cnt // bs.SLOT_LIMITS[e])
                    if v > best_v:
                        best_v, best_at = v, (e, t, cnt)
            print(f"staircase [{name}]: {best_v} at {best_at}")
        t0 = time.time()
        eb = energetic_bound(ops, preds, floors)
        fb = bs.fungible_lb(ops)
        print(json.dumps({"energetic_interval_LB": eb, "fungible_LB": fb,
                          "realized": max(place0) + 1,
                          "open_window": max(place0) + 1 - eb,
                          "secs": round(time.time() - t0, 1)}))
        return

    if args.cmd == "regret":
        jumps, F, eng, cp = jump_cycles(ops, preds, floors, place0)
        lb = bs.lb_total(ops, preds, floors)
        print(f"total {max(place0)+1}  LB {lb['lb']}  engines {lb['engine']} "
              f"cp {lb['cp']}  regret {max(place0)+1-lb['lb']}")
        prev = lb["lb"]
        for c in range(len(F)):
            if F[c] > prev:
                tagset = sorted({ops[i][10][0] for i in range(len(ops))
                                 if place0[i] == c and ops[i][10]})
                print(f"  c={c:>4} +{F[c]-prev} F={F[c]} engLB={eng[c]} "
                      f"cpLB={cp[c]} rounds={tagset}")
            prev = max(prev, F[c])
        with open(os.path.join(SCRATCH, "f39_jumps.json"), "w") as f:
            json.dump(jumps, f)
        print("jumps:", jumps)
        return

    if args.cmd == "probe":
        h = bs.tails(ops, preds)
        est = bs.ests(ops, preds, floors)
        p, n0 = bs.greedy_schedule(ops, preds, floors)
        print(f"greedy emission order: {n0}")
        for name, pr in [
            ("tail_height", h),
            ("est+tail (CP)", [e + t for e, t in zip(est, h)]),
            ("neg emission (reverse)", [-i for i in range(len(ops))]),
            ("emission (forward)", list(range(len(ops)))),
        ]:
            t0 = time.time()
            place, n = bs.priority_schedule(ops, preds, floors, pr)
            ok = bs.check_feasible(ops, preds, floors, place)
            print(f"priority {name}: {n} cycles feasible={ok} "
                  f"({time.time()-t0:.1f}s)", flush=True)
        return

    base = max(place0) + 1

    if args.cmd == "disc1":
        delays = [int(x) for x in args.delays.split(",")]
        end = len(ops) if args.end < 0 else min(args.end, len(ops))
        t0 = time.time()
        best = base
        tried = 0
        hits = []
        for i in range(args.start, end):
            for d in delays:
                place, n = bs.greedy_schedule(ops, preds, floors,
                                              extra_floors={i: place0[i] + d},
                                              limit=None)
                tried += 1
                if n is not None and n < best:
                    best = n
                    hits.append((i, d, n))
                    save_incumbent("disc1", n, {i: place0[i] + d}, place)
                    print(f"  IMPROVED -> {n} op={i} d={d}", flush=True)
            if (i - args.start) % 2000 == 1999:
                print(f"  ...{i - args.start + 1} ops, {tried} trials, "
                      f"{time.time()-t0:.0f}s, best {best}", flush=True)
        print(json.dumps({"tier": "disc1", "range": [args.start, end],
                          "delays": delays, "trials": tried, "best": best,
                          "baseline": base, "hits": hits,
                          "secs": round(time.time() - t0, 1)}))
        return

    if args.cmd == "pairs":
        jumps, _, _, _ = jump_cycles(ops, preds, floors, place0)
        engset = set(args.engines.split(","))
        rad = args.radius
        t0 = time.time()
        best, tried = base, 0
        hits = []
        for jc in jumps:
            cand = [i for i in range(len(ops))
                    if abs(place0[i] - jc) <= rad and ops[i][0] in engset]
            print(f"jump c={jc}: {len(cand)} candidates "
                  f"({time.time()-t0:.0f}s, tried {tried})", flush=True)
            done = False
            for ai in range(len(cand)):
                if time.time() - t0 > args.budget:
                    print("budget exhausted", flush=True)
                    done = True
                    break
                i = cand[ai]
                for bi in range(ai + 1, len(cand)):
                    j = cand[bi]
                    for di in (1, 2):
                        for dj in (1, 2):
                            trial = {i: place0[i] + di, j: place0[j] + dj}
                            place, n = bs.greedy_schedule(
                                ops, preds, floors, extra_floors=trial)
                            tried += 1
                            if n is not None and n < best:
                                best = n
                                hits.append((trial, n))
                                save_incumbent("pairs", n, trial, place)
                                print(f"  IMPROVED -> {n} {trial}", flush=True)
            if done:
                break
        print(json.dumps({"tier": "pairs", "radius": rad, "jumps": jumps,
                          "trials": tried, "best": best, "baseline": base,
                          "hits": hits, "secs": round(time.time() - t0, 1)}))
        return

    if args.cmd == "triples":
        jumps, _, _, _ = jump_cycles(ops, preds, floors, place0)
        engset = set(args.engines.split(","))
        rng = random.Random(args.seed)
        pool = [i for i in range(len(ops))
                if ops[i][0] in engset and
                any(abs(place0[i] - jc) <= 8 for jc in jumps)]
        print(f"triple pool: {len(pool)} ops near {len(jumps)} jumps",
              flush=True)
        t0 = time.time()
        best, tried = base, 0
        hits = []
        while tried < args.trials and time.time() - t0 < args.budget:
            a, b, c = rng.sample(pool, 3)
            trial = {a: place0[a] + rng.randint(1, 2),
                     b: place0[b] + rng.randint(1, 2),
                     c: place0[c] + rng.randint(1, 2)}
            place, n = bs.greedy_schedule(ops, preds, floors,
                                          extra_floors=trial)
            tried += 1
            if n is not None and n < best:
                best = n
                hits.append((trial, n))
                save_incumbent("triples", n, trial, place)
                print(f"  IMPROVED -> {n} {trial}", flush=True)
            if tried % 2000 == 0:
                print(f"  ...{tried} trials {time.time()-t0:.0f}s best {best}",
                      flush=True)
        print(json.dumps({"tier": "triples", "pool": len(pool),
                          "trials": tried, "best": best, "baseline": base,
                          "hits": hits, "secs": round(time.time() - t0, 1)}))
        return

    if args.cmd == "verify":
        place = place0
        src = "greedy(identity)"
        for tag in ("disc1", "pairs", "triples"):
            p = os.path.join(SCRATCH, f"f39_incumbent_{tag}.pkl")
            if os.path.exists(p):
                with open(p, "rb") as f:
                    inc = pickle.load(f)
                if inc["cycles"] < max(place) + 1:
                    place = inc["place"]
                    src = f"incumbent-{tag}({inc['cycles']})"
        ok = bs.check_feasible(ops, preds, floors, place)
        print(f"source: {src}  feasible={ok}")
        res = bs.reconstruct_and_verify(ops, place)
        print(json.dumps(res))
        return

    raise SystemExit(f"unknown cmd {args.cmd}")


if __name__ == "__main__":
    main()
