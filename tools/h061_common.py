"""H-061 shared harness: the 1006 mainline stream and its load-bound family.

Everything here is a read-only wrapper over existing tools (run_variant,
h059_curve's MIX, f37_lib's plan loader).  The one lever this hypothesis
cares about is `l4_gmin`: serving FEWER level-4 group-rounds converts
tournament/select compute into level-4 GATHERS, i.e. pushes the binding
engine from valu towards load.

Usage:
  python3 tools/h061_common.py base                 # measure the 1006 stream
  python3 tools/h061_common.py family [gmins...]    # gmin sweep, realized+floors
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h059_curve as H  # noqa: E402
import f37_lib as F  # noqa: E402
from run_variant import BASE_KWARGS, measure  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

PLAN_1006 = os.path.join(REPO_ROOT, "tools", "h057_best_plan_1006.json")
SHAPE = (256, 16, 10)

# Ring plans are ORDER-SPECIFIC *and* config-specific: the 1006 plan's
# borrow windows were mined at l4_gmin=(6,31).  Changing gmin changes which
# groups are served at L4 and therefore which registers are dead when, so
# carrying the ring plan across a gmin change is UNSOUND.  Every gmin probe
# in this module therefore runs RING-FREE (same rule H-059 adopted), and the
# gmin=(6,31) point is measured both ways so the ring's worth is visible.
ORDER_1006, _ = F.load_point(PLAN_1006)
MIX = dict(H.MIX)
NORING = {k: v for k, v in MIX.items() if k not in ("parity_ring", "parity_ring_plan")}


def kwargs(gmin: tuple[int, int] | None = None, rings: bool = True,
           **extra: Any) -> dict[str, Any]:
    mix = dict(MIX if rings else NORING)
    if gmin is not None:
        mix["l4_gmin"] = tuple(gmin)
        if rings:
            raise SystemExit("ring plan is gmin-specific; use rings=False")
    kw = dict(BASE_KWARGS, **mix)
    kw["emission_plan"] = ORDER_1006
    kw["debug_compares"] = False
    kw.update(extra)
    return kw


def build(kw: dict[str, Any]):
    from dev import KernelBuilder
    kb = KernelBuilder()
    kb.build_kernel_scheduled(*SHAPE, **kw)
    return kb


def slot_counts(kb) -> Counter:
    c: Counter[str] = Counter()
    for bundle in kb.instrs:
        for engine, ops in bundle.items():
            if engine == "debug":
                continue
            c[engine] += len(ops) if isinstance(ops, list) else 1
    return c


def floors(kb) -> dict[str, int]:
    c = slot_counts(kb)
    return {e: -(-n // SLOT_LIMITS[e]) for e, n in sorted(c.items())}


def report(label: str, kw: dict[str, Any], run: bool = True) -> dict[str, Any]:
    t = time.time()
    kb = build(kw)
    cyc = len(kb.instrs)
    c = slot_counts(kb)
    f = floors(kb)
    out: dict[str, Any] = {
        "label": label, "bundles": cyc,
        "slots": dict(c), "floors": f,
        "floor": max(f.values()), "binder": max(f, key=lambda e: f[e]),
    }
    out["regret_vs_own_floor"] = cyc - out["floor"]
    if run:
        cycles, ok = measure(kw, seed=1)
        out["cycles"], out["correct"] = cycles, ok
    out["build_s"] = round(time.time() - t, 1)
    return out


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "base"
    if cmd == "base":
        print(json.dumps(report("1006-mainline", kwargs())))
        print(json.dumps(report("1006-noring", kwargs(rings=False))))
    elif cmd == "family":
        args = sys.argv[2:] or ["6,31", "9,31", "12,31", "16,31", "20,31",
                                "24,31", "28,31", "32,32"]
        for a in args:
            e0, e1 = (int(x) for x in a.split(","))
            print(json.dumps(report(f"gmin={e0},{e1}",
                                    kwargs((e0, e1), rings=False))), flush=True)
    else:
        raise SystemExit(f"unknown cmd {cmd}")


if __name__ == "__main__":
    main()
