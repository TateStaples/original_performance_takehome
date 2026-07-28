"""H-054: per-engine shadow price of the frontier schedule.

Counterfactual relaxation probe. Widening engine e by k slots/cycle is a
STRICT relaxation that dominates every legal mechanism which merely moves
work off e (spelling choice, emission order, placement policy, plan search).
If widening e does not shorten the schedule, no such mechanism can.

The programs built here are ILLEGAL on the real machine -- diagnostics only.

Usage: python3 tools/h054_shadow.py [--bias N]
"""
from __future__ import annotations

import argparse
import sys

import problem
import h054_common as C
from dev import KernelBuilder

REAL = dict(problem.SLOT_LIMITS)


def build(widths: dict[str, int], **extra):
    for e, w in widths.items():
        problem.SLOT_LIMITS[e] = w
    try:
        kb = KernelBuilder()
        kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                                  C.SHAPE["forest_height"], **C.frontier_kwargs(**extra))
    finally:
        problem.SLOT_LIMITS.clear()
        problem.SLOT_LIMITS.update(REAL)
    return kb


def row(label, widths, **extra):
    kb = build(widths, **extra)
    n = len(kb.instrs)
    slots = {e: sum(len(b.get(e, [])) for b in kb.instrs)
             for e in ("valu", "alu", "load", "flow", "store")}
    legal_floor = max(-(-slots[e] // REAL[e]) for e in slots)
    print(f"{label:32s} cycles {n:5d}  legal-floor {legal_floor:5d}  "
          f"valu {slots['valu']:5d} alu {slots['alu']:6d} load {slots['load']:5d} "
          f"flow {slots['flow']:4d}", flush=True)
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bias", type=int, default=0)
    args = ap.parse_args()
    extra = {"flow_race_bias": args.bias} if args.bias else {}
    print("real widths:", REAL)
    row("baseline", {}, **extra)
    for e, ws in (("flow", (2, 4, 8)), ("valu", (7, 8, 12)),
                  ("alu", (14, 16, 24)), ("load", (3, 4)),
                  ("store", (4,))):
        for w in ws:
            row(f"{e} {REAL[e]} -> {w}", {e: w}, **extra)
    row("valu 8 + alu 16", {"valu": 8, "alu": 16}, **extra)
    row("valu 8 + load 4", {"valu": 8, "load": 4}, **extra)
    row("alu 16 + load 4", {"alu": 16, "load": 4}, **extra)
    row("valu8+alu16+load4", {"valu": 8, "alu": 16, "load": 4}, **extra)
    row("all x2", {"valu": 12, "alu": 24, "load": 4, "flow": 2, "store": 4}, **extra)


if __name__ == "__main__":
    main()
