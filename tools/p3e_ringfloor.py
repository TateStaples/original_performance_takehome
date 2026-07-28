"""P3-E: map T2 ring COVERAGE -> residual support vec-ops -> C1* floor.

P3-A's T2 removes 259 vec-ops of support (cond.mask 78 + pos.fold 141 +
pos.seed 40) *for the group-rounds it covers*.  An uncovered served
group-round keeps the packed position accumulator and pays the full rate.
So residual support = 259 * (1 - coverage), and P3-D's joint model
(tools/p3d_joint.py) prices residual support directly via its `mask` knob.

This tool inverts that: for each coverage fraction, the minimum feasible C.

Usage: python3 tools/p3e_ringfloor.py
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import p3d_joint as J  # noqa: E402

T2_TOTAL = 259  # vec-ops removable at 100% coverage


def min_C(mask: int, **kw) -> int:
    pts = J.pareto({s: J.group_cost(s) for s in J.all_schedules()}.values())
    for C in range(880, 1050):
        if J.solve(C, pts, setup_vec=J.SETUP_VEC_MIN,
                   setup_flow=J.SETUP_FLOW_MIN, mask=mask, **kw):
            return C
    return -1


def main() -> None:
    print(f"{'coverage':>10} {'rings/64':>9} {'residual vec':>13} {'min C':>6}"
          f" {'min C (shipped fold spelling +4%)':>34}")
    for rings in (64, 60, 56, 50, 46, 43, 40, 32, 24, 20, 10, 0):
        c = rings / 64.0
        resid = round(T2_TOTAL * (1 - c))
        print(f"{c:>9.1%} {rings:>9} {resid:>13} {min_C(resid):>6}"
              f" {min_C(resid, fold_ovh=1.04):>34}")


if __name__ == "__main__":
    main()
