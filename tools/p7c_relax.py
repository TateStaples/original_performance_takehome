"""P7-C: UPPER BOUND on what any dependency-model tightening can buy.

Monkeypatches ListScheduler.ready with progressively more relaxed models
(some deliberately UNSOUND -- this measures the ceiling, not a shippable
build) and reports realized cycles + correctness of the 1006 frontier.

Modes:
  base      shipped model (control; must reproduce 1006)
  waw0      WAW-scratch relaxed to truth (0 separation)
  nomem     all three coarse mem clocks dropped entirely
  all       waw0 + nomem
  noraw     ALSO drop RAW-scratch (pure slot-limit lower bound; UNSOUND,
            answers "how much of 1006 is dependency height at all")
  nowar     drop WAR-scratch only (unsound; sizes the anti-dep pressure)
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dev  # noqa: E402
import h060_common as C  # noqa: E402

ORIG = dev.ListScheduler.ready


def make_ready(waw0=False, nomem=False, noraw=False, nowar=False):
    def ready(self, reads=(), writes=(), mem_read=False, mem_write=False,
              min_cycle=0, ignore_mem_read_hazard=False,
              ignore_mem_write_hazard=False):
        cycle = min_cycle
        lw = self.last_write
        lr = self.last_read
        if not noraw:
            for addr in reads:
                t = lw.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
        for addr in writes:
            if not waw0 and not noraw:
                t = lw.get(addr, -1) + 1
                if t > cycle:
                    cycle = t
            if not nowar:
                t = lr.get(addr, -1)
                if t > cycle:
                    cycle = t
        if not nomem:
            if mem_read and not ignore_mem_write_hazard and self.last_mem_write_cycle + 1 > cycle:
                cycle = self.last_mem_write_cycle + 1
            if mem_write:
                t = self.last_mem_write_cycle + (0 if self.pair_writes else 1)
                if t > cycle:
                    cycle = t
                if not ignore_mem_read_hazard and self.last_mem_read_cycle > cycle:
                    cycle = self.last_mem_read_cycle
        return cycle
    return ready


MODES = {
    "base": {},
    "waw0": {"waw0": True},
    "nomem": {"nomem": True},
    "all": {"waw0": True, "nomem": True},
    "nowar": {"nowar": True},
    "noraw": {"noraw": True, "waw0": True, "nomem": True, "nowar": True},
}


def main() -> None:
    which = sys.argv[1:] or list(MODES)
    for mode in which:
        dev.ListScheduler.ready = (ORIG if mode == "base"
                                   else make_ready(**MODES[mode]))  # type: ignore
        kb, prog = C.build(C.frontier())
        try:
            cyc, ok = C.measure(C.frontier(), seed=1)
        except Exception as exc:  # unsound modes crash the simulator
            cyc, ok = -1, f"CRASH {type(exc).__name__}"
        print(f"{mode:7s} bundles={len(prog):5d} cycles={cyc:5d} correct={ok}")
        sys.stdout.flush()
    dev.ListScheduler.ready = ORIG  # type: ignore


if __name__ == "__main__":
    main()
