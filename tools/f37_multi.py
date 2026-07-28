"""F-37 phase B+: simultaneous k-entry displacement search at the 1006 plan.

Single moves are provably empty (G-30), so a k>=2 escape must be strictly
PAIRED: two individually-neutral (or one worse / one better) displacements
that only descend together.  Candidate sets are built from the phase-A
single-move map (`tools/f37_single.py`) restricted to rounds 12-15.

Screening
---------
`machine.cycle == len(kernel_builder.instrs)` exactly (VLIW, one bundle per
cycle), so the screen only needs the BUILD -- ~0.074 s vs ~0.103 s for the
full build+simulate+reference measure, and the problem image is built once
per worker instead of once per eval.  Every candidate strictly below the
base is then RE-MEASURED with the shared `run_variant.measure` (build +
frozen grader) before it is reported, so nothing is accepted on the screen.

Modes
-----
  nn      neutral x neutral, spans OVERLAPPING, exhaustive
  nnd     neutral x neutral, spans DISJOINT (additivity control), sampled
  wn      worse x neutral, spans overlapping, exhaustive  (the +1/-2 shape)
  ww      worse x worse, spans overlapping, exhaustive
  k3/k4   k=3 / k=4 sampled from the neutral plateau, mutually overlapping

Usage (repo root):
  python3 tools/f37_multi.py --seed-json tools/h057_best_plan_1006.json \
      --single SCRATCH/f37/single_r1215.jsonl --mode nn \
      --start 0 --stop 60000 --out SCRATCH/f37/nn.jsonl
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import f37_lib as F  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, measure  # noqa: E402

_G: dict[str, Any] = {}


def _init(kwargs: dict[str, Any]) -> None:
    from dev import KernelBuilder  # noqa: F401
    _G["kwargs"] = kwargs
    _G["KB"] = KernelBuilder


def _cycles(order: tuple) -> int:
    """Screen: schedule length only (== machine.cycle), no simulation."""
    kw = dict(_G["kwargs"])
    kw["emission_plan"] = order
    try:
        kb = _G["KB"]()
        kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                                  SHAPE["forest_height"], **kw)
    except Exception:
        return 10 ** 9
    return len(kb.instrs)


# ------------------------------------------------------------------ sets


def load_single(path: str) -> list[dict]:
    return [json.loads(l) for l in open(path)]


def bucket(recs: Sequence[dict], lo: int, hi: int) -> list[tuple[int, int]]:
    out = [(r["s"], r["a"]) for r in recs
           if r["correct"] and lo <= r["cycles"] <= hi]
    out.sort()
    return out


def pair_list(plan, A, B, same: bool, want_overlap: bool):
    n = len(plan)
    sa = [F.span(n, m) for m in A]
    sb = [F.span(n, m) for m in B]
    out = []
    for i, ma in enumerate(A):
        a0, a1 = sa[i]
        rng = range(i + 1, len(B)) if same else range(len(B))
        for j in rng:
            mb = B[j]
            if ma[0] == mb[0]:
                continue
            b0, b1 = sb[j]
            if (a0 <= b1 and b0 <= a1) != want_overlap:
                continue
            out.append((ma, mb))
    return out


def ktuples(plan, A, k: int, count: int, rng: random.Random):
    """Random k-subsets of A that are pairwise span-overlapping (a k-clique
    in the interaction graph -- non-interacting members would just re-test
    the additive case already covered by `nnd`)."""
    n = len(plan)
    sp = {m: F.span(n, m) for m in A}
    out, seen, guard = [], set(), 0
    while len(out) < count and guard < count * 400:
        guard += 1
        m0 = rng.choice(A)
        a0, a1 = sp[m0]
        cand = [m for m in A if m[0] != m0[0]
                and sp[m][0] <= a1 and a0 <= sp[m][1]]
        if len(cand) < k - 1:
            continue
        pick = rng.sample(cand, k - 1)
        grp = tuple(sorted([m0] + pick))
        if grp in seen:
            continue
        ok = True
        for x in range(len(grp)):
            for y in range(x + 1, len(grp)):
                if grp[x][0] == grp[y][0]:
                    ok = False
                bx, by = sp[grp[x]], sp[grp[y]]
                if not (bx[0] <= by[1] and by[0] <= bx[1]):
                    ok = False
        if not ok:
            continue
        seen.add(grp)
        out.append(grp)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--single", required=True)
    ap.add_argument("--mode", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--stop", type=int, default=10 ** 9)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--count", type=int, default=20000)
    ap.add_argument("--worse-hi", type=int, default=1009)
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--only-resolved", action="store_true",
                    help="scan ONLY the sets whose anchor is swept away by "
                         "another member (skipped by the plain pass), with "
                         "the anchor slid forward to the surviving entry")
    ap.add_argument("--time-budget", type=float, default=1e9)
    args = ap.parse_args()

    order, mix = F.load_point(args.seed_json)
    plan = list(order)
    kwargs = dict(BASE_KWARGS, **mix)
    recs = load_single(args.single)
    neu = bucket(recs, 1006, 1006)
    worse = bucket(recs, 1007, args.worse_hi)
    rng = random.Random(args.rng)

    if args.mode == "nn":
        cands = pair_list(plan, neu, neu, True, True)
    elif args.mode == "nnd":
        allp = pair_list(plan, neu, neu, True, False)
        rng.shuffle(allp)
        cands = allp[:args.count]
    elif args.mode == "wn":
        cands = pair_list(plan, worse, neu, False, True)
    elif args.mode == "ww":
        cands = pair_list(plan, worse, worse, True, True)
    elif args.mode in ("k3", "k4"):
        cands = ktuples(plan, neu, int(args.mode[1]), args.count, rng)
    else:
        raise SystemExit("unknown mode")
    print(f"mode={args.mode} candidates={len(cands)} "
          f"(neutral {len(neu)}, worse {len(worse)})", flush=True)
    if args.count_only:
        return

    base_c, base_ok = measure(dict(mix, emission_plan=order), seed=1)
    print(f"base {base_c} correct={base_ok}", flush=True)

    chunk = cands[args.start:args.stop]
    pool = mp.Pool(args.workers, initializer=_init, initargs=(kwargs,))
    out = open(args.out, "a", buffering=1)
    t0 = time.time()
    B = args.workers * 24
    hist: dict[int, int] = {}
    nskip = 0
    best = base_c
    k = 0
    while k < len(chunk):
        batch = []
        while len(batch) < B and k < len(chunk):
            grp = chunk[k]
            k += 1
            q = F.apply_moves(plan, grp)
            if args.only_resolved:
                if q is not None:
                    nskip += 1
                    continue
                q = F.apply_moves(plan, grp, resolve=True)
            if q is None or not F.valid(q):
                nskip += 1
                continue
            batch.append((grp, q))
        if not batch:
            break
        res = pool.map(_cycles, [q for _, q in batch])
        for (grp, q), c in zip(batch, res):
            hist[c] = hist.get(c, 0) + 1
            if c < base_c:
                cc, ok = measure(dict(mix, emission_plan=q), seed=1)
                out.write(json.dumps({"moves": [list(m) for m in grp],
                                      "screen": c, "cycles": cc,
                                      "correct": ok}) + "\n")
                print(f"  HIT screen={c} measured={cc} correct={ok} {grp}",
                      flush=True)
                if ok and cc < best:
                    best = cc
                    with open(args.out + ".best.json", "w") as f:
                        json.dump({"cycles": cc, "moves": [list(m) for m in grp],
                                   "plan": [list(e) for e in q]}, f)
        if (k // B) % 20 == 0:
            print(f"  {args.start + k}/{len(cands)} skip={nskip} best={best} "
                  f"t={time.time() - t0:.0f}s "
                  f"rate={k / max(1e-9, time.time() - t0):.0f}/s", flush=True)
        if time.time() - t0 > args.time_budget:
            print(f"  TIME BUDGET reached at index {args.start + k}", flush=True)
            break
    top = sorted(hist.items())[:12]
    print(f"DONE mode={args.mode} scanned={k} skipped={nskip} best={best} "
          f"t={time.time() - t0:.0f}s next_start={args.start + k}", flush=True)
    print("screen hist (low 12): " + json.dumps(top), flush=True)
    with open(args.out + ".hist.json", "a") as f:
        f.write(json.dumps({"mode": args.mode, "start": args.start,
                            "scanned": k, "skipped": nskip,
                            "hist": {str(a): b for a, b in sorted(hist.items())}}) + "\n")


if __name__ == "__main__":
    main()
