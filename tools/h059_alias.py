"""H-059: the realized trade curve WITH register aliasing.

tools/h059_curve.py prices the cycle leg (a rolling-window emission plan
holding W groups live); this one turns on dev's `group_window=W`, which
actually aliases group g onto slot g % W, and reports what that buys in
scratch words alongside what it costs in cycles.

Usage:
  python3 tools/h059_alias.py                # curve at the searched lags
  python3 tools/h059_alias.py --w 16         # one point, verbose
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402
from run_variant import BASE_KWARGS, measure  # noqa: E402
from problem import SCRATCH_SIZE  # noqa: E402
import dev  # noqa: E402

SHAPE = (256, 16, 10)

# Best base diagonal found per window size by tools/h059_search.py
# (ring-free, 100 s of local walk each, ~950 evals).
BEST_LAGS: dict[int, list[int]] = {
    32: [0, 0, 0, 0, 4, 2, 2, 2, 4, 6, 4, 4, 6, 6, 6, 6,
         8, 8, 8, 8, 10, 10, 10, 10, 12, 12, 12, 12, 14, 14, 14, 14],
    24: [0, 0, 0, 2, 4, 2, 4, 4, 4, 6, 6, 6,
         8, 8, 8, 10, 10, 10, 12, 12, 15, 13, 14, 14],
    20: [1, 0, 0, 0, 3, 6, 3, 3, 6, 4, 6, 6, 9, 9, 8, 9, 12, 12, 13, 12],
    16: [0, 0, 0, 0, 4, 3, 2, 4, 8, 6, 5, 6, 9, 9, 9, 9],
    14: [0, 2, 2, 2, 12, 2, 6, 6, 8, 6, 8, 14, 12, 14],
    12: [0, 2, 0, 2, 4, 5, 5, 5, 9, 10, 13, 9],
    8: [0, 1, 0, 4, 8, 8, 3, 8],
    4: [0, 0, 0, 1],
}


def base_mix() -> dict[str, Any]:
    """Ring-free 1006 mix + lazy_val_loads (group_window's precondition)."""
    return dict(BASE_KWARGS, **{k: v for k, v in H.MIX.items()
                                if k not in ("parity_ring", "parity_ring_plan")},
                lazy_val_loads=True, debug_compares=False)


def census(instrs) -> dict[str, int]:
    out: dict[str, int] = {}
    for b in instrs:
        for eng, slots in b.items():
            out[eng] = out.get(eng, 0) + len(slots)
    return out


def point(w: int, alias: bool, seed: int | None = 1) -> dict[str, Any]:
    # alu_val_addrs derives va[g] from va[g-4], so a lazily-loaded group
    # must not start before g-4 does; sorting the searched lag vector is a
    # free relabelling (groups are interchangeable) that guarantees it.
    lags = sorted(BEST_LAGS[w])
    plan = H.rolling_plan_lags(w, lags, "zip")
    ov = dict(base_mix(), emission_plan=plan)
    if alias and w < H.N_GROUPS:
        ov["group_window"] = w
    kb = dev.KernelBuilder()
    try:
        kb.build_kernel_scheduled(*SHAPE, **ov)
    except Exception as exc:
        return {"w": w, "alias": alias,
                "error": f"{type(exc).__name__}: {exc}"[:140]}
    rec: dict[str, Any] = {
        "w": w, "alias": alias, "bundles": len(kb.instrs),
        "scratch": kb.scratch_next_addr,
        "free_words": SCRATCH_SIZE - kb.scratch_next_addr,
        "census": census(kb.instrs),
    }
    try:
        cyc, ok = measure(ov, seed=seed)
        rec["cycles"], rec["correct"] = cyc, bool(ok)
    except Exception as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"[:140]
    return rec


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--w", type=int, action="append", default=[])
    args = ap.parse_args()
    ws = args.w or [32, 24, 20, 16, 14, 12, 8, 4]
    for w in ws:
        for alias in ((False,) if w == 32 else (False, True)):
            print(json.dumps(point(w, alias)), flush=True)


if __name__ == "__main__":
    main()
