"""H-061 verification: the shipped 1006 stream is unchanged and correct.

H-061 landed NO source change, so this is a re-confirmation of the frontier
config rather than a check of a new one:

  * multi-seed correctness of the 1006 stream on the frozen grader
  * the full bound stack for the write-up (engine floors, cp, energetic
    load bound)

Usage: python3 tools/h061_verify.py
"""
from __future__ import annotations

import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_common as C  # noqa: E402
import backtrack_sched as B  # noqa: E402
import h061_attrib as A  # noqa: E402
from run_variant import measure  # noqa: E402


def main() -> None:
    kw = C.kwargs()
    for seed in (None, 1, 2, 7, 42, 99):
        cyc, ok = measure(kw, seed=seed)
        print(json.dumps({"seed": seed, "cycles": cyc, "correct": ok}),
              flush=True)
        assert ok, f"INCORRECT at seed {seed}"
    cyc, ok = measure(dict(kw, debug_compares=True), seed=1)
    print(json.dumps({"seed": 1, "debug_compares": True, "cycles": cyc,
                      "correct": ok}))
    assert ok

    data, ops, preds, floors = A.capture_stream(None)
    place = [op[9] for op in ops]
    pl, ne = B.greedy_schedule(ops, preds, floors)
    lb = B.lb_total(ops, preds, floors)
    print(json.dumps({"model_exact": pl == place, "offline_cycles": ne,
                      "bound_stack": lb}))


if __name__ == "__main__":
    main()
