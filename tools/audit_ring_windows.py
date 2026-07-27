"""H-048 scratch-availability audit + global ring-funding planner.

Windows: ring accesses for (epoch, g) span rounds [0..4] (epoch 0) /
[11..15] (epoch 1): the P0 write is emitted at the END of round e_base
(feeding level 1), reads end at L4 (round 4 / 15).

Safety criterion per donor word w and window [lo,hi] (emission indices):
  (a) no access to w inside [lo,hi];
  (b) every read of w after hi has its defining write after hi
      (no live range spans the window).
Multi-window reuse of a donor is safe iff the windows are disjoint
(ring's first access is a write, so an earlier ring's accesses act like
"donor accesses before the window").

Usage: python audit_h048.py [--set k=v ...] [--plan-out FILE]
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from dev import KernelBuilder  # noqa: E402
from problem import VLEN  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402

CONFIG = {"parity_ring": True, "l4_gmin": (7, 30)}


def build(overrides: dict[str, Any]):
    kwargs = dict(BASE_KWARGS)
    kwargs.update(CONFIG)
    kwargs.update(overrides)
    kb = KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs)
    return kb


def main():
    overrides = {}
    plan_out = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--set":
            k, v = args[i + 1].split("=", 1)
            overrides[k] = parse_value(v)
            i += 2
        elif args[i] == "--plan-out":
            plan_out = args[i + 1]
            i += 2
        else:
            i += 1
    kb = build(overrides)
    trace = kb.sched_trace
    lay = kb._h048_layout
    period, rounds = lay["period"], lay["rounds"]
    ring_map = lay["parity_ring_map"]
    n_groups = SHAPE["batch_size"] // VLEN
    total = kb.scratch_next_addr
    served = lay["served"]

    # identity map addr -> label
    label_of: dict[int, str] = {}
    for nm in ("state_vecs", "hash_chain_vecs", "node_val_vecs"):
        short = {"state_vecs": "st", "hash_chain_vecs": "val", "node_val_vecs": "nv"}[nm]
        for g, base in enumerate(lay[nm] or []):
            for a in range(base, base + VLEN):
                label_of[a] = f"{short}{g}"
    for nm in ("temp_pool", "condA", "condB", "tm", "tmM"):
        for k, base in enumerate(lay[nm] or []):
            for a in range(base, base + VLEN):
                label_of[a] = f"{nm}[{k}]"
    blocks = sorted((a, n, ln) for a, (n, ln) in kb.scratch_debug.items())
    for a0, n, ln in blocks:
        for a in range(a0, a0 + ln):
            label_of.setdefault(a, n if ln == 1 else f"{n}+{a - a0}")

    def klass(a: int) -> str:
        lab = label_of.get(a, "anon")
        for p in ("st", "val", "nv", "va", "rec"):
            if lab.startswith(p) and lab[len(p):].isdigit():
                return p
        return lab.split("[")[0].split("+")[0]

    acc: dict[int, list[tuple[int, str]]] = defaultdict(list)
    span: dict[tuple[int, int], list[int]] = {}
    for idx, (cyc, eng, tag, slot, reads, writes, mr, mw) in enumerate(trace):
        for a in reads:
            acc[a].append((idx, "r"))
        for a in writes:
            acc[a].append((idx, "w"))
        if tag is not None:
            s = span.setdefault(tag, [idx, idx])
            s[1] = idx

    def ring_rounds(epoch: int) -> list[int]:
        return list(range(0, 5)) if epoch == 0 else list(range(period, rounds))

    def window(epoch: int, g: int) -> tuple[int, int] | None:
        idxs = []
        for r in ring_rounds(epoch):
            if (r, g) in span:
                idxs += span[(r, g)]
        return (min(idxs), max(idxs)) if idxs else None

    def available(addr: int, lo: int, hi: int) -> bool:
        events = acc.get(addr)
        if not events:
            return True
        last_w = -1
        for i, k in events:
            if lo <= i <= hi:
                return False
            if k == "w":
                last_w = i
            elif i > hi and last_w < lo:
                return False
        return True

    # sanity: verify every FUNDED ring's donors satisfy the criterion when
    # ring accesses themselves are removed from the donor's access list
    print("-- funded-ring safety recheck (donor real accesses vs window) --")
    bad = 0
    for (epoch, g), bases in sorted(ring_map.items()):
        w = window(epoch, g)
        assert w
        lo, hi = w
        for b in bases:
            for a in range(b, b + VLEN):
                events = [ev for ev in acc.get(a, []) if not (lo <= ev[0] <= hi)]
                # donor real accesses = accesses outside this ring's window
                # (ring accesses are inside); check live-across on the rest
                last_w = -1
                for i, k in events:
                    if k == "w":
                        last_w = i
                    elif i > hi and last_w < lo:
                        print(f"  LIVE-ACROSS?? ({epoch},{g}) donor {label_of.get(a)} read@{i}")
                        bad += 1
    print(f"  {'OK' if not bad else f'{bad} violations'} over {len(ring_map)} rings")

    unfunded = [(e, g) for e in (0, 1) for g in range(n_groups) if (e, g) not in ring_map]

    def prize(e: int, g: int) -> int:
        if e == 0:
            return 6 if served.get((4, g)) else 3
        return 8 if served.get((rounds - 1, g)) else 3

    # ---- per-window availability report ----
    win_of = {}
    free_of = {}
    print("\n-- availability per unfunded window (corrected rounds 0-4 / 11-15) --")
    for (e, g) in unfunded:
        w = window(e, g)
        win_of[(e, g)] = w
        if w is None:
            continue
        lo, hi = w
        free = {a for a in range(total) if available(a, lo, hi)}
        free_of[(e, g)] = free
        by_class: dict[str, int] = defaultdict(int)
        for a in free:
            by_class[klass(a)] += 1
        cls = ", ".join(f"{k}:{v}" for k, v in sorted(by_class.items(), key=lambda t: -t[1])[:9])
        print(f"  ({e},{g:2d}) prize={prize(e, g)} win={w} free={len(free):4d}  {cls}")

    # ---- global greedy plan ----
    # word -> list of committed emission intervals (its own busy intervals
    # are implicit via availability; commitments are ring windows assigned)
    committed: dict[int, list[tuple[int, int]]] = defaultdict(list)
    plan: dict[tuple[int, int], tuple[int, int, int]] = {}
    order = sorted(unfunded, key=lambda eg: (-prize(*eg), eg))

    # H-048 soundness restriction: donors limited to STRUCTURAL classes
    # whose reads cannot appear/disappear with schedule state. emit_any
    # races read DIFFERENT addresses per encoding (dual_fold: diff vs odd
    # table; race_idx_madd: rec scalar vs rec vector, one_c vs
    # two_vec/omf_vec), so any race-alternative operand is unsafe to
    # borrow -- its read may materialize inside a window only in the
    # modified build (root cause of the (1,1) miscompare on addr 227).
    candidate_bases: list[int] = []
    for nm in ("state_vecs", "node_val_vecs"):
        candidate_bases += list(lay[nm] or [])
    lt = lay.get("level_table")
    if lt is not None:
        for k in range(lay["level_table_word_count"] // VLEN):
            candidate_bases.append(lt + k * VLEN)
    for a0, n, ln in blocks:
        if n == "root_nv_vec":
            candidate_bases.append(a0)
    candidate_bases = sorted(set(candidate_bases))

    def base_ok(a: int, free: set[int], lo: int, hi: int,
                extra_claimed: set[int]) -> bool:
        for x in range(a, a + VLEN):
            if x not in free or x in extra_claimed:
                return False
            for (clo, chi) in committed[x]:
                if not (chi < lo or hi < clo):
                    return False
        return True

    for pos, (e, g) in enumerate(order):
        w = win_of.get((e, g))
        if w is None:
            continue
        lo, hi = w
        free = free_of[(e, g)]
        # candidate bases with a scarcity score: how many OTHER pending
        # overlapping windows could also use this base (lower = pick first)
        pending = []
        for (e2, g2) in order[pos + 1:]:
            if (e2, g2) in plan:
                continue
            w2 = win_of.get((e2, g2))
            if w2 and not (w2[1] < lo or hi < w2[0]):
                pending.append((e2, g2))
        cands: list[tuple[int, int]] = []
        for a in candidate_bases:
            if not base_ok(a, free, lo, hi, set()):
                continue
            score = 0
            for eg2 in pending:
                f2 = free_of.get(eg2)
                if f2 and all(x in f2 for x in range(a, a + VLEN)):
                    score += 1
            cands.append((score, a))
        cands.sort()
        picks: list[int] = []
        claimed: set[int] = set()
        for score, a in cands:
            if len(picks) == 3:
                break
            if all(x not in claimed for x in range(a, a + VLEN)):
                picks.append(a)
                claimed.update(range(a, a + VLEN))
        if len(picks) == 3:
            plan[(e, g)] = tuple(sorted(picks))
            for b in picks:
                for x in range(b, b + VLEN):
                    committed[x].append((lo, hi))

    print(f"\n-- global plan: {len(plan)} new rings ({sum(prize(*eg) for eg in plan)} ops) --")
    for (e, g), picks in sorted(plan.items()):
        labs = [label_of.get(b, str(b)) for b in picks]
        print(f"  ({e},{g:2d}) prize={prize(e, g)} <- {picks}  {labs}")
    unmet = [eg for eg in unfunded if eg not in plan and win_of.get(eg)]
    print(f"unfunded remaining: {len(unmet)}: {unmet}")
    new_words = 24 * len(plan)
    print(f"words newly ring-funded: {new_words} (distance to 384-word full-retention: "
          f"{384 - new_words})")
    if plan_out:
        with open(plan_out, "w") as f:
            f.write(repr(tuple(sorted((eg, picks) for eg, picks in plan.items()))))
        print(f"plan written to {plan_out}")


if __name__ == "__main__":
    main()
