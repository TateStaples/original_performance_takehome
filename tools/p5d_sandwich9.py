#!/usr/bin/env python3
"""Driver rerun of P5-D's headline OPEN shape at long solver budget.

sandwich9 = madd / sigmaC / madd / sigmaC / madd -- THE natural 3-madd 9-op
shape (not a deletion of the real 11-op form; all constants, multipliers,
xor-masks and shifts free). P5-D's 424s run TIMED OUT; per its STATE.md this
is the single most plausible 9-op shape and the highest-value z3 target.

Soundness inherited from tools/p5d_cegis.py: UNSAT on the sample set is a
sound closure; SAT candidates are verified bit-exactly outside Z3 (2^20
sweep + 10M random) with CEGIS iteration on mismatch; TIMEOUT stays OPEN.

Usage: python3 tools/p5d_sandwich9.py [solver_timeout_s=7200] [max_iters=8]
"""
import sys
import time

sys.path.insert(0, "tools")
from p5d_cegis import cegis, myhash  # noqa: E402

# Slot 0 = input x; op k writes slot k+1. sigmaC = shr + xorc + xor2.
SANDWICH_9 = [
    ("madd", 0),      # 1
    ("shr", 1),       # 2
    ("xorc", 1),      # 3
    ("xor2", 2, 3),   # 4
    ("madd", 4),      # 5
    ("shr", 5),       # 6
    ("xorc", 5),      # 7
    ("xor2", 6, 7),   # 8
    ("madd", 8),      # 9 = out
]

if __name__ == "__main__":
    timeout_s = int(sys.argv[1]) if len(sys.argv) > 1 else 7200
    max_iters = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    t0 = time.time()
    verdict, detail = cegis(
        SANDWICH_9, 1, myhash, "sandwich9-long", timeout_s, max_iters
    )
    print(f"SANDWICH9 VERDICT: {verdict}  detail={detail}  "
          f"wall={time.time() - t0:.0f}s", flush=True)
