"""H-061: rigorous ramp/drain bounds on the LOAD engine.

For the captured op stream and its constraint DAG:

  est[i]  = earliest cycle op i can possibly occupy (release date)
  h[i]    = tail height: op i must be followed by >= h[i] more cycles

Two staircase (energetic) bounds hold for ANY feasible packing of the
stream, not just greedy's:

  head:  makespan >= t + ceil(#{load ops with est >= t} / 2)
  drain: makespan >= ceil(#{load ops with h >= k} / 2) + k

and, dually, the load engine PROVABLY cannot be saturated over [0, c)
whenever  #{load ops with est < c} < 2c  -- the deficit
  head_deficit(c) = 2c - #{est < c}
is load capacity that no scheduler whatsoever can use.

Usage: python3 tools/h061_bound.py [gmin ...]
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtrack_sched as B  # noqa: E402
import h061_attrib as A  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def analyse(a: str) -> None:
    g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
    data, ops, preds, floors = A.capture_stream(g)
    place = [op[9] for op in ops]
    n_cycles = max(place) + 1
    est = B.ests(ops, preds, floors)
    h = B.tails(ops, preds)
    load = [i for i in range(len(ops)) if ops[i][0] == "load"]
    cap = SLOT_LIMITS["load"]
    nl = len(load)
    floor = -(-nl // cap)

    # address-independent loads: no predecessor edges at all
    indep = [i for i in load if not preds[i]]

    # head staircase: max over t of t + ceil(#{est >= t}/cap)
    ev = sorted((est[i] for i in load), reverse=True)
    head_v, head_at = 0, None
    for cnt, t in enumerate(ev, 1):
        v = t + -(-cnt // cap)
        if v > head_v:
            head_v, head_at = v, (t, cnt)
    hv = sorted((h[i] for i in load), reverse=True)
    tail_v, tail_at = 0, None
    for cnt, k in enumerate(hv, 1):
        v = k + -(-cnt // cap)
        if v > tail_v:
            tail_v, tail_at = v, (k, cnt)

    # 2D energetic bound: every load with est >= t and tail >= k must live in
    # the window [t, M-k], so M >= t + k + ceil(#{est>=t, h>=k}/cap).
    ks = sorted({h[i] for i in load if h[i] <= 400})
    best2, at2 = 0, None
    for k in ks:
        sub = sorted((est[i] for i in load if h[i] >= k), reverse=True)
        for cnt, t in enumerate(sub, 1):
            v = t + k + -(-cnt // cap)
            if v > best2:
                best2, at2 = v, (t, k, cnt)

    # head deficit profile: load capacity that NO schedule can use in [0, c)
    est_sorted = sorted(est[i] for i in load)
    prof = {}
    j = 0
    for c in (32, 51, 65, 100, 150, 200):
        cnt = sum(1 for e in est_sorted if e < c)
        prof[c] = cap * c - min(cap * c, cnt)

    print(json.dumps({
        "label": a,
        "cycles": n_cycles,
        "loads": nl,
        "load_floor(naive)": floor,
        "addr_independent_loads": len(indep),
        "head_staircase_bound": head_v, "head_at(est,count)": head_at,
        "drain_staircase_bound": tail_v, "drain_at(tail,count)": tail_at,
        "energetic_2d_bound": best2, "at(est,tail,count)": at2,
        "unusable_head_slots_by_cycle": prof,
        "loads_est_lt_65": sum(1 for i in load if est[i] < 65),
    }))


def chain(a: str) -> None:
    """Walk the est-critical chain into the EARLIEST gather -- the 51-cycle
    release date that dominates the energetic bound."""
    g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
    data, ops, preds, floors = A.capture_stream(g)
    place = [op[9] for op in ops]
    est = B.ests(ops, preds, floors)
    load = [i for i in range(len(ops)) if ops[i][0] == "load"]
    # the earliest gather (a load whose est is >= 10, i.e. not setup)
    gathers = [i for i in load if ops[i][1][0] == "load" and ops[i][10]]
    tgt = min(gathers, key=lambda i: est[i])
    print(f"== {a}: earliest gather op#{tgt} est={est[tgt]} "
          f"placed={place[tgt]} tag={ops[tgt][10]} ==")
    path = []
    cur = tgt
    while True:
        path.append(cur)
        nxt, best = None, -1
        for j, lag in preds[cur]:
            if est[j] + lag > best:
                best, nxt = est[j] + lag, j
        if nxt is None or best < floors[cur] or best <= 0:
            break
        cur = nxt
    path.reverse()
    from collections import Counter
    kinds: Counter[str] = Counter()
    for k, i in enumerate(path):
        kinds[f"{ops[i][0]}:{A.opname_of(ops[i])}"] += 1
    print(f"chain length {len(path)} ops, est span "
          f"{est[path[0]]} -> {est[path[-1]]}")
    print("chain composition:", dict(kinds.most_common()))
    print("first 6:", [(ops[i][0], A.opname_of(ops[i]), est[i], ops[i][10])
                       for i in path[:6]])
    print("last 6 :", [(ops[i][0], A.opname_of(ops[i]), est[i], ops[i][10])
                       for i in path[-6:]])
    tags = [ops[i][10] for i in path if ops[i][10]]
    print("rounds touched:", sorted({t[0] for t in tags}))


def main() -> None:
    args = sys.argv[1:]
    if args and args[0] == "chain":
        for a in (args[1:] or ["main"]):
            chain(a)
        return
    for a in (args or ["main", "16,31", "20,31", "28,31"]):
        analyse(a)


if __name__ == "__main__":
    main()
