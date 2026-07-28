"""H-059: spend the freed scratch at each point of the trade curve.

At window size W the aliasing frees (32-W)*24 words.  This buys the ONE
spend that survived the relaxation pre-screens (tools/h059_oracle.py closed
temp/cond pools, tools/h059_ringmax.py closed ring COUNT beyond 40 at the
1006 stream): parity rings funded from REAL freed words instead of borrowed
dead windows -- which is the mechanism H-045/H-048 could not afford and the
one H-059 was raised to enable.

For each W it fills the freed space with as many 24-word rings as fit, over
several ring-key orders, and reports the best correct configuration.

Usage: python3 tools/h059_spend.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_alias as A  # noqa: E402
import h059_curve as H  # noqa: E402
import h059_oracle as O  # noqa: E402
from run_variant import measure  # noqa: E402
from problem import SCRATCH_SIZE  # noqa: E402

N_GROUPS, ROUNDS = 32, 16


def ring_orders() -> dict[str, list[tuple[int, int]]]:
    gs = list(range(N_GROUPS))
    return {
        "e0-asc": [(0, g) for g in gs],
        "e1-asc": [(1, g) for g in gs],
        "e0-desc": [(0, g) for g in reversed(gs)],
        "e1-desc": [(1, g) for g in reversed(gs)],
        "e1-late": [(1, g) for g in gs[16:] + gs[:16]],
        "e0-late": [(0, g) for g in gs[16:] + gs[:16]],
        "zip": [(e, g) for g in gs for e in (0, 1)],
    }


def main() -> None:
    out = []
    for w in (24, 20, 16, 12, 8):
        plan = H.rolling_plan_lags(w, sorted(A.BEST_LAGS[w]), "zip")
        base = dict(A.base_mix(), emission_plan=plan, group_window=w)
        try:
            nb, top = O.build(base)
        except Exception as exc:
            print(json.dumps({"w": w, "error": str(exc)[:120]}))
            continue
        free = SCRATCH_SIZE - top
        c0, ok0 = measure(base, seed=1)
        rec: dict[str, Any] = {"w": w, "free_words": free, "no_rings": c0,
                               "no_rings_correct": bool(ok0),
                               "rings_affordable": free // 24}
        best = (c0, "none", 0) if ok0 else (10 ** 6, "none", 0)
        for name, keys in ring_orders().items():
            plan_r, a = [], top
            for k in keys:
                if a + 24 > SCRATCH_SIZE:
                    break
                plan_r.append((k, (a, a + 8, a + 16)))
                a += 24
            if not plan_r:
                continue
            try:
                c, ok = measure(dict(base, parity_ring=True,
                                     parity_ring_plan=tuple(plan_r)), seed=1)
            except Exception:
                continue
            if ok and c < best[0]:
                best = (c, name, len(plan_r))
        rec["best"] = best[0]
        rec["best_ring_order"] = best[1]
        rec["best_ring_count"] = best[2]
        print(json.dumps(rec), flush=True)
        out.append(rec)
    # reference: same flags, full 32-group liveness, with and without rings
    plan32 = H.rolling_plan_lags(32, sorted(A.BEST_LAGS[32]), "zip")
    c, ok = measure(dict(A.base_mix(), emission_plan=plan32), seed=1)
    print(json.dumps({"w": 32, "free_words": 3, "no_rings": c,
                      "no_rings_correct": bool(ok), "best": c}))


if __name__ == "__main__":
    main()
