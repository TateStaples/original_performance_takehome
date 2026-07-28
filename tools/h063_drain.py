"""H-063 direction C: audit of the drain window (cycles ~958..1005).

H-061 measured 48 idle load slots there.  This tool splits that window into
its two structurally different halves and prices each:

  A. the LATE-STEADY half (compute still 6/6 valu, 12/12 alu; load idle in
     short bursts) -- the same head-style inversion, and
  B. the TRUE TAIL (compute falling off, store engine at 2/2) -- where the
     question is whether the last cycles are bound by the final result
     vstores, by the last groups' compute chain, or by neither.

For every cycle in the window it reports occupancy, the last-round tag mix,
the critical-path lower bound from that cycle on (longest remaining
dependency chain), and the engine lower bound from remaining slot counts --
so "latency" vs "throughput" is decided per cycle, not by eyeball.

Usage (repo root):  python3 tools/h063_drain.py [lo] [hi]
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
import h063_head as HD  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def main() -> None:
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 950
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 6
    data, ops, preds, floors = A.capture_stream(None)
    place = [op[9] for op in ops]
    n = len(ops)
    n_cycles = max(place) + 1
    hi = min(hi, n_cycles)
    occ = A.occupancy(ops, place, n_cycles)

    # successors, for the remaining-critical-path (height) computation
    succ: list[list[int]] = [[] for _ in range(n)]
    for i in range(n):
        for j, lag in preds[i]:
            succ[j].append(i)
    height = [0] * n
    for i in range(n - 1, -1, -1):
        h = 0
        for k in succ[i]:
            if height[k] + 1 > h:
                h = height[k] + 1
        height[i] = h

    order = sorted(range(n), key=lambda i: place[i])
    print(f"== {n_cycles} cycles, window [{lo},{hi}) ==")
    print(f"{'cyc':>5} {'valu':>4} {'alu':>4} {'ld':>3} {'st':>3} {'fl':>3}"
          f" | {'remain':>6} {'engLB':>5} {'cpLB':>5} {'bound':>6}  tail-tags")
    idx = 0
    for c in range(lo, hi):
        while idx < n and place[order[idx]] < c:
            idx += 1
        rem = [order[k] for k in range(idx, n)]
        cnt: Counter[str] = Counter()
        for i in rem:
            cnt[ops[i][0]] += 1
        eng_lb = max((-(-cnt[e] // SLOT_LIMITS[e]) for e in cnt), default=0)
        cp_lb = (max(height[i] for i in rem) + 1) if rem else 0
        tags = sorted({ops[i][10][0] for i in rem if ops[i][10] is not None})
        o = occ[c]
        bound = "cp" if cp_lb > eng_lb else ("eng" if eng_lb > cp_lb else "tie")
        print(f"{c:>5} {o['valu']:>4} {o['alu']:>4} {o['load']:>3} {o['store']:>3}"
              f" {o['flow']:>3} | {len(rem):>6} {eng_lb:>5} {cp_lb:>5} {bound:>6}"
              f"  rounds={tags[-3:] if tags else []}")

    # what the tail actually contains
    print("\n-- ops placed in the last 20 cycles, by (engine, opcode) --")
    tail: Counter[tuple[str, str]] = Counter()
    for i, c in enumerate(place):
        if c >= n_cycles - 20:
            tail[(ops[i][0], HD.opname(ops[i]))] += 1
    for k, v in tail.most_common(20):
        print(f"  {v:>4}  {k[0]:<6} {k[1]}")

    # final vstores: how many, and could they be earlier?
    vst = [i for i in range(n) if HD.opname(ops[i]) == "vstore"]
    print(f"\n-- {len(vst)} vstores; placed {min(place[i] for i in vst)}.."
          f"{max(place[i] for i in vst)} --")
    ready, bind = A.ready_and_bind(ops, preds, floors, place)
    late = sorted(vst, key=lambda i: -place[i])[:12]
    for i in late:
        j = bind[i]
        why = "floor" if j is None else (
            f"{A.edge_kind(ops, i, j)} {ops[j][0]}:{HD.opname(ops[j])}"
            f"@{place[j]} tag={ops[j][10]}")
        print(f"  vstore@{place[i]:>4} ready={ready[i]:>4} slack="
              f"{place[i]-ready[i]:>3}  <- {why}")


if __name__ == "__main__":
    main()
