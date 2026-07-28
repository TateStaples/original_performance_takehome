"""F-34: round-window productivity map.

Launches N concurrent `emission_order_search.py local` chains, one per
`--window` spec, all seeded from the same point, and reports which windows
descend.  Shared tools are only CALLED here, never edited.

Usage:
  python tools/f34_map.py --seed-json FILE --budget 240 --rng 7 \
      --jumps 1,2,4,8,16 --tag A r:0-0 r:1-1 ...
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("windows", nargs="+")
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--budget", type=float, default=240)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--jumps", default="1,2,4,8")
    ap.add_argument("--tag", default="A")
    ap.add_argument("--overrides-json", default=None,
                    help="JSON file whose params.mix is the EOS_OVERRIDES mix")
    args = ap.parse_args()

    with open(args.overrides_json or args.seed_json) as f:
        mix = json.load(f)["params"]["mix"]
    outdir = os.path.join(SCRATCH, f"f34map_{args.tag}")
    os.makedirs(outdir, exist_ok=True)

    procs = []
    for w in args.windows:
        safe = w.replace(":", "").replace("-", "_")
        out = os.path.join(outdir, f"{safe}.jsonl")
        for p in (out, out + ".best.json"):
            if os.path.exists(p):
                os.unlink(p)
        env = dict(os.environ,
                   EOS_OVERRIDES=json.dumps(mix),
                   EOS_SEED=str(args.rng),
                   EOS_JUMPS=args.jumps)
        log = open(os.path.join(outdir, f"{safe}.log"), "w")
        procs.append((w, out, log, subprocess.Popen(
            [sys.executable, os.path.join(REPO_ROOT, "tools", "emission_order_search.py"),
             "local", "--seed-json", args.seed_json, "--budget", str(args.budget),
             "--workers", "1", "--window", w, "--out", out],
            cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)))

    t0 = time.time()
    for w, out, log, p in procs:
        p.wait()
        log.close()
    rows = []
    for w, out, log, p in procs:
        txt = open(log.name).read()
        start = re.search(r"local start: \((\d+),", txt)
        best = re.search(r"local done: best (\d+)", txt)
        n = sum(1 for _ in open(out)) if os.path.exists(out) else 0
        rows.append((w, int(start.group(1)) if start else -1,
                     int(best.group(1)) if best else -1, n,
                     out + ".best.json" if os.path.exists(out + ".best.json") else ""))
    rows.sort(key=lambda r: (r[2], r[0]))
    print(f"\n== f34_map tag={args.tag} rng={args.rng} jumps={args.jumps} "
          f"budget={args.budget}s wall={time.time()-t0:.0f}s ==")
    for w, s, b, n, bj in rows:
        mark = "  <<<" if 0 < b < s else ""
        print(f"  {w:10s} start {s} -> best {b}   evals {n:6d}{mark}")
    print(json.dumps({"tag": args.tag, "rows": [
        {"window": w, "start": s, "best": b, "evals": n, "best_json": bj}
        for w, s, b, n, bj in rows]}))


if __name__ == "__main__":
    main()
