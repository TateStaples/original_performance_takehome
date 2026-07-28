"""H-064: extract the SETUP DEPENDENCY CHAIN op-by-op.

H-063 measured that freeing any single engine's setup ops is worth exactly
zero while freeing the whole 252-op setup phase together is worth -13.  That
signature is a serial dependency CHAIN, not slot pressure.  This tool names
the chain.

Definitions used throughout:
  est[i]    earliest start (longest path from the sources, floors included)
  lst[i]    latest start that does not extend the schedule (C-1 - tail[i])
  slack[i]  lst[i] - est[i]
  place[i]  where greedy actually put it

Commands (repo root):
  python3 tools/h064_chain.py setup       # every setup op, ordered by place
  python3 tools/h064_chain.py chain       # longest est-path inside setup
  python3 tools/h064_chain.py gate        # what gates the earliest steady work
  python3 tools/h064_chain.py head        # per-cycle head profile + who is ready
  python3 tools/h064_chain.py loads       # head load-bandwidth accounting
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtrack_sched as B  # noqa: E402
import h061_common as C  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def capture(**extra):
    kw = C.kwargs(**extra)
    old = B.H51_OVERRIDES
    B.H51_OVERRIDES = {}
    try:
        data = B.capture(kw)
    finally:
        B.H51_OVERRIDES = old
    ops = data["ops"]
    preds, floors = B.build_model(ops, data["pair_writes"])
    return data, ops, preds, floors


def names_of(scratch_debug):
    out: dict[int, str] = {}
    for addr, val in scratch_debug.items():
        name, length = (val if isinstance(val, tuple) else (val, 1))
        for k in range(int(length)):
            out[int(addr) + k] = f"{name}[{k}]" if int(length) > 1 else str(name)
    return out


def opname(op) -> str:
    for x in op[1]:
        if isinstance(x, str):
            return x
    return str(op[1][0])


def fmt_addrs(addrs, names):
    return ",".join(f"{a}:{names.get(a, '?')}" for a in addrs)


def analyse(data, ops, preds, floors):
    est = B.ests(ops, preds, floors)
    tail = B.tails(ops, preds)
    place = [op[9] for op in ops]
    n_cyc = data["n_cycles"]
    lst = [n_cyc - 1 - t for t in tail]
    slack = [lst[i] - est[i] for i in range(len(ops))]
    # binding predecessor under est (defines the est-critical chain)
    bind = [None] * len(ops)
    for i in range(len(ops)):
        b, best = None, floors[i]
        for j, lag in preds[i]:
            t = est[j] + lag
            if t > best:
                best, b = t, j
        bind[i] = b
    return est, tail, lst, slack, place, bind


def describe(i, ops, names, est, place, slack, bind, preds):
    op = ops[i]
    eng, reads, writes, tag = op[0], op[2], op[3], op[10]
    kind = "setup" if tag is None else f"tag={tag}"
    b = bind[i]
    bs = "-" if b is None else f"#{b}({opname(ops[b])}@est{est[b]})"
    return (f"#{i:<6} {eng:<5} {opname(op):<14} est={est[i]:<4} "
            f"pl={place[i]:<4} slack={slack[i]:<5} {kind:<12} "
            f"W[{fmt_addrs(writes, names)}] R[{fmt_addrs(reads, names)}] "
            f"bind={bs}")


def cmd_setup(ops, names, est, place, slack, bind, preds):
    idxs = [i for i in range(len(ops)) if ops[i][10] is None]
    idxs.sort(key=lambda i: (place[i], est[i], i))
    print(f"== {len(idxs)} setup ops (tag is None), ordered by placement ==")
    for i in idxs:
        print(describe(i, ops, names, est, place, slack, bind, preds))


def cmd_chain(ops, names, est, place, slack, bind, preds):
    """Longest est-path that ENDS in a setup op, plus the longest est-path
    inside the setup-op subgraph (setup->setup edges only)."""
    setup = [i for i in range(len(ops)) if ops[i][10] is None]
    # 1) global: setup op with the largest est
    tgt = max(setup, key=lambda i: est[i])
    path = []
    cur = tgt
    while cur is not None:
        path.append(cur)
        cur = bind[cur]
    path.reverse()
    print(f"== longest est-path ending at a SETUP op (est {est[tgt]}) ==")
    for i in path:
        print(describe(i, ops, names, est, place, slack, bind, preds))

    # 2) setup-only subgraph longest path (depth in ops, not est)
    dep = {}
    par = {}
    sset = set(setup)
    for i in setup:
        best, bp = 1, None
        for j, lag in preds[i]:
            if j in sset and dep.get(j, 0) + 1 > best:
                best, bp = dep[j] + 1, j
        dep[i], par[i] = best, bp
    tgt2 = max(setup, key=lambda i: dep[i])
    p2 = []
    cur = tgt2
    while cur is not None:
        p2.append(cur)
        cur = par[cur]
    p2.reverse()
    print(f"\n== deepest SETUP-ONLY chain: {len(p2)} ops ==")
    for i in p2:
        print(describe(i, ops, names, est, place, slack, bind, preds))


def cmd_gate(ops, names, est, place, slack, bind, preds):
    """What gates the earliest steady-state work?  For each of the first
    steady ops by est, walk back to the first SETUP ancestor."""
    steady = [i for i in range(len(ops)) if ops[i][10] is not None]
    steady.sort(key=lambda i: est[i])
    print("== est histogram of steady ops (first 40 est values) ==")
    h = Counter(est[i] for i in steady)
    for e in sorted(h)[:40]:
        print(f"  est={e:<4} n={h[e]}")
    print("\n== chain into the est-latest op in the whole stream ==")
    tgt = max(range(len(ops)), key=lambda i: est[i] + 0)
    print(f"  (max est = {est[tgt]} at #{tgt})")
    print("\n== deepest est-chain reaching cycle>=31 through setup ==")
    # ops whose est-chain passes through setup: pick steady ops with the
    # largest est whose binding ancestor chain contains a setup op
    def chain_of(i):
        out = []
        cur = i
        while cur is not None:
            out.append(cur)
            cur = bind[cur]
        return out[::-1]
    best = None
    for i in steady[:4000]:
        ch = chain_of(i)
        if any(ops[k][10] is None for k in ch) and (best is None or est[i] > est[best]):
            best = i
    if best is not None:
        for k in chain_of(best):
            print(describe(k, ops, names, est, place, slack, bind, preds))


def cmd_head(ops, names, est, place, slack, bind, preds, lo=0, hi=40):
    n_c = max(place) + 1
    occ = [dict.fromkeys(B.ENGINES, 0) for _ in range(n_c)]
    ready_cnt = [dict.fromkeys(B.ENGINES, 0) for _ in range(n_c)]
    for i, c in enumerate(place):
        occ[c][ops[i][0]] += 1
        if est[i] < n_c:
            ready_cnt[est[i]][ops[i][0]] += 1
    print(f"{'cyc':>4} | " + " ".join(f"{e[:4]:>9}" for e in B.ENGINES) +
          "   (occ/cap, [n ops with est==cyc])")
    for c in range(lo, min(hi, n_c)):
        cells = []
        for e in B.ENGINES:
            cells.append(f"{occ[c][e]:>2}/{SLOT_LIMITS[e]:<2}[{ready_cnt[c][e]:>2}]")
        print(f"{c:>4} | " + " ".join(f"{x:>9}" for x in cells))


def cmd_loads(ops, names, est, place, slack, bind, preds):
    ld = [i for i in range(len(ops)) if ops[i][0] == "load"]
    print(f"== {len(ld)} loads; est distribution in the head ==")
    h = Counter(min(est[i], 200) for i in ld)
    cum = 0
    for e in sorted(h):
        cum += h[e]
        if e <= 70:
            print(f"  est={e:<4} n={h[e]:<5} cum={cum}")
    print("\n== setup loads, ordered by placement ==")
    for i in sorted([i for i in ld if ops[i][10] is None], key=lambda i: place[i]):
        print(describe(i, ops, names, est, place, slack, bind, preds))


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "chain"
    data, ops, preds, floors = capture()
    names = names_of(data["scratch_debug"])
    est, tail, lst, slack, place, bind = analyse(data, ops, preds, floors)
    print(f"# stream {data['n_cycles']} cycles, {len(ops)} ops, "
          f"cp={max(e + t for e, t in zip(est, tail)) + 1}")
    fn = {"setup": cmd_setup, "chain": cmd_chain, "gate": cmd_gate,
          "head": cmd_head, "loads": cmd_loads}[cmd]
    fn(ops, names, est, place, slack, bind, preds)


if __name__ == "__main__":
    main()
