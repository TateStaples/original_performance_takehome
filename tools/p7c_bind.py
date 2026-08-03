"""P7-C: which dependency classes actually BIND in the 1006 frontier build?

Read-only instrumentation: monkeypatches ListScheduler.ready to recompute,
per call, the cycle each constraint class alone would demand, so we can
count (a) which class is the max (binding) and (b) how much earlier a
TRUTH-EXACT model would allow the op (before slot availability).

Truth (problem.py:382-429):
  RAW scratch 1 | WAR scratch 0 | WAW scratch 0 (last-wins in bundle)
  RAW mem 1 (per ADDRESS) | WAR mem 0 | WAW mem 0 (per address, last-wins)
Model (dev.py ListScheduler.ready:163-186):
  RAW scratch 1 | WAR scratch 0 | WAW scratch 1  <-- conservative
  RAW mem 1 vs COARSE whole-mem write clock      <-- coarse
  WAR mem 0 vs COARSE whole-mem read clock       <-- coarse-but-exact-bound
  WAW mem 1 (0 if pair_writes) coarse            <-- store_pair=True => exact
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h060_common as C  # noqa: E402

STATS: Counter[str] = Counter()
SLACK: Counter[str] = Counter()


def patched_ready(self, reads=(), writes=(), mem_read=False, mem_write=False,
                  min_cycle=0, ignore_mem_read_hazard=False,
                  ignore_mem_write_hazard=False):
    lw = self.last_write
    lr = self.last_read
    c_min = min_cycle
    c_raw = -1
    c_waw = -1
    c_war = -1
    for addr in reads:
        t = lw.get(addr, -1) + 1
        if t > c_raw:
            c_raw = t
    for addr in writes:
        t = lw.get(addr, -1) + 1
        if t > c_waw:
            c_waw = t
        t = lr.get(addr, -1)
        if t > c_war:
            c_war = t
    c_mraw = -1
    c_mwaw = -1
    c_mwar = -1
    if mem_read and not ignore_mem_write_hazard:
        c_mraw = self.last_mem_write_cycle + 1
    if mem_write:
        c_mwaw = self.last_mem_write_cycle + (0 if self.pair_writes else 1)
        if not ignore_mem_read_hazard:
            c_mwar = self.last_mem_read_cycle
    parts = {"min": c_min, "raw": c_raw, "waw": c_waw, "war": c_war,
             "mraw": c_mraw, "mwaw": c_mwaw, "mwar": c_mwar}
    cycle = max(parts.values())
    if cycle < 0:
        cycle = 0
    # which classes are (co-)binding at the max
    binders = [k for k, v in parts.items() if v == cycle and v >= 0]
    STATS["calls"] += 1
    for b in binders:
        STATS["bind_" + b] += 1
    if len(binders) == 1:
        STATS["solebind_" + binders[0]] += 1
        # how much earlier would dropping this sole binder let us go?
        rest = max([v for k, v in parts.items() if k != binders[0]] + [0])
        SLACK["solebind_" + binders[0]] += cycle - rest
    return cycle


def main() -> None:
    dev.ListScheduler.ready = patched_ready  # type: ignore[method-assign]
    cfg = C.frontier()
    kb, prog = C.build(cfg)
    n_empty = sum(1 for b in prog if not b)
    n_debug_only = sum(1 for b in prog
                       if b and all(e == "debug" for e in b))
    print(f"bundles={len(prog)} empty={n_empty} debug_only={n_debug_only}")
    print("floors", C.floors(prog))
    for k in sorted(STATS):
        print(f"  {k:22s} {STATS[k]}")
    print("sole-binder total slack (cycles that class alone pushed):")
    for k in sorted(SLACK):
        print(f"  {k:22s} {SLACK[k]}")


if __name__ == "__main__":
    main()
