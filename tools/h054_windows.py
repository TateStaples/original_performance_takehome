"""H-054: windowed co-location of flow bubbles and flow-LOST selects.

If bubbles and lost selects share windows, the anti-correlation is a
fine-grained cadence problem (order/policy levers apply). If they live in
different windows, no local mechanism can pair them and the only lever is
global (op-count / chain structure).
"""
from __future__ import annotations

import sys
from collections import Counter

import h054_common as C
import h054_diag as D

W = int(sys.argv[1]) if len(sys.argv) > 1 else 50


def main() -> None:
    kwargs = C.frontier_kwargs()
    kwargs.pop("flow_spelling_plan", None)
    kb = D.build(kwargs, {}, logging=True, trace=True)
    log = list(D.RACE_LOG)
    n = len(kb.instrs)
    occ = D.flow_occupancy(kb)
    valu = []
    for b in kb.instrs:
        ops = b.get("valu", [])
        valu.append(len(ops) if isinstance(ops, list) else (1 if ops else 0))

    lost = Counter()
    won = Counter()
    for r in log:
        if r["site"] is None or r["site"] < 0 or r["flow_idx"] is None:
            continue
        c = r["placed"]
        (won if r["chosen"] == r["flow_idx"] else lost)[c // W] += 1

    print(f"window={W}  cycles={n}")
    print(f"{'win':>6} {'bubbles':>8} {'flowused':>9} {'lost':>5} {'won':>5} "
          f"{'valu_free':>10} {'valu%':>6}")
    tot_b = tot_l = 0
    for w in range((n + W - 1) // W):
        lo, hi = w * W, min(n, (w + 1) * W)
        b = sum(1 for c in range(lo, hi) if occ[c] == 0)
        fu = sum(occ[lo:hi])
        vf = 6 * (hi - lo) - sum(valu[lo:hi])
        tot_b += b
        tot_l += lost[w]
        print(f"{lo:>6} {b:>8} {fu:>9} {lost[w]:>5} {won[w]:>5} {vf:>10} "
              f"{sum(valu[lo:hi]) / (6 * (hi - lo)):>6.1%}")
    print(f"TOTAL bubbles {tot_b}, lost {tot_l}")
    # pairing bound: within each window, min(bubbles, lost)
    pair = sum(min(sum(1 for c in range(w * W, min(n, (w + 1) * W)) if occ[c] == 0),
                   lost[w]) for w in range((n + W - 1) // W))
    print(f"window-local pairing bound: {pair} selects could move (W={W})")


if __name__ == "__main__":
    main()
