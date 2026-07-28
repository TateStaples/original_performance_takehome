"""H-054 / F-17: cross emission-ORDER families with flow-migration POLICY.

H-049 closed every structured order family at greedy spellings; F-17's claim
is that the evaluation was on the wrong board -- de-synchronizing families
(bigger lags, more blocks, stage round-robin) stretch a greedy stream but
might pay once the stream is flow-heavy (floor 30 lower). This measures the
2-D grid (order family x flow_race_bias), correctness-checked.

Usage: python3 tools/h054_cross.py [--workers N]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import sys
from typing import Any

import h054_common as C
import emission_order_search as eos
from run_variant import measure

BIASES = (0, 2, 6, 16, 40, 200)


def _eval(job):
    name, plan, bias = job
    over = dict(C.FRONTIER)
    over["emission_plan"] = plan
    if bias:
        over["flow_race_bias"] = bias
    try:
        cycles, correct = measure(over, seed=1)
    except Exception as e:
        return name, bias, -1, False
    return name, bias, cycles, bool(correct)


def order_families() -> list[tuple[str, tuple[Any, ...]]]:
    out: list[tuple[str, tuple[Any, ...]]] = [
        ("h047_plan_1022", eos.load_plan(C.PLAN_1022)),
        ("default(4,3)", eos.make_plan()),
    ]
    variants: list[tuple[str, dict[str, Any]]] = []
    for lags in ((0, 2, 4, 6), (0, 4, 8, 12), (0, 6, 12, 18), (0, 8, 16, 24),
                 (0, 3, 6, 9), (0, 5, 10, 15)):
        variants.append((f"lags{lags}", {"lags": lags}))
    for k, step in ((8, 1), (8, 2), (8, 3), (8, 4), (16, 1), (16, 2), (32, 1)):
        nb = k
        variants.append((f"blocks{nb}x{step}", {
            "lags": tuple(step * i for i in range(nb)),
            "blocks": [list(range((32 * i) // nb, (32 * (i + 1)) // nb))
                       for i in range(nb)]}))
    variants.append(("zip", {"interleave": "zip"}))
    variants.append(("group_rev", {"group_order": "rev"}))
    variants.append(("stage_rr_all", {"stage_rr": tuple(range(40))}))
    variants.append(("stage_rr_all_wave", {"stage_rr": tuple(range(40)),
                                           "stage_rr_scope": "wave"}))
    for name, v in variants:
        try:
            out.append((name, eos.make_plan(**v)))
        except (AssertionError, ValueError) as e:
            print(f"skip {name}: {e}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    fams = order_families()
    jobs = [(n, p, b) for n, p in fams for b in BIASES]
    print(f"{len(fams)} order families x {len(BIASES)} biases = {len(jobs)} evals",
          flush=True)
    with mp.Pool(args.workers) as pool:
        results = pool.map(_eval, jobs)
    table: dict[str, dict[int, tuple[int, bool]]] = {}
    for name, bias, cycles, ok in results:
        table.setdefault(name, {})[bias] = (cycles, ok)
    hdr = "".join(f"{('b=%d' % b):>12}" for b in BIASES)
    print(f"{'order':>22}{hdr}")
    for name, _ in fams:
        row = "".join(
            f"{(('%d' % table[name][b][0]) + ('' if table[name][b][1] else '!')):>12}"
            for b in BIASES)
        print(f"{name:>22}{row}", flush=True)
    best = min((c, n, b) for n, d in table.items() for b, (c, ok) in d.items()
               if ok and c > 0)
    print("best correct:", best)


if __name__ == "__main__":
    main()
