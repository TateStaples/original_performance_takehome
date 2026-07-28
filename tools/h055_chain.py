#!/usr/bin/env python3
"""H-055: extract and characterize the critical path(s) of the 1022 build.

Reuses backtrack_sched's exact op-stream capture + precedence DAG (read-only;
that module is NOT modified -- H51_OVERRIDES is patched in-process).

Subcommands
    cp        longest path through the DAG, printed op-by-op with engine,
              slot opname, (round, group) tag and the RAW register that
              carries each edge; plus the engine-transition census
              (how many valu<->load alternations, at which ops).
    cycle     per-cycle engine occupancy profile + saturation windows.
    slack     per-op total slack (lst - est); which ops are ON any CP.
    rounds    per-(round,group) chain depth decomposition.

Usage (repo root):
    PYTHONPATH=.:tools python3 tools/h055_chain.py cp
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import backtrack_sched as B  # noqa: E402
import h054_common as C  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

ENGINES = ("valu", "alu", "load", "flow", "store")


PLAN_ENV = "H055_PLAN"   # override the emission plan (e.g. tools/f13_best_plan_1020.json)


def frontier_kwargs(**extra):
    """h054_common's frontier config, with the emission plan overridable via
    $H055_PLAN so the tools track mainline as F-13's order walks land."""
    kw = C.frontier_kwargs(**extra)
    plan = os.environ.get(PLAN_ENV)
    if plan:
        import emission_order_search as eos
        kw["emission_plan"] = eos.load_plan(plan)
    return kw


def frontier_capture():
    """Capture the frontier op stream (patch H51_OVERRIDES in-process)."""
    kw = frontier_kwargs()
    kw.pop("debug_compares", None)
    B.H51_OVERRIDES.clear()
    data = B.capture(overrides=kw)
    return data


def model(data):
    ops = data["ops"]
    preds, floors = B.build_model(ops, data["pair_writes"])
    return ops, preds, floors


def opname(op):
    slot = op[1]
    return slot[0] if isinstance(slot, tuple) else str(slot)


def describe(i, ops):
    eng, slot, reads, writes, mr, mw, _a, _b, mc, cyc, tag = ops[i]
    return (f"#{i:6d} c={cyc:5d} {eng:5s} {opname(ops[i]):14s} "
            f"tag={str(tag):10s} r={list(reads)[:3]} w={list(writes)[:2]}")


def critical_path(ops, preds, floors):
    est = B.ests(ops, preds, floors)
    h = B.tails(ops, preds)
    best = max(range(len(ops)), key=lambda i: est[i] + h[i])
    cp_len = est[best] + h[best] + 1
    # walk backwards from `best` to a source, then forward from `best`
    path = [best]
    i = best
    while True:
        cand = None
        for j, lag in preds[i]:
            if est[j] + lag == est[i] and lag > 0:
                cand = j
                break
        if cand is None:
            for j, lag in preds[i]:
                if est[j] + lag == est[i]:
                    cand = j
                    break
        if cand is None:
            break
        path.append(cand)
        i = cand
    path.reverse()
    # forward extension: successors
    succs = defaultdict(list)
    for a in range(len(ops)):
        for j, lag in preds[a]:
            succs[j].append((a, lag))
    i = best
    while True:
        cand = None
        for a, lag in succs.get(i, ()):
            if est[a] == est[i] + lag and h[i] == h[a] + lag:
                cand = a
                break
        if cand is None:
            break
        path.append(cand)
        i = cand
    return cp_len, path, est, h


def cmd_cp(args):
    data = frontier_capture()
    ops, preds, floors = model(data)
    print(f"captured {len(ops)} ops, greedy cycles {data['n_cycles']}")
    lb = B.lb_total(ops, preds, floors)
    print("LB:", lb)
    cp_len, path, est, h = critical_path(ops, preds, floors)
    print(f"\ncritical path length {cp_len}, {len(path)} ops on it")

    # engine transition census along the path
    engs = [ops[i][0] for i in path]
    trans = Counter()
    for a, b in zip(engs, engs[1:]):
        if a != b:
            trans[(a, b)] += 1
    print("\nengine sequence census on CP:", Counter(engs))
    print("engine transitions on CP:")
    for (a, b), n in trans.most_common():
        print(f"   {a:5s} -> {b:5s}  {n}")
    vl = trans[("valu", "load")] + trans[("load", "valu")]
    print(f"  valu<->load alternations on CP: {vl}")

    # print the path, grouped by tag
    print("\n--- CP ops ---")
    prev_tag = "INIT"
    for k, i in enumerate(path):
        tag = ops[i][10]
        if tag != prev_tag:
            print(f"  == tag {tag} ==")
            prev_tag = tag
        print("   ", describe(i, ops), f"est={est[i]}")
        if args.limit and k >= args.limit:
            print(f"    ... ({len(path)-k} more)")
            break


def cmd_cycle(args):
    data = frontier_capture()
    ops = data["ops"]
    n = data["n_cycles"]
    span = max(op[9] for op in ops) + 1
    occ = [Counter() for _ in range(span)]
    for op in ops:
        occ[op[9]][op[0]] += 1
    print(f"span {span} cycles (nonempty {n})")
    tot = Counter()
    for op in ops:
        tot[op[0]] += 1
    print("slots:", dict(tot))
    print("floors:", {e: -(-tot[e] // SLOT_LIMITS[e]) for e in tot})
    # saturation windows
    print("\ncycle-block occupancy (means per 50-cycle block, %% of width):")
    print(f"{'blk':>6} " + " ".join(f"{e:>7}" for e in ENGINES) + "   full3")
    for s in range(0, span, 50):
        e = min(s + 50, span)
        w = e - s
        row = []
        for eng in ENGINES:
            u = sum(occ[c][eng] for c in range(s, e)) / (w * SLOT_LIMITS[eng])
            row.append(f"{100*u:6.1f}%")
        full3 = sum(1 for c in range(s, e)
                    if occ[c]["valu"] >= SLOT_LIMITS["valu"]
                    and occ[c]["alu"] >= SLOT_LIMITS["alu"]
                    and occ[c]["load"] >= SLOT_LIMITS["load"])
        print(f"{s:6d} " + " ".join(row) + f"   {full3:3d}/{w}")
    # exact counts of simultaneous saturation
    both = sum(1 for c in range(span)
               if occ[c]["valu"] >= 6 and occ[c]["load"] >= 2)
    vfull = sum(1 for c in range(span) if occ[c]["valu"] >= 6)
    lfull = sum(1 for c in range(span) if occ[c]["load"] >= 2)
    afull = sum(1 for c in range(span) if occ[c]["alu"] >= 12)
    print(f"\nvalu-full {vfull}  alu-full {afull}  load-full {lfull}  valu&load-full {both}")


def cmd_slack(args):
    data = frontier_capture()
    ops, preds, floors = model(data)
    est = B.ests(ops, preds, floors)
    h = B.tails(ops, preds)
    cp = max(e + t for e, t in zip(est, h)) + 1
    slack = [cp - 1 - (est[i] + h[i]) for i in range(len(ops))]
    zero = [i for i in range(len(ops)) if slack[i] == 0]
    print(f"CP {cp}; ops with zero slack (on SOME critical path): {len(zero)}")
    by = Counter((ops[i][0], opname(ops[i])) for i in zero)
    for k, v in by.most_common(30):
        print(f"   {k[0]:6s} {k[1]:16s} {v}")
    # distribution of slack
    print("\nslack histogram (all ops):")
    hist = Counter(min(s // 50, 20) for s in slack)
    for b in sorted(hist):
        print(f"   {b*50:5d}-{b*50+49:5d}: {hist[b]}")
    # by tag: how much of the CP each (round,group) owns
    tagc = Counter(ops[i][10] for i in zero if ops[i][10] is not None)
    print("\nzero-slack ops by tag (top 25):")
    for k, v in tagc.most_common(25):
        print(f"   {k}: {v}")


def cmd_rounds(args):
    """Per-(round,group) chain depth: est span of each tag's ops."""
    data = frontier_capture()
    ops, preds, floors = model(data)
    est = B.ests(ops, preds, floors)
    spans = {}
    for i, op in enumerate(ops):
        t = op[10]
        if t is None:
            continue
        lo, hi = spans.get(t, (10**9, -1))
        spans[t] = (min(lo, est[i]), max(hi, est[i]))
    # per-round: min est over groups, max est
    per_round = defaultdict(lambda: (10**9, -1))
    for (r, g), (lo, hi) in spans.items():
        a, b = per_round[r]
        per_round[r] = (min(a, lo), max(b, hi))
    print("round   est_lo  est_hi   depth   delta_lo")
    prev = None
    for r in sorted(per_round):
        lo, hi = per_round[r]
        d = "" if prev is None else str(lo - prev)
        print(f"{r:5d}  {lo:7d} {hi:7d} {hi-lo:7d}   {d}")
        prev = lo
    # per-group chain for a representative group
    g0 = 0
    print(f"\ngroup {g0} per-round est window:")
    for r in range(16):
        if (r, g0) in spans:
            lo, hi = spans[(r, g0)]
            print(f"  r={r:2d} est {lo:5d}..{hi:5d}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cp", "cycle", "slack", "rounds"])
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    {"cp": cmd_cp, "cycle": cmd_cycle, "slack": cmd_slack,
     "rounds": cmd_rounds}[args.cmd](args)


if __name__ == "__main__":
    main()
