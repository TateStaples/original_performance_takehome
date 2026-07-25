"""
Bridge: build a kernel program with the Rust harness (rust_harness/,
`cargo run --bin gen_kernel`) and validate it against the *real* grading
simulator, tests/frozen_problem.py -- the same one tests/submission_tests.py
uses -- without touching anything under tests/.

This is the last step of the workflow described in rust_harness/README.md:
iterate fast in Rust (typed API, `cargo test`, fixture-based debug compares),
then run this once you're happy to confirm it actually passes grading.

Usage (from the repo root):
    python tools/load_rust_kernel.py
    python tools/load_rust_kernel.py --forest-height 10 --batch-size 256 --rounds 16
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from problem import Engine, Instruction, Program

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUST_DIR = os.path.join(REPO_ROOT, "rust_harness")

sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))


def instrs_from_json(bundles: list[dict[Engine, list[list[Any]]]]) -> Program:
    """Rust's JSON bundles (lists of lists) -> KernelBuilder's tuple form."""
    instrs: Program = []
    for bundle in bundles:
        instr: Instruction = {}
        for engine, slots in bundle.items():
            instr[engine] = [tuple(slot) for slot in slots]
        instrs.append(instr)
    return instrs


def gen_kernel_json(forest_height: int, n_nodes: int, batch_size: int, rounds: int) -> Any:
    try:
        result = subprocess.run(
            [
                "cargo", "run", "--release", "--quiet", "--bin", "gen_kernel", "--",
                str(forest_height), str(n_nodes), str(batch_size), str(rounds),
            ],
            cwd=RUST_DIR,
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise SystemExit("cargo not found -- install Rust (https://rustup.rs) to use the Rust harness")
    except subprocess.CalledProcessError as e:
        sys.stderr.write(e.stderr)
        raise SystemExit(f"gen_kernel failed (exit {e.returncode})")
    return json.loads(result.stdout)


def main() -> None:
    arg_parser = argparse.ArgumentParser(description=__doc__)
    arg_parser.add_argument("--forest-height", type=int, default=10)
    arg_parser.add_argument("--batch-size", type=int, default=256)
    arg_parser.add_argument("--rounds", type=int, default=16)
    arg_parser.add_argument("--seed", type=int, default=123)
    args = arg_parser.parse_args()

    # Import the frozen grading copy, exactly like tests/submission_tests.py.
    from frozen_problem import Machine, DebugInfo, build_mem_image, reference_kernel2, Tree, Input, N_CORES

    random.seed(args.seed)
    forest = Tree.generate(args.forest_height)
    problem_input = Input.generate(forest, args.batch_size, args.rounds)
    mem = build_mem_image(forest, problem_input)

    bundles = gen_kernel_json(args.forest_height, len(forest.values), args.batch_size, args.rounds)
    instrs = instrs_from_json(bundles)

    machine = Machine(mem, instrs, DebugInfo(scratch_map={}), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    ref_mem = mem
    for ref_mem in reference_kernel2(ref_mem):
        pass

    input_values_ptr = ref_mem[6]
    value_count = len(problem_input.values)
    correct = (
        machine.mem[input_values_ptr : input_values_ptr + value_count]
        == ref_mem[input_values_ptr : input_values_ptr + value_count]
    )

    print(f"bundles: {len(instrs)}")
    print(f"CYCLES: {machine.cycle}")
    print(f"CORRECT: {correct}")
    if not correct:
        sys.exit(1)


if __name__ == "__main__":
    main()
