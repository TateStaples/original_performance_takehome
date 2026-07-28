"""H-054: joint slack x flow-wait oracle on the CURRENT (1022) stream.

For every flow-capable race site that greedy routed OFF flow, measure both
sides of the anti-correlation at once:

  wait_i  = retire(flow encoding) - retire(chosen encoding)
            (how many cycles later the 1-wide flow engine would retire it)
  slack_i = (first consumer's cycle - 1) - retire(chosen)
            (how much later it may retire before a consumer stalls)

H-042 measured these separately at the OLD order/mix (46/155 slack > 0,
0/155 with a free flow slot within 3). This re-measures the JOINT
condition wait_i <= slack_i on the H-047 frontier stream, and dumps the
feasible set so it can be batch-forced through flow_spelling_plan.
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

import h054_common as C
import h054_diag as D

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h054_slack.json")


def main() -> None:
    kwargs = C.frontier_kwargs()
    kwargs.pop("flow_spelling_plan", None)
    kb = D.build(kwargs, {}, logging=True, trace=True)
    log = list(D.RACE_LOG)
    n_cycles = len(kb.instrs)
    trace = kb.sched_trace
    print(f"stream: {n_cycles} cycles, {len(trace)} traced ops, "
          f"{len(log)} race sites")

    rows = []
    for r in log:
        if r["site"] is None or r["site"] < 0 or r["flow_idx"] is None:
            continue
        chosen_retire = r["retires"][r["chosen"]]
        flow_retire = r["retires"][r["flow_idx"]]
        wait = flow_retire - chosen_retire
        dest = set(r["dest"])
        deadline = n_cycles + 50
        for entry in trace[r["trace_pos"]:]:
            cyc, _eng, _tag, _slot, reads, writes, _mr, _mw = entry
            if dest & set(reads) or dest & set(writes):
                deadline = cyc - 1
                break
        rows.append({"site": r["site"], "tag": r["tag"], "flow_idx": r["flow_idx"],
                     "on_flow": r["chosen"] == r["flow_idx"],
                     "retire": chosen_retire, "wait": wait,
                     "slack": deadline - chosen_retire})

    lost = [x for x in rows if not x["on_flow"]]
    won = [x for x in rows if x["on_flow"]]
    print(f"flow-capable sites {len(rows)}: on flow {len(won)}, lost {len(lost)}")
    print("lost wait histogram:", dict(sorted(Counter(x["wait"] for x in lost).items())))
    print("lost slack histogram:", dict(sorted(Counter(min(x["slack"], 20) for x in lost).items())))
    feas = [x for x in lost if x["wait"] <= x["slack"]]
    print(f"JOINT feasible (wait <= slack): {len(feas)} / {len(lost)}")
    print("  feasible waits:", dict(sorted(Counter(x["wait"] for x in feas).items())))
    print("  feasible by round:", dict(sorted(Counter(
        (x["tag"][0] if x["tag"] else -1) for x in feas).items())))
    with open(OUT, "w") as f:
        json.dump({"cycles": n_cycles, "rows": rows}, f)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
