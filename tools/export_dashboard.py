"""
Phase 0 of the kernel dashboard: build the static data model the HTML
dashboard renders.

Everything here is DERIVED -- it reads the kernel through the existing
`kb.sched_trace` hook (dev.py `ListScheduler.put`) and changes nothing about
how the kernel is built or scheduled. Rebuild the JSON after any kernel
change; it is not checked in.

What it emits (one JSON file, columnar so the browser can index it cheaply):

  meta    -- shape, config, slot limits, cycle count, engine floors
  ops     -- every scheduled slot: placement (cycle/engine/slot index),
             opcode, (round, group) tag, purpose class, dependency-only
             ASAP/ALAP/slack, its binding hazard, and its dependency
             predecessors
  edges   -- the dependency DAG (pred, succ, delta) that ASAP/ALAP and the
             critical path are computed from
  scratch -- named scratch blocks, for naming addresses in the UI

Dependency semantics mirror problem.py exactly (reads see start-of-cycle
state): RAW/WAW force consumer >= producer + 1, WAR allows the write in the
same cycle as the read (delta 0). Memory is treated as one aliasing
location, matching the scheduler's own `mem_read`/`mem_write` hazards.

Usage (repo root):
    python tools/export_dashboard.py                  # mainline config
    python tools/export_dashboard.py --set skew=8,2   # any variant
    python tools/export_dashboard.py -o dash.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from diagnose_kernel import classify, opcode_key  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402
from sched_profile import build_scratch_name_lookup, build_traced_kernel  # noqa: E402

# Engines in the fixed display order the timeline uses top-to-bottom.
ENGINE_ORDER = ["valu", "alu", "load", "store", "flow"]


def compute_dependencies(
    trace: list[tuple[Any, ...]],
) -> tuple[
    list[list[tuple[int, int]]],
    list[tuple[str, int | None, int | None]],
    list[int],
]:
    """
    Per op: its dependency predecessors as (producer_idx, delta) pairs, its
    BINDING hazard (the one that set its earliest legal cycle), and its
    ready cycle under the ACTUAL schedule.

    That last one is what makes the queued-ops view exact: an op is ready but
    unissued for exactly the half-open cycle interval [ready, cycle), so the
    ready set at any cycle is an interval-stabbing query rather than a
    replay.

    Emission order is a topological order -- the scheduler is greedy in
    program order, so every producer was put() before its consumer. This is
    the same walk `sched_profile.replay` does, extended to keep ALL
    predecessors rather than only the binding one.
    """
    last_write: dict[int, tuple[int, int]] = {}  # addr -> (cycle, op idx)
    last_read: dict[int, tuple[int, int]] = {}
    last_mem_write: tuple[int, int | None] = (-1, None)
    last_mem_read: tuple[int, int | None] = (-1, None)

    all_preds: list[list[tuple[int, int]]] = []
    hazards: list[tuple[str, int | None, int | None]] = []
    ready_cycles: list[int] = []

    for cycle, _engine, _tag, _slot, reads, writes, mem_read, mem_write in trace:
        preds: dict[int, int] = {}  # producer idx -> max delta
        ready_cycle = 0
        hazard: tuple[str, int | None, int | None] = ("none", None, None)

        def note(producer: tuple[int, int] | tuple[int, int | None],
                 delta: int, kind: str, addr: int | None) -> None:
            nonlocal ready_cycle, hazard
            producer_cycle, producer_idx = producer
            if producer_idx is None:
                return
            if producer_cycle + delta > ready_cycle:
                ready_cycle = producer_cycle + delta
                hazard = (kind, addr, producer_idx)
            if preds.get(producer_idx, -1) < delta:
                preds[producer_idx] = delta

        for addr in reads:
            producer = last_write.get(addr)
            if producer is not None:
                note(producer, 1, "RAW", addr)
        for addr in writes:
            producer = last_write.get(addr)
            if producer is not None:
                note(producer, 1, "WAW", addr)
            producer = last_read.get(addr)
            if producer is not None:
                note(producer, 0, "WAR", addr)
        if mem_read:
            note(last_mem_write, 1, "MEM-RAW", None)
        if mem_write:
            note(last_mem_write, 1, "MEM-WAW", None)
            note(last_mem_read, 0, "MEM-WAR", None)

        all_preds.append(sorted(preds.items()))
        hazards.append(hazard)
        ready_cycles.append(ready_cycle)

        idx = len(all_preds) - 1
        for addr in reads:
            seen = last_read.get(addr)
            if seen is None or seen[0] < cycle:
                last_read[addr] = (cycle, idx)
        for addr in writes:
            last_write[addr] = (cycle, idx)
        if mem_read and last_mem_read[0] < cycle:
            last_mem_read = (cycle, idx)
        if mem_write and last_mem_write[0] < cycle:
            last_mem_write = (cycle, idx)

    return all_preds, hazards, ready_cycles


def compute_slack(
    all_preds: list[list[tuple[int, int]]], span: int
) -> tuple[list[int], list[int], list[int]]:
    """
    Dependency-only ASAP/ALAP and the critical path.

    ASAP ignores slot limits entirely, so `cycle - asap` is exactly the delay
    a op suffered from CONTENTION rather than from its dependencies -- the
    throughput-vs-latency split the dashboard is meant to show. ALAP is taken
    against the achieved span, so slack == 0 marks the critical path.
    """
    n = len(all_preds)
    asap = [0] * n
    for i, preds in enumerate(all_preds):
        earliest = 0
        for producer_idx, delta in preds:
            if asap[producer_idx] + delta > earliest:
                earliest = asap[producer_idx] + delta
        asap[i] = earliest

    succs: list[list[tuple[int, int]]] = [[] for _ in range(n)]
    for i, preds in enumerate(all_preds):
        for producer_idx, delta in preds:
            succs[producer_idx].append((i, delta))

    horizon = max(asap) if n else 0
    alap = [horizon] * n
    for i in range(n - 1, -1, -1):
        latest = horizon
        for succ_idx, delta in succs[i]:
            if alap[succ_idx] - delta < latest:
                latest = alap[succ_idx] - delta
        alap[i] = latest

    critical = [i for i in range(n) if asap[i] == alap[i]]
    return asap, alap, critical


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("-o", "--out", default="dashboard_data.json")
    args = parser.parse_args()

    overrides: dict[str, Any] = {}
    for override_arg in args.set:
        key, _, value = override_arg.partition("=")
        overrides[key] = parse_value(value)

    kb, kwargs = build_traced_kernel(overrides)
    trace = kb.sched_trace
    lookup = build_scratch_name_lookup(kb)

    span = max(entry[0] for entry in trace) + 1
    all_preds, hazards, ready_cycles = compute_dependencies(trace)
    asap, alap, critical = compute_slack(all_preds, span)

    # Slot index within (cycle, engine), assigned in emission order. The
    # machine treats a bundle's slot list as unordered, so this is purely a
    # stable row assignment for the timeline.
    slot_index: list[int] = []
    fill: Counter[tuple[int, str]] = Counter()
    occupancy = [dict.fromkeys(SLOT_LIMITS, 0) for _ in range(span)]
    for cycle, engine, _tag, *_rest in trace:
        key = (cycle, engine)
        slot_index.append(fill[key])
        fill[key] += 1
        occupancy[cycle][engine] += 1

    columns: dict[str, list[Any]] = {
        "cycle": [], "engine": [], "slot": [], "opcode": [], "purpose": [],
        "round": [], "group": [], "asap": [], "alap": [], "slack": [],
        "hazard": [], "hazard_addr": [], "hazard_producer": [], "text": [],
        "ready": [], "queued": [],
    }
    edges: list[tuple[int, int, int]] = []

    for i, (cycle, engine, tag, slot, *_rest) in enumerate(trace):
        hazard_kind, hazard_addr, hazard_producer = hazards[i]
        columns["cycle"].append(cycle)
        columns["engine"].append(ENGINE_ORDER.index(engine))
        columns["slot"].append(slot_index[i])
        columns["opcode"].append(opcode_key(engine, slot[0]))
        columns["purpose"].append(classify(engine, slot, lookup))
        columns["round"].append(tag[0] if isinstance(tag, tuple) else None)
        columns["group"].append(tag[1] if isinstance(tag, tuple) else None)
        columns["asap"].append(asap[i])
        columns["alap"].append(alap[i])
        columns["slack"].append(alap[i] - asap[i])
        columns["hazard"].append(hazard_kind)
        columns["hazard_addr"].append(
            lookup(hazard_addr) if hazard_addr is not None else None
        )
        columns["hazard_producer"].append(hazard_producer)
        # [ready, cycle) is exactly the window this op sat ready but unissued,
        # i.e. deferred by CONTENTION rather than by its dependencies.
        columns["ready"].append(ready_cycles[i])
        columns["queued"].append(cycle - ready_cycles[i])
        # Named form, e.g. "vselect val12 <- cond, a, b" is more useful in a
        # tooltip than the raw address tuple.
        columns["text"].append(
            str(tuple(lookup(x) or x if isinstance(x, int) else x for x in slot))
        )
        for producer_idx, delta in all_preds[i]:
            edges.append((producer_idx, i, delta))

    # Per-cycle backlog: how many ops were ready but unissued, per engine.
    # Difference array over each op's [ready, cycle) window. Comparing this
    # against SLOT_LIMITS is the throughput-vs-latency read: backlog above the
    # limit means the engine is oversubscribed (throughput-bound); backlog at
    # zero with empty slots means nothing was runnable (latency-bound).
    backlog_delta = [[0] * (span + 1) for _ in ENGINE_ORDER]
    for i, (cycle, engine, *_rest) in enumerate(trace):
        engine_i = ENGINE_ORDER.index(engine)
        backlog_delta[engine_i][ready_cycles[i]] += 1
        backlog_delta[engine_i][cycle] -= 1
    backlog = [[0] * len(ENGINE_ORDER) for _ in range(span)]
    for engine_i in range(len(ENGINE_ORDER)):
        running = 0
        for c in range(span):
            running += backlog_delta[engine_i][c]
            backlog[c][engine_i] = running

    slots_used = Counter(entry[1] for entry in trace)
    floors = {
        engine: -(-slots_used[engine] // SLOT_LIMITS[engine]) for engine in SLOT_LIMITS
        if engine in slots_used
    }

    payload = {
        "meta": {
            "shape": SHAPE,
            "config": {k: repr(v) for k, v in kwargs.items()},
            "overrides": {k: repr(v) for k, v in overrides.items()},
            "slot_limits": SLOT_LIMITS,
            "engine_order": ENGINE_ORDER,
            "span": span,
            "cycles": sum(1 for c in range(span) if any(occupancy[c].values())),
            "n_ops": len(trace),
            "slots_used": dict(slots_used),
            "floors": floors,
            "critical_path_len": len(critical),
            "dep_only_span": max(asap) + 1 if trace else 0,
        },
        "ops": columns,
        "edges": edges,
        "critical": critical,
        "occupancy": [
            [occupancy[c][engine] for engine in ENGINE_ORDER] for c in range(span)
        ],
        "backlog": backlog,
        "scratch": sorted(
            (addr, name, length) for addr, (name, length) in kb.scratch_debug.items()
        ),
    }

    with open(args.out, "w") as handle:
        json.dump(payload, handle, separators=(",", ":"))

    size_mb = os.path.getsize(args.out) / 1e6
    meta = payload["meta"]
    print(f"wrote {args.out}  ({size_mb:.1f} MB)")
    print(f"  cycles {meta['cycles']}   span {meta['span']}   ops {meta['n_ops']}")
    print(f"  dependency-only span (no slot limits): {meta['dep_only_span']}")
    print(f"  critical-path ops (slack 0): {meta['critical_path_len']}")
    print(f"  per-engine floors: {meta['floors']}")
    print(f"  edges: {len(edges)}")


if __name__ == "__main__":
    main()
