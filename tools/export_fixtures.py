"""
Export golden test fixtures for rust_harness from the real problem.py.

We deliberately do NOT try to reproduce Python's `random` module bit-for-bit
in Rust (see rust_harness/src/problem.rs) — instead this script runs the
real generation + reference kernel here, in Python, and dumps the resulting
memory image (in) / memory image (out) / per-step value trace to JSON. The
Rust harness then only has to *simulate*, not *regenerate*, to check a
candidate kernel against exactly the workload tests/submission_tests.py
grades.

Run from the repo root: python tools/export_fixtures.py
"""

from __future__ import annotations

import json
import os
import random
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from problem import Tree, Input, build_mem_image, reference_kernel2

FIXTURES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "rust_harness",
    "tests",
    "fixtures",
)


def trace_key(key: tuple[Any, ...]) -> str:
    """(round, i, field) or (round, i, "hash_stage", hi) -> "round|i|field[|hi]" """
    return "|".join(str(part) for part in key)


def export(name: str, forest_height: int, batch_size: int, rounds: int, seed: int, with_trace: bool) -> None:
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem_in = build_mem_image(forest, inp)

    mem_out = list(mem_in)
    trace: dict[Any, int] = {}
    for _ in reference_kernel2(mem_out, trace):
        pass

    fixture = {
        "params": {
            "forest_height": forest_height,
            "n_nodes": len(forest.values),
            "batch_size": batch_size,
            "rounds": rounds,
            "seed": seed,
        },
        "mem_in": mem_in,
        "mem_out": mem_out,
        "trace": {trace_key(k): v for k, v in trace.items()} if with_trace else {},
    }

    os.makedirs(FIXTURES_DIR, exist_ok=True)
    path = os.path.join(FIXTURES_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(fixture, f)
    size_kb = os.path.getsize(path) / 1024
    print(f"wrote {path} ({size_kb:.0f} KiB, {len(fixture['trace'])} trace entries)")


if __name__ == "__main__":
    # Small + fast: for cargo test's default run, and for exercising the
    # tree-wraparound edge case (height=2 wraps every few steps).
    export("small", forest_height=2, batch_size=8, rounds=4, seed=1, with_trace=True)

    # The actual benchmark workload from perf_takehome.py / submission_tests.py
    # (BASELINE = 147734 cycles). Trace omitted by default -- it's ~30MB+ of
    # JSON for this size and cargo test doesn't need per-step checking here,
    # only final-memory + cycle-count parity. Pass with_trace=True if you
    # want to debug a divergence at this scale.
    export("baseline", forest_height=10, batch_size=256, rounds=16, seed=123, with_trace=False)
