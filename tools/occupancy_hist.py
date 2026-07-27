"""H-041 measurement tool: per-cycle engine occupancy histogram + gather
census by round/tree level for any build_kernel_scheduled variant.

Answers, for a given flag configuration:
  - total slots and utilization per engine, and the per-engine cycle floors
    (slots / SLOT_LIMITS[e]) that bound any rebalancing argument;
  - which engine combinations are simultaneously saturated, cycle by cycle
    (the "who binds where" histogram corsix's 7.5:2:1 framing asks for);
  - windowed occupancy (50-cycle windows) with free load/flow slot counts,
    to locate ramp / steady-state / drain slack;
  - load slots by emission round (tree level = round mod (forest_height+1)),
    i.e. the gather census a gather->select-tree conversion would target;
  - the conversion currency: cycles that are load-full while flow (or valu)
    still has a free slot.

Usage (repo root):
    python tools/occupancy_hist.py                    # mainline config
    python tools/occupancy_hist.py --set l4_gmin="({8,9},{30,31})"
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from dev import KernelBuilder  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE, parse_value  # noqa: E402

ENGINES = ["alu", "valu", "load", "store", "flow"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", action="append", default=[], metavar="FLAG=VALUE")
    ap.add_argument("--window", type=int, default=50)
    args = ap.parse_args()

    overrides: dict[str, Any] = {}
    for item in args.set:
        key, _, text = item.partition("=")
        overrides[key.strip()] = parse_value(text.strip())

    kwargs = dict(BASE_KWARGS, **overrides)
    kb = KernelBuilder()
    kb.sched_trace = []
    kb.build_kernel_scheduled(
        SHAPE["batch_size"], SHAPE["rounds"], SHAPE["forest_height"], **kwargs
    )

    instrs = kb.instrs
    n = len(instrs)
    lim = {e: SLOT_LIMITS[e] for e in ENGINES}
    occ = [{e: len(b.get(e, ())) for e in ENGINES} for b in instrs]
    tot = {e: sum(o[e] for o in occ) for e in ENGINES}

    print(f"cycles={n}")
    print("total slots:", tot)
    print("utilization %:", {e: round(tot[e] / (lim[e] * n) * 100, 1) for e in ENGINES})
    print("per-engine cycle floors (slots/limit):",
          {e: round(tot[e] / lim[e], 1) for e in ENGINES})

    combo = Counter()
    for o in occ:
        combo[tuple(e for e in ENGINES if o[e] == lim[e])] += 1
    print("\nsaturated-engine combos (cycles where exactly these engines are full):")
    for c, k in combo.most_common():
        print(f"  {','.join(c) if c else '(none full)':30s} {k}")

    W = args.window
    print(f"\nwindowed occupancy (avg slots used per cycle over {W}-cycle windows):")
    print(f"{'win':>9s} " + " ".join(f"{e:>9s}" for e in ENGINES) + "  loadfree flowfree")
    for s in range(0, n, W):
        w = occ[s:s + W]
        row = {e: sum(o[e] for o in w) / len(w) for e in ENGINES}
        loadfree = sum(lim["load"] - o["load"] for o in w)
        flowfree = sum(lim["flow"] - o["flow"] for o in w)
        print(f"{s:4d}-{min(s + W, n):4d} "
              + " ".join(f"{row[e]:5.1f}/{lim[e]:<3d}" for e in ENGINES)
              + f"  {loadfree:8d} {flowfree:8d}")

    for lo, hi in [(0, 100), (100, 950), (950, n)]:
        w = occ[lo:min(hi, n)]
        fr = {e: sum(lim[e] - o[e] for o in w) for e in ENGINES}
        print(f"free slots cycles {lo}-{min(hi, n)}: {fr}")

    # gather census by emission round (trace tag = (round, group) or None)
    by_round_slots: dict[Any, Counter] = defaultdict(Counter)
    for ent in kb.sched_trace:
        eng, tag = ent[1], ent[2]
        by_round_slots["setup/drain" if tag is None else tag[0]][eng] += 1
    period = SHAPE["forest_height"] + 1
    print("\nper-round engine slots (tree level = round mod "
          f"{period}; gathers for round r+1 are emitted under round r's tag):")
    for rnd in sorted(by_round_slots, key=str):
        lvl = rnd % period if isinstance(rnd, int) else "-"
        counts = by_round_slots[rnd]
        print(f"  round {rnd!s:>11s} (lvl {lvl!s:>2s}): "
              + " ".join(f"{e}={counts[e]}" for e in ENGINES))

    load_full = [o for o in occ if o["load"] == lim["load"]]
    print(f"\nload-full cycles: {len(load_full)}")
    print("load-full & flow-free:",
          sum(1 for o in load_full if o["flow"] < lim["flow"]),
          " load-full & valu-free:",
          sum(1 for o in load_full if o["valu"] < lim["valu"]),
          " both:",
          sum(1 for o in load_full
              if o["flow"] < lim["flow"] and o["valu"] < lim["valu"]))


if __name__ == "__main__":
    main()
