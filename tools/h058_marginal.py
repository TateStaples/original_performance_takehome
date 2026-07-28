"""H-058: MEASURED marginal exchange rate of serving vs gathering.

The whole 940 arithmetic turns on three slopes:
    d(alu+valu vec-ops) / d(served level-4 group-round)
    d(load slots)       / d(served level-4 group-round)
    d(flow slots)       / d(served level-4 group-round)
Modelling them from the ISA (15 selects vs 8 loads + 1 combine) is a guess;
`l4_gmin` moves exactly this variable, so the slopes can be MEASURED.

For each l4_gmin the tool builds the dev kernel at the 1006 artifact's mix
and emission order and reports the full engine census plus the realized
cycle count.  Nothing shared is modified; `run_variant.measure`-style build
path is reused via dev.KernelBuilder directly.

Usage (repo root):
    python3 tools/h058_marginal.py tools/h057_best_plan_1006.json
"""
from __future__ import annotations

import json
import os
import random
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))
sys.path.insert(0, os.path.join(REPO_ROOT, "tests"))

import dev  # noqa: E402
import f37_lib as F  # noqa: E402
from run_variant import BASE_KWARGS, SHAPE  # noqa: E402
from problem import VLEN  # noqa: E402

ENGINES = ("alu", "valu", "load", "store", "flow")


def build(ov: dict) -> dict | None:
    from frozen_problem import Tree, Input, build_mem_image
    random.seed(0)
    forest = Tree.generate(SHAPE["forest_height"])
    problem_input = Input.generate(forest, SHAPE["batch_size"], SHAPE["rounds"])
    build_mem_image(forest, problem_input)
    kb = dev.KernelBuilder()
    try:
        kb.build_kernel_scheduled(SHAPE["batch_size"], SHAPE["rounds"],
                                  SHAPE["forest_height"],
                                  **dict(BASE_KWARGS, **ov))
    except (AssertionError, IndexError, KeyError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    slots = {e: 0 for e in ENGINES}
    madd = vsel = gather = 0
    for bundle in kb.instrs:
        for e, ss in bundle.items():
            if e == "debug":
                continue
            slots[e] += len(ss)
            for s in ss:
                if e == "valu" and s[0] == "multiply_add":
                    madd += 1
                if e == "flow" and s[0] == "vselect":
                    vsel += 1
                if e == "load" and s[0] == "load":
                    gather += 1
    lanes = slots["alu"] + VLEN * slots["valu"]
    return dict(cycles=len(kb.instrs), vecops=lanes / VLEN, lanes=lanes,
                madd=madd, vsel=vsel, gather_loads=gather,
                scratch=kb.scratch_next_addr, **slots)


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else \
        os.path.join(REPO_ROOT, "tools", "h057_best_plan_1006.json")
    order, mix = F.load_point(path)
    mix = dict(mix)
    if "--no-ring" in sys.argv:
        # the shipped parity_ring_plan is mined AT l4_gmin=(6,31) and asserts
        # if the serving set moves, so slope measurement must drop it.
        mix.pop("parity_ring_plan", None)
        mix["parity_ring"] = False
    base = dict(mix, emission_plan=order, debug_compares=False)

    print(f"{'l4_gmin':>10}{'s4':>4}{'cyc':>6}{'vecops':>9}{'alu':>7}"
          f"{'valu':>6}{'load':>6}{'flow':>6}{'vsel':>6}{'madd':>6}{'scr':>6}"
          f"{'cmpFl':>7}{'ldFl':>6}{'binder':>8}{'regret':>7}")
    rows = []
    for e0 in (0, 2, 4, 6, 8, 12, 16, 20, 24, 28, 32):
        for e1 in (16, 31):
            gm = (e0, e1)
            r = build(dict(base, l4_gmin=gm))
            s4 = (32 - e0) + (32 - e1)
            if r is None or "error" in r:
                print(f"{str(gm):>10}{s4:>4}   {r['error'][:60] if r else 'None'}")
                continue
            rows.append((s4, r))
            cf, lf, ff = r["vecops"] / 7.5, r["load"] / 2, float(r["flow"])
            binder = max((cf, "compute"), (lf, "load"), (ff, "flow"))
            print(f"{str(gm):>10}{s4:>4}{r['cycles']:>6}{r['vecops']:>9.1f}"
                  f"{r['alu']:>7}{r['valu']:>6}{r['load']:>6}{r['flow']:>6}"
                  f"{r['vsel']:>6}{r['madd']:>6}{r['scratch']:>6}"
                  f"{cf:>7.0f}{lf:>6.0f}{binder[1]:>8}"
                  f"{r['cycles'] - binder[0]:>7.0f}")

    if len(rows) >= 2:
        rows.sort()
        (s_lo, r_lo), (s_hi, r_hi) = rows[0], rows[-1]
        ds = s_hi - s_lo
        print(f"\nMEASURED SLOPES over s4 {s_lo} -> {s_hi} (per served "
              f"level-4 group-round):")
        for k in ("vecops", "load", "flow", "vsel", "madd", "alu", "valu",
                  "scratch", "cycles"):
            print(f"  d({k})/d(s4) = "
                  f"{(r_hi[k] - r_lo[k]) / ds:+8.2f}")
        print("\nREGRET BY BINDING ENGINE (the schedulability finding): a")
        print("compute-bound point carries ~20 cycles of regret over its own")
        print("floor; a LOAD-bound point carries ~70.  Any design that plans")
        print("to run the load engine at 100% must budget the larger number.")
        print(json.dumps({"note": "gather_loads/8 = gathered group-rounds",
                          "lo": {"s4": s_lo, "gathered": r_lo["gather_loads"] // 8},
                          "hi": {"s4": s_hi, "gathered": r_hi["gather_loads"] // 8}}))


if __name__ == "__main__":
    main()
