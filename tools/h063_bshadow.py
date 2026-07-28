"""H-063 direction B: shadow-price sweep of the UNCONVERTED "X + b*K" sites.

tools/h063_bsites.py's census says the kernel's parity-consuming arithmetic
falls into two convertible families:

  (i)  `st +/- par` after a madd with an INVARIANT addend (the epoch-exit /
       boundary reconstruction) -- covered by `idx_boundary_select` (H-035),
       currently OFF.
  (ii) `evens + b*diffs` with BOTH operands invariant (the tournament folds
       and the level-4 W-combines) -- convertible to `vselect(b, odd, even)`
       by keeping an `odd = even + diff` broadcast alive.  Only levels
       `auto_raced_first_fold_levels` and the first
       `pair_tournament_first_fold_race` L4 pairs carry that arm today.

Family (ii)'s cost was always stated in SCRATCH terms (H-019: "funding more
than 3 pairs via a cond-pool trade is DEAD"), which G-33 says must be
re-checked with the limit removed.  This sweep does exactly that: every
probe is built with `dev.SCRATCH_SIZE` monkeypatched to 10^6, so the
reported delta is the mechanism's price with scratch FREE.

Usage (repo root):  python3 tools/h063_bshadow.py
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h059_oracle as O  # noqa: E402
import h061_common as C  # noqa: E402

PROBES: list[tuple[str, dict[str, Any]]] = [
    # --- family (ii): more first-fold races (needs an odd-value arm each) ---
    ("auto_fold levels (1,2,3)", {"auto_raced_first_fold_levels": (1, 2, 3)}),
    ("auto_fold levels (1,2,3,4)", {"auto_raced_first_fold_levels": (1, 2, 3, 4)}),
    ("auto_fold levels (1,)", {"auto_raced_first_fold_levels": (1,)}),
    ("auto_fold levels ()", {"auto_raced_first_fold_levels": ()}),
    ("l4 pairs 4", {"pair_tournament_first_fold_race": 4}),
    ("l4 pairs 6", {"pair_tournament_first_fold_race": 6}),
    ("l4 pairs 8 (all)", {"pair_tournament_first_fold_race": True}),
    ("l4 pairs 0", {"pair_tournament_first_fold_race": 0}),
    ("both maxed", {"auto_raced_first_fold_levels": (1, 2, 3),
                    "pair_tournament_first_fold_race": True}),
    ("both maxed + rev race", {"auto_raced_first_fold_levels": (1, 2, 3),
                               "pair_tournament_first_fold_race": True,
                               "shallow_tournament_reverse_select_race": True}),
    ("reverse_select_race", {"shallow_tournament_reverse_select_race": True}),
    # --- family (i): the boundary +/- par site ---
    ("idx_boundary_select", {"idx_boundary_select": True}),
    ("idx_boundary_select, no idx race",
     {"idx_boundary_select": True, "idx_recurrence_race": False}),
    # --- controls ---
    ("hard flow first-fold (1,2,3)", {"flow_first_fold_levels": (1, 2, 3)}),
]


def main() -> None:
    base = C.kwargs()
    nb, sc = O.build(base)
    print(json.dumps({"case": "base", "bundles": nb, "scratch": sc, "delta": 0}),
          flush=True)
    for name, ov in PROBES:
        try:
            n2, s2 = O.build(dict(base, **ov), scratch_limit=10 ** 6)
            print(json.dumps({"case": name, "bundles": n2, "scratch": s2,
                              "delta": n2 - nb,
                              "over_budget": max(0, s2 - 1536)}), flush=True)
        except Exception as exc:
            print(json.dumps({"case": name,
                              "error": f"{type(exc).__name__}: {exc}"[:140]}),
                  flush=True)


if __name__ == "__main__":
    main()
