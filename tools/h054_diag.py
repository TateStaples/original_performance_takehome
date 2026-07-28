"""H-054 diagnosis: the select-readiness x flow-bubble anti-correlation,
measured ON the floor-990 flowmax stream (F-17's instruction), not the
baseline.

Instruments dev.ListScheduler.emit_any so that for every multi-encoding race
site we record, per encoding, the hazard-ready cycle and the cycle
find_free() actually lands on. For flow-capable sites that gives exactly the
two numbers the hypothesis is about:
    arrival  = ready(reads, writes)        -- when the select COULD go on flow
    placed   = find_free('flow', arrival)  -- when the 1-wide flow engine takes it
    wait     = placed - arrival            -- flow queueing delay

Reports:
  * arrivals-per-cycle histogram (burst size distribution)
  * inter-arrival distribution of burst cycles
  * flow occupancy / bubbles, and how many bubbles precede vs follow bursts
  * required queue depth: max backlog of a 1-server FIFO fed by the arrivals

Usage:
  python3 tools/h054_diag.py greedy
  python3 tools/h054_diag.py flowmax
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any

import h054_common as C
from dev import KernelBuilder, ListScheduler
from problem import SLOT_LIMITS

RACE_LOG: list[dict[str, Any]] = []
LOGGING = False

_orig_emit_any = ListScheduler.emit_any


def logging_emit_any(self, encodings):
    encodings = list(encodings)
    is_race = len(encodings) > 1
    is_flow_site = is_race and any(
        all(e == "flow" for e, *_ in enc) for enc in encodings
    )
    site_idx = None
    if is_race:
        if is_flow_site:
            site_idx = self.flow_site_idx
            self.flow_site_idx += 1
        else:
            site_idx = -(self.aux_site_idx + 1)
            self.aux_site_idx += 1
    forced = self.flow_site_plan.get(site_idx) if is_race else None
    encodings_run = [encodings[forced]] if forced is not None else encodings

    trials = []
    for encoding in encodings_run:
        trial_occupancy: dict[str, dict[int, int]] = {}
        trial_last_write: dict[int, int] = {}
        trial_last_read: dict[int, int] = {}
        placements: list[int] = []
        arrivals: list[int] = []
        retire = -1
        for engine, slot, reads, writes in encoding:
            cycle = self.ready(reads, writes)
            for addr in reads:
                t = trial_last_write.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
            for addr in writes:
                t = trial_last_write.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
                t = trial_last_read.get(addr, -1)
                if t > cycle:
                    cycle = t
            arrivals.append(cycle)
            cycle = self.find_free(engine, cycle, trial_occupancy.setdefault(engine, {}))
            trial_occupancy[engine][cycle] = trial_occupancy[engine].get(cycle, 0) + 1
            placements.append(cycle)
            if cycle > retire:
                retire = cycle
            for addr in reads:
                if trial_last_read.get(addr, -1) < cycle:
                    trial_last_read[addr] = cycle
            for addr in writes:
                trial_last_write[addr] = cycle
        trials.append((retire, encoding, placements, arrivals))
    best_idx = min(range(len(trials)), key=lambda i: trials[i][0])
    retire, encoding, placements, arrivals = trials[best_idx]
    for (engine, slot, reads, writes), cycle in zip(encoding, placements):
        self.put(engine, slot, cycle, reads, writes)

    if is_race and LOGGING:
        shapes = tuple(tuple(sorted({e for e, *_ in enc})) for enc in encodings)
        fidx = next((i for i, s in enumerate(shapes) if s == ("flow",)), None)
        chosen = forced if forced is not None else best_idx
        RACE_LOG.append({
            "site": site_idx,
            "tag": self.tag,
            "shapes": shapes,
            "flow_idx": fidx,
            "chosen": chosen,
            "retire": retire,
            "arrival": min(arrivals),
            "placed": max(placements),
            "engines": tuple(sorted({e for e, *_ in encoding})),
            "dest": tuple(sorted({a for _, _, _, ws in encoding for a in ws})),
            "forced": forced is not None,
            "trace_pos": len(self.trace) if self.trace is not None else -1,
            "retires": tuple(t[0] for t in trials),
        })
    return retire


ListScheduler.emit_any = logging_emit_any


def build(kwargs, plan, logging=False, trace=False):
    global LOGGING
    RACE_LOG.clear()
    LOGGING = logging
    kb = KernelBuilder()
    if trace:
        kb.sched_trace = []
    kb.build_kernel_scheduled(
        C.SHAPE["batch_size"], C.SHAPE["rounds"], C.SHAPE["forest_height"],
        **dict(kwargs, flow_spelling_plan=tuple(sorted(plan.items())))
    )
    LOGGING = False
    return kb


def flow_occupancy(kb) -> list[int]:
    out = []
    for bundle in kb.instrs:
        ops = bundle.get("flow", [])
        out.append(len(ops) if isinstance(ops, list) else (1 if ops else 0))
    return out


def analyze(kb, log, label):
    n = len(kb.instrs)
    occ = flow_occupancy(kb)
    flow_recs = [r for r in log if r["flow_idx"] is not None
                 and r["chosen"] == r["flow_idx"]]
    arrivals = Counter(r["arrival"] for r in flow_recs)
    waits = Counter(r["placed"] - r["arrival"] for r in flow_recs)

    # 1-server FIFO backlog fed by the arrivals (deterministic, service 1/cyc)
    backlog = 0
    peak = 0
    peak_cycle = -1
    total_wait_area = 0
    for c in range(n + 400):
        backlog += arrivals.get(c, 0)
        if backlog > peak:
            peak, peak_cycle = backlog, c
        total_wait_area += backlog
        if backlog:
            backlog -= 1

    burst_cycles = sorted(c for c, k in arrivals.items() if k >= 2)
    gaps = [b - a for a, b in zip(burst_cycles, burst_cycles[1:])]
    bubbles = [c for c in range(n) if occ[c] == 0]

    # bubble proximity: for each bubble, distance to the nearest arrival cycle
    arr_cycles = sorted(arrivals)
    import bisect
    near = Counter()
    for c in bubbles:
        i = bisect.bisect_left(arr_cycles, c)
        d = min([abs(arr_cycles[j] - c) for j in (i - 1, i)
                 if 0 <= j < len(arr_cycles)] or [999])
        near[min(d, 10)] += 1

    print(f"\n=== {label}: {n} cycles, floor {C.max_floor(kb)} ===")
    print("engines:", json.dumps(C.slot_stats(kb)))
    print(f"flow sites on flow: {len(flow_recs)} / {sum(1 for r in log if r['flow_idx'] is not None)}")
    print(f"flow slots used {sum(occ)}, bubbles {len(bubbles)} ({len(bubbles)/n:.1%})")
    print("arrivals-per-cycle histogram:",
          dict(sorted(Counter(arrivals.values()).items())))
    print(f"distinct arrival cycles {len(arrivals)}, burst cycles (>=2) {len(burst_cycles)}")
    print("wait (placed-arrival) histogram:", dict(sorted(waits.items())[:15]),
          "max", max(waits) if waits else 0,
          "mean %.2f" % (sum(k * v for k, v in waits.items()) / max(1, len(flow_recs))))
    print(f"required 1-server queue depth: peak backlog {peak} at cycle {peak_cycle}")
    print("burst inter-arrival gaps:", dict(sorted(Counter(gaps).items())[:15]))
    print("bubble -> nearest-arrival distance histogram:", dict(sorted(near.items())))
    return {"n": n, "occ": occ, "log": log, "arrivals": arrivals,
            "flow_recs": flow_recs, "peak_backlog": peak}


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "greedy"
    kwargs = C.frontier_kwargs()
    kwargs.pop("flow_spelling_plan", None)
    kb0 = build(kwargs, {}, logging=True)
    log0 = list(RACE_LOG)
    if mode == "greedy":
        analyze(kb0, log0, "greedy (frontier 1022)")
        return
    plan = {r["site"]: r["flow_idx"] for r in log0
            if r["site"] is not None and r["site"] >= 0 and r["flow_idx"] is not None}
    kb1 = build(kwargs, plan, logging=True)
    analyze(kb1, list(RACE_LOG), f"flowmax ({len(plan)} sites forced)")


if __name__ == "__main__":
    main()
