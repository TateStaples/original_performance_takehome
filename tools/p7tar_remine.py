"""P7-TAR: derive a parity-ring plan that COEXISTS with the with-idx tail.

Background.  `parity_ring` funds retained-parity vectors out of registers its
liveness model believes are dead.  `store_final_indices` (the with-idx tail)
resurrects every group's `st` (level-5 index, stored at the drain) and `nv`
(parity temp / newest-parity b3) at round 15, so a plan mined WITHOUT the tail
goes dirty: donors get overwritten while someone still needs them.  Measured on
the 1006 mainline: 0 liveness violations without the tail, 200 with it.

The fix is not to hand-exclude the tail's registers from the donor pool.  It is
to mine availability from the REALIZED tail-inclusive trace -- then donors whose
liveness the tail extends simply stop being available, and no exclusion list can
go stale.  Borrow-safety criterion is unchanged from
`tools/audit_ring_windows.py` (donor word must carry no live value across the
ring's borrow window); the oracle is `KernelBuilder.audit_ring_donor_liveness`.

Derivation, all under `store_final_indices=True`:
  1. Empty plan.  Fixpoint: build -> audit -> add every implicated ring to
     `parity_ring_drop` -> rebuild, until the audit is clean.  Dropping rings
     reschedules the stream, so new violations surface; the fixpoint is
     required (it is NOT a one-shot subtract).  Lands at 14 native rings.
  2. Mine fresh donor triples for the unfunded (epoch, group)s off that clean
     build's trace, prize-ordered (a served-at-L4 ring deletes 6-8 ops, an
     unserved one 3).
  3. Apply, fixpoint again, and re-mine until coverage stops growing.

Result at the 1006 stream (`h061_common.kwargs()`): 6 native drops + 17 mined
entries = 31/40 rings, 1034 cycles, values and indices exact on 10 seeds.
For comparison: ring-free + tail is 1048, and PRUNING the inherited (no-tail)
1006 plan tops out at 25 rings / 1036 -- every one of its 15 dropped rings goes
dirty again on re-add, so the prune set is exactly minimal.

Usage:
  python3 tools/p7tar_remine.py [--out FILE]      # derive + report
  python3 tools/p7tar_remine.py --verify FILE     # replay a saved plan
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import h061_common as C  # noqa: E402
from dev import KernelBuilder  # noqa: E402
from problem import VLEN  # noqa: E402

SHAPE = (256, 16, 10)
N_GROUPS = 32
DEFAULT_OUT = os.path.join(REPO_ROOT, "tools", "p7tar_best_plan_1034.json")


def build(drop, plan) -> KernelBuilder:
    kb = KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(*SHAPE, **C.kwargs(
        store_final_indices=True, b3l_safe_leaf_fallback=True,
        parity_ring_plan=tuple(plan), parity_ring_drop=tuple(sorted(drop)),
        # the derivation calls the audit itself; auto-ON would abort the
        # intermediate (still dirty) builds it needs to inspect.
        ring_liveness_assert=False))
    return kb


def fixpoint(drop, plan, limit: int = 12):
    """Drop every liveness-violating ring until the audit is clean."""
    drop = set(drop)
    for _ in range(limit):
        kb = build(drop, plan)
        if not kb.audit_ring_donor_liveness():
            return kb, drop
        drop |= set(kb._ring_liveness_bad)
    return None, drop


def _trace_index(kb):
    acc: dict[int, list[tuple[int, bool]]] = defaultdict(list)
    span: dict[Any, list[int]] = {}
    for idx, e in enumerate(kb.sched_trace):
        tag = e[2]
        for a in e[4]:
            acc[a].append((idx, False))
        for a in e[5]:
            acc[a].append((idx, True))
        if tag is not None:
            s = span.setdefault(tag, [idx, idx])
            s[1] = idx
    return acc, span


def mine(kb, drop, existing: dict) -> dict:
    """Greedy donor assignment for the unfunded rings, off kb's trace."""
    lay = kb._h048_layout
    period, rounds = lay["period"], lay["rounds"]
    served, ring_map = lay["served"], lay["parity_ring_map"]
    acc, span = _trace_index(kb)

    def ring_rounds(e):
        return range(0, 5) if e == 0 else range(period, rounds)

    def window(e, g):
        i = [x for r in ring_rounds(e) if (r, g) in span for x in span[(r, g)]]
        return (min(i), max(i)) if i else None

    def avail(a, lo, hi) -> bool:
        last_w = -1
        for i, w in acc.get(a, ()):
            if lo <= i <= hi:
                return False
            if w:
                last_w = i
            elif i > hi and last_w < lo:
                return False
        return True

    def prize(e, g) -> int:
        if e == 0:
            return 6 if served.get((4, g)) else 3
        return 8 if served.get((rounds - 1, g)) else 3

    # Donor classes are deliberately restricted to STRUCTURAL ones whose reads
    # cannot appear/disappear with schedule state -- see audit_ring_windows.py:
    # emit_any races read DIFFERENT addresses per encoding, so any
    # race-alternative operand is unsafe to borrow.  Do NOT widen this set.
    cands = list(lay["state_vecs"] or []) + list(lay["node_val_vecs"] or [])
    lt = lay.get("level_table")
    if lt is not None:
        cands += [lt + k * VLEN for k in range(lay["level_table_word_count"] // VLEN)]
    for a0, (nm, _ln) in kb.scratch_debug.items():
        if nm == "root_nv_vec":
            cands.append(a0)
    cands = sorted(set(cands))

    unfunded = [(e, g) for e in (0, 1) for g in range(N_GROUPS)
                if (e, g) not in ring_map and (e, g) not in drop]
    win = {eg: window(*eg) for eg in unfunded}
    unfunded = [eg for eg in unfunded if win.get(eg)]
    free = {eg: {a for a in range(kb.scratch_next_addr) if avail(a, *win[eg])}
            for eg in unfunded}

    committed: dict[int, list[tuple[int, int]]] = defaultdict(list)
    plan = dict(existing)
    for eg, bases in existing.items():          # already-placed entries hold their windows
        w = window(*eg)
        if w:
            for b in bases:
                for x in range(b, b + VLEN):
                    committed[x].append(w)

    order = sorted(unfunded, key=lambda eg: (-prize(*eg), eg))
    for pos, eg in enumerate(order):
        lo, hi = win[eg]
        fr = free[eg]
        pending = [x for x in order[pos + 1:]
                   if x not in plan and not (win[x][1] < lo or hi < win[x][0])]
        scored = []
        for a in cands:
            if any(x not in fr for x in range(a, a + VLEN)):
                continue
            if any(not (chi < lo or hi < clo)
                   for x in range(a, a + VLEN) for clo, chi in committed[x]):
                continue
            # scarcity: prefer donors that few other overlapping windows want
            scored.append((sum(1 for p in pending
                               if free.get(p) and all(x in free[p] for x in range(a, a + VLEN))), a))
        scored.sort()
        picks: list[int] = []
        claimed: set[int] = set()
        for _s, a in scored:
            if len(picks) == 3:
                break
            if all(x not in claimed for x in range(a, a + VLEN)):
                picks.append(a)
                claimed.update(range(a, a + VLEN))
        if len(picks) == 3:
            plan[eg] = tuple(sorted(picks))
            for b in picks:
                for x in range(b, b + VLEN):
                    committed[x].append((lo, hi))
    return plan


def derive(rounds_limit: int = 6):
    drop: set = set()
    plan: dict = {}
    best = None
    for it in range(rounds_limit):
        kb, drop = fixpoint(drop, tuple(sorted(plan.items())))
        assert kb is not None, "no clean liveness fixpoint"
        nr, cy = len(kb._h048_layout["parity_ring_map"]), len(kb.instrs)
        print(f"iter {it}: rings={nr:3d} cycles={cy} drop={len(drop)} plan={len(plan)}", flush=True)
        if best is None or cy < best[0]:
            best = (cy, nr, dict(plan), set(drop))
        newplan = mine(kb, drop, plan)
        if len(newplan) == len(plan):
            print("  mine adds nothing -> converged")
            break
        plan = newplan
    return best


def verify(path: str) -> None:
    d = json.load(open(path))
    drop = tuple(tuple(x) for x in d["drop"])
    plan = tuple((tuple(k), tuple(v)) for k, v in d["plan"])
    kb = KernelBuilder()
    # assert left at its auto-ON default: this build must pass it.
    kb.build_kernel_scheduled(*SHAPE, **C.kwargs(
        store_final_indices=True, b3l_safe_leaf_fallback=True,
        parity_ring_plan=plan, parity_ring_drop=drop))
    print(f"verify {path}: cycles={len(kb.instrs)} "
          f"rings={len(kb._h048_layout['parity_ring_map'])} "
          f"scratch={kb.scratch_next_addr} (liveness assert passed)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--verify", default=None)
    args = ap.parse_args()
    if args.verify:
        verify(args.verify)
        return
    cy, nr, plan, drop = derive()
    print(f"BEST rings={nr} cycles={cy} drop={sorted(drop)}")
    out = args.out or DEFAULT_OUT
    json.dump({"drop": sorted(drop),
               "plan": [[list(k), list(v)] for k, v in sorted(plan.items())]},
              open(out, "w"))
    print(f"written to {out}")


if __name__ == "__main__":
    main()
