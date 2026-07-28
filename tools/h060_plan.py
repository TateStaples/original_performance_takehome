"""H-060 step 2/3: OFFLINE-SEARCHED per-site alu/valu partition.

The crisp form of the hypothesis. Start from the plan the retire-race itself
produces (verified in tools/h060_verify.py to replay 1006 bit-for-bit), then
ask whether any single-site reassignment improves it, and descend greedily
if so. If every single flip is >= 0 the race's assignment is a local optimum
of the partition landscape and the axis closes.

Modes:
  scan    evaluate every single-site flip from the incumbent, report the
          delta distribution and the best flips
  greedy  repeat `scan`, committing the best improving flip each round
          (multi-flip descent)

Usage:
  python3 tools/h060_plan.py scan   [--sites CLASS] [--workers N]
  python3 tools/h060_plan.py greedy [--rounds R] [--workers N]
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import os
import sys
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402

SCRATCH = os.environ.get(
    "H060_OUT",
    "/private/tmp/claude-501/-Users-tatestaples-Code-original-performance-takehome"
    "/5cfbd141-00dc-4755-aaa3-3deea70ab9f0/scratchpad")


def race_log() -> list[list[Any]]:
    """(site, op, kind, r_alu, r_valu, winner, ready) for the incumbent."""
    import dev
    import h060_race as R
    R.LOG.clear()
    orig = dev.KernelBuilder._sched_vec
    dev.KernelBuilder._sched_vec = R.logging_sched_vec  # type: ignore
    try:
        C.build(C.frontier())
    finally:
        dev.KernelBuilder._sched_vec = orig  # type: ignore
    return [list(r) for r in R.LOG]


def race_plan(log: list[list[Any]]) -> list[str]:
    return ["a" if r[5] == "alu" else "v" for r in log]


_BASE_PLAN: list[str] = []


def _init(plan: list[str]) -> None:
    global _BASE_PLAN
    _BASE_PLAN = plan


def _eval(site: int) -> tuple[int, int]:
    plan = list(_BASE_PLAN)
    plan[site] = "v" if plan[site] == "a" else "a"
    cfg = C.frontier(vec_partition_plan=tuple(enumerate(plan)))
    try:
        _, prog = C.build(cfg)
        return site, len(prog)
    except Exception:
        return site, 10 ** 6


def scan(plan: list[str], sites: list[int], workers: int
         ) -> list[tuple[int, int]]:
    t0 = time.time()
    with mp.Pool(workers, initializer=_init, initargs=(plan,)) as pool:
        out = []
        for i, res in enumerate(pool.imap_unordered(_eval, sites, chunksize=8)):
            out.append(res)
            if (i + 1) % 400 == 0:
                print(f"    ... {i+1}/{len(sites)} "
                      f"({time.time()-t0:.0f}s)", flush=True)
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["scan", "greedy", "plateau"])
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--start", default="", help="JSON with a 'plan' key")
    ap.add_argument("--out", default="h060_plateau.json")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4)))
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--sites", default="all",
                    choices=["all", "race", "free", "forced", "tie"])
    args = ap.parse_args()

    log = race_log()
    plan = race_plan(log)
    cfg = C.frontier(vec_partition_plan=tuple(enumerate(plan)))
    _, prog = C.build(cfg)
    incumbent = len(prog)
    print(f"incumbent replay: {incumbent} bundles over {len(plan)} sites "
          f"({plan.count('a')} alu / {plan.count('v')} valu)")
    assert incumbent == 1006

    def pick(kind_filter) -> list[int]:
        return [r[0] for r in log if kind_filter(r)]

    sel = {
        "all": lambda r: True,
        "race": lambda r: r[2] == "race",
        "free": lambda r: r[2] == "valu_free",
        "forced": lambda r: r[2] == "forced",
        "tie": lambda r: r[2] == "valu_free" and r[4] == r[3],
    }[args.sites]
    sites = pick(sel)
    print(f"candidate sites ({args.sites}): {len(sites)}")

    if args.mode == "scan":
        res = scan(plan, sites, args.workers)
        hist = collections.Counter(c - incumbent for _s, c in res)
        print("single-flip delta histogram:")
        for d in sorted(hist):
            print(f"   {d:+5d}: {hist[d]:6d}")
        best = sorted(res, key=lambda t: t[1])[:20]
        print("best flips:")
        kind = {r[0]: (r[2], r[1], r[5], r[3], r[4]) for r in log}
        for s, c in best:
            print(f"   site {s:5d} {kind[s]} -> {c} ({c-incumbent:+d})")
        with open(os.path.join(SCRATCH, "h060_scan.json"), "w") as f:
            json.dump({"incumbent": incumbent, "res": res}, f)
        n_neg = sum(v for k, v in hist.items() if k < 0)
        print(f"\nimproving single flips: {n_neg} / {len(res)}")
        return

    if args.mode == "plateau":
        # Single flips cannot improve, but many are NEUTRAL. Walk the neutral
        # plateau (accept any flip that does not raise the cycle count),
        # accumulating a large multi-flip move, then re-scan for improving
        # single flips from the new point. Repeats until nothing changes.
        import random
        rng = random.Random(args.seed)
        cur = list(plan)
        if args.start:
            with open(args.start) as f:
                cur = list(json.load(f)["plan"])
            assert len(cur) == len(plan)
        _, p0 = C.build(C.frontier(vec_partition_plan=tuple(enumerate(cur))))
        cur_cyc = len(p0)
        print(f"start point: {cur_cyc}", flush=True)
        for rnd in range(args.rounds):
            res = scan(cur, sites, args.workers)
            neutral = [s for s, c in res if c <= cur_cyc]
            best_s, best_c = min(res, key=lambda t: t[1])
            print(f"round {rnd}: {len(neutral)} neutral, best single "
                  f"{best_c} ({best_c-cur_cyc:+d})", flush=True)
            if best_c < cur_cyc:
                cur[best_s] = "v" if cur[best_s] == "a" else "a"
                cur_cyc = best_c
                print(f"   committed improving flip {best_s} -> {cur_cyc}")
                continue
            rng.shuffle(neutral)
            n_taken = 0
            for s in neutral:
                trial = list(cur)
                trial[s] = "v" if trial[s] == "a" else "a"
                _, prog2 = C.build(C.frontier(
                    vec_partition_plan=tuple(enumerate(trial))))
                if len(prog2) <= cur_cyc:
                    cur = trial
                    if len(prog2) < cur_cyc:
                        print(f"   IMPROVED via plateau to {len(prog2)}")
                    cur_cyc = len(prog2)
                    n_taken += 1
            print(f"   plateau walk accepted {n_taken}/{len(neutral)} flips, "
                  f"now {cur_cyc} ({cur.count('a')} alu / "
                  f"{cur.count('v')} valu)", flush=True)
            with open(os.path.join(SCRATCH, args.out), "w") as f:
                json.dump({"cycles": cur_cyc, "plan": cur, "round": rnd}, f)
            if n_taken == 0:
                break
        print(f"final: {cur_cyc}")
        cyc, ok = C.measure(C.frontier(
            vec_partition_plan=tuple(enumerate(cur))))
        print(f"graded: {cyc} correct={ok}")
        return

    # greedy descent
    cur = list(plan)
    cur_cyc = incumbent
    trail: list[dict[str, Any]] = []
    for rnd in range(args.rounds):
        res = scan(cur, sites, args.workers)
        s, c = min(res, key=lambda t: t[1])
        print(f"round {rnd}: best flip site {s} -> {c} ({c-cur_cyc:+d})")
        if c >= cur_cyc:
            print("no improving flip; local optimum")
            break
        cur[s] = "v" if cur[s] == "a" else "a"
        cur_cyc = c
        trail.append({"round": rnd, "site": s, "cycles": c})
        with open(os.path.join(SCRATCH, "h060_greedy.json"), "w") as f:
            json.dump({"cycles": cur_cyc, "plan": cur, "trail": trail}, f)
    print(f"final: {cur_cyc}")
    cyc, ok = C.measure(C.frontier(vec_partition_plan=tuple(enumerate(cur))))
    print(f"graded: {cyc} correct={ok}")


if __name__ == "__main__":
    main()
