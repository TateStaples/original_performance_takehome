"""P4-C: the JOINT-selection extreme -- force every flow-eligible race onto
flow and measure, instead of letting the greedy retire race decide.

corsix's claim is that instruction selection and scheduling are ONE joint
search.  Our 1038 build lets a myopic earliest-retire race pick each
spelling, and 156 flow-eligible sites LOSE that race (p4c_flowsupply.py),
leaving flow at 0.77/1 while compute (the binder) is full in 90% of cycles.
This measures the opposite extreme and some middles, so the friction
between "greedy spelling" and "best spelling" is a number, not an opinion.

Usage (repo root):  python3 tools/p4c_forceflow.py [--rounds 4,13,15,2,1]
"""
from __future__ import annotations

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import spelling_plan_search as sps  # noqa: E402
from run_variant import BASE_KWARGS, measure  # noqa: E402
from problem import SLOT_LIMITS  # noqa: E402

ENG = ["alu", "valu", "load", "store", "flow"]


def census(kb):
    n = len(kb.instrs)
    tot = {e: sum(len(b.get(e, ())) for b in kb.instrs) for e in ENG}
    lane = tot["alu"] + 8 * tot["valu"]
    return dict(cycles=n, lane=lane, f_cmp=lane / 60, f_valu=tot["valu"] / 6,
                f_alu=tot["alu"] / 12, f_load=tot["load"] / 2, **tot)


def show(tag, c, plan_size, graded=None):
    print(f"{tag:<28} cyc {c['cycles']:5d}  lane {c['lane']:6d}  "
          f"f_cmp {c['f_cmp']:7.1f}  f_valu {c['f_valu']:7.1f}  "
          f"f_alu {c['f_alu']:6.1f}  f_load {c['f_load']:6.1f}  "
          f"flow {c['flow']:4d}  |plan| {plan_size:4d}"
          + (f"  graded {graded}" if graded is not None else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", default="")
    a = ap.parse_args()
    kw = dict(BASE_KWARGS)

    kb = sps.build(kw, {}, logging=True, trace=False)
    log = list(sps.RACE_LOG)
    base = census(kb)
    show("greedy (mainline)", base, 0, measure({}, seed=1))

    lost = [r for r in log if r["flow_idx"] is not None
            and r["chosen"] != r["flow_idx"]]
    full = {r["site"]: r["flow_idx"] for r in lost}
    kb2 = sps.build(kw, full)
    c2 = census(kb2)
    g2 = measure({"flow_spelling_plan": tuple(sorted(full.items()))}, seed=1)
    show("force ALL 156 -> flow", c2, len(full), g2)

    # by emission round
    byr: dict = {}
    for r in lost:
        t = r["tag"][0] if isinstance(r["tag"], tuple) else "setup"
        byr.setdefault(t, {})[r["site"]] = r["flow_idx"]
    for t in sorted(byr, key=str):
        p = byr[t]
        kbi = sps.build(kw, p)
        gi = measure({"flow_spelling_plan": tuple(sorted(p.items()))}, seed=1)
        show(f"force round {t} ({len(p)})", census(kbi), len(p), gi)

    # prefix sizes of the full plan, cheapest-first by site order
    keys = sorted(full)
    for frac in (0.25, 0.5, 0.75):
        k = int(len(keys) * frac)
        p = {s: full[s] for s in keys[:k]}
        gi = measure({"flow_spelling_plan": tuple(sorted(p.items()))}, seed=1)
        show(f"force first {k}", census(sps.build(kw, p)), k, gi)


if __name__ == "__main__":
    main()
