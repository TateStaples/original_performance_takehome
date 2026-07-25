"""
Measure a build_kernel_scheduled VARIANT against the real frozen grader
(tests/frozen_problem.py) without touching build_kernel() dispatch.

The research loop's fast measurement tool: strain agents and the sweep use
this to cost flag-gated variants; the mainline accept gate remains
`python tests/submission_tests.py`.

Usage (repo root):
    python tools/run_variant.py                          # mainline config
    python tools/run_variant.py --set skew=8,2 --set temp_and_cond_pool_sizes=15,4
    python tools/run_variant.py --set tournament_levels=1,2 --seed 7

Values parse via ast.literal_eval; bare comma lists become tuples
(`skew=4,3` -> (4, 3)); `skew=[0,3,6,9]` stays a list. Prints one JSON line:
{"config": ..., "cycles": N, "correct": bool} so callers can machine-read it.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import random
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

# Graded defaults (perf_takehome.build_kernel dispatch) — kept in one place
# so sweep grids and agents share them.
BASE_KWARGS: dict[str, Any] = {
    "tournament_levels": (1, 2, 3),
    "alu_offload": True,
    "l4_gmin": (9, 30),
    "temp_and_cond_pool_sizes": (16, 4),
    "skew": (4, 3),
    "parity_conds": True,  # H-001 accepted iter 1 (1140 -> 1130)
    "auto_raced_first_fold_levels": (1, 2),  # H-017 iter 2; (1,3) sweep-win superseded by H-019 retune
    "c5_prexored_value_domain": True,  # H-015 accepted iter 2 (composed retune -> 1088)
    "pair_tournament_second_fold_race": True,  # H-019 accepted iter 3 (emit_any U-combine race)
    "pair_tournament_first_fold_race": 3,  # H-019: first 3 W-pairs dual-encoded
    "idx_recurrence_race": True,  # H-019: Idx madds get alu spellings
    "derive_consts": True,  # H-024 accepted iter 5 (setup consts on alu)
    "alu_val_addrs": True,  # H-024: va addresses off the 1-wide flow engine
    "c5_primed_gather_levels": (5,),  # H-026 iter 6: in-mem C5-priming of level 5
    "store_pair": True,  # H-028 iter 6: disjoint same-cycle store pairing
    "reverse_newest_parity_fold": (15,),  # H-027 iter 6: reverse-newest-parity-fold final round...
    "newest_parity_last_leaf_diff_tables": True,  # ...with leaf-diff tables in dead registers
    "idx_select_before_madd": True,  # H-029 accepted: steady-gather idx update as vselect (1053 -> 1043 composed w/ l4_gmin retune)
    "tie_break": "fold_flow",  # H-021/H-029-follow-up: dual_fold ties favor flow over valu (1043 -> 1041, re-measured under the new engine mix)
    "debug_compares": False,  # speed; grader ignores debug slots anyway
}
SHAPE: dict[str, int] = {"forest_height": 10, "batch_size": 256, "rounds": 16}


def parse_value(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        if "," in text:
            return tuple(ast.literal_eval(t.strip()) for t in text.split(","))
        return text  # bare string (e.g. a mode name)


def measure(
    overrides: dict[str, Any] | None = None,
    seed: int | None = None,
    shape: dict[str, int] | None = None,
) -> tuple[int, bool]:
    """Build the variant and run it on the frozen grader.
    Returns (cycles, correct: bool). Unseeded (like the grader) unless seed
    is given for reproducible inner loops."""
    from frozen_problem import (
        Machine, N_CORES, Tree, Input, build_mem_image, reference_kernel2,
    )
    # dev.py keeps the full flag-configurable build_kernel_scheduled that
    # this tool sweeps over; perf_takehome.py is the flag-free submission.
    from dev import KernelBuilder

    resolved_shape = dict(SHAPE, **(shape or {}))
    kwargs = dict(BASE_KWARGS, **(overrides or {}))
    if seed is not None:
        random.seed(seed)
    forest = Tree.generate(resolved_shape["forest_height"])
    problem_input = Input.generate(
        forest, resolved_shape["batch_size"], resolved_shape["rounds"]
    )
    mem = build_mem_image(forest, problem_input)

    kernel_builder = KernelBuilder()
    kernel_builder.build_kernel_scheduled(
        resolved_shape["batch_size"],
        resolved_shape["rounds"],
        resolved_shape["forest_height"],
        **kwargs
    )

    machine = Machine(mem, kernel_builder.instrs, kernel_builder.debug_info(), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for ref_mem in reference_kernel2(mem):
        pass
    input_values_ptr = ref_mem[6]
    value_count = len(problem_input.values)
    correct = (
        machine.mem[input_values_ptr : input_values_ptr + value_count]
        == ref_mem[input_values_ptr : input_values_ptr + value_count]
    )
    return machine.cycle, correct


def main() -> None:
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                             help="override a build_kernel_scheduled kwarg")
    arg_parser.add_argument("--seed", type=int, default=None)
    args = arg_parser.parse_args()

    overrides: dict[str, Any] = {}
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
