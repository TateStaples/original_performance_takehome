"""H-054: batch/incremental forcing of the slack-feasible migration set.

Reads tools/h054_slack.json (produced by h054_slack.py) and forces the
flow-lost sites whose flow wait fits inside their consumer slack onto flow
via `flow_spelling_plan`, in batches, re-measuring floor + cycles.

Modes:
  batch   force the whole feasible set at once, plus wait<=K prefixes
  greedy  iteratively add the feasible site that helps most (fixpoint)
  refix   re-derive the feasible set from the CURRENT plan's stream and
          repeat (the oracle is first-order; forcing moves the deadlines)
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

import h054_common as C
import h054_diag as D
from dev import KernelBuilder

SLACK_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "h054_slack.json")


def build_plan(plan: dict[int, int]):
    kw = C.frontier_kwargs()
    kw["flow_spelling_plan"] = tuple(sorted(plan.items()))
    kb = KernelBuilder()
    kb.build_kernel_scheduled(C.SHAPE["batch_size"], C.SHAPE["rounds"],
                              C.SHAPE["forest_height"], **kw)
    return kb


def report(label, plan):
    kb = build_plan(plan)
    st = C.slot_stats(kb)
    n = len(kb.instrs)
    fl = max(v["floor"] for v in st.values())
    print(f"{label:34s} |plan| {len(plan):4d}  cycles {n:5d}  floor {fl:5d}  "
          f"gap {n-fl:4d}  valu {st['valu']['slots']:5d} flow {st['flow']['slots']:4d}",
          flush=True)
    return n, fl


def oracle(plan: dict[int, int]):
    """(rows, n_cycles) for the stream produced by `plan`."""
    kwargs = C.frontier_kwargs()
    kwargs.pop("flow_spelling_plan", None)
    kb = D.build(kwargs, plan, logging=True, trace=True)
    log = list(D.RACE_LOG)
    n_cycles = len(kb.instrs)
    trace = kb.sched_trace
    rows = []
    for r in log:
        if r["site"] is None or r["site"] < 0 or r["flow_idx"] is None:
            continue
        if r["forced"]:
            rows.append({"site": r["site"], "tag": r["tag"], "on_flow": True,
                         "wait": 0, "slack": 0, "flow_idx": r["flow_idx"]})
            continue
        chosen_retire = r["retires"][r["chosen"]]
        flow_retire = r["retires"][r["flow_idx"]]
        dest = set(r["dest"])
        deadline = n_cycles + 50
        for entry in trace[r["trace_pos"]:]:
            cyc, _e, _t, _s, reads, writes, _mr, _mw = entry
            if dest & set(reads) or dest & set(writes):
                deadline = cyc - 1
                break
        rows.append({"site": r["site"], "tag": r["tag"],
                     "on_flow": r["chosen"] == r["flow_idx"],
                     "flow_idx": r["flow_idx"],
                     "wait": flow_retire - chosen_retire,
                     "slack": deadline - chosen_retire})
    return rows, n_cycles


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "batch"
    data = json.load(open(SLACK_JSON))
    rows = data["rows"]
    feas = [r for r in rows if not r["on_flow"] and r["wait"] <= r["slack"]]
    feas.sort(key=lambda r: r["wait"])

    if mode == "batch":
        report("greedy", {})
        for k in (1, 2, 3, 4, 5, 6, 20):
            sub = [r for r in feas if r["wait"] <= k]
            report(f"feasible wait<={k} (n={len(sub)})",
                   {r["site"]: r["flow_idx"] for r in sub})
        # also: force by round window
        for rd in sorted({r["tag"][0] for r in feas if r["tag"]}):
            sub = [r for r in feas if r["tag"] and r["tag"][0] == rd]
            report(f"feasible round {rd} (n={len(sub)})",
                   {r["site"]: r["flow_idx"] for r in sub})
        return

    if mode == "greedy":
        plan: dict[int, int] = {}
        best, _ = report("start", plan)
        pool = list(feas)
        improved = True
        while improved and pool:
            improved = False
            for r in list(pool):
                trial = dict(plan, **{r["site"]: r["flow_idx"]})
                n = len(build_plan(trial).instrs)
                if n <= best:
                    if n < best:
                        print(f"  descent: site {r['site']} {r['tag']} -> {n}", flush=True)
                        improved = True
                    plan, best = trial, n
                    pool.remove(r)
            if not improved:
                break
        report("greedy-feasible fixpoint", plan)
        print("plan =", tuple(sorted(plan.items())))
        return

    if mode == "refix":
        plan: dict[int, int] = {}
        for it in range(8):
            rws, n = oracle(plan)
            cand = [r for r in rws if not r["on_flow"] and r["wait"] <= r["slack"]]
            print(f"iter {it}: cycles {n}, |plan| {len(plan)}, feasible {len(cand)}")
            if not cand:
                break
            for r in cand:
                plan[r["site"]] = r["flow_idx"]
            nn, fl = report(f"  after iter {it}", plan)
            if nn > n:
                print("  (regressed; stopping)")
                break
        print("plan =", tuple(sorted(plan.items())))
        return


if __name__ == "__main__":
    main()
