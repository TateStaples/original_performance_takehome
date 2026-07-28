"""P3-B: per-call-site, per-level attribution of INDEX-MAINTENANCE slots.

Read-only. Same monkeypatch funnel as tools/p3a_attrib.py (ListScheduler.put),
but grouped so every op that touches the index/parity recurrence is attributed
to (call-site, next_level, engine, opcode) and normalised per group-round.

Usage: python3 tools/p3b_attrib.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import perf_takehome as P  # noqa: E402
import diagnose_kernel as D  # noqa: E402
from problem import VLEN  # noqa: E402

SKIP = {"put", "emit", "emit_any", "find_free", "ready", "_sched_vec",
        "_sched_multiply_add", "_sched_vselect", "<lambda>"}

records: list[tuple[str, str, str, int, int, int, int]] = []
# (site, engine, opcode, round, level, next_level, group)


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
    nxt = ((rnd + 1) % 11) if rnd >= 0 else -1
    records.append((chain[0] if chain else "?", engine, op, rnd, lvl, nxt, grp))
    return orig_put(self, engine, slot, cycle, reads, writes, mem_read, mem_write)


orig_put = P.ListScheduler.put
P.ListScheduler.put = patched_put  # type: ignore[assignment]


def main() -> None:
    kb = D.build_diagnostic_kernel()
    lookup = D.named_range_lookup(kb)
    print(f"cycles {len(kb.instrs)}  records {len(records)}")

    # re-derive purpose per record by walking the emitted stream in order is
    # not possible (put order != bundle order); instead classify from the site.
    by: Counter[tuple[str, str, str]] = Counter()
    for site, engine, op, rnd, lvl, nxt, grp in records:
        by[(site, engine, op)] += 1
    print("\n== every slot by call-site ==")
    print(f"{'site':<42}{'eng':<6}{'op':<14}{'slots':>7}{'lane-ops':>10}")
    for (site, engine, op), n in sorted(by.items(), key=lambda kv: -kv[1]):
        lanes = n * (VLEN if engine in ("valu", "flow") and op not in
                     ("pause", "add_imm") else 1)
        print(f"{site:<42}{engine:<6}{op:<14}{n:>7}{lanes:>10}")

    # index-maintenance sites only (the state-update tail, lines 1600-1673,
    # plus race_idx_madd), split by the level being ENTERED
    IDX_LINES = {1607, 1615, 1617, 1620, 1622, 1631, 1655, 1656}
    def is_idx(site: str) -> bool:
        fn, _, ln = site.partition(":")
        if fn == "race_idx_madd":
            return True
        return fn == "_round_stage_generator" and int(ln) in IDX_LINES

    print("\n== index/parity sites by next_level (state-update tail only) ==")
    b2: Counter[tuple[str, str, str, int]] = Counter()
    for site, engine, op, rnd, lvl, nxt, grp in records:
        if rnd >= 0 and is_idx(site):
            b2[(site, engine, op, nxt)] += 1
    print(f"{'site':<30}{'eng':<6}{'op':<14}{'nxtL':>5}{'slots':>7}")
    for (site, engine, op, nxt), n in sorted(b2.items()):
        print(f"{site:<30}{engine:<6}{op:<14}{nxt:>5}{n:>7}")

    # per (L -> nextL) vec-op-equivalents and group-round counts
    print("\n== state-update tail: vec-op-equivalents per (L -> nextL) ==")
    prof: Counter[tuple[int, int]] = Counter()
    grs: dict[tuple[int, int], set[tuple[int, int]]] = {}
    for site, engine, op, rnd, lvl, nxt, grp in records:
        if rnd < 0 or not is_idx(site):
            continue
        key = (lvl, nxt)
        prof[key] += 1 if engine != "alu" else 0.125  # 8 alu lanes = 1 vec-op
        grs.setdefault(key, set()).add((rnd, grp))
    tot = 0.0
    for (lvl, nxt), n in sorted(prof.items()):
        k = len(grs[(lvl, nxt)])
        tot += n
        print(f"  L{lvl:>2} -> L{nxt:<2}: {n:8.3f} vec-ops over {k:4d} group-rounds"
              f"  = {n / k:.3f}/gr")
    print(f"  TOTAL {tot:.3f} vec-ops = {tot * VLEN:.0f} lane-ops")

    # how many group-rounds emit a state update at all
    allgr = {(r, g) for _, _, _, r, _, _, g in records if r >= 0}
    updgr = {gr for s in grs.values() for gr in s}
    print(f"  group-rounds seen {len(allgr)}, with state update {len(updgr)}")


if __name__ == "__main__":
    main()
