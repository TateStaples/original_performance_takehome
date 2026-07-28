#!/usr/bin/env python3
"""H-055 pre-screen: the valu<->load slot-floor EXCHANGE.

The 1022 frontier sits at valu floor 1009 (binder) / alu 981 / load 946.
G-27's "-181 joint shadow price" is max-of-two-floors arithmetic, not a
chain effect (see h055_chain.py: only 10 of 708 CP ops are loads). The
actionable reading is therefore: any mechanism that trades vector slots for
load slots at a rate better than the marginal exchange (1 valu slot = 1/6
cyc, 1 load slot = 1/2 cyc once load binds) lowers the JOINT floor
max(valu/6, alu/12, load/2, flow/1).

`l4_gmin` is the one knob that runs that trade directly: each L4 group-round
NOT served by the pair tournament sheds tournament vector ops and pays 8
gather loads instead.

Usage (repo root):
    PYTHONPATH=.:tools python3 tools/h055_balance.py gmin
    PYTHONPATH=.:tools python3 tools/h055_balance.py loadbudget
"""
from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import problem  # noqa: E402
import h054_common as C  # noqa: E402
import h055_chain as _H  # noqa: E402  (shared $H055_PLAN-aware frontier)
from dev import KernelBuilder  # noqa: E402
from run_variant import measure  # noqa: E402

W = dict(problem.SLOT_LIMITS)
ENG = ("valu", "alu", "load", "flow", "store")


def stats(**extra):
    kb = KernelBuilder()
    kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                              C.SHAPE["forest_height"], **_H.frontier_kwargs(**extra))
    slots = {e: sum(len(b.get(e, [])) for b in kb.instrs) for e in ENG}
    floors = {e: -(-slots[e] // W[e]) for e in ENG}
    return len(kb.instrs), slots, floors


def line(label, **extra):
    try:
        n, s, f = stats(**extra)
    except Exception as exc:  # noqa: BLE001
        print(f"{label:28s} BUILD-FAIL {type(exc).__name__}: {str(exc)[:60]}")
        return None
    cyc, ok = measure(_H.frontier_kwargs(**extra))
    jf = max(f.values())
    print(f"{label:28s} cyc {cyc:5d} ok {int(ok)}  jointfloor {jf:5d}  "
          f"regret {cyc-jf:4d} | valu {s['valu']:5d}/{f['valu']:5d} "
          f"alu {s['alu']:6d}/{f['alu']:5d} load {s['load']:5d}/{f['load']:4d} "
          f"flow {s['flow']:4d}/{f['flow']:4d}", flush=True)
    return cyc, ok, s, f


def cmd_gmin(args):
    print("baseline + l4_gmin exchange sweep (e0, e1); serve fewer = raise gmin")
    line("frontier (7,30)")
    for e0 in (4, 5, 6, 7, 8, 10, 12, 16, 20, 24, 28, 32):
        line(f"gmin ({e0},30)", l4_gmin=(e0, 30))
    for e1 in (27, 28, 29, 30, 31, 32):
        line(f"gmin (7,{e1})", l4_gmin=(7, e1))
    for e0 in (10, 16, 24, 32):
        for e1 in (31, 32):
            line(f"gmin ({e0},{e1})", l4_gmin=(e0, e1))


def cmd_loadbudget(args):
    """How many free load slots exist, and where."""
    from collections import Counter
    kb = KernelBuilder()
    kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                              C.SHAPE["forest_height"], **_H.frontier_kwargs())
    n = len(kb.instrs)
    occ = [len(b.get("load", [])) for b in kb.instrs]
    free = [W["load"] - o for o in occ]
    print(f"cycles {n}; total load slots {W['load']*n}; used {sum(occ)}; "
          f"free {sum(free)}")
    print("free load slots by 50-cycle block:")
    for s in range(0, n, 50):
        e = min(s + 50, n)
        print(f"  {s:5d}-{e-1:5d}: {sum(free[s:e]):4d}")
    print("\nlongest run of zero-free-load cycles:")
    best = cur = 0
    beststart = curstart = 0
    for c in range(n):
        if free[c] == 0:
            if cur == 0:
                curstart = c
            cur += 1
            if cur > best:
                best, beststart = cur, curstart
        else:
            cur = 0
    print(f"  {best} cycles starting at {beststart}")
    # also store-slot vacancy (mechanism 'free stores during setup')
    socc = [len(b.get("store", [])) for b in kb.instrs]
    print(f"store slots used {sum(socc)} of {W['store']*n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["gmin", "loadbudget"])
    args = ap.parse_args()
    {"gmin": cmd_gmin, "loadbudget": cmd_loadbudget}[args.cmd](args)


if __name__ == "__main__":
    main()
