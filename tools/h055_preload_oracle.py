#!/usr/bin/env python3
"""H-055: DAG oracle for DEINTERLEAVED PAIR-PRELOAD (the user's mechanism).

Surgical edit of backtrack_sched's exact captured op stream (whose offline
greedy reproduces the real 1022 schedule cycle-for-cycle), so a mechanism can
be costed WITHOUT implementing it in dev.py.

At a gather site the current chain is

    hash -> par(&)  ->  A: st = base -/+ par  ->  8x load(nv[l]=mem[st[l]])
         -> fold-in ^ (next round's hash)

`base` is already parity-free and hoisted (a madd emitted before the hash).
Pair-preload replaces it with

    M: base            ->  8x load(nv [l] = mem[base[l]])
       base2 = base-/+1 ->  8x load(nv2[l] = mem[base2[l]])      (both hoisted)
    hash -> par(&) -> vselect(nv, par, nv2, nv) -> fold-in ^

i.e. the post-parity chain drops from {arith, load} to {vselect}: -1
dependency level per site, at the price of +8 load slots, +1 valu op
(base2) and -0/+1 flow op per site, plus 16 scratch words.

The oracle applies that rewrite to a chosen SUBSET of sites and reports the
offline-greedy cycle count. It is an OPTIMISTIC ceiling: scratch is assumed
free (fresh virtual registers), and the extra loads are emitted as early as
the model allows.

Usage (repo root):
    PYTHONPATH=.:tools python3 tools/h055_preload_oracle.py sites
    PYTHONPATH=.:tools python3 tools/h055_preload_oracle.py run --last N
    PYTHONPATH=.:tools python3 tools/h055_preload_oracle.py run --all
    PYTHONPATH=.:tools python3 tools/h055_preload_oracle.py sweep
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import backtrack_sched as B  # noqa: E402
import h054_common as C  # noqa: E402

VIRT = 100000  # virtual scratch base (oracle assumes scratch is free)
LOAD_ENGINE = "load"  # set to "oracle" by --free-loads (isolates the CHAIN gain)


def enable_free_loads() -> None:
    """Give the gathers a 64-wide zero-cost engine: isolates pair-preload's
    LATENCY effect from its load-throughput cost (upper bound on the chain
    gain alone)."""
    global LOAD_ENGINE
    from problem import SLOT_LIMITS
    SLOT_LIMITS["oracle"] = 64
    B.ENGINES = tuple(e for e in SLOT_LIMITS if e != "debug")
    LOAD_ENGINE = "oracle"


def capture():
    kw = C.frontier_kwargs()
    B.H51_OVERRIDES.clear()
    return B.capture(overrides=kw)


def find_sites(ops):
    """Return [(first_load_idx, n_loads, st, A_idx, M_idx, par, P_idx, tag)]."""
    n = len(ops)
    # group consecutive scalar gather loads
    runs = []
    i = 0
    while i < n:
        e, slot = ops[i][0], ops[i][1]
        if e == "load" and slot[0] == "load" and ops[i][10] is not None:
            j = i
            while (j < n and ops[j][0] == "load" and ops[j][1][0] == "load"
                   and ops[j][10] == ops[i][10]):
                j += 1
            runs.append((i, j - i))
            i = j
        else:
            i += 1
    sites = []
    for first, cnt in runs:
        st = min(ops[first][2])          # base scratch of the address vector
        # last writer of st before `first`
        A = None
        for k in range(first - 1, -1, -1):
            if st in ops[k][3]:
                A = k
                break
        if A is None:
            continue
        reads = list(ops[A][2])
        par = None
        for a in reads:
            if a != st:
                par = a
        M = None
        for k in range(A - 1, -1, -1):
            if st in ops[k][3]:
                M = k
                break
        P = None
        if par is not None:
            for k in range(A - 1, -1, -1):
                if par in ops[k][3]:
                    P = k
                    break
        sites.append(dict(first=first, cnt=cnt, st=st, A=A, M=M, par=par,
                          P=P, tag=ops[first][10]))
    return sites


def rewrite(ops, sites, chosen):
    """Return a new op list with pair-preload applied at `chosen` site idxs."""
    ins_after = defaultdict(list)   # emission index -> ops to append after it
    drop = set()
    virt = VIRT
    for si in chosen:
        s = sites[si]
        if s["M"] is None or s["P"] is None or s["A"] is None:
            continue
        first, cnt, st, A, P = s["first"], s["cnt"], s["st"], s["A"], s["P"]
        nv = min(ops[first][3])
        st2 = virt
        nv2 = virt + 16
        virt += 32
        anchor = s["M"]
        # base2 = base -/+ 1 (valu, parity-free, right after the hoisted madd)
        extra = [("valu", ("+", st2, st, 0), tuple(range(st, st + cnt)),
                  tuple(range(st2, st2 + cnt)),
                  False, False, False, False, 0, 0, s["tag"])]
        # the 8 mirror loads, hoisted to just after the madd
        for lane in range(cnt):
            extra.append((LOAD_ENGINE, ("load", nv2 + lane, st2 + lane),
                          (st2 + lane,), (nv2 + lane,), True, False,
                          ops[first][6], ops[first][7], ops[first][8], 0, s["tag"]))
        ins_after[anchor].extend(extra)
        # the ORIGINAL 8 loads must now read `base` (written by M), not the
        # post-parity address: drop A and move the loads next to the mirrors.
        drop.add(A)
        for k in range(first, first + cnt):
            drop.add(k)
            e, slot, rd, wr, mr, mw, a, b, mc, cy, tg = ops[k]
            lane = min(rd) - st
            ins_after[anchor].append(
                (LOAD_ENGINE, ("load", nv + lane, st + lane), (st + lane,),
                 (nv + lane,), mr, mw, a, b, mc, 0, tg))
        # The value select must be emitted after BOTH the parity op and the
        # (hoisted) loads. dev.py emits the parity BEFORE the address madd,
        # so the anchor is max(P, M) -- appending to the same bucket keeps
        # it behind the loads inserted there.
        ins_after[max(P, anchor)].append(
            ("flow", ("vselect", nv, s["par"], nv2, nv),
             (s["par"],) + tuple(range(nv2, nv2 + cnt)) + tuple(range(nv, nv + cnt)),
             tuple(range(nv, nv + cnt)),
             False, False, False, False, 0, 0, s["tag"]))
    out = []
    for i, op in enumerate(ops):
        if i not in drop:
            out.append(op)
        out.extend(ins_after.get(i, ()))
    return out


def run_model(ops, pair_writes):
    preds, floors = B.build_model(ops, pair_writes)
    place, n = B.greedy_schedule(ops, preds, floors)
    lb = B.lb_total(ops, preds, floors)
    return n, lb


def cmd_sites(args):
    data = capture()
    ops = data["ops"]
    sites = find_sites(ops)
    print(f"{len(sites)} gather sites ({sum(s['cnt'] for s in sites)} load slots)")
    from collections import Counter
    print("loads/site:", Counter(s["cnt"] for s in sites))
    print("sites with a resolvable (M, P, A) triple:",
          sum(1 for s in sites if s["M"] is not None and s["P"] is not None))
    print("\nlast 12 sites (emission order) — the drain:")
    for s in sites[-12:]:
        print(f"   tag={s['tag']} first={s['first']} cnt={s['cnt']} "
              f"A@c={ops[s['A']][9]} P@c={ops[s['P']][9] if s['P'] is not None else None} "
              f"M@c={ops[s['M']][9] if s['M'] is not None else None} "
              f"load@c={ops[s['first']][9]}")


def cmd_run(args):
    data = capture()
    ops = data["ops"]
    pw = data["pair_writes"]
    sites = find_sites(ops)
    base_n, base_lb = run_model(ops, pw)
    print(f"baseline offline greedy {base_n}  lb {base_lb}")
    ok = [i for i, s in enumerate(sites)
          if s["M"] is not None and s["P"] is not None and s["A"] is not None]
    if args.all:
        chosen = ok
    else:
        chosen = ok[-args.last:]
    print(f"applying pair-preload at {len(chosen)} sites")
    new = rewrite(ops, sites, chosen)
    n, lb = run_model(new, pw)
    print(f"pair-preload    cycles {n}  ({n-base_n:+d})  lb {lb}")


def cmd_sweep(args):
    data = capture()
    ops = data["ops"]
    pw = data["pair_writes"]
    sites = find_sites(ops)
    ok = [i for i, s in enumerate(sites)
          if s["M"] is not None and s["P"] is not None and s["A"] is not None]
    base_n, base_lb = run_model(ops, pw)
    print(f"baseline offline greedy {base_n}   lb {base_lb}")
    print(f"{'#sites(last)':>14} {'cycles':>7} {'delta':>6} {'lb':>6} {'loadfloor':>10}")
    for k in (1, 2, 4, 8, 12, 16, 24, 32, 48, 64, 96, 128, len(ok)):
        if k > len(ok):
            continue
        new = rewrite(ops, sites, ok[-k:])
        n, lb = run_model(new, pw)
        print(f"{k:>14} {n:>7} {n-base_n:>+6} {lb['lb']:>6} {lb['engine']['load']:>10}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sites", "run", "sweep"])
    ap.add_argument("--last", type=int, default=8)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--free-loads", action="store_true")
    args = ap.parse_args()
    if args.free_loads:
        enable_free_loads()
    {"sites": cmd_sites, "run": cmd_run, "sweep": cmd_sweep}[args.cmd](args)


if __name__ == "__main__":
    main()
