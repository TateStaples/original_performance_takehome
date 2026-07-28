"""F-37: bound stack + regret at an arbitrary (order, mix) artifact.

`tools/backtrack_sched.py` and `tools/h055_chain.py` are pinned to the
H-047/1022 frontier config; this wrapper captures the op stream at a JSON
artifact's own `params.mix` + emission order instead and reprints the same
quantities.  Both shared tools are imported and called, never modified.

Usage (repo root):
  python3 tools/f37_bounds.py tools/h057_best_plan_1006.json
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import backtrack_sched as B  # noqa: E402
import f37_lib as F  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def energetic_lb(ops, preds, floors) -> int:
    est = B.ests(ops, preds, floors)
    h = B.tails(ops, preds)

    def feasible(C: int) -> bool:
        for e in SLOT_LIMITS:
            cap = SLOT_LIMITS[e]
            pts = [(est[i], C - 1 - h[i]) for i in range(len(ops))
                   if ops[i][0] == e]
            if not pts:
                continue
            if any(d < r for r, d in pts):
                return False
            for t1 in sorted({r for r, _ in pts}):
                dls = sorted(d for r, d in pts if r >= t1)
                for k, t2 in enumerate(dls, 1):
                    if k > (t2 - t1 + 1) * cap:
                        return False
        return True

    lo, hi = 960, 1040
    while not feasible(hi):
        hi += 8
    while lo < hi:
        mid = (lo + hi) // 2
        if feasible(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def main() -> None:
    path = sys.argv[1]
    order, mix = F.load_point(path)
    B.H51_OVERRIDES.clear()
    data = B.capture(overrides=dict(mix, emission_plan=order,
                                    debug_compares=False))
    ops = data["ops"]
    preds, floors = B.build_model(ops, data["pair_writes"])
    place, n = B.greedy_schedule(ops, preds, floors)
    print(f"realized(greedy) {n}   lb_total {B.lb_total(ops, preds, floors)}")
    print(f"energetic {energetic_lb(ops, preds, floors)}")
    print(f"fungible {B.fungible_lb(ops)}")
    p0 = [[(j, 0) for j, _ in p] for p in preds]
    print(f"all-lags-zero {B.greedy_schedule(ops, p0, [0] * len(ops))[1]}")
    cnt = Counter(op[0] for op in ops)
    print(f"ops {len(ops)}: " + " ".join(f"{e} {c}" for e, c in cnt.most_common()))
    print("cp " + str(max(B.ests(ops, preds, floors)[i] + B.tails(ops, preds)[i]
                          for i in range(len(ops))) + 1))

    # regret: idle slots per band on the engine that binds (max floor)
    floor = max(-(-cnt[e] // SLOT_LIMITS[e]) for e in cnt)
    print(f"slot floor {floor}  regret {n - floor}")
    bands = {"ramp": (0, 120), "mid": (120, n - 120), "drain": (n - 120, n + 1)}
    for name, (lo, hi) in bands.items():
        sub = [i for i in range(len(ops)) if lo <= place[i] < hi]
        c2 = Counter(ops[i][0] for i in sub)
        f2 = max(-(-c2[e] // SLOT_LIMITS[e]) for e in c2) if c2 else 0
        print(f"  {name:6s} cycles {min(hi, n) - lo:4d} ops {len(sub):6d} "
              f"band floor {f2:4d} slack {min(hi, n) - lo - f2}")


if __name__ == "__main__":
    main()
