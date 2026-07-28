"""H-053: FREE-SLOT ORACLE -- a standing pre-screen for op-removal hypotheses.

Question it answers in one run: "if the ops I want to delete/migrate cost
NOTHING at all, how many cycles would that be worth?" That is a hard upper
bound on any respelling, migration, or algebraic removal of the class -- so if
the oracle says 0, the hypothesis is dead before any code is written.

Mechanism: re-route the chosen ops to the machine's `debug` engine (64 slots
per cycle, and `Machine.step` does not advance `cycle` for a bundle that holds
only debug slots). Dependency edges and the 1-cycle write latency are
PRESERVED, only the slot cost disappears -- so the result isolates "slot
pressure" from "dependency structure". The resulting program is NOT correct
(debug slots are not executed when `enable_debug=False`); this tool reports
cycles only, never a `correct` flag.

Reported cycles = bundles that still contain non-debug work, which is exactly
what `Machine.run` would count.

Why it exists (H-053, research/strains/flow-balance/STATE.md): at 1023 cycles
the engine-floor model says valu binds at 1010, yet freeing ALL 59 vbroadcasts
measures 1024 and freeing ALL 7,051 vector ops measures 993. The census floor
is not causal; screen against this instead of `ceil(slots/width)`.

Usage (repo root):
    python tools/free_slot_oracle.py --class bcast
    python tools/free_slot_oracle.py --class vec --count 300 --offset 1500
    python tools/free_slot_oracle.py --class all --set l4_gmin=9,30

Classes: bcast (vbroadcast), vec (elementwise vector ops via _sched_vec),
madd (multiply_add via _sched_madd), gather (scalar tree loads), all
(vec + madd). --count/--offset select a window in the class's emission order,
so the marginal value can be mapped by phase.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dev  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402

CLASSES = ("bcast", "vec", "madd", "gather", "all")


def measure_free(op_class: str, count: int, offset: int,
                 overrides: dict[str, Any] | None = None,
                 seed: int | None = None) -> tuple[int, int]:
    """Return (cycles, ops_freed) with the selected op window made free."""
    from frozen_problem import Tree, Input, build_mem_image

    state = {"seen": 0, "freed": 0}

    def take() -> bool:
        i = state["seen"]
        state["seen"] = i + 1
        if offset <= i < offset + count:
            state["freed"] += 1
            return True
        return False

    orig_vec = dev.KernelBuilder._sched_vec
    orig_madd = dev.KernelBuilder._sched_madd
    orig_emit = dev.ListScheduler.emit

    def free_vec(self, scheduler, op, dest, a, b, allow_alu=False,
                 force_alu=False, valu_ties=False):
        if op_class in ("vec", "all") and take():
            scheduler.emit("debug", (op, dest, a, b),
                           self._v(a) + self._v(b), self._v(dest))
            return dest
        return orig_vec(self, scheduler, op, dest, a, b, allow_alu, force_alu,
                        valu_ties)

    def free_madd(self, scheduler, dst, a, b, c):
        if op_class in ("madd", "all") and take():
            scheduler.emit("debug", ("multiply_add", dst, a, b, c),
                           self._v(a) + self._v(b) + self._v(c), self._v(dst))
            return dst
        return orig_madd(self, scheduler, dst, a, b, c)

    def free_emit(self, engine, slot, reads=(), writes=(), mem_read=False,
                  mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
                  ignore_mem_write_hazard=False):
        if op_class == "bcast" and slot[0] == "vbroadcast" and take():
            engine = "debug"
        elif (op_class == "gather" and engine == "load" and slot[0] == "load"
                and take()):
            engine = "debug"
        return orig_emit(self, engine, slot, reads, writes, mem_read, mem_write,
                         min_cycle, ignore_mem_read_hazard,
                         ignore_mem_write_hazard)

    dev.KernelBuilder._sched_vec = free_vec       # type: ignore[method-assign]
    dev.KernelBuilder._sched_madd = free_madd     # type: ignore[method-assign]
    dev.ListScheduler.emit = free_emit            # type: ignore[method-assign]
    try:
        if seed is not None:
            random.seed(seed)
        forest = Tree.generate(SHAPE["forest_height"])
        problem_input = Input.generate(forest, SHAPE["batch_size"], SHAPE["rounds"])
        build_mem_image(forest, problem_input)
        kb = dev.KernelBuilder()
        kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                                  SHAPE["forest_height"],
                                  **dict(BASE_KWARGS, **(overrides or {})))
    finally:
        dev.KernelBuilder._sched_vec = orig_vec       # type: ignore[method-assign]
        dev.KernelBuilder._sched_madd = orig_madd     # type: ignore[method-assign]
        dev.ListScheduler.emit = orig_emit            # type: ignore[method-assign]

    cycles = sum(1 for b in kb.instrs if any(e != "debug" for e in b))
    return cycles, state["freed"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="op_class", choices=CLASSES, default="bcast")
    ap.add_argument("--count", type=int, default=10 ** 9)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    ap.add_argument("--plan-json", default=None, metavar="PATH",
                    help="an emission-plan JSON (tools/h049_best_plan.json "
                         "shape): applies its config_overrides + plan first")
    args = ap.parse_args()

    overrides: dict[str, Any] = {}
    if args.plan_json:
        with open(args.plan_json) as fh:
            doc = json.load(fh)

        def tup(x: Any) -> Any:
            return tuple(tup(i) for i in x) if isinstance(x, list) else x

        overrides.update({k: tup(v) for k, v in doc["config_overrides"].items()})
        overrides["emission_plan"] = tup(doc["plan"])
    for item in args.set:
        key, sep, val = item.partition("=")
        if not sep:
            raise SystemExit(f"--set expects KEY=VALUE, got {item!r}")
        overrides[key] = parse_value(val)

    base, _ = measure_free("none", 0, 0, overrides, args.seed)
    cycles, freed = measure_free(args.op_class, args.count, args.offset,
                                 overrides, args.seed)
    print(json.dumps({
        "class": args.op_class, "count": args.count, "offset": args.offset,
        "freed": freed, "baseline_cycles": base, "oracle_cycles": cycles,
        "delta": cycles - base,
        "note": "oracle programs are NOT bit-correct; cycles only",
    }))


if __name__ == "__main__":
    main()
