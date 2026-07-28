"""P3-E: attribute the group-liveness (K) realized-cycle cost.

For each window size W, on ONE common ring-free base with a per-W tuned
diagonal, report realized bundles AND the per-engine slot floors, so the
K penalty can be split into "engine floor rose" vs "regret rose"
(= chain / ILP structure).  G-33 attributed it to the alu_offload race
raising the valu floor; G-36 later said the floor decouples under a static
partition but the cycle curve does not move.

Usage: python3 tools/p3e_kfloor.py [--lags W:l0,l1,...]
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE  # noqa: E402

SLOT_LIMITS = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1}
LANES = {"alu": 1, "valu": 8, "load": 1, "store": 1, "flow": 1}


def profile(ov):
    from dev import KernelBuilder
    kb = KernelBuilder()
    kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                              SHAPE["forest_height"], **dict(BASE_KWARGS, **ov))
    slots = {e: 0 for e in SLOT_LIMITS}
    for bundle in kb.instrs:
        for engine, s in bundle.items():
            if engine in slots:
                slots[engine] += len(s)
    cyc = len(kb.instrs)
    floors = {e: slots[e] / SLOT_LIMITS[e] for e in slots}
    avf = (slots["alu"] + slots["valu"]) / 18.0
    return cyc, slots, floors, avf


CASES = {
    32: [0, 0, 0, 0, 4, 2, 2, 2, 4, 6, 4, 4, 6, 6, 6, 6, 8, 8, 8, 8,
         10, 10, 10, 10, 12, 12, 12, 12, 14, 14, 14, 14],
    16: [0, 0, 0, 0, 4, 3, 2, 4, 8, 6, 5, 6, 9, 9, 9, 9],
}


def main() -> None:
    for w, lags in CASES.items():
        plan = H.rolling_plan_lags(w, lags, "zip")
        ov = dict(H.NORING, emission_plan=plan)
        cyc, slots, floors, avf = profile(ov)
        print(json.dumps({
            "w": w, "cycles": cyc, "slots": slots,
            "floors": {e: round(v, 1) for e, v in floors.items()},
            "alu+valu/18": round(avf, 1),
            "binder": max(floors, key=lambda e: floors[e]),
            "regret": round(cyc - max(max(floors.values()), avf), 1),
        }), flush=True)


if __name__ == "__main__":
    main()
