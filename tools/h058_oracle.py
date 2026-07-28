"""H-058: multi-class free-slot oracle at an arbitrary plan artifact.

`tools/free_slot_oracle.py` frees ONE op class per run and expects the older
artifact schema (`config_overrides` + `plan`).  Phase-2's latency question
needs COMBINATIONS ("compute free AND gathers free AND selects free -> what
is left?") on the 1006 artifact, whose schema is `params.mix` + `plan`.

This wrapper reuses free_slot_oracle's exact mechanism (re-route the chosen
ops to the machine's 64-wide `debug` engine: dependency edges and the
1-cycle write latency are preserved, only the slot cost disappears) but
composes classes, and loads the point through `tools/f37_lib.load_point`
(the same loader `f37_bounds.py` uses, so the stream is the one that
measures 1006).  Neither shared tool is modified.

Classes: vec, madd (the two compute paths), gather (scalar tree loads),
         bcast (vbroadcast), sel (flow vselects), vload, store.
Result cycles are NOT correct programs -- cycles only.

Usage (repo root):
    python3 tools/h058_oracle.py tools/h057_best_plan_1006.json \
        vec+madd  vec+madd+gather  vec+madd+gather+sel
"""
from __future__ import annotations

import json
import os
import random
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import dev  # noqa: E402
import f37_lib as F  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE  # noqa: E402


def measure(classes: set[str], overrides: dict[str, Any]) -> tuple[int, int]:
    """(cycles, ops_freed) with every op in `classes` made slot-free."""
    from frozen_problem import Tree, Input, build_mem_image

    freed = [0]
    orig_vec = dev.KernelBuilder._sched_vec
    orig_madd = dev.KernelBuilder._sched_madd
    orig_emit = dev.ListScheduler.emit

    def free_vec(self, scheduler, op, dest, a, b, allow_alu=False,
                 force_alu=False, valu_ties=False):
        if "vec" in classes:
            freed[0] += 1
            scheduler.emit("debug", (op, dest, a, b),
                           self._v(a) + self._v(b), self._v(dest))
            return dest
        return orig_vec(self, scheduler, op, dest, a, b, allow_alu, force_alu,
                        valu_ties)

    def free_madd(self, scheduler, dst, a, b, c):
        if "madd" in classes:
            freed[0] += 1
            scheduler.emit("debug", ("multiply_add", dst, a, b, c),
                           self._v(a) + self._v(b) + self._v(c), self._v(dst))
            return dst
        return orig_madd(self, scheduler, dst, a, b, c)

    def free_emit(self, engine, slot, reads=(), writes=(), mem_read=False,
                  mem_write=False, min_cycle=0, ignore_mem_read_hazard=False,
                  ignore_mem_write_hazard=False):
        op = slot[0]
        hit = (("bcast" in classes and op == "vbroadcast")
               or ("gather" in classes and engine == "load" and op == "load")
               or ("vload" in classes and engine == "load" and op == "vload")
               or ("sel" in classes and engine == "flow" and op == "vselect")
               or ("store" in classes and engine == "store"))
        if hit:
            freed[0] += 1
            engine = "debug"
        return orig_emit(self, engine, slot, reads, writes, mem_read, mem_write,
                         min_cycle, ignore_mem_read_hazard,
                         ignore_mem_write_hazard)

    dev.KernelBuilder._sched_vec = free_vec       # type: ignore[method-assign]
    dev.KernelBuilder._sched_madd = free_madd     # type: ignore[method-assign]
    dev.ListScheduler.emit = free_emit            # type: ignore[method-assign]
    try:
        random.seed(0)
        forest = Tree.generate(SHAPE["forest_height"])
        problem_input = Input.generate(forest, SHAPE["batch_size"],
                                       SHAPE["rounds"])
        build_mem_image(forest, problem_input)
        kb = dev.KernelBuilder()
        kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                                  SHAPE["forest_height"],
                                  **dict(BASE_KWARGS, **overrides))
    finally:
        dev.KernelBuilder._sched_vec = orig_vec       # type: ignore[method-assign]
        dev.KernelBuilder._sched_madd = orig_madd     # type: ignore[method-assign]
        dev.ListScheduler.emit = orig_emit            # type: ignore[method-assign]

    cycles = sum(1 for b in kb.instrs if any(e != "debug" for e in b))
    return cycles, freed[0]


def main() -> None:
    path = sys.argv[1]
    combos = sys.argv[2:] or ["vec+madd"]
    order, mix = F.load_point(path)
    ov = dict(mix, emission_plan=order, debug_compares=False)
    base, _ = measure(set(), ov)
    print(json.dumps({"artifact": path, "baseline_cycles": base}))
    for combo in combos:
        classes = set(combo.split("+"))
        cycles, freed = measure(classes, ov)
        print(json.dumps({"free": sorted(classes), "freed_ops": freed,
                          "oracle_cycles": cycles, "delta": cycles - base}))


if __name__ == "__main__":
    main()
