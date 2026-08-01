"""P4-C: per-CYCLE valu:load:flow ratio distribution (audit of G-23 leg 1).

corsix states valu:load:flow = 7.5:2:1 in every INDIVIDUAL cycle.  G-23
answered with an AVERAGE ("we already run his balance ... 666/1038 cycles
have all four engines full").  Those are different claims.  This tool
reports the actual cycle-by-cycle distribution of the compute:load:flow
occupancy triple, where compute is measured in vec-op-equivalents
(alu slot = 1/8 vec-op-equivalent of lane throughput, valu slot = 1), so
that a perfectly balanced cycle reads exactly (7.5, 2, 1).

Usage (repo root):
    python3 tools/p4c_ratio.py [--set FLAG=VALUE]...
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
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
    args = ap.parse_args()
    ov: dict[str, Any] = {}
    for item in args.set:
        k, _, t = item.partition("=")
        ov[k.strip()] = parse_value(t.strip())
    kw = dict(BASE_KWARGS, **ov)
    kb = KernelBuilder()
    kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                              SHAPE["forest_height"], **kw)
    instrs = kb.instrs
    n = len(instrs)
    lim = {e: SLOT_LIMITS[e] for e in ENGINES}
    occ = [{e: len(b.get(e, ())) for e in ENGINES} for b in instrs]

    print(f"cycles = {n}")
    # compute in vec-op-equivalents: alu contributes alu/8, valu contributes valu
    trip = Counter()
    for o in occ:
        cv = o["alu"] / 8.0 + o["valu"]
        trip[(round(cv, 3), o["load"], o["flow"])] += 1
    print("\n== exact per-cycle (compute_vec_equiv, load, flow) triples, "
          "top 25 of "
          f"{len(trip)} distinct ==")
    print(f"{'compute':>8}{'load':>6}{'flow':>6}{'cycles':>8}{'%':>7}  note")
    for (cv, ld, fl), k in trip.most_common(25):
        note = ""
        if (cv, ld, fl) == (7.5, 2, 1):
            note = "<<< corsix 7.5:2:1 EXACTLY"
        elif cv == 7.5:
            note = "compute full, ratio off"
        print(f"{cv:>8.3f}{ld:>6}{fl:>6}{k:>8}{k/n*100:>6.1f}%  {note}")

    exact = trip[(7.5, 2, 1)]
    cfull = sum(k for (cv, _, _), k in trip.items() if cv >= 7.5)
    print(f"\ncycles at EXACTLY 7.5:2:1              : {exact:5d} "
          f"({exact/n*100:.1f}%)")
    print(f"cycles with compute at 7.5 (full)      : {cfull:5d} "
          f"({cfull/n*100:.1f}%)")
    print(f"cycles compute-full but NOT 7.5:2:1    : {cfull-exact:5d} "
          f"({(cfull-exact)/n*100:.1f}%)")

    # marginal distributions
    for e in ENGINES:
        c = Counter(o[e] for o in occ)
        tot = sum(o[e] for o in occ)
        print(f"\n{e:5s} lim {lim[e]}  total {tot}  util "
              f"{tot/(lim[e]*n)*100:.1f}%   histogram: "
              + "  ".join(f"{v}:{c[v]}" for v in sorted(c)))

    # the currency question: where are the idle flow slots?
    idle_flow = [(i, o) for i, o in enumerate(occ) if o["flow"] < lim["flow"]]
    print(f"\nidle-flow cycles: {len(idle_flow)}  idle flow slots: "
          f"{sum(lim['flow']-o['flow'] for _, o in idle_flow)}")
    for lo, hi, tag in [(0, 100, "ramp"), (100, 950, "steady"),
                        (950, n, "drain")]:
        w = occ[lo:min(hi, n)]
        f = sum(lim["flow"] - o["flow"] for o in w)
        print(f"  {tag:7s} {lo}-{min(hi,n)}: idle flow slots {f}")
    # of the idle-flow cycles, how many also have compute FULL (so a fold
    # moved onto flow there would strictly relieve the binder)?
    both = sum(1 for _, o in idle_flow if o["alu"]/8.0 + o["valu"] >= 7.5)
    print(f"  idle-flow AND compute-full cycles: {both}  "
          "(each is one vec-op of binder relief available in principle)")


if __name__ == "__main__":
    main()
