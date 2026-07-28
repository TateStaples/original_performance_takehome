"""H-059: full verification of a plan artifact.

Runs the artifact's config against the frozen grader on the standard seed
set (unseeded + 1,2,3,7,42,99), once more with debug_compares on (the
value-trace compare path), and prints the bound stack inputs.

Usage: python3 tools/h059_verify.py tools/h059_best_plan_1050.json
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import f37_lib as F  # noqa: E402
from run_variant import measure  # noqa: E402


def main() -> None:
    path = sys.argv[1]
    order, mix = F.load_point(path)
    ov = dict(mix, emission_plan=order, lazy_val_loads=True,
              debug_compares=False)
    rows = []
    for seed in (None, 1, 2, 3, 7, 42, 99):
        c, ok = measure(ov, seed=seed)
        rows.append({"seed": seed, "cycles": c, "correct": bool(ok)})
        print(json.dumps(rows[-1]), flush=True)
    c, ok = measure(dict(ov, debug_compares=True), seed=1)
    print(json.dumps({"seed": 1, "debug_compares": True, "cycles": c,
                      "correct": bool(ok)}))
    print(json.dumps({"all_correct": all(r["correct"] for r in rows) and bool(ok),
                      "cycles": sorted({r["cycles"] for r in rows})}))


if __name__ == "__main__":
    main()
