"""H-061: relaxation oracles that isolate the LOAD-side regret.

Each row relaxes exactly one thing about the machine/scheduler and reports
the resulting bundle count.  Programs built under a relaxation are NOT
runnable (the point is the schedule length, which upper-bounds what any
sound version of that mechanism could buy).

  base        the stream as shipped
  nomem       ListScheduler.ready ignores BOTH coarse mem clocks entirely
              (upper bound on any mem-hazard precision work, H-031/F-15 class)
  loadwide    SLOT_LIMITS["load"] raised to 64 (upper bound on everything
              that load-slot contention costs -- i.e. what a perfect
              load-issue policy plus infinite bandwidth could buy)
  freecompute every _sched_vec / _sched_madd op costs no slot (H-053 oracle),
              deps preserved: what is left is load slots + the address
              recurrence
  both        freecompute + loadwide: pure dependency span

Usage:
  python3 tools/h061_oracle.py [gmin ...]     # default: main + load-bound pts
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h061_common as C  # noqa: E402
import free_slot_oracle as FSO  # noqa: E402
import problem  # noqa: E402


def build_len(kw: dict[str, Any]) -> int:
    kb = dev.KernelBuilder()
    kb.build_kernel_scheduled(*C.SHAPE, **kw)
    return sum(1 for b in kb.instrs if any(e != "debug" for e in b))


def with_nomem(kw: dict[str, Any]) -> int:
    orig = dev.ListScheduler.ready

    def ready(self, reads=(), writes=(), mem_read=False, mem_write=False,
              min_cycle=0, ignore_mem_read_hazard=False,
              ignore_mem_write_hazard=False):
        return orig(self, reads, writes, False, False, min_cycle, True, True)

    dev.ListScheduler.ready = ready  # type: ignore[method-assign]
    try:
        return build_len(kw)
    finally:
        dev.ListScheduler.ready = orig  # type: ignore[method-assign]


def with_wide(kw: dict[str, Any], engine: str, width: int) -> int:
    old = problem.SLOT_LIMITS[engine]
    # dev/ListScheduler read SLOT_LIMITS by identity from problem
    problem.SLOT_LIMITS[engine] = width
    try:
        return build_len(kw)
    finally:
        problem.SLOT_LIMITS[engine] = old


def with_free_compute(kw: dict[str, Any], wide_load: int | None = None) -> int:
    old = problem.SLOT_LIMITS["load"]
    if wide_load:
        problem.SLOT_LIMITS["load"] = wide_load
    try:
        cyc, _ = FSO.measure_free("all", 10 ** 9, 0,
                                  {k: v for k, v in kw.items()}, seed=1)
        return cyc
    finally:
        problem.SLOT_LIMITS["load"] = old


def with_nofloor(kw: dict[str, Any]) -> int:
    """Drop every explicit min_cycle floor on LOAD ops (the mem_prime
    `gather_gate`, H-039).  Unsound; bounds what gate precision is worth."""
    orig = dev.ListScheduler.emit

    def emit(self, engine, slot, reads=(), writes=(), mem_read=False,
             mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
             ignore_mem_write_hazard=False):
        if engine == "load":
            min_cycle = 0
        return orig(self, engine, slot, reads, writes, mem_read, mem_write,
                    min_cycle, ignore_mem_read_hazard, ignore_mem_write_hazard)

    dev.ListScheduler.emit = emit  # type: ignore[method-assign]
    try:
        return build_len(kw)
    finally:
        dev.ListScheduler.emit = orig  # type: ignore[method-assign]


def row(label: str, kw: dict[str, Any]) -> dict[str, Any]:
    base = build_len(kw)
    kb = dev.KernelBuilder()
    kb.build_kernel_scheduled(*C.SHAPE, **kw)
    fl = C.floors(kb)
    return {
        "label": label,
        "base": base,
        "floors": fl,
        "load_floor": fl.get("load"),
        "nomem": with_nomem(kw),
        "nofloor": with_nofloor(kw),
        "load3": with_wide(kw, "load", 3),
        "load4": with_wide(kw, "load", 4),
        "loadwide": with_wide(kw, "load", 64),
        "freecompute": with_free_compute(kw),
        "both": with_free_compute(kw, wide_load=64),
    }


def main() -> None:
    args = sys.argv[1:] or ["main", "16,31", "20,31", "24,31", "28,31"]
    for a in args:
        g = None if a in ("main", "mainline") else tuple(int(x) for x in a.split(","))
        kw = C.kwargs(g, rings=(g is None))
        print(json.dumps(row(a, kw)), flush=True)


if __name__ == "__main__":
    main()
