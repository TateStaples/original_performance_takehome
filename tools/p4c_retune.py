"""P4-C: friction decomposition for G-23's L4 sweep.

G-23 rejected gather->select conversion partly because the l4_gmin count
sweep is monotone around (9,30): serving MORE L4 group-rounds measures
worse.  That sweep moved ONE dial while every other spelling / emission /
pool flag stayed at the value it was tuned to AT (9,30).  corsix's claim is
that selection and scheduling are one JOINT search, so the honest question
is: how much of the +2 / +6 / +8 is census cost and how much is friction
from un-retuned co-adapted flags?

This tool runs a coordinate-descent retune of the co-adapted flag set at a
given l4_gmin point and reports the retuned best.  Read-only w.r.t. dev.py.

Usage (repo root):
    python3 tools/p4c_retune.py --gmin "(8,30)" [--rounds 3]
    python3 tools/p4c_retune.py --gmin "(9,30)" --axes skew,pool
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

from run_variant import BASE_KWARGS, measure  # noqa: E402

AXES: dict[str, tuple[str, list]] = {
    "skew": ("skew", [(4, 3), (3, 3), (5, 3), (4, 4), (4, 2), (3, 4), (5, 4),
                      (2, 3), (6, 3), (5, 2), (3, 2), (6, 4)]),
    "pool": ("temp_and_cond_pool_sizes",
             [(16, 4), (15, 4), (17, 4), (16, 3), (16, 5), (14, 4), (18, 4),
              (15, 3), (17, 5)]),
    "arff": ("auto_raced_first_fold_levels",
             [(1, 2), (1,), (2,), (), (1, 3), (2, 3), (1, 2, 3), (3,)]),
    "ptff": ("pair_tournament_first_fold_race", [3, 0, 1, 2, 4, 5, 6, 7, 8]),
    "ptsf": ("pair_tournament_second_fold_race", [True, False]),
    "tie": ("tie_break", [("fold_flow",), (), ("fold_flow", "vec_valu"),
                          ("fold_flow", "idx_alu"), ("vec_valu",),
                          ("fold_flow", "vec_valu", "idx_alu")]),
    "rnpf": ("reverse_newest_parity_fold", [(15,), (), (14, 15), (15, 4),
                                            (4,), (3, 15)]),
    "idxrace": ("idx_recurrence_race", [True, False]),
    "idxsel": ("idx_select_before_madd", [True, False]),
    "bias": ("flow_race_bias", [0, 1, -1, 2, -2]),
    "vto": ("vec_tie_offload", [0, 1, 2, -1]),
    "vtp": ("vec_tie_phase", [0, 1, 2]),
    "nplfr": ("newest_parity_last_fold_race", [True, False]),
    "npldt": ("newest_parity_last_leaf_diff_tables", [True, False]),
    "c5p": ("c5_primed_gather_levels", [(5,), (), (5, 6), (6,)]),
    "spec": ("speculative_fold_levels", [(), (4,), (3,), (3, 4)]),
    "vfirst": ("vals_first", [False, True, "hash"]),
    "aoff": ("alu_offload", [True, False]),
}


def safe(kw: dict) -> tuple[int, bool]:
    try:
        c, ok = measure(kw, seed=1)
    except Exception:
        return (10 ** 6, False)
    return (c if ok else 10 ** 6, ok)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmin", required=True)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--axes", default=",".join(AXES))
    a = ap.parse_args()

    gmin = ast.literal_eval(a.gmin)
    axes = [x for x in a.axes.split(",") if x in AXES]

    cur = dict(BASE_KWARGS)
    cur["l4_gmin"] = gmin
    base, ok = safe(cur)
    print(f"l4_gmin={gmin}  as-shipped-flags = {base} (correct={ok})")
    if base >= 10 ** 6:
        print("  baseline invalid; aborting")
        return

    best = base
    evals = 1
    for it in range(a.rounds):
        improved = False
        for ax in axes:
            key, vals = AXES[ax]
            cbest, vbest = best, cur.get(key)
            for v in vals:
                if v == cur.get(key):
                    continue
                trial = dict(cur)
                trial[key] = v
                c, _ = safe(trial)
                evals += 1
                if c < cbest:
                    cbest, vbest = c, v
            if cbest < best:
                print(f"  iter{it} {key}: {cur.get(key)} -> {vbest}  "
                      f"{best} -> {cbest}")
                cur[key], best, improved = vbest, cbest, True
        if not improved:
            break
    delta = {k: v for k, v in cur.items() if BASE_KWARGS.get(k) != v}
    print(f"l4_gmin={gmin}  RETUNED = {best}  (was {base}, "
          f"friction {base - best})  evals={evals}")
    print(f"  plan delta: {delta}")


if __name__ == "__main__":
    main()
