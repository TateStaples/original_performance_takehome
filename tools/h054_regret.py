"""H-054: run H-051's regret profiler against an H-054 stream.

Wrapper only: patches backtrack_sched.H51_OVERRIDES in-process (the module
itself is another strain's region and is NOT modified) and drives its
capture -> model -> regret pipeline, so the H-047 frontier stream and its
flow-migrated variants get the same 2026-07-27 friction attribution.

Usage:
  python3 tools/h054_regret.py [key=value ...]      # extra dev kwargs
  e.g.  python3 tools/h054_regret.py flow_race_bias=40
"""
from __future__ import annotations

import sys
from typing import Any

import h054_common as C
import backtrack_sched as B
from problem import SLOT_LIMITS
from run_variant import parse_value


def main() -> None:
    extra: dict[str, Any] = {}
    for item in sys.argv[1:]:
        k, _, v = item.partition("=")
        extra[k.strip()] = parse_value(v.strip())

    over = dict(C.FRONTIER)
    over["emission_plan"] = C.frontier_kwargs()["emission_plan"]
    over.update(extra)
    B.H51_OVERRIDES.clear()
    B.H51_OVERRIDES.update(over)

    data = B.capture()
    ops = data["ops"]
    preds, floors = B.build_model(ops, data["pair_writes"])
    place = [op[9] for op in ops]
    lb = B.lb_total(ops, preds, floors)
    print("ops", len(ops), "cycles", data["n_cycles"])
    print("LB(total):", lb)

    est = B.ests(ops, preds, floors)
    h = B.tails(ops, preds)
    for name, key in (("release(est)", est), ("tail(h)", h)):
        best_v, best_at = 0, None
        for e in B.ENGINES:
            vals = sorted((key[i] for i in range(len(ops)) if ops[i][0] == e),
                          reverse=True)
            for cnt, t in enumerate(vals, 1):
                v = t + -(-cnt // SLOT_LIMITS[e])
                if v > best_v:
                    best_v, best_at = v, (e, t, cnt)
        print(f"staircase [{name}]: {best_v} {best_at}")

    F, eng_lb, cp_lb = B.regret_profile(ops, preds, floors, place)
    print(f"total {max(place)+1}  LB {lb['lb']}  regret {max(place)+1-lb['lb']}")
    prev = lb["lb"]
    for c in range(len(F)):
        if F[c] > prev:
            tagset = sorted({ops[i][10][0] for i in range(len(ops))
                             if place[i] == c and ops[i][10]})
            print(f"  c={c:>4} +{F[c]-prev} F={F[c]} engLB={eng_lb[c]} "
                  f"cpLB={cp_lb[c]} rounds={tagset}")
        prev = max(prev, F[c])


if __name__ == "__main__":
    main()
