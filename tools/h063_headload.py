"""H-063 direction A (replacement): can anything be MOVED INTO the head bubble?

Direction A as chartered ("bulk-vload the shallow-level tables") is already
implemented -- tools/h063_head.py shows the level-1..4 tree words arrive as
4 contiguous `vload`s at cycles 6..9 with one flow `add_imm` each, and
tools/h063_oracle.py shows the whole table-construction class is worth
EXACTLY 0 cycles when made free.  What remains of the charter's intent is
the other half: the head bubble (cycles ~29-64, 70 idle load slots) sits
BEHIND a load engine that is 2/2 saturated for cycles 0..30, and the
biggest occupant of that saturated stretch is the 44-op setup vload stream
(the per-group initial value vectors).  If some of those loads are DEFERRED
past cycle 30 they land in the bubble for free.

`lazy_val_loads` (H-024) and `vals_first` already express exactly that
placement choice, so this is a policy sweep, not new code.

Usage (repo root):  python3 tools/h063_headload.py
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
from run_variant import measure  # noqa: E402

PROBES: list[tuple[str, dict[str, Any]]] = [
    ("lazy_val_loads", {"lazy_val_loads": True}),
    ("vals_first", {"vals_first": True}),
    ("lazy + derive off", {"lazy_val_loads": True, "derive_consts": False}),
    ("lazy + alu_val_addrs off", {"lazy_val_loads": True, "alu_val_addrs": False}),
    ("alu_val_addrs off", {"alu_val_addrs": False}),
    ("derive_consts off", {"derive_consts": False}),
    ("flow_consts", {"flow_consts": True}),
]


def main() -> None:
    base = C.kwargs()
    nb, sc = O.build(base)
    print(json.dumps({"case": "base", "bundles": nb, "scratch": sc, "delta": 0}),
          flush=True)
    for name, ov in PROBES:
        try:
            kw = dict(base, **ov)
            n2, s2 = O.build(kw, scratch_limit=10 ** 6)
            rec: dict[str, Any] = {"case": name, "bundles": n2, "scratch": s2,
                                   "delta": n2 - nb}
            if n2 <= nb and s2 <= 1536:
                rec["measured"] = measure(kw, seed=1)
            print(json.dumps(rec), flush=True)
        except Exception as exc:
            print(json.dumps({"case": name,
                              "error": f"{type(exc).__name__}: {exc}"[:140]}),
                  flush=True)


if __name__ == "__main__":
    main()
