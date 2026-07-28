"""H-054: emission-order local re-search ON a flow-migrated stream.

"Order absorbs spelling" (H-049) is the loop's strongest empirical rule, so
before declaring the flow-migration axis closed we give the migrated stream
the same treatment the greedy stream got: seed from the 1022 order and run
emission_order_search's windowed local search with `flow_race_bias` pinned.

Wrapper only: patches eos.FRONTIER_OVERRIDES (passed by value into the
worker pool) -- emission_order_search.py itself is untouched.

Usage: python3 tools/h054_local.py --bias 2 --budget 900 --workers 10
"""
from __future__ import annotations

import argparse
import os
import sys

import h054_common as C
import emission_order_search as eos


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bias", type=int, required=True)
    ap.add_argument("--budget", type=float, default=900.0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--window", default="all")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    over = dict(C.FRONTIER)
    over["flow_race_bias"] = args.bias
    eos.FRONTIER_OVERRIDES.clear()
    eos.FRONTIER_OVERRIDES.update(over)
    out = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"h054_local_bias{args.bias}.jsonl")
    eos.local(args.budget, args.workers, out, C.PLAN_1022, window=args.window)


if __name__ == "__main__":
    main()
