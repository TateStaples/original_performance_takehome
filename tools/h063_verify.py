"""H-063: verification of the config carried forward (unchanged 1006 mainline).

H-063 found no accepted change, so the "best config" is the frontier it
started from.  This re-verifies it end to end so the strain log carries a
fresh, self-contained record: multi-seed correctness, ring audit, and the
full bound stack (cp / per-engine floors / energetic / realized / regret).

Usage (repo root):  python3 tools/h063_verify.py
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
import h061_common as C  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402
from run_variant import measure  # noqa: E402


def main() -> None:
    kw = C.kwargs()

    print("== multi-seed correctness ==")
    for seed in (None, 1, 2, 3, 7, 42, 99):
        cyc, ok = measure(kw, seed=seed)
        print(f"  seed={str(seed):<5} cycles={cyc} correct={ok}")
    cyc, ok = measure(dict(kw, debug_compares=True), seed=5)
    print(f"  debug_compares=True  cycles={cyc} correct={ok}")

    print("\n== slot census + bound stack ==")
    rep = C.report("1006-mainline", kw)
    print(json.dumps({k: rep[k] for k in
                      ("bundles", "slots", "floors", "floor", "binder",
                       "regret_vs_own_floor", "cycles", "correct")}))

    data, ops, preds, floors = A.capture_stream(None)
    place = [op[9] for op in ops]
    n = len(ops)
    # critical path (longest dependency chain, unit lag)
    succ: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j, _lag in preds[i]:
            succ[j].append(i)
    height = [0] * n
    for i in range(n - 1, -1, -1):
        height[i] = max((height[k] + 1 for k in succ[i]), default=0)
    cp = max(height) + 1
    # energetic load bound (H-061 / G-34): naive load floor + ramp/drain 31
    n_load = sum(1 for op in ops if op[0] == "load")
    print(json.dumps({
        "cp_lower_bound": cp,
        "load_ops": n_load,
        "naive_load_floor": -(-n_load // SLOT_LIMITS["load"]),
        "energetic_load_bound_G34": -(-n_load // SLOT_LIMITS["load"]) + 31,
        "realized": max(place) + 1,
    }))


if __name__ == "__main__":
    main()
