"""
Measure a build_kernel_scheduled VARIANT against the real frozen grader
(tests/frozen_problem.py) without touching build_kernel() dispatch.

The research loop's fast measurement tool: strain agents and the sweep use
this to cost flag-gated variants; the mainline accept gate remains
`python tests/submission_tests.py`.

Usage (repo root):
    python tools/run_variant.py                          # mainline config
    python tools/run_variant.py --set skew=8,2 --set pool_sizes=15,4
    python tools/run_variant.py --set tournament_levels=1,2 --seed 7

Values parse via ast.literal_eval; bare comma lists become tuples
(`skew=4,3` -> (4, 3)); `skew=[0,3,6,9]` stays a list. Prints one JSON line:
{"config": ..., "cycles": N, "correct": bool} so callers can machine-read it.
"""

import argparse
import ast
import json
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

# Graded defaults (perf_takehome.build_kernel dispatch) — kept in one place
# so sweep grids and agents share them.
BASE_KWARGS = {
    "tournament_levels": (1, 2, 3),
    "alu_offload": True,
    "l4_gmin": (15, 29),
    "pool_sizes": (17, 4),
    "skew": (4, 3),
    "parity_conds": True,  # H-001 accepted iter 1 (1140 -> 1130)
    "vsel_auto": (1, 3),  # H-017 iter 2; retuned to (1,3) by phase-3 sweep @1087
    "c5_prexor": True,  # H-015 accepted iter 2 (composed retune -> 1088)
    "debug_compares": False,  # speed; grader ignores debug slots anyway
}
SHAPE = {"forest_height": 10, "batch_size": 256, "rounds": 16}


def parse_value(text):
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        if "," in text:
            return tuple(ast.literal_eval(t.strip()) for t in text.split(","))
        return text  # bare string (e.g. a mode name)


def measure(overrides=None, seed=None, shape=None):
    """Build the variant and run it on the frozen grader.
    Returns (cycles, correct: bool). Unseeded (like the grader) unless seed
    is given for reproducible inner loops."""
    from frozen_problem import (
        Machine, N_CORES, Tree, Input, build_mem_image, reference_kernel2,
    )
    from perf_takehome import KernelBuilder

    sh = dict(SHAPE, **(shape or {}))
    kwargs = dict(BASE_KWARGS, **(overrides or {}))
    if seed is not None:
        random.seed(seed)
    forest = Tree.generate(sh["forest_height"])
    inp = Input.generate(forest, sh["batch_size"], sh["rounds"])
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder()
    kb.build_kernel_scheduled(
        sh["batch_size"], sh["rounds"], sh["forest_height"], **kwargs
    )

    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for ref_mem in reference_kernel2(mem):
        pass
    p = ref_mem[6]
    n = len(inp.values)
    correct = machine.mem[p : p + n] == ref_mem[p : p + n]
    return machine.cycle, correct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override a build_kernel_scheduled kwarg")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    overrides = {}
    for item in args.set:
        key, _, val = item.partition("=")
        if not _:
            raise SystemExit(f"--set expects KEY=VALUE, got {item!r}")
        overrides[key] = parse_value(val)

    cycles, correct = measure(overrides, seed=args.seed)
    print(json.dumps({
        "config": {k: repr(v) for k, v in overrides.items()},
        "cycles": cycles,
        "correct": correct,
    }))
    if not correct:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
