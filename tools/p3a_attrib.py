"""P3-A: exact call-site attribution of every emitted slot in the 1006 kernel.

Read-only. Monkeypatches ListScheduler.put (the single funnel through which
emit/emit_any/_sched_vec all place slots) and records, for each placed slot,
the innermost perf_takehome.py call-site chain plus the round/level/group of
the enclosing `_round_stage_generator` frame when there is one.

Usage: python3 tools/p3a_attrib.py [--by-site|--by-mech]
"""

from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import perf_takehome as P  # noqa: E402
from problem import VLEN  # noqa: E402

SKIP = {"put", "emit", "emit_any", "find_free", "ready", "_sched_vec",
        "_sched_multiply_add", "_sched_vselect"}

records: list[tuple[tuple[str, ...], str, str, int, int, int]] = []
# (site chain, engine, opcode, round, level, group)


def patched_put(self, engine, slot, cycle, reads=(), writes=(),
                mem_read=False, mem_write=False):
    f = sys._getframe(1)
    chain: list[str] = []
    rnd = lvl = grp = -1
    while f is not None:
        code = f.f_code
        if code.co_filename.endswith("perf_takehome.py"):
            name = code.co_name
            if name == "_round_stage_generator":
                rnd = f.f_locals.get("round", -1)
                lvl = f.f_locals.get("L", -1)
                grp = f.f_locals.get("g", -1)
            if name not in SKIP:
                chain.append(f"{name}:{f.f_lineno}")
            if name in ("build_kernel_scheduled", "build_kernel"):
                break
        f = f.f_back
    op = slot[0] if isinstance(slot, tuple) else str(slot)
    records.append((tuple(chain[:3]), engine, op, rnd, lvl, grp))
    return orig_put(self, engine, slot, cycle, reads, writes, mem_read, mem_write)


orig_put = P.ListScheduler.put
P.ListScheduler.put = patched_put  # type: ignore[assignment]


def lane_ops(engine: str, op: str, n: int) -> int:
    if engine == "alu":
        return n
    if engine == "valu":
        return VLEN * n
    return 0


def main() -> None:
    kb = P.KernelBuilder()
    kb.build_kernel(forest_height=10, n_nodes=2047, batch_size=256, rounds=16)
    print(f"cycles {len(kb.instrs)}  records {len(records)}")

    by_site: Counter[tuple[tuple[str, ...], str, str]] = Counter()
    for chain, engine, op, r, l, g in records:
        by_site[(chain, engine, op)] += 1

    tot_av = 0
    rows = []
    for (chain, engine, op), n in by_site.items():
        lo = lane_ops(engine, op, n)
        tot_av += lo
        rows.append((lo, n, engine, op, chain))
    rows.sort(reverse=True)
    print(f"\n{'lane-ops':>9}{'slots':>7}  {'engine':<6}{'op':<14} site chain")
    for lo, n, engine, op, chain in rows:
        print(f"{lo:>9}{n:>7}  {engine:<6}{op:<14} {' <- '.join(chain)}")
    print(f"\nTOTAL alu+valu lane-ops {tot_av}")

    # per-level breakdown of alu+valu
    print("\n== alu+valu lane-ops by round-level (level -1 = setup/outside) ==")
    per_level: Counter[int] = Counter()
    per_level_slots: Counter[tuple[int, str, str]] = Counter()
    for chain, engine, op, r, l, g in records:
        lo = lane_ops(engine, op, 1)
        per_level[l] += lo
        if lo:
            per_level_slots[(l, engine, op)] += 1
    for l in sorted(per_level):
        print(f"  level {l:>3}: {per_level[l]:>7}")

    # flow / load / store
    print("\n== non-compute engines by site ==")
    for (chain, engine, op), n in sorted(by_site.items(), key=lambda kv: -kv[1]):
        if engine in ("flow", "load", "store"):
            print(f"  {engine:<6}{op:<12}{n:>6}  {' <- '.join(chain)}")


if __name__ == "__main__":
    main()
