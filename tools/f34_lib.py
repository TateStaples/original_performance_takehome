"""F-34/F-35 helpers: programmatic ring-plan mining + audit, in-process.

Wraps the SHARED tool `tools/audit_ring_windows.py` (never modified) by
driving its `main()` with a patched argv and capturing stdout.  Two
primitives:

  audit(order, mix)          -> (violations, n_rings, line)
  mine_fixpoint(order, mix)  -> (plan, violations, n_rings, line, iters)

`mine_fixpoint` always starts from `parity_ring_plan=()` (H-057 sec. 3.3:
mining seeded from a carried plan gives unsound assignments) and iterates
audit -> append newly-planned rings -> re-audit until the tool proposes no
new rings, then reports the closed-loop recheck of the accumulated plan.
"""
from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import sys
import tempfile
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import audit_ring_windows as arw  # noqa: E402

_RECHECK = re.compile(r"^\s+(OK|(\d+) violations) over (\d+) rings\s*$", re.M)


def tuplify(v: Any) -> Any:
    return tuple(tuplify(x) for x in v) if isinstance(v, list) else v


def _run_audit(sets: dict[str, Any], plan_out: str | None) -> str:
    argv = ["audit_ring_windows.py"]
    for k, v in sets.items():
        argv += ["--set", f"{k}={v!r}"]
    if plan_out:
        argv += ["--plan-out", plan_out]
    old = sys.argv
    buf = io.StringIO()
    try:
        sys.argv = argv
        with contextlib.redirect_stdout(buf):
            arw.main()
    finally:
        sys.argv = old
    return buf.getvalue()


def _recheck(text: str) -> tuple[int, int, str]:
    m = _RECHECK.search(text)
    if not m:
        raise RuntimeError("no recheck line in audit output:\n" + text[:2000])
    viol = 0 if m.group(1) == "OK" else int(m.group(2))
    return viol, int(m.group(3)), m.group(0).strip()


_LIVE = re.compile(r"LIVE-ACROSS\?\? \((\d+),(\d+)\)")


def audit(order: tuple, mix: dict[str, Any]) -> tuple[int, int, str]:
    """Closed-loop recheck of `mix['parity_ring_plan']` at `order`."""
    sets = dict(mix)
    sets["emission_plan"] = order
    return _recheck(_run_audit(sets, None))


def audit_detail(order: tuple, mix: dict[str, Any]) -> tuple[int, int, str, set]:
    """audit() plus the set of (epoch, group) ring keys that violate."""
    sets = dict(mix)
    sets["emission_plan"] = order
    text = _run_audit(sets, None)
    viol, n, line = _recheck(text)
    keys = {(int(a), int(b)) for a, b in _LIVE.findall(text)}
    return viol, n, line, keys


def mine_fixpoint(order: tuple, mix: dict[str, Any],
                  max_iters: int = 8) -> tuple[tuple, int, int, str, int]:
    """Mine a ring plan from EMPTY to an audit->add->re-audit fixpoint."""
    plan: tuple = ()
    fd, tmp = tempfile.mkstemp(suffix=".plan")
    os.close(fd)
    it = 0
    try:
        for it in range(1, max_iters + 1):
            sets = dict(mix)
            sets["emission_plan"] = order
            sets["parity_ring_plan"] = plan
            try:
                text = _run_audit(sets, tmp)
            except AssertionError:
                # dev.py rejects the accumulated plan (key collision) --
                # treat as a hard mining failure at this order/gmin.
                return plan, -1, len(plan), "ASSERT", it
            with open(tmp) as f:
                new = tuplify(ast.literal_eval(f.read()))
            if not new:
                break
            plan = tuple(sorted(plan + new))
    finally:
        os.unlink(tmp)
    viol, n, line = audit(order, dict(mix, parity_ring_plan=plan))
    return plan, viol, n, line, it


def load_json_point(path: str) -> tuple[tuple, dict[str, Any]]:
    import json
    with open(path) as f:
        d = json.load(f)
    plan = []
    for e in d["plan"]:
        plan.append(("rr", tuple(tuple(p) for p in e[1])) if e[0] == "rr" else tuple(e))
    return tuple(plan), {k: tuplify(v) for k, v in d["params"]["mix"].items()}
