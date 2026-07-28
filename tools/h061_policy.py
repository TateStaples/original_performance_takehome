"""H-061: does a different LOAD-ISSUE POLICY buy anything?

The mainline scheduler is online greedy in emission order.  On a
load-saturated stream that is a policy: whichever gather was emitted first
takes the slot.  This probes the alternative -- offline parallel list
scheduling (backtrack_sched.priority_schedule) over the SAME captured op
stream and the SAME constraint DAG, under priorities that deliberately
favour the load engine and/or long dependent tails.

Any result below greedy is a real headroom signal for a scheduler change;
equal-or-worse closes the direction for this stream.

Usage: python3 tools/h061_policy.py [gmin ...]
"""
from __future__ import annotations

import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import backtrack_sched as B  # noqa: E402
import h061_attrib as A  # noqa: E402

BIG = 10 ** 6


def main() -> None:
    for a in (sys.argv[1:] or ["main", "20,31"]):
        g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
        data, ops, preds, floors = A.capture_stream(g)
        place0 = [op[9] for op in ops]
        pl, n0 = B.greedy_schedule(ops, preds, floors)
        assert pl == place0
        h = B.tails(ops, preds)
        est = B.ests(ops, preds, floors)
        is_load = [op[0] == "load" for op in ops]
        n = len(ops)
        cases = [
            ("greedy-emission(baseline)", None),
            ("tail_height", h),
            ("est+tail(CP)", [e + t for e, t in zip(est, h)]),
            ("load-first", [h[i] + (BIG if is_load[i] else 0) for i in range(n)]),
            ("load-last", [h[i] - (BIG if is_load[i] else 0) for i in range(n)]),
            ("emission(sanity)", [-i for i in range(n)]),
        ]
        print(f"== {a}: greedy {n0} cycles, {sum(is_load)} loads ==")
        for name, pr in cases:
            if pr is None:
                print(f"  {name:<26} {n0}")
                continue
            t0 = time.time()
            place, cyc = B.priority_schedule(ops, preds, floors, pr)
            ok = B.check_feasible(ops, preds, floors, place)
            print(f"  {name:<26} {cyc}  feasible={ok}  ({time.time()-t0:.0f}s)",
                  flush=True)


if __name__ == "__main__":
    main()
