#!/usr/bin/env python3
"""F-39: parallel (multiprocessing) discrepancy search over the 1006 stream.

Workers share the captured op stream / DAG via fork; each trial is a full
offline greedy re-schedule (bs.greedy_schedule) with forced min_cycle
floors, exactly the H-051/G-25 deviation model.

    python3 tools/f39_par.py disc1 --delays 1,2 [--workers 8]
    python3 tools/f39_par.py pairs --radius 3 [--jump-engines ...]
    python3 tools/f39_par.py triples --trials N --radius 8
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import pickle
import random
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import f39_pack as fp  # noqa: E402  (patches bs.H51_OVERRIDES / CAPTURE_PATH)
import backtrack_sched as bs  # noqa: E402

_G: dict = {}


def _init():
    data, ops, preds, floors = fp.load()
    _G["ops"] = ops
    _G["preds"] = preds
    _G["floors"] = floors
    _G["place0"] = [op[9] for op in ops]


def _eval(trial: dict[int, int]):
    place, n = bs.greedy_schedule(_G["ops"], _G["preds"], _G["floors"],
                                  extra_floors=trial)
    return n, (place if n is not None else None)


def _work(chunk):
    out = []
    for trial in chunk:
        n, place = _eval(trial)
        if n is not None:
            out.append((n, trial, place if n < _G["base"] else None))
    return out


def _work_min(chunk):
    """Return only best-so-far in the chunk (keeps IPC small)."""
    best = None
    cnt = 0
    for trial in chunk:
        n, place = _eval(trial)
        cnt += 1
        if n is not None and (best is None or n < best[0]):
            best = (n, trial, place)
    return cnt, best


def chunks(it, size):
    buf = []
    for x in it:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def run(gen, workers, label, base, total_hint=None):
    t0 = time.time()
    tried = 0
    best = (base, None, None)
    hits = []
    with mp.Pool(workers, initializer=_init) as pool:
        for cnt, b in pool.imap_unordered(_work_min, chunks(gen, 400)):
            tried += cnt
            if b is not None and b[0] < best[0]:
                best = b
                hits.append((b[0], b[1]))
                with open(os.path.join(fp.SCRATCH,
                                       f"f39_incumbent_{label}.pkl"), "wb") as f:
                    pickle.dump({"cycles": b[0], "floors": b[1],
                                 "place": b[2]}, f)
                print(f"  IMPROVED -> {b[0]} {b[1]}", flush=True)
            if tried % 20000 < 400:
                el = time.time() - t0
                print(f"  ...{tried} trials {el:.0f}s best {best[0]}",
                      flush=True)
    print(json.dumps({"tier": label, "trials": tried, "best": best[0],
                      "baseline": base, "hits": hits,
                      "secs": round(time.time() - t0, 1)}))
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd")
    ap.add_argument("--delays", default="1,2")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--radius", type=int, default=3)
    ap.add_argument("--engines", default="valu,load,flow,alu,store")
    ap.add_argument("--trials", type=int, default=200000)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    _init()
    ops = _G["ops"]
    place0 = _G["place0"]
    base = max(place0) + 1
    _G["base"] = base
    print(f"baseline {base}, ops {len(ops)}", flush=True)

    if args.cmd == "disc1":
        delays = [int(x) for x in args.delays.split(",")]

        def gen():
            for i in range(len(ops)):
                for d in delays:
                    yield {i: place0[i] + d}
        run(gen(), args.workers, f"disc1_d{args.delays.replace(',','')}", base)
        return

    if args.cmd == "pairs":
        jumps, _, _, _ = fp.jump_cycles(ops, _G["preds"], _G["floors"], place0)
        jumps = [0] + jumps
        engset = set(args.engines.split(","))
        rad = args.radius

        def gen():
            for jc in jumps:
                cand = [i for i in range(len(ops))
                        if abs(place0[i] - jc) <= rad and ops[i][0] in engset]
                for ai in range(len(cand)):
                    for bi in range(ai + 1, len(cand)):
                        i, j = cand[ai], cand[bi]
                        for di in (1, 2):
                            for dj in (1, 2):
                                yield {i: place0[i] + di, j: place0[j] + dj}
        print(f"jumps {jumps} radius {rad}", flush=True)
        run(gen(), args.workers, f"pairs_r{rad}", base)
        return

    if args.cmd == "triples":
        jumps, _, _, _ = fp.jump_cycles(ops, _G["preds"], _G["floors"], place0)
        jumps = [0] + jumps
        engset = set(args.engines.split(","))
        rng = random.Random(args.seed)
        pool = [i for i in range(len(ops))
                if ops[i][0] in engset and
                any(abs(place0[i] - jc) <= args.radius for jc in jumps)]
        print(f"triple pool {len(pool)} ops (radius {args.radius})", flush=True)

        def gen():
            for _ in range(args.trials):
                a, b, c = rng.sample(pool, 3)
                yield {a: place0[a] + rng.randint(1, 2),
                       b: place0[b] + rng.randint(1, 2),
                       c: place0[c] + rng.randint(1, 2)}
        run(gen(), args.workers, "triples", base)
        return

    raise SystemExit(f"unknown cmd {args.cmd}")


if __name__ == "__main__":
    main()
