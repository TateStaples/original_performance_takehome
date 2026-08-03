"""P7-GMIN: derive a parity-ring plan for an ARBITRARY `l4_gmin`, with or
without the with-idx tail, and measure the result end to end.

Why this exists.  The ring plan shipped in `h059_curve.MIX` was mined at
`l4_gmin=(6,31)`; `h061_common.kwargs()` refuses to combine a different gmin
with rings for exactly that reason (borrow windows are liveness-timed, and
gmin decides which groups are L4-SERVED and therefore which registers are
dead when).  So any gmin screen run ring-free is only half the question: the
other half is what a ring plan mined AT that gmin is worth.  This tool
answers it by reusing `tools/p7tar_remine.py`'s derivation verbatim --
drop-and-rebuild liveness fixpoint, then greedy donor mining off the realized
trace, iterated until coverage stops growing -- with the build step
re-parameterised over (gmin, tail).

`p7tar_remine` is imported, never modified: its `fixpoint`/`derive`/`mine`
resolve `build` from their own module globals, so this module installs its
own `build` there for the duration of a run.  That keeps the search logic
bit-identical to the reviewed P7-TAR one and confines the delta to kwargs.

The liveness audit is a NECESSARY condition, not a sufficient one; every
number this tool reports as good must still pass `--verify`, which replays
the saved plan with `ring_liveness_assert` at its auto-ON default and checks
values (and, under `--tail on`, the final indices) against `reference_kernel2`
on N seeds.

Usage (repo root):
  python3 tools/p7g_remine.py --gmin 9,30 --tail off --out tools/p7g_9_30.json
  python3 tools/p7g_remine.py --verify tools/p7g_9_30.json --seeds 10
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import h061_common as C  # noqa: E402
import p7tar_remine as T  # noqa: E402
from dev import KernelBuilder  # noqa: E402

SHAPE = T.SHAPE                       # (batch, rounds, height) = (256, 16, 10)
RUN_SHAPE = {"batch_size": 256, "rounds": 16, "forest_height": 10}


def load_order(path: str | None):
    """An emission order from either artifact format: `emission_order_search`'s
    `*.best.json` (a bare {"plan": [...]}) or an f37/h057 point with a
    `params.mix` block.  None = the shipped h057 1006 order."""
    if not path:
        return None
    d = json.load(open(path))
    if "plan" in d:
        return tuple(("rr", tuple(tuple(p) for p in e[1])) if e[0] == "rr"
                     else tuple(e) for e in d["plan"])
    import f37_lib as F  # noqa: PLC0415
    return F.load_point(path)[0]


def config(gmin: tuple[int, int], tail: bool, drop=(), plan=(), order=None,
           **extra: Any) -> dict[str, Any]:
    """h061's shipped stream (BASE + h059 MIX + the h057 1006 emission order)
    with l4_gmin overridden and the ring plan replaced wholesale.

    C.kwargs() deliberately raises when asked for a non-shipped gmin WITH
    rings; the guard is about carrying the SHIPPED plan across a gmin change,
    which is exactly what this function does not do -- the plan is always one
    derived at this gmin (empty on the first build).

    `order` swaps the emission plan too (the h057 order was mined at (6,31)
    and is itself gmin-specific), for the full order-then-ring cascade."""
    kw = C.kwargs()                                   # rings ON, gmin (6,31)
    kw["l4_gmin"] = tuple(gmin)
    kw["parity_ring_plan"] = tuple(plan)
    kw["parity_ring_drop"] = tuple(sorted(drop))
    if order is not None:
        kw["emission_plan"] = order
    if tail:
        kw["store_final_indices"] = True
        kw["b3l_safe_leaf_fallback"] = True
    kw.update(extra)
    return kw


def install_build(gmin: tuple[int, int], tail: bool, order=None) -> None:
    """Point p7tar_remine's derivation at this (gmin, tail, order) build."""

    def build(drop, plan) -> KernelBuilder:
        kb = KernelBuilder()
        kb.sched_trace = []
        # the derivation calls the audit itself; auto-ON would abort the
        # intermediate (still dirty) builds it needs to inspect.
        kb.build_kernel_scheduled(*SHAPE, **config(
            gmin, tail, drop, plan, order, ring_liveness_assert=False))
        return kb

    T.build = build


def run_once(kw: dict[str, Any], seed: int | None, tail: bool):
    """Build + run on the frozen grader.  Returns (cycles, values_ok, idx_ok).

    idx_ok is None unless `tail`; it compares the 256 final indices the tail
    stores (mem[inp_values_p - batch : inp_values_p]) against reference."""
    from frozen_problem import (  # noqa: PLC0415
        Machine, N_CORES, Tree, Input, build_mem_image, reference_kernel2,
    )
    if seed is not None:
        random.seed(seed)
    forest = Tree.generate(RUN_SHAPE["forest_height"])
    problem_input = Input.generate(forest, RUN_SHAPE["batch_size"], RUN_SHAPE["rounds"])
    mem = build_mem_image(forest, problem_input)

    kb = KernelBuilder()
    kb.build_kernel_scheduled(RUN_SHAPE["batch_size"], RUN_SHAPE["rounds"],
                              RUN_SHAPE["forest_height"], **kw)
    machine = Machine(mem, kb.instrs, kb.debug_info(), n_cores=N_CORES)
    machine.enable_pause = False
    machine.enable_debug = False
    machine.run()

    for ref_mem in reference_kernel2(mem):
        pass
    ivp = ref_mem[6]
    n = len(problem_input.values)
    values_ok = machine.mem[ivp:ivp + n] == ref_mem[ivp:ivp + n]
    idx_ok = None
    if tail:
        iip = ivp - RUN_SHAPE["batch_size"]
        idx_ok = machine.mem[iip:ivp] == ref_mem[iip:ivp]
    return machine.cycle, values_ok, idx_ok


def derive(gmin: tuple[int, int], tail: bool, rounds_limit: int = 6, order=None):
    install_build(gmin, tail, order)
    return T.derive(rounds_limit=rounds_limit)


def save(path: str, gmin, tail, plan, drop, cycles, rings, order_path=None) -> None:
    json.dump({"gmin": list(gmin), "tail": bool(tail),
               "cycles": cycles, "rings": rings, "order": order_path,
               "drop": sorted(tuple(x) for x in drop),
               "plan": [[list(k), list(v)] for k, v in sorted(plan.items())]},
              open(path, "w"))


def verify(path: str, seeds: int) -> int:
    d = json.load(open(path))
    gmin = tuple(d["gmin"])
    tail = bool(d["tail"])
    drop = tuple(tuple(x) for x in d["drop"])
    plan = tuple((tuple(k), tuple(v)) for k, v in d["plan"])
    # ring_liveness_assert left at its auto-ON default (on iff rings+tail).
    kw = config(gmin, tail, drop, plan, load_order(d.get("order")))
    bad = 0
    for seed in range(1, seeds + 1):
        cyc, vok, iok = run_once(kw, seed, tail)
        bad += (not vok) or (tail and not iok)
        print(f"  seed={seed:<3} cycles={cyc} values={vok} indices={iok}", flush=True)
    print(f"verify {path}: gmin={gmin} tail={tail} rings={len(plan)}+native "
          f"{'PASS' if not bad else f'FAIL ({bad}/{seeds})'}")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gmin", default=None, help="e.g. 9,30")
    ap.add_argument("--tail", choices=("on", "off"), default="off")
    ap.add_argument("--rounds", type=int, default=6, help="mine/fixpoint iterations")
    ap.add_argument("--out", default=None)
    ap.add_argument("--verify", default=None)
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--order", default=None,
                    help="emission-order artifact (default: the shipped h057 order)")
    args = ap.parse_args()

    if args.verify:
        raise SystemExit(verify(args.verify, args.seeds))
    if not args.gmin:
        raise SystemExit("--gmin or --verify required")

    gmin = tuple(int(x) for x in args.gmin.split(","))
    tail = args.tail == "on"
    order = load_order(args.order)
    cy, nr, plan, drop = derive(gmin, tail, args.rounds, order)
    kw = config(gmin, tail, drop, tuple(sorted(plan.items())), order)
    cycles, vok, iok = run_once(kw, 1, tail)
    print(f"BEST gmin={gmin} tail={args.tail} rings={nr} bundles={cy} "
          f"cycles={cycles} values={vok} indices={iok} drop={sorted(drop)}")
    # NOT tools/: a bare plan file there invites a stale-plan accident (P7 (c)
    # open issue 4).  These plans are gmin- AND order-specific evidence.
    out = args.out or os.path.join(
        REPO_ROOT, "research", "strains", "p7",
        f"p7g_plan_{gmin[0]}_{gmin[1]}_{args.tail}.json")
    save(out, gmin, tail, plan, drop, cycles, nr, args.order)
    print(f"written to {out}")


if __name__ == "__main__":
    main()
