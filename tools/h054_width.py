"""H-054 counterfactual: how wide would the flow engine have to be for the
flow-heavy stream to schedule near its floor?

Mutates problem.SLOT_LIMITS['flow'] (shared dict, so dev.ListScheduler sees
it) and rebuilds. The resulting programs are ILLEGAL on the real machine --
this is a diagnostic, never a candidate. It separates "the selects can't get
a flow slot when they are ready" (widening fixes it) from "migrating selects
lengthens chains regardless" (widening does not fix it).
"""
from __future__ import annotations

import sys

import problem
import h054_common as C
from dev import KernelBuilder


def build(width, **extra):
    old = problem.SLOT_LIMITS["flow"]
    problem.SLOT_LIMITS["flow"] = width
    try:
        kw = C.frontier_kwargs(**extra)
        kb = KernelBuilder()
        kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                                  C.SHAPE["forest_height"], **kw)
    finally:
        problem.SLOT_LIMITS["flow"] = old
    return kb


def row(label, width, **extra):
    kb = build(width, **extra)
    n = len(kb.instrs)
    # recompute floors at the REAL width-1 flow limit
    st = C.slot_stats(kb)
    st["flow"]["floor"] = st["flow"]["slots"]
    fl = max(v["floor"] for v in st.values())
    print(f"{label:34s} cycles {n:5d}  legal-floor {fl:5d}  "
          f"valu {st['valu']['slots']:5d} flow {st['flow']['slots']:4d} "
          f"alu {st['alu']['slots']:6d}", flush=True)


if __name__ == "__main__":
    for w in (1, 2, 3, 4, 8):
        for b in (0, 6, 40, 200):
            row(f"flow_width={w} bias={b}", w, **({"flow_race_bias": b} if b else {}))
