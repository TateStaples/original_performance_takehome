"""H-060 step 4: discharge G-33's reopen-if clause.

G-33 (H-059) closed the scratch/parallelism trade with:
  "reopen-if: the alu/valu assignment stops depending on live-group count
   (i.e. H-060's static partition works)."

The mechanism it recorded is that as the live-group window W shrinks, fewer
independent ops exist at each `_sched_vec` decision, the alu offload wins
fewer races, and the VALU floor RISES (1008 -> 1010 -> 1018 at W = 32/24/16)
while the alu floor falls (993 -> 962 -> 933).

This tool re-runs that curve with the H-060 planned partition turned on
(`vec_tie_offload` forces the alu spelling to be PRICED at valu-free sites
too, which is exactly the decision the race skips when ILP is thin), and
reports whether the split, the floors, and the cycles decouple from W.

Usage: python3 tools/h060_liveness.py [--ws 32,24,16] [--workers N]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h059_curve as H  # noqa: E402
import h060_common as C  # noqa: E402
from run_variant import BASE_KWARGS  # noqa: E402


def point(w: int, extra: dict[str, Any]) -> dict[str, Any]:
    # Exactly H-059's own curve points (tools/h059_alias.py): ring-free 1006
    # mix + lazy_val_loads, the per-W searched lag vectors, group_window
    # aliasing on below 32.
    import h059_alias as A
    lags = sorted(A.BEST_LAGS[w])
    plan = H.rolling_plan_lags(w, lags, "zip")
    ov: dict[str, Any] = dict(A.base_mix(), emission_plan=plan)
    if w < H.N_GROUPS:
        ov["group_window"] = w
    ov.update(extra)
    try:
        _, prog = C.build(ov)
    except Exception as exc:
        return {"w": w, "error": f"{type(exc).__name__}: {exc}"[:110]}
    cen = C.slot_census(prog)
    fl = C.floors(prog)
    return {"w": w, "cycles": len(prog), "alu": cen.get("alu", 0),
            "valu": cen.get("valu", 0), "alu_floor": fl["alu"],
            "valu_floor": fl["valu"],
            "bind": max(fl["alu"], fl["valu"], fl["load"], fl["flow"])}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ws", default="32,24,16,12,8")
    args = ap.parse_args()
    ws = [int(x) for x in args.ws.split(",")]

    policies: list[tuple[str, dict[str, Any]]] = [
        ("race (baseline)", {}),
        ("tie_offload K=64", {"vec_tie_offload": 64}),
        ("tie_offload K=16", {"vec_tie_offload": 16}),
        ("tie_offload K=4", {"vec_tie_offload": 4}),
        ("tie_offload K=1", {"vec_tie_offload": 1}),
    ]
    print(f"{'policy':<20}{'W':>4}{'cyc':>7}{'valu':>7}{'alu':>7}"
          f"{'vfl':>6}{'afl':>6}{'bind':>6}")
    rows = []
    for name, ov in policies:
        for w in ws:
            r = point(w, ov)
            r["policy"] = name
            rows.append(r)
            if "error" in r:
                print(f"{name:<20}{w:>4}  ERROR {r['error']}")
                continue
            print(f"{name:<20}{w:>4}{r['cycles']:>7}{r['valu']:>7}"
                  f"{r['alu']:>7}{r['valu_floor']:>6}{r['alu_floor']:>6}"
                  f"{r['bind']:>6}", flush=True)
    out = os.environ.get("H060_OUT", "/tmp")
    with open(os.path.join(out, "h060_liveness.json"), "w") as f:
        json.dump(rows, f, indent=1)


if __name__ == "__main__":
    main()
