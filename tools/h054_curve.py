"""H-054: floor-vs-realized curve for a family of flow-migration policies.

Prints, per policy point, the op stream's per-engine slot counts / floors
(the "target board") next to the greedy schedule's actual cycle count, so a
policy that lowers the floor but not the schedule is visibly distinguished
from one that does neither.
"""
from __future__ import annotations

import json
import sys

import h054_common as C
from dev import KernelBuilder


def build(**extra):
    kw = C.frontier_kwargs(**extra)
    kb = KernelBuilder()
    kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                              C.SHAPE["forest_height"], **kw)
    return kb


def row(label, **extra):
    kb = build(**extra)
    st = C.slot_stats(kb)
    n = len(kb.instrs)
    fl = max(v["floor"] for v in st.values())
    binder = max(st, key=lambda e: st[e]["floor"])
    print(f"{label:36s} cycles {n:5d}  floor {fl:5d} ({binder})  gap {n-fl:4d}  "
          f"valu {st['valu']['slots']:5d} flow {st['flow']['slots']:4d} "
          f"alu {st['alu']['slots']:6d}", flush=True)
    return n, fl


if __name__ == "__main__":
    row("greedy")
    for b in (1, 2, 3, 4, 6, 8, 12, 16, 24, 40, 100):
        row(f"bias={b}", flow_race_bias=b)
