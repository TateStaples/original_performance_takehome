"""H-063: what actually occupies the head (cycles 0..64) and drain windows.

H-061 measured that the load engine idles in two windows only -- head
[29,65) (70 free load slots) and drain [958,1006) (48 free) -- while in
every head-bubble cycle valu is 6/6 and alu 12/12.  This tool answers the
follow-up question the hypothesis needs: WHICH ops fill those saturated
head cycles, and how many of them are shallow-level *table construction*
(the class direction A would replace with bulk vloads)?

Classification is structural, not name-based where possible:
  setup-*   ops with scheduler.tag None (emitted before the group loop)
  r<r>g<g>  steady-state group-round work

Within setup, ops are bucketed by their write target's scratch debug name
and opcode, which separates:
  lv-vload      the level-table bulk vloads (ALREADY a bulk vload today)
  lv-prime      the ^C5 priming of the level table
  tbl-diff      the scalar (odd-even) pair subtracts
  tbl-bcast     vbroadcast splats of table words (the replication step)
  const-bcast   vbroadcast splats of loop-invariant constants
  const         ("const", ...) literal loads
  val-vload     per-group initial value vloads
  memprime      the deep-level in-memory priming stream
  other-setup   everything else

Usage (repo root):
  python3 tools/h063_head.py census            # window occupancy + classes
  python3 tools/h063_head.py drain             # drain-window detail
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tools"), os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import h061_attrib as A  # noqa: E402
from problem import SLOT_LIMITS, VLEN  # noqa: E402

HEAD = (0, 65)
DRAIN = (958, 1006)


def opname(op) -> str:
    for x in op[1]:
        if isinstance(x, str):
            return x
    return str(op[1][0])


def name_map(scratch_debug: dict) -> dict[int, str]:
    """address -> debug name.  scratch_debug maps base_addr -> (name, length)."""
    out: dict[int, str] = {}
    for addr, val in scratch_debug.items():
        name, length = (val if isinstance(val, tuple) else (val, 1))
        for k in range(int(length)):
            out[int(addr) + k] = str(name)
    return out


def classify(op, names: dict[int, str], lv_lo: int, lv_hi: int) -> str:
    engine, slot, reads, writes = op[0], op[1], op[2], op[3]
    tag = op[10]
    nm = opname(op)
    if tag is not None:
        return "steady"
    w0 = writes[0] if writes else None
    r0 = reads[0] if reads else None
    wname = names.get(w0, "") if w0 is not None else ""
    if nm == "vload" and w0 is not None and lv_lo <= w0 < lv_hi:
        return "lv-vload"
    if nm == "vload":
        return "val-vload"
    if nm == "vstore":
        return "memprime-store"
    if nm == "const":
        return "const"
    if nm == "vbroadcast":
        src = reads[0] if reads else None
        if src is not None and lv_lo <= src < lv_hi:
            return "tbl-bcast(lv)"
        return "tbl-bcast(diff)" if not wname else "const-bcast"
    if engine == "alu" and nm == "-" and r0 is not None and lv_lo <= r0 < lv_hi:
        return "tbl-diff"
    if engine == "valu" and nm == "^" and w0 is not None and lv_lo <= w0 < lv_hi:
        return "lv-prime"
    if nm == "add_imm":
        return "setup-addr(flow)"
    if engine == "load":
        return "setup-load"
    return f"other-setup({engine})"


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "census"
    data, ops, preds, floors = A.capture_stream(None)
    place = [op[9] for op in ops]
    n_cycles = max(place) + 1
    names = name_map(data["scratch_debug"])
    lv_addrs = sorted(a for a, n in names.items() if n == "lv")
    assert lv_addrs, "no lv block in scratch_debug"
    lv_lo, lv_hi = lv_addrs[0], lv_addrs[-1] + 1
    occ = A.occupancy(ops, place, n_cycles)
    ready, bind = A.ready_and_bind(ops, preds, floors, place)

    cls = [classify(op, names, lv_lo, lv_hi) for op in ops]

    print(f"== stream: {n_cycles} cycles, {len(ops)} ops; lv @ {lv_lo}..{lv_hi} ==")

    win = HEAD if cmd == "census" else DRAIN
    lo, hi = win
    print(f"\n-- window [{lo},{hi}) per-cycle occupancy --")
    print(f"{'cyc':>5} {'valu':>5} {'alu':>5} {'load':>5} {'store':>5} {'flow':>5}")
    free = Counter()
    for c in range(lo, min(hi, n_cycles)):
        o = occ[c]
        print(f"{c:>5} {o['valu']:>5} {o['alu']:>5} {o['load']:>5} "
              f"{o['store']:>5} {o['flow']:>5}")
        for e in ("valu", "alu", "load", "store", "flow"):
            free[e] += SLOT_LIMITS[e] - o[e]

    print(f"\nfree slots in [{lo},{hi}): " +
          ", ".join(f"{e}={free[e]}" for e in ("valu", "alu", "load", "store", "flow")))

    print(f"\n-- op classes placed in [{lo},{hi}) --")
    per_engine: dict[str, Counter] = defaultdict(Counter)
    tot: Counter[str] = Counter()
    for i, c in enumerate(place):
        if lo <= c < hi:
            tot[cls[i]] += 1
            per_engine[cls[i]][ops[i][0]] += 1
    for k, n in tot.most_common():
        eng = " ".join(f"{e}:{m}" for e, m in per_engine[k].most_common())
        print(f"  {n:>5}  {k:<22} {eng}")

    # whole-stream totals for the table-construction classes
    print("\n-- whole-stream totals for setup classes --")
    allc: Counter[str] = Counter()
    alle: dict[str, Counter] = defaultdict(Counter)
    span: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(place):
        if cls[i] == "steady":
            continue
        allc[cls[i]] += 1
        alle[cls[i]][ops[i][0]] += 1
        span[cls[i]].append(c)
    for k, n in allc.most_common():
        eng = " ".join(f"{e}:{m}" for e, m in alle[k].most_common())
        print(f"  {n:>5}  {k:<22} {eng:<28} cycles {min(span[k])}..{max(span[k])}")
    print(f"\n  setup ops total: {sum(allc.values())}, steady: {len(ops)-sum(allc.values())}")


if __name__ == "__main__":
    main()
