"""H-056: search the PROGRAM ORGANIZATION (block partition x lag diagonal x
interleave) at the current 1020 mix, screening every candidate for its
any-packing LOWER BOUND as well as its realized cycles.

Why this is not G-29 again: G-29 closed *local* moves around the one F-13
plan. This driver enumerates the STRUCTURED organization space -- how the 32
groups are partitioned into software-pipeline blocks, what lag diagonal the
blocks run on, and how the active waves interleave -- which was last measured
under a greedy emission order and the pre-H-042 spelling regime (H-049
phase1). Per H-047/F-13 those measurements are invalid at the current mix.

Every candidate reports BOTH:
  * `LB`   -- backtrack_sched's any-packing lower bound for the op stream the
              candidate produces (the deliverable: a stream with LB < 1006 is
              the input to the next order round even if it schedules worse),
  * `cyc`  -- the greedy-realized, grader-verified cycle count.

Usage (repo root):
  python3 tools/h056_org.py fam --out FILE [--workers N]   # structured families
  python3 tools/h056_org.py lagrand --out FILE [--budget S] [--blocks K]
  python3 tools/h056_org.py cfg --cfg-file F --out FILE    # config axes x plan
Results stream as JSON lines.
"""
from __future__ import annotations

import argparse
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

from emission_order_search import make_plan, load_plan  # noqa: E402
from run_variant import measure  # noqa: E402

ROUNDS, N_GROUPS = 16, 32

# The H-056 frontier mix (mainline 1020) -- everything EXCEPT emission_plan.
MIX: dict[str, Any] = {
    "parity_ring": True,
    "l4_gmin": (7, 30),
    "parity_ring_plan": (((0, 5), (193, 201, 601)), ((0, 6), (609, 617, 625)),
                         ((0, 15), (185, 1225, 1233)), ((0, 16), (193, 201, 1297))),
    "c5_primed_gather_levels": (5, 6),
    "mem_prime_region_hazards": True,
    "mem_prime_dead_reg_staging": True,
    "flow_spelling_plan": (),
}


# --------------------------------------------------------------------------
# partitions
# --------------------------------------------------------------------------
def even_blocks(k: int) -> list[list[int]] | None:
    if N_GROUPS % k:
        return None
    s = N_GROUPS // k
    return [list(range(b * s, (b + 1) * s)) for b in range(k)]


def cut_blocks(k: int) -> list[list[int]]:
    """Integer-division cut points -- the external repo's uneven shape."""
    return [list(range((N_GROUPS * i) // k, (N_GROUPS * (i + 1)) // k))
            for i in range(k)]


def strided_blocks(k: int) -> list[list[int]] | None:
    """Non-contiguous: block b = groups congruent to b mod k."""
    if N_GROUPS % k:
        return None
    return [list(range(b, N_GROUPS, k)) for b in range(k)]


def ramp_blocks(sizes: Sequence[int]) -> list[list[int]] | None:
    if sum(sizes) != N_GROUPS:
        return None
    out, i = [], 0
    for s in sizes:
        out.append(list(range(i, i + s)))
        i += s
    return out


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------
_screen = None


def _init() -> None:
    global _screen
    import h056_screen
    _screen = h056_screen


def _eval(job: tuple[str, dict[str, Any], tuple[Any, ...], dict[str, Any], bool]
          ) -> dict[str, Any]:
    name, params, plan, extra_mix, want_lb = job
    over = dict(MIX, **extra_mix)
    if plan:
        over["emission_plan"] = plan
    rec: dict[str, Any] = {"name": name, "params": params}
    try:
        cyc, ok = measure(over, seed=1)
        rec["cyc"], rec["correct"] = cyc, bool(ok)
    except Exception as exc:
        rec["cyc"], rec["correct"] = -1, False
        rec["err"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return rec
    if want_lb:
        try:
            s = _screen.screen(name, over, verify=False)
            for k in ("LB", "LB_energetic", "fungible", "cp", "census",
                      "floors", "realized"):
                if k in s:
                    rec[k] = s[k]
        except Exception as exc:
            rec["lb_err"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return rec


class Pool:
    def __init__(self, workers: int, out_path: str):
        self.pool = mp.Pool(workers, initializer=_init)
        self.out = open(out_path, "a", buffering=1)
        self.best = (10 ** 9, None)
        self.best_lb = (10 ** 9, None)
        self.n = 0

    def run(self, jobs: list[Any]) -> list[dict[str, Any]]:
        recs = self.pool.map(_eval, jobs)
        for rec in recs:
            self.n += 1
            self.out.write(json.dumps(rec, default=str) + "\n")
            if rec.get("correct") and rec["cyc"] < self.best[0]:
                self.best = (rec["cyc"], rec["name"])
                print(f"  NEW BEST CYC {rec['cyc']} <- {rec['name']}", flush=True)
            lb = rec.get("LB")
            if lb is not None and lb < self.best_lb[0]:
                self.best_lb = (lb, rec["name"])
                print(f"  NEW BEST LB {lb} <- {rec['name']} (cyc {rec['cyc']})",
                      flush=True)
        return recs


# --------------------------------------------------------------------------
# families
# --------------------------------------------------------------------------
def family_jobs() -> list[Any]:
    jobs: list[Any] = []

    def add(name: str, params: dict[str, Any], mix: dict[str, Any] | None = None):
        try:
            plan = make_plan(**params)
        except (AssertionError, ValueError):
            return
        jobs.append((name, params, plan, mix or {}, True))

    # the F-13 incumbent plan and the default diagonal, as controls
    jobs.append(("ctrl:f13_1020", {"seed": "f13"},
                 load_plan(os.path.join(REPO_ROOT, "tools",
                                        "f13_best_plan_1020.json")), {}, True))
    add("ctrl:default(4x8,lag3)", {})

    # A. block COUNT, even partitions, uniform stagger
    for k in (1, 2, 4, 8, 16, 32):
        blk = even_blocks(k)
        if blk is None:
            continue
        for stagger in (0, 1, 2, 3, 4, 5, 6, 8, 12):
            if k == 1 and stagger:
                continue
            lags = tuple(stagger * b for b in range(k))
            if max(lags) > 40:
                continue
            add(f"A:even{k}xstag{stagger}", {"lags": lags, "blocks": blk})

    # B. block count with integer-division CUT points (uneven, external shape)
    for k in (3, 5, 6, 7, 9, 10, 11, 13, 17, 21, 24):
        blk = cut_blocks(k)
        for stagger in (1, 2, 3):
            lags = tuple(stagger * b for b in range(k))
            if max(lags) > 40:
                continue
            add(f"B:cut{k}xstag{stagger}", {"lags": lags, "blocks": blk})

    # C. STRIDED (non-contiguous) blocks -- a different group->block map
    for k in (2, 4, 8):
        blk = strided_blocks(k)
        if blk is None:
            continue
        for stagger in (1, 2, 3, 4):
            add(f"C:stride{k}xstag{stagger}",
                {"lags": tuple(stagger * b for b in range(k)), "blocks": blk})

    # D. UNEVEN sizes at 4 blocks (ramp/anti-ramp) -- the pipeline fill shape
    for sizes in [(4, 8, 8, 12), (12, 8, 8, 4), (2, 6, 10, 14), (14, 10, 6, 2),
                  (6, 8, 8, 10), (10, 8, 8, 6), (4, 4, 12, 12), (12, 12, 4, 4),
                  (8, 8, 8, 8), (2, 10, 10, 10), (16, 8, 4, 4), (4, 4, 8, 16)]:
        blk = ramp_blocks(sizes)
        for lags in ((0, 3, 6, 9), (0, 2, 4, 6), (0, 4, 8, 12), (0, 3, 5, 8)):
            add(f"D:sizes{sizes}xlags{lags}", {"lags": lags, "blocks": blk})

    # E. NON-UNIFORM lag diagonals at the 4x8 shape (the round-period phase:
    #    period is 11 and rounds 16, so lags near 11 realign the epochs)
    for lags in [(0, 1, 2, 3), (0, 2, 4, 6), (0, 3, 6, 9), (0, 4, 8, 12),
                 (0, 5, 10, 15), (0, 1, 4, 9), (0, 3, 4, 7), (0, 2, 6, 8),
                 (0, 3, 6, 11), (0, 4, 7, 11), (0, 11, 22, 33), (0, 11, 1, 12),
                 (0, 5, 11, 16), (0, 6, 11, 17), (0, 1, 11, 12), (0, 2, 11, 13),
                 (0, 3, 11, 14), (0, 3, 9, 12), (0, 6, 9, 12), (0, 2, 5, 11),
                 (0, 7, 3, 10), (0, 9, 3, 6), (0, 6, 3, 9), (3, 0, 9, 6),
                 (0, 3, 7, 10), (0, 4, 6, 10), (0, 2, 7, 9), (0, 5, 7, 10)]:
        add(f"E:lags{lags}", {"lags": lags})

    # F. 8-block diagonals (half-size blocks, finer pipeline)
    for lags in [(0, 1, 2, 3, 4, 5, 6, 7), (0, 2, 4, 6, 8, 10, 12, 14),
                 (0, 1, 1, 2, 2, 3, 3, 4), (0, 3, 3, 6, 6, 9, 9, 12),
                 (0, 0, 3, 3, 6, 6, 9, 9), (0, 1, 3, 4, 6, 7, 9, 10),
                 (0, 2, 3, 5, 6, 8, 9, 11), (0, 1, 2, 3, 8, 9, 10, 11),
                 (0, 11, 1, 12, 2, 13, 3, 14)]:
        add(f"F:b8lags{lags}", {"lags": lags, "blocks": even_blocks(8)})

    # G. interleave / wave / group order on the best few diagonals
    for lags in ((0, 3, 6, 9), (0, 2, 4, 6), (0, 4, 8, 12)):
        for iv in ("block", "zip"):
            for wo in ("default", "rev", "rot:1"):
                for go in ("asc", "rev", "rot:1", "rot:2"):
                    if iv == "block" and wo == "default" and go == "asc":
                        continue
                    add(f"G:lags{lags}/{iv}/{wo}/{go}",
                        {"lags": lags, "interleave": iv, "wave_order": wo,
                         "group_order": go})

    # H. drain shape: tail depth-first + stage round-robin
    for lags in ((0, 3, 6, 9), (0, 2, 4, 6)):
        for td in (1, 2, 3, 4, 6, 8):
            add(f"H:lags{lags}/tail_df{td}", {"lags": lags, "tail_df": td})
        for n in (1, 2, 3, 5):
            steps = ROUNDS + max(lags)
            add(f"H:lags{lags}/rr_tail{n}",
                {"lags": lags, "stage_rr": tuple(range(steps - n, steps))})
            add(f"H:lags{lags}/rr_ramp{n}",
                {"lags": lags, "stage_rr": tuple(range(n))})
        add(f"H:lags{lags}/rr_all", {"lags": lags,
                                     "stage_rr": tuple(range(ROUNDS + max(lags)))})
    return jobs


def lagrand_jobs(rng: random.Random, k: int, n: int) -> list[Any]:
    """Random lag diagonals at k blocks (even partition where possible)."""
    blk = even_blocks(k) or cut_blocks(k)
    jobs = []
    for _ in range(n):
        lags = tuple(sorted(rng.randrange(0, 14) for _ in range(k)))
        if rng.random() < 0.3:
            lags = tuple(rng.randrange(0, 14) for _ in range(k))
        try:
            plan = make_plan(lags=lags, blocks=blk)
        except (AssertionError, ValueError):
            continue
        jobs.append((f"R{k}:lags{lags}", {"lags": lags, "k": k}, plan, {}, True))
    return jobs


def rand_jobs(rng: random.Random, n: int) -> list[Any]:
    """Uniform sample of the whole structured organization space: block
    partition x lag diagonal x interleave x wave/group order x drain shape.
    Wider than family_jobs, which only sweeps one axis at a time."""
    jobs = []
    for _ in range(n):
        kind = rng.choice(["even", "cut", "stride", "ramp"])
        if kind == "even":
            k = rng.choice([2, 4, 8, 16])
            blk = even_blocks(k)
        elif kind == "cut":
            k = rng.choice([3, 5, 6, 7, 9, 10, 11, 13])
            blk = cut_blocks(k)
        elif kind == "stride":
            k = rng.choice([2, 4, 8])
            blk = strided_blocks(k)
        else:
            k = 4
            sizes = [2] * 4
            for _ in range(24):
                sizes[rng.randrange(4)] += 1
            blk = ramp_blocks(sizes)
        if blk is None:
            continue
        step = rng.choice([1, 1, 2, 2, 3, 3, 4, 4, 5, 6])
        lags = tuple(step * b for b in range(k))
        if rng.random() < 0.45:  # non-uniform diagonal
            lags = tuple(rng.randrange(0, min(14, 2 + 4 * k)) for _ in range(k))
        if max(lags) > 40:
            continue
        params: dict[str, Any] = {"lags": lags, "blocks": blk}
        params["interleave"] = rng.choice(["block", "zip", "zip", "zip"])
        params["wave_order"] = rng.choice(["default", "rev", "rot:1", "rot:2"])
        params["group_order"] = rng.choice(
            ["asc", "asc", "rev", "rot:1", "rot:2", "rot:3", "rot:4"])
        if rng.random() < 0.2:
            params["tail_df"] = rng.randrange(1, 6)
        if rng.random() < 0.15:
            steps = ROUNDS + max(lags)
            m = rng.randrange(1, 4)
            params["stage_rr"] = (tuple(range(steps - m, steps)) if rng.random() < 0.5
                                  else tuple(range(m)))
            params["stage_rr_scope"] = rng.choice(["step", "wave"])
        try:
            plan = make_plan(**params)
        except (AssertionError, ValueError):
            continue
        nm = (f"X:{kind}{k}/lags{lags}/{params['interleave']}/"
              f"{params['wave_order']}/{params['group_order']}"
              f"{'/tdf' + str(params['tail_df']) if 'tail_df' in params else ''}"
              f"{'/rr' if 'stage_rr' in params else ''}")
        jobs.append((nm, {k2: v for k2, v in params.items() if k2 != "blocks"},
                     plan, {}, True))
    return jobs


def deep_jobs() -> list[Any]:
    """Exhaustive cross of the axes the random sweep flagged: partition x
    uniform stagger x interleave x wave order x group order."""
    parts: list[tuple[str, list[list[int]]]] = []
    for k in (2, 4, 8, 16, 32):
        b = even_blocks(k)
        if b:
            parts.append((f"even{k}", b))
    for k in (3, 5, 6, 7, 9, 10, 11, 13):
        parts.append((f"cut{k}", cut_blocks(k)))
    for k in (2, 4, 8):
        b = strided_blocks(k)
        if b:
            parts.append((f"stride{k}", b))
    jobs = []
    for pname, blk in parts:
        k = len(blk)
        for stag in (1, 2, 3, 4):
            lags = tuple(stag * b for b in range(k))
            if max(lags) > 40:
                continue
            for iv in ("block", "zip"):
                for wo in ("default", "rev", "rot:1", "rot:2"):
                    for go in ("asc", "rev", "rot:1", "rot:2", "rot:3", "rot:4"):
                        params = {"lags": lags, "blocks": blk, "interleave": iv,
                                  "wave_order": wo, "group_order": go}
                        try:
                            plan = make_plan(**params)
                        except (AssertionError, ValueError):
                            continue
                        jobs.append((f"D:{pname}/stag{stag}/{iv}/{wo}/{go}",
                                     {k2: v for k2, v in params.items()
                                      if k2 != "blocks"}, plan, {}, True))
    return jobs


def perturb_jobs(rng: random.Random, base_lags: Sequence[int],
                 blocks: list[list[int]], n: int) -> list[Any]:
    """Local perturbations of one lag diagonal (the LB-descent direction the
    sweep found), keeping partition/interleave fixed at the winner's."""
    jobs = []
    k = len(base_lags)
    for _ in range(n):
        lags = list(base_lags)
        for _ in range(rng.randrange(1, 4)):
            i = rng.randrange(k)
            lags[i] = max(0, lags[i] + rng.choice([-3, -2, -1, 1, 2, 3]))
        lt = tuple(lags)
        for iv, wo, go in [("zip", "rev", "asc"), ("zip", "rev", "rot:4"),
                           ("zip", "rot:1", "asc"), ("zip", "rot:1", "rot:4"),
                           ("zip", "default", "asc")]:
            params = {"lags": lt, "blocks": blocks, "interleave": iv,
                      "wave_order": wo, "group_order": go}
            try:
                plan = make_plan(**params)
            except (AssertionError, ValueError):
                continue
            jobs.append((f"P:{len(blocks)}b/lags{lt}/{iv}/{wo}/{go}",
                         {k2: v for k2, v in params.items() if k2 != "blocks"},
                         plan, {}, True))
    return jobs


def dump_plan(spec: str, path: str) -> None:
    """Materialise one organization as an emission_order_search seed file.

    spec = "<part><k>/stag<s>/<interleave>/<wave_order>/<group_order>", e.g.
    "even8/stag2/zip/rot:1/asc" -- the format `deep_jobs` prints.
    """
    part, stag, iv, wo, go = spec.split("/")
    s = int(stag[4:])
    for pref, fn in (("even", even_blocks), ("cut", cut_blocks),
                     ("stride", strided_blocks)):
        if part.startswith(pref):
            blk = fn(int(part[len(pref):]))
            break
    else:
        raise ValueError(part)
    assert blk is not None
    lags = tuple(s * b for b in range(len(blk)))
    plan = make_plan(lags=lags, blocks=blk, interleave=iv, wave_order=wo,
                     group_order=go)
    cyc, ok = measure(dict(MIX, emission_plan=plan), seed=1)
    with open(path, "w") as f:
        json.dump({"cycles": cyc, "params": {"spec": spec, "lags": list(lags)},
                   "plan": [list(e) if e[0] != "rr"
                            else ["rr", [list(p) for p in e[1]]] for e in plan]},
                  f)
    print(json.dumps({"spec": spec, "cycles": cyc, "correct": bool(ok),
                      "entries": len(plan), "path": path}))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["fam", "lagrand", "rand", "deep",
                                     "perturb", "dump", "cfg"])
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec", default=None, help="dump mode organization spec")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 4) - 1))
    ap.add_argument("--budget", type=float, default=600.0)
    ap.add_argument("--blocks", type=int, default=4)
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--stagger", type=int, default=2)
    ap.add_argument("--cfg-file", default=None)
    ap.add_argument("--plan", default=None)
    # The H-045 parity ring borrows registers across skew blocks and its
    # plan is LIVENESS-TIMED, i.e. tied to the mainline organization -- so a
    # frozen plan silently kills unrelated organizations (106/257 of the
    # first family sweep came back correct:false). `--mix` re-runs the same
    # organization space with the ring relaxed so the comparison is clean:
    #   plan   = frontier (pinned parity_ring_plan)  [+0 on the f13 order]
    #   ring   = parity_ring on, plan re-derived by dev  [+6]
    #   noring = parity_ring off                       [+10]
    ap.add_argument("--mix", default="plan", choices=["plan", "ring", "noring"])
    args = ap.parse_args()

    # NOTE: mp uses spawn on darwin, so mutating MIX in the parent would not
    # reach the workers -- the relaxation travels in each job's extra_mix.
    mixov: dict[str, Any] = {}
    if args.mix == "ring":
        mixov = {"parity_ring_plan": ()}
    elif args.mix == "noring":
        mixov = {"parity_ring_plan": (), "parity_ring": False}

    if args.mode == "dump":
        assert args.spec, "dump needs --spec"
        dump_plan(args.spec, args.out)
        return

    p = Pool(args.workers, args.out)
    t0 = time.time()
    if args.mode in ("fam", "deep"):
        raw = family_jobs() if args.mode == "fam" else deep_jobs()
        jobs = [(f"{args.mix}|{n}", pr, pl, dict(m, **mixov), w)
                for n, pr, pl, m, w in raw]
        print(f"{len(jobs)} candidates", flush=True)
        for i in range(0, len(jobs), 64):
            if time.time() - t0 > args.budget:
                print("budget exhausted", flush=True)
                break
            p.run(jobs[i:i + 64])
            print(f"  {p.n} done, best cyc {p.best}, best LB {p.best_lb}, "
                  f"t={time.time()-t0:.0f}s", flush=True)
    elif args.mode == "perturb":
        rng = random.Random(args.seed)
        k = args.blocks
        blk = even_blocks(k) or cut_blocks(k)
        base = tuple(args.stagger * b for b in range(k))
        while time.time() - t0 < args.budget:
            p.run([(f"{args.mix}|{n}", pr, pl, dict(m, **mixov), w)
                   for n, pr, pl, m, w in perturb_jobs(rng, base, blk, 24)])
            print(f"  {p.n} done, best cyc {p.best}, best LB {p.best_lb}, "
                  f"t={time.time()-t0:.0f}s", flush=True)
    elif args.mode in ("lagrand", "rand"):
        rng = random.Random(args.seed)
        gen = (lagrand_jobs if args.mode == "lagrand" else rand_jobs)
        while time.time() - t0 < args.budget:
            raw = (gen(rng, args.blocks, 96) if args.mode == "lagrand"
                   else gen(rng, 96))
            p.run([(f"{args.mix}|{n}", pr, pl, dict(m, **mixov), w)
                   for n, pr, pl, m, w in raw])
            print(f"  {p.n} done, best cyc {p.best}, best LB {p.best_lb}, "
                  f"t={time.time()-t0:.0f}s", flush=True)
    else:
        with open(args.cfg_file) as f:
            cands = json.load(f)
        plan = load_plan(args.plan) if args.plan else None

        def tup(v):
            return tuple(tup(x) for x in v) if isinstance(v, list) else v
        jobs = [(name, over, plan or (),
                 dict(mixov, **{k: tup(v) for k, v in over.items()}), True)
                for name, over in cands.items()]
        for i in range(0, len(jobs), 64):
            p.run(jobs[i:i + 64])
            print(f"  {p.n} done, best cyc {p.best}, best LB {p.best_lb}",
                  flush=True)
    print(f"DONE {p.n} evals; best cyc {p.best}; best LB {p.best_lb}", flush=True)


if __name__ == "__main__":
    main()
