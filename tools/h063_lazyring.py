"""H-063: lazy_val_loads measured RING-FREE (the ring plan is config-specific).

`parity_ring_plan`'s borrow windows are liveness-timed against the 1006
stream, so any flag that moves the per-group value vloads invalidates them
(the build asserts).  F-25 / H-059's standing rule: probe such changes
ring-free, against the ring-free baseline, and only re-mine rings on a
point that is taken forward.

Usage (repo root):  python3 tools/h063_lazyring.py
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
    ("noring base", {}),
    ("noring + lazy_val_loads", {"lazy_val_loads": True}),
    ("noring + vals_first", {"vals_first": True}),
    # lazy_val_loads needs alu_val_addrs off: the alu +32 chain reads
    # val_addrs[g-4], which only exists when groups are emitted 0..31.
    ("noring + lazy + no alu_val_addrs",
     {"lazy_val_loads": True, "alu_val_addrs": False}),
    ("noring + no alu_val_addrs (control)", {"alu_val_addrs": False}),
    ("noring + lazy + no alu_val_addrs, no dead-reg staging",
     {"lazy_val_loads": True, "alu_val_addrs": False,
      "mem_prime_dead_reg_staging": False}),
]


def main() -> None:
    ref = C.kwargs()
    nb0, _ = O.build(ref)
    print(json.dumps({"case": "ringed mainline", "bundles": nb0}), flush=True)
    base = C.kwargs(rings=False)
    nb, sc = O.build(base)
    print(json.dumps({"case": "noring base", "bundles": nb, "scratch": sc,
                      "delta_vs_ringed": nb - nb0}), flush=True)
    for name, ov in PROBES[1:]:
        try:
            kw = dict(base, **ov)
            n2, s2 = O.build(kw, scratch_limit=10 ** 6)
            rec: dict[str, Any] = {"case": name, "bundles": n2, "scratch": s2,
                                   "delta_vs_noring": n2 - nb}
            if s2 <= 1536:
                rec["measured"] = measure(kw, seed=1)
            print(json.dumps(rec), flush=True)
        except Exception as exc:
            print(json.dumps({"case": name,
                              "error": f"{type(exc).__name__}: {exc}"[:140]}),
                  flush=True)


if __name__ == "__main__":
    main()
