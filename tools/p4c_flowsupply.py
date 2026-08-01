"""P4-C: is our flow under-use (0.77/1) a SCHEDULING fact or a SUPPLY fact?

G-23 leg 1 says we already run corsix's 7.5:2:1.  Measured per cycle we run
7.5:2:0.768 and hit the exact triple in only 64% of cycles (p4c_ratio.py).
The 241 idle flow slots are only convertible if the program CONTAINS 241
more flow-eligible ops.  This counts the flow-eligible race sites in the
emitted stream (reusing spelling_plan_search's emit_any instrumentation)
and reports the supply ceiling on flow slots.

Usage (repo root):  python3 tools/p4c_flowsupply.py
"""
from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import spelling_plan_search as sps  # noqa: E402  (patches emit_any)
from run_variant import BASE_KWARGS  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402


def main() -> None:
    kw = dict(BASE_KWARGS)
    kb, cycles = None, None
    out = sps.build(kw, {}, logging=True, trace=False)
    if isinstance(out, tuple):
        kb = out[0]
        cycles = out[1] if len(out) > 1 else None
    else:
        kb = out
    log = list(sps.RACE_LOG)
    instrs = kb.instrs if hasattr(kb, "instrs") else None
    n = len(instrs) if instrs is not None else cycles
    flow_slots = sum(len(b.get("flow", ())) for b in instrs)
    print(f"cycles {n}   flow slots used {flow_slots}  "
          f"(util {flow_slots/n*100:.1f}%)   idle flow slots {n - flow_slots}")

    flow_sites = [r for r in log if r["flow_idx"] is not None]
    won = [r for r in flow_sites if r["chosen"] == r["flow_idx"]]
    lost = [r for r in flow_sites if r["chosen"] != r["flow_idx"]]
    print(f"\nemit_any race sites total        : {len(log)}")
    print(f"  with a pure-flow encoding      : {len(flow_sites)}")
    print(f"    flow WON the retire race     : {len(won)}")
    print(f"    flow LOST                    : {len(lost)}")
    print(f"\nflow slots from non-race (forced-flow) emissions: "
          f"{flow_slots - len(won)}")
    print(f"SUPPLY CEILING on flow slots = forced + every flow site = "
          f"{flow_slots - len(won) + len(flow_sites)}")
    print(f"  vs cycles {n}: "
          f"{'flow CAN be saturated' if flow_slots - len(won) + len(flow_sites) >= n else 'flow CANNOT be saturated -- SUPPLY-limited'}")
    print(f"  headroom over today's {flow_slots}: "
          f"{len(lost)} slots")

    c = Counter(r["tag"][0] if isinstance(r["tag"], tuple) else "setup"
                for r in lost)
    print("\nflow-LOST sites by emission round tag (where the unspent "
          "flow supply lives):")
    for k, v in sorted(c.items(), key=lambda t: str(t[0])):
        print(f"  round {k!s:>11s}: {v}")
    cs = Counter(r["shapes"] for r in lost)
    print("\nshapes of the flow-LOST races (top 8):")
    for k, v in cs.most_common(8):
        print(f"  {v:5d}  {k}")


if __name__ == "__main__":
    main()
