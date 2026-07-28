"""P3-E: re-baseline the group-liveness (K) cycle curve, ring-free AND ringed.

G-33/H-059 recorded "W=32 1006 | W=24 1045 | W=16 1097".  The W=32 entry came
from the flag on the MAINLINE build (rings on); the W<32 entries came from
tools/h059_curve.py, which is deliberately RING-FREE (ring borrow windows are
order-specific).  G-37 records the ring-free base as 1026.  If that is right
the published curve mixes two bases and overstates the K penalty by ~20.

This tool measures every point on the SAME base.

Usage: python3 tools/p3e_kcurve.py [W ...]
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import h059_curve as H  # noqa: E402
from run_variant import measure  # noqa: E402


def main() -> None:
    ws = [int(x) for x in sys.argv[1:]] or [32, 24, 16, 11]
    for w in ws:
        for spec in ("f24",):
            plan = H.rolling_plan(w, spec)
            if not plan:
                print(json.dumps({"w": w, "spec": spec, "skip": True}), flush=True)
                continue
            peak, _ = H.live_profile(plan)
            ov = dict(H.NORING, emission_plan=plan)
            t0 = time.time()
            try:
                cyc, ok = measure(ov, seed=1)
                rec = {"w": w, "spec": spec, "ring": False, "cycles": cyc,
                       "correct": bool(ok), "peak_live": peak,
                       "reuse_ok": H.reuse_ok(plan, w)}
            except Exception as exc:
                rec = {"w": w, "spec": spec, "ring": False,
                       "error": f"{type(exc).__name__}: {exc}"[:200]}
            rec["secs"] = round(time.time() - t0, 1)
            print(json.dumps(rec), flush=True)


if __name__ == "__main__":
    main()
