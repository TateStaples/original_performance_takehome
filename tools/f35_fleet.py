"""F-35: run a fleet of independent audit-aware chains (f35_loop) in
parallel, one process per chain with a single sim worker each, and report
the best CLEAN point found.  H-057's lesson: many fresh re-seeded chains
beat one long chain.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.environ.get(
    "F34_SCRATCH",
    "/private/tmp/claude-501/-Users-tatestaples-Code-original-performance-takehome/"
    "5cfbd141-00dc-4755-aaa3-3deea70ab9f0/scratchpad")

# Windows ranked by the F-34 productivity map (descent from a common 1015
# start, ~1200 evals each): drain -6, all -6, r:12-13/r:13-15/r:14-15/
# r:15-15 -5, both/r:11-15/r:8-15 -4, r:0-7/r:5-10/r:11-11 -3,
# r:0-4/mid/ramp/r:0-0 0.  Lanes are weighted toward the epoch-1 tail.
LANES = [
    dict(jumps="1,2,4,8", windows="drain,r:15-15,r:14-15", kick=3, ops="kick,walk,remine"),
    dict(jumps="1,2,4,8,16,32", windows="all,drain,r:12-13", kick=4, ops="kick,walk,remine"),
    dict(jumps="1,3,6,12,24", windows="r:13-15,r:15-15,drain", kick=2, ops="remine,walk,kick"),
    dict(jumps="1,2,4,8,16,32,64", windows="all,drain,both", kick=6, ops="kick,walk"),
    dict(jumps="1,2,3,5,8,13", windows="r:12-13,r:14-15,r:8-15", kick=3, ops="kick,gmin,walk,remine"),
    dict(jumps="2,4,8,16", windows="drain,all,r:13-15", kick=5, ops="kick,remine,walk"),
    dict(jumps="1,2,4,8,16", windows="r:15-15,r:12-13,drain,all", kick=2, ops="walk,remine,kick"),
    dict(jumps="1,4,16,64", windows="all,drain,r:14-15", kick=8, ops="kick,walk"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", action="append", required=True)
    ap.add_argument("--budget", type=float, default=420)
    ap.add_argument("--branch", type=float, default=90)
    ap.add_argument("--lanes", type=int, default=8)
    ap.add_argument("--rng0", type=int, default=1000)
    ap.add_argument("--tag", default="F")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    outdir = os.path.join(SCRATCH, f"f35_{args.tag}")
    os.makedirs(outdir, exist_ok=True)
    procs = []
    for i in range(args.lanes):
        lane = LANES[i % len(LANES)]
        seed = args.seed_json[i % len(args.seed_json)]
        best = os.path.join(outdir, f"lane{i}_best.json")
        if not args.resume and os.path.exists(best):
            os.unlink(best)
        log = open(os.path.join(outdir, f"lane{i}.log"), "a")
        cmd = [sys.executable, os.path.join(REPO_ROOT, "tools", "f35_loop.py"),
               "--seed-json", seed, "--best-out", best,
               "--budget", str(args.budget), "--branch", str(args.branch),
               "--workers", "1", "--rng", str(args.rng0 + i),
               "--jumps", lane["jumps"], "--windows", lane["windows"],
               "--ops", lane["ops"], "--kick", str(lane["kick"]),
               "--log", os.path.join(outdir, "chains.jsonl")]
        procs.append((i, lane, seed, best, log,
                      subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=log,
                                       stderr=subprocess.STDOUT)))
    t0 = time.time()
    for _, _, _, _, log, p in procs:
        p.wait()
        log.close()

    print(f"\n== f35_fleet tag={args.tag} lanes={args.lanes} budget={args.budget}s "
          f"wall={time.time()-t0:.0f}s ==")
    agg = {}
    best_overall = (10**9, None)
    for i, lane, seed, best, log, p in procs:
        txt = open(log.name).read()
        m = re.findall(r"done: home CLEAN (\d+)", txt)
        st = re.findall(r"^\{\"evals\".*$", txt, re.M)
        stats = json.loads(st[-1]) if st else {}
        for k, v in stats.items():
            agg[k] = agg.get(k, 0) + v
        home = int(m[-1]) if m else -1
        dirty = re.findall(r"DIRTY (\d+) < home (\d+)", txt)
        print(f"  lane{i} seed={os.path.basename(seed):28s} home {home}  "
              f"evals {stats.get('evals', 0):6d} desc {stats.get('descents', 0):3d} "
              f"dirty {stats.get('dirty_descents', 0):3d} "
              f"recov {stats.get('remine_recovered', 0):3d} "
              f"dirty<home {len(dirty)}")
        if os.path.exists(best) and home > 0 and home < best_overall[0]:
            best_overall = (home, best)
    print(f"  AGG {json.dumps(agg)}")
    print(f"  BEST CLEAN {best_overall[0]}  {best_overall[1]}")


if __name__ == "__main__":
    main()
