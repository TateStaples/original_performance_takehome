"""H-060 shared plumbing: the 1006 frontier config + measurement helpers.

The frontier is tools/h057_best_plan_1006.json (`params.mix` + `plan` as
`emission_plan`) on top of run_variant.BASE_KWARGS.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from run_variant import BASE_KWARGS, SHAPE  # noqa: E402


def _tuplify(v: Any) -> Any:
    return tuple(_tuplify(x) for x in v) if isinstance(v, list) else v


PLAN_PATH = os.path.join(REPO_ROOT, "tools", "h057_best_plan_1006.json")


def frontier(**overrides: Any) -> dict[str, Any]:
    with open(PLAN_PATH) as f:
        d = json.load(f)
    mix = {k: _tuplify(v) for k, v in d["params"]["mix"].items()}
    plan = []
    for e in d["plan"]:
        plan.append(("rr", tuple(tuple(p) for p in e[1]))
                    if e[0] == "rr" else tuple(e))
    cfg = dict(BASE_KWARGS, **mix)
    cfg["emission_plan"] = tuple(plan)
    cfg["debug_compares"] = False
    cfg.update(overrides)
    return cfg


def build(cfg: dict[str, Any]):
    """Build the kernel only (no grader). Returns (KernelBuilder, program)."""
    import dev
    kb = dev.KernelBuilder()
    kb.build_kernel_scheduled(**dict(SHAPE, **cfg))
    return kb, kb.instrs


def slot_census(prog) -> dict[str, int]:
    from collections import Counter
    c: Counter[str] = Counter()
    for instr in prog:
        for eng, slots in instr.items():
            c[eng] += len(slots)
    return dict(c)


def op_census(prog) -> dict[tuple[str, str], int]:
    from collections import Counter
    c: Counter[tuple[str, str]] = Counter()
    for instr in prog:
        for eng, slots in instr.items():
            for s in slots:
                c[(eng, str(s[0]))] += 1
    return dict(c)


SLOT_LIMITS = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1}


def floors(prog) -> dict[str, int]:
    import math
    cen = slot_census(prog)
    return {e: math.ceil(cen.get(e, 0) / w) for e, w in SLOT_LIMITS.items()}


def measure(cfg: dict[str, Any], seed: int | None = None) -> tuple[int, bool]:
    from run_variant import measure as _m
    return _m(cfg, seed=seed)
