"""H-060 step 1: instrument `_sched_vec`'s alu/valu retire race.

For every offloadable vector site (op in dev._SCALARIZABLE, allow_alu on,
force_alu off) we record BOTH candidate retire times -- the 1-slot valu
spelling and the 8-slot scalar alu spelling -- and which one the greedy
race actually took, plus the margin.  The tool monkeypatches
`dev.KernelBuilder._sched_vec` with a logging copy that makes exactly the
same placements (verified: identical cycle count + identical instruction
stream vs the unpatched build).

Usage: python3 tools/h060_race.py [--json OUT]
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"),
          os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h060_common as C  # noqa: E402
import dev  # noqa: E402


def trial_retire(sched: Any, encoding: Any) -> int:
    """Replica of emit_any's per-encoding trial placement (no side effects)."""
    trial_occ: dict[str, dict[int, int]] = {}
    tlw: dict[int, int] = {}
    tlr: dict[int, int] = {}
    retire = -1
    for engine, _slot, reads, writes in encoding:
        cycle = sched.ready(reads, writes)
        for addr in reads:
            t = tlw.get(addr, -1) + 1
            if t > cycle:
                cycle = t
        for addr in writes:
            t = tlw.get(addr, -1) + 1
            if t > cycle:
                cycle = t
            t = tlr.get(addr, -1)
            if t > cycle:
                cycle = t
        cycle = sched.find_free(engine, cycle, trial_occ.setdefault(engine, {}))
        trial_occ[engine][cycle] = trial_occ[engine].get(cycle, 0) + 1
        if cycle > retire:
            retire = cycle
        for addr in reads:
            if tlr.get(addr, -1) < cycle:
                tlr[addr] = cycle
        for addr in writes:
            tlw[addr] = cycle
    return retire


LOG: list[tuple[Any, ...]] = []


def logging_sched_vec(self, scheduler, op, dest, a, b,
                      allow_alu=False, force_alu=False, valu_ties=False,
                      partition=None):
    assert partition is None, "instrumentation covers the raced path only"
    reads = self._v(a) + self._v(b)
    writes = self._v(dest)
    if op in dev._SCALARIZABLE and (force_alu or allow_alu):
        alu_enc = tuple(
            ("alu", (op, dest + i, a + i, b + i), (a + i, b + i), (dest + i,))
            for i in range(dev.VLEN)
        )
        site = len(LOG)
        if force_alu:
            LOG.append((site, op, "forced", None, None, "alu", None))
            return scheduler.emit_any((alu_enc,))
        hazard_ready_cycle = scheduler.ready(reads, writes)
        valu_free_cycle = scheduler.find_free("valu", hazard_ready_cycle)
        valu_enc = (("valu", (op, dest, a, b), reads, writes),)
        r_alu = trial_retire(scheduler, alu_enc)
        r_valu = trial_retire(scheduler, valu_enc)
        if valu_free_cycle > hazard_ready_cycle:
            encs = (alu_enc, valu_enc)
            winner = ("valu" if (r_valu < r_alu if not valu_ties
                                 else r_valu <= r_alu) else "alu")
            LOG.append((site, op, "race", r_alu, r_valu, winner,
                        hazard_ready_cycle))
            return scheduler.emit_any(encs[::-1] if valu_ties else encs)
        LOG.append((site, op, "valu_free", r_alu, r_valu, "valu",
                    hazard_ready_cycle))
        scheduler.put("valu", (op, dest, a, b), valu_free_cycle, reads, writes)
        return valu_free_cycle
    valu_free_cycle = scheduler.find_free("valu", scheduler.ready(reads, writes))
    scheduler.put("valu", (op, dest, a, b), valu_free_cycle, reads, writes)
    return valu_free_cycle


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    cfg = C.frontier()
    _, ref_prog = C.build(cfg)

    orig = dev.KernelBuilder._sched_vec
    dev.KernelBuilder._sched_vec = logging_sched_vec  # type: ignore[assignment]
    try:
        _, prog = C.build(cfg)
    finally:
        dev.KernelBuilder._sched_vec = orig  # type: ignore[assignment]

    assert len(prog) == len(ref_prog), (len(prog), len(ref_prog))
    assert prog == ref_prog, "instrumented build diverged"
    print(f"instrumented build identical: {len(prog)} bundles, "
          f"{len(LOG)} offloadable sites")

    kinds = collections.Counter(r[2] for r in LOG)
    print("site kinds:", dict(kinds))

    races = [r for r in LOG if r[2] == "race"]
    frees = [r for r in LOG if r[2] == "valu_free"]

    # --- margin distribution over the sites where the race actually ran ---
    print()
    print("=== RACE SITES (valu backed up at decision time) ===")
    wins = collections.Counter(r[5] for r in races)
    print("winners:", dict(wins))
    marg = collections.Counter()
    for _s, _op, _k, ra, rv, w, _h in races:
        marg[rv - ra] += 1   # >0: alu strictly better; 0 tie; <0 valu better
    print("margin (r_valu - r_alu) histogram, all race sites:")
    for m in sorted(marg):
        print(f"   {m:+4d}: {marg[m]:6d}")
    alu_wins = [r for r in races if r[5] == "alu"]
    valu_wins = [r for r in races if r[5] == "valu"]
    am = collections.Counter(r[4] - r[3] for r in alu_wins)
    vm = collections.Counter(r[3] - r[4] for r in valu_wins)
    print("alu-win margins (r_valu - r_alu):",
          {k: am[k] for k in sorted(am)})
    print("valu-win margins (r_alu - r_valu):",
          {k: vm[k] for k in sorted(vm)})
    n_marg_alu = sum(v for k, v in am.items() if k <= 1)
    n_marg_valu = sum(v for k, v in vm.items() if k <= 1)
    print(f"MARGINAL (|margin| <= 1): alu {n_marg_alu}/{len(alu_wins)}, "
          f"valu {n_marg_valu}/{len(valu_wins)}")

    print()
    print("=== NON-RACE SITES (valu had a free slot; taken unconditionally) ===")
    fm = collections.Counter(r[4] - r[3] for r in frees)
    print("would-be margin (r_valu - r_alu) histogram:")
    for m in sorted(fm):
        print(f"   {m:+4d}: {fm[m]:6d}")
    print("sites where alu would have TIED or beaten valu but was never "
          f"considered: {sum(v for k, v in fm.items() if k >= 0)}")

    print()
    print("=== by op ===")
    per: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    for _s, op, k, _ra, _rv, w, _h in LOG:
        per[op][f"{k}/{w}"] += 1
    for op in sorted(per):
        print(f"  {op:>3}: {dict(per[op])}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump([list(r) for r in LOG], f)
        print("wrote", args.json)


if __name__ == "__main__":
    main()
