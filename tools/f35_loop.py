"""F-35: audit-aware emission-order walk with IN-LOOP ring re-mining.

H-057 walked the order with `emission_order_search local`, then audited at
hand-picked checkpoints; ~half of the walked orders invalidated their own
ring plan and the fast-but-dirty points were discarded or re-mined only at
a checkpoint.  This driver folds the audit into the walk:

  * every accepted descent is audited against the CARRIED ring plan;
  * a DIRTY descent is not rejected -- the plan is re-mined from EMPTY at
    that order (H-057 sec. 3.3) and the walk CONTINUES from the re-mined
    stream, which is a different order landscape (re-conditioning);
  * the frontier reported is the best AUDIT-CLEAN point, but dirty points
    are kept as walk state instead of being thrown away.

Structure = branch-and-return basin hopping so the chain cannot drift:
`home` is the best clean point; each branch applies one re-conditioning
operator (truncated re-mine / gmin re-slide / small kick / plain walk),
walks it in a window portfolio, and is discarded unless it beats home.

Shared tools (emission_order_search, audit_ring_windows) are imported and
called, never modified.
"""
from __future__ import annotations

import argparse
import ast
import json
import multiprocessing as mp
import os
import random
import sys
import tempfile
import time
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import emission_order_search as eos  # noqa: E402
import f34_lib as L  # noqa: E402
from run_variant import measure  # noqa: E402

ROUNDS, N_GROUPS = 16, 32


def round_of(entry) -> int:
    members = entry[1] if entry and entry[0] == "rr" else (entry,)
    return min(r_ for r_, _ in members)


def valid(p: list[Any]) -> bool:
    nr = [0] * N_GROUPS
    for entry in p:
        members = entry[1] if entry and entry[0] == "rr" else (entry,)
        for rr_, gg_ in members:
            if nr[gg_] != rr_:
                return False
            nr[gg_] += 1
    return all(v == ROUNDS for v in nr)


def propose(cur: list[Any], window: str, jumps: tuple[int, ...],
            rng: random.Random) -> tuple[Any, ...] | None:
    n = len(cur)
    p = list(cur)
    if window.startswith("r:"):
        lo, hi = (int(x) for x in window[2:].split("-"))
        idxs = [k for k, e in enumerate(p) if lo <= round_of(e) <= hi]
        if not idxs:
            return None
        i = rng.choice(idxs)
    elif window.startswith("p:"):
        lo, hi = (int(x) for x in window[2:].split("-"))
        i = rng.randrange(max(0, lo), min(n, hi + 1))
    elif window == "ramp":
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
    j = i + rng.choice(jumps)
    if not (0 <= j < n):
        return None
    e = p.pop(i)
    p.insert(j, e)
    return tuple(p) if valid(p) else None


def mine_trunc(order: tuple, base_mix: dict[str, Any], stop_at: int):
    """Mine from EMPTY to a GROW-then-PRUNE fixpoint.

    Grow: audit -> append the tool's proposed rings -> re-audit, until it
    proposes none.  The accumulated plan is not automatically sound (each
    added ring shifts the emission windows the next audit sees), so the
    prune phase then drops every ring the closed-loop recheck flags as
    live-across and re-audits until the recheck is clean.  Monotone
    decreasing, so it terminates.
    """
    plan: tuple = ()
    fd, tmp = tempfile.mkstemp(suffix=".plan")
    os.close(fd)
    try:
        for it in range(1, 9):
            try:
                L._run_audit(dict(base_mix, emission_plan=order,
                                  parity_ring_plan=plan), tmp)
            except AssertionError:
                return (), -1, ""
            new = L.tuplify(ast.literal_eval(open(tmp).read()))
            if not new:
                break
            plan = tuple(sorted(plan + new))
            if it >= stop_at:
                break
    finally:
        os.unlink(tmp)
    if not plan:
        return (), -1, ""
    v = -1
    line = ""
    for _ in range(12):
        try:
            v, n, line, keys = L.audit_detail(
                order, dict(base_mix, parity_ring_plan=plan))
        except AssertionError:
            return (), -1, ""
        if v == 0:
            return plan, 0, line
        # only PLAN rings are prunable: `parity_ring_map` also holds the
        # ~20 natively-derived rings, and a live-across on one of those is
        # a property of the ORDER that no plan can repair.
        prunable = {tuple(p[0]) for p in plan} & keys
        if not prunable:
            return plan, v, "NATIVE " + line
        plan = tuple(p for p in plan if tuple(p[0]) not in prunable)
        if not plan:
            return (), -1, "pruned empty"
    return plan, v, line


def save_point(path: str, cycles: int, order: tuple, mix: dict[str, Any],
               note: str, extra: dict | None = None) -> None:
    m = dict(mix)
    m["parity_ring_plan"] = [[list(k), list(v)] for k, v in m["parity_ring_plan"]]
    m["l4_gmin"] = list(m["l4_gmin"])
    m["c5_primed_gather_levels"] = list(m.get("c5_primed_gather_levels", ()))
    m["flow_spelling_plan"] = list(m.get("flow_spelling_plan", ()))
    params: dict[str, Any] = {"hypothesis": "F-34/F-35", "note": note, "mix": m}
    if extra:
        params.update(extra)
    with open(path, "w") as f:
        json.dump({"cycles": cycles, "params": params,
                   "plan": [list(e) if e[0] != "rr" else ["rr", [list(x) for x in e[1]]]
                            for e in order]}, f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed-json", required=True)
    ap.add_argument("--best-out", required=True)
    ap.add_argument("--log", default=None)
    ap.add_argument("--budget", type=float, default=420)
    ap.add_argument("--branch", type=float, default=70, help="seconds per branch")
    ap.add_argument("--workers", type=int, default=7)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--jumps", default="1,2,4,8,16")
    ap.add_argument("--windows", default="r:11-15,drain,both,all,r:13-15,mid")
    ap.add_argument("--ops", default="remine,gmin,kick,walk")
    ap.add_argument("--kick", type=int, default=2)
    args = ap.parse_args()

    js = [int(x) for x in args.jumps.split(",")]
    jumps = tuple(sorted(set(js) | {-j for j in js}))
    windows = args.windows.split(",")
    ops = args.ops.split(",")
    rng = random.Random(args.rng)

    order, mix = L.load_json_point(args.seed_json)
    base_mix = {k: v for k, v in mix.items() if k != "parity_ring_plan"}
    c0, ok0 = measure(dict(mix, emission_plan=order), seed=1)
    v0, n0, line0 = L.audit(order, mix)
    assert ok0, "seed point not correct"
    print(f"seed {c0} correct={ok0} audit={line0}", flush=True)

    home = (c0, order, dict(mix), line0)
    if os.path.exists(args.best_out):
        bo, bm = L.load_json_point(args.best_out)
        bc = json.load(open(args.best_out))["cycles"]
        bv, bn, bline = L.audit(bo, bm)
        if bv == 0 and bc < home[0]:
            home = (bc, bo, bm, bline)
            print(f"resumed home from {args.best_out}: {bc} ({bline})", flush=True)

    stats = {k: 0 for k in ("evals", "branches", "descents", "dirty_descents",
                            "remine_recovered", "remine_failed", "clean_descents",
                            "home_improves", "dirty_best_seen")}
    dirty_log: list[tuple[int, str]] = []
    pool = mp.Pool(args.workers)
    t0 = time.time()

    while time.time() - t0 < args.budget:
        stats["branches"] += 1
        op = rng.choice(ops)
        cur_c, cur_o, cur_m = home[0], home[1], dict(home[2])
        cur_bm = {k: v for k, v in cur_m.items() if k != "parity_ring_plan"}
        tag = op
        if op == "remine":
            plan2, v2, ln2 = mine_trunc(cur_o, cur_bm, rng.choice([1, 2, 9]))
            if not plan2 or v2 != 0 or tuple(plan2) == tuple(cur_m["parity_ring_plan"]):
                tag = "remine(noop)"
            else:
                m2 = dict(cur_bm, parity_ring_plan=plan2)
                try:
                    c2, ok2 = measure(dict(m2, emission_plan=cur_o), seed=1)
                except Exception:
                    ok2 = False
                if ok2:
                    cur_c, cur_m = c2, m2
                    tag = f"remine({len(plan2)}r)->{c2}"
        elif op == "gmin":
            g = rng.choice([(a, b) for a in (5, 6, 7, 8) for b in (29, 30, 31, 32)
                            if (a, b) != tuple(cur_m["l4_gmin"])])
            bm2 = dict(cur_bm, l4_gmin=g)
            plan2, v2, ln2 = mine_trunc(cur_o, bm2, 9)
            if plan2 and v2 == 0:
                m2 = dict(bm2, parity_ring_plan=plan2)
                try:
                    c2, ok2 = measure(dict(m2, emission_plan=cur_o), seed=1)
                except Exception:
                    ok2 = False
                if ok2 and c2 <= home[0] + 4:
                    cur_c, cur_m, cur_bm = c2, m2, bm2
                    tag = f"gmin{g}({len(plan2)}r)->{c2}"
                else:
                    tag = "gmin(reject)"
            else:
                tag = "gmin(unsound)"
        elif op == "kick":
            p = list(cur_o)
            for _ in range(args.kick):
                q = propose(p, rng.choice(windows), jumps, rng)
                if q:
                    p = list(q)
            try:
                c2, ok2 = measure(dict(cur_m, emission_plan=tuple(p)), seed=1)
            except Exception:
                c2, ok2 = 10**9, False
            if ok2 and c2 <= home[0] + 6:
                cur_o, cur_c = tuple(p), c2
                tag = f"kick->{c2}"
            else:
                tag = "kick(reject)"

        w = rng.choice(windows)
        tb = time.time()
        moved = False
        while time.time() - tb < args.branch:
            batch = []
            guard = 0
            while len(batch) < args.workers * 8 and guard < 4000:
                guard += 1
                p = propose(list(cur_o), w, jumps, rng)
                if p is not None:
                    batch.append(p)
            if not batch:
                break
            res = pool.map(eos._eval, [(cur_m, p) for p in batch])
            stats["evals"] += len(batch)
            cand = [(c, p) for (c, okk), p in zip(res, batch) if okk and c < cur_c]
            side = [p for (c, okk), p in zip(res, batch) if okk and c == cur_c]
            if cand:
                c_new, o_new = min(cand, key=lambda t: t[0])
                stats["descents"] += 1
                moved = True
                vv, nn, ln = L.audit(o_new, cur_m)
                if vv == 0:
                    stats["clean_descents"] += 1
                    cur_o, cur_c = o_new, c_new
                else:
                    stats["dirty_descents"] += 1
                    if c_new < home[0]:
                        stats["dirty_best_seen"] += 1
                        dirty_log.append((c_new, ln))
                        print(f"  [{tag}|{w}] DIRTY {c_new} < home {home[0]} ({ln})",
                              flush=True)
                    plan2, v2, ln2 = mine_trunc(o_new, cur_bm, 9)
                    if plan2 and v2 == 0:
                        m2 = dict(cur_bm, parity_ring_plan=plan2)
                        try:
                            c2, ok2 = measure(dict(m2, emission_plan=o_new), seed=1)
                        except Exception:
                            ok2 = False
                        if ok2:
                            stats["remine_recovered"] += 1
                            cur_o, cur_c, cur_m = o_new, c2, m2
                        else:
                            stats["remine_failed"] += 1
                    else:
                        stats["remine_failed"] += 1
            elif side and rng.random() < 0.7:
                cur_o = rng.choice(side)
        vv, nn, ln = L.audit(cur_o, cur_m)
        if vv == 0 and cur_c < home[0]:
            home = (cur_c, cur_o, dict(cur_m), ln)
            stats["home_improves"] += 1
            save_point(args.best_out, cur_c, cur_o, cur_m,
                       f"F-35 audit-aware branch loop; op={tag}; {ln}",
                       {"stats": dict(stats)})
            print(f"  *** CLEAN HOME {cur_c} via {tag}|{w} ({ln})", flush=True)
        print(f"  branch {stats['branches']:3d} op={tag:22s} w={w:8s} "
              f"end {cur_c}{' clean' if vv == 0 else ' DIRTY'} home {home[0]} "
              f"evals {stats['evals']} t={time.time()-t0:.0f}s", flush=True)

    print(f"\ndone: home CLEAN {home[0]} ({home[3]})", flush=True)
    print(json.dumps(stats), flush=True)
    if dirty_log:
        print("dirty-below-home points: " + json.dumps(sorted(dirty_log)[:20]), flush=True)
    if args.log:
        with open(args.log, "a") as f:
            f.write(json.dumps({"rng": args.rng, "home": home[0], "stats": stats,
                                "dirty": dirty_log}) + "\n")


if __name__ == "__main__":
    main()
