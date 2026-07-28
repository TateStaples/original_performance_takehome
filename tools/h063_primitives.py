"""H-063: EXECUTABLE validation of the two memory-backed lane-movement
primitives, so the catalogue in STATE.md carries measured prices rather
than asserted ones.

The ISA (docs/isa.md) has no shuffle, no gather, no stride-0 read and no
cross-lane op: `valu` is strictly lanewise, `vload`/`vstore` are
contiguous-only, and `vbroadcast` is the single lane-crossing instruction.
Memory is therefore the ONLY route from lane i to lane j, via two shapes:

  P1  arbitrary 8-element permute / gather-into-lanes
      8x ("store", addr_k, src_k) + 1x ("vload", dst, base)
      price: 8 store slots (4 cycles at the 2-slot limit, or free in a
      window where store is idle -- store runs 46/2,012 = 2.3% occupied)
             + 1 load slot + 8 address registers, >= 2 cycles of latency.

  P2  lane rotation by k
      1x ("vstore", A, src) + 1x ("vload", dst, A+k)
      price: 1 store slot + 1 load slot + 2 address registers, 2 cycles
      of latency.  Lanes k..7 come from src; lanes 0..k-1 are whatever
      already lives at mem[A+8..], so a rotation that must WRAP needs a
      second vstore at A+8 (2 store + 1 load).

Both are validated below on tests/frozen_problem.Machine, which is the
graded simulator.

Usage (repo root):  python3 tools/h063_primitives.py
"""
from __future__ import annotations

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (REPO_ROOT, os.path.join(REPO_ROOT, "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from frozen_problem import Machine, DebugInfo, VLEN  # noqa: E402

MEM_BASE = 64          # a scratch region of memory for the probes
SRC = 0                # scratch: source vector lanes 0..7
DST = 16               # scratch: destination vector
ADDR = 32              # scratch: 8 address words for the permute
BASE = 48              # scratch: rotation base address


def run(program, mem_words=256):
    mem = [0] * mem_words
    m = Machine(mem, program, DebugInfo({}), scratch_size=256)
    m.enable_pause = False
    m.enable_debug = False
    m.run()
    return m, m.cores[0]


def consts(pairs):
    """One bundle per pair of consts (load engine has 2 slots)."""
    out = []
    items = list(pairs)
    for i in range(0, len(items), 2):
        out.append({"load": [("const", d, v) for d, v in items[i:i + 2]]})
    return out


def test_permute(perm):
    """P1: gather scratch[SRC+perm[i]] into DST+i via memory."""
    prog: list = []
    prog += consts([(SRC + i, 100 + i) for i in range(VLEN)])
    # address words: mem slot for destination lane i, and the base
    prog += consts([(ADDR + i, MEM_BASE + i) for i in range(VLEN)])
    prog += consts([(BASE, MEM_BASE)])
    # 8 scalar stores: mem[MEM_BASE+i] = scratch[SRC+perm[i]]  -- 2 slots/cycle
    st = [("store", ADDR + i, SRC + perm[i]) for i in range(VLEN)]
    n_store_cycles = 0
    for i in range(0, VLEN, 2):
        prog.append({"store": st[i:i + 2]})
        n_store_cycles += 1
    prog.append({"load": [("vload", DST, BASE)]})
    _, core = run(prog)
    got = core.scratch[DST:DST + VLEN]
    want = [100 + perm[i] for i in range(VLEN)]
    return got == want, got, want, n_store_cycles


def test_rotation(k):
    """P2: vstore at A, vload at A+k -> lanes rotated by k (no wrap)."""
    prog: list = []
    prog += consts([(SRC + i, 200 + i) for i in range(VLEN)])
    prog += consts([(BASE, MEM_BASE), (BASE + 1, MEM_BASE + VLEN)])
    prog += consts([(BASE + 2, MEM_BASE + k)])
    # write src twice, at A and A+8, so the read window A+k .. A+k+7 wraps
    prog.append({"store": [("vstore", BASE, SRC), ("vstore", BASE + 1, SRC)]})
    prog.append({"load": [("vload", DST, BASE + 2)]})
    _, core = run(prog)
    got = core.scratch[DST:DST + VLEN]
    want = [200 + ((i + k) % VLEN) for i in range(VLEN)]
    return got == want, got, want


def test_broadcast_via_overlap():
    """The vstore-overlap replication trick (H-053 leg 3), priced."""
    prog: list = []
    prog += consts([(SRC + i, 300 + i) for i in range(VLEN)])
    prog += consts([(BASE + i, MEM_BASE + i) for i in range(VLEN)])
    # ascending overlapping vstores: mem[A..A+7] all end up = src[0]
    # WAW-serialised, so one per cycle even though store has 2 slots
    for i in range(VLEN):
        prog.append({"store": [("vstore", BASE + i, SRC)]})
    prog.append({"load": [("vload", DST, BASE)]})
    _, core = run(prog)
    got = core.scratch[DST:DST + VLEN]
    want = [300] * VLEN
    return got == want, got, want


def main() -> None:
    print("== P1: arbitrary 8-element permute (8 scalar stores + 1 vload) ==")
    for perm in ([7, 6, 5, 4, 3, 2, 1, 0], [0, 0, 3, 3, 7, 1, 2, 2],
                 [1, 2, 3, 4, 5, 6, 7, 0]):
        ok, got, want, cyc = test_permute(perm)
        print(f"  perm={perm} -> {'OK' if ok else 'FAIL'}  got={got}"
              f"{'' if ok else f' want={want}'}   store-cycles={cyc}")
    print("  price: 8 store slots + 1 load slot + 8 address regs; "
          "store engine is 2.3% occupied so the stores are usually free")

    print("\n== P2: lane rotation by k (1-2 vstores + 1 vload) ==")
    for k in (1, 3, 5, 7):
        ok, got, want = test_rotation(k)
        print(f"  k={k} -> {'OK' if ok else 'FAIL'}  got={got}"
              f"{'' if ok else f' want={want}'}")
    print("  price: 1 vstore (no wrap) or 2 vstores (wrap) + 1 vload, "
          "2 cycles of latency, 2-3 address regs")

    print("\n== control: vstore-overlap replication (a broadcast via memory) ==")
    ok, got, want = test_broadcast_via_overlap()
    print(f"  {'OK' if ok else 'FAIL'}  got={got}{'' if ok else f' want={want}'}")
    print("  price: 8 vstores, WAW-SERIALISED (1/cycle) + 1 vload = 9 cycles "
          "of latency for ONE vector that `vbroadcast` produces in 1 valu slot")


if __name__ == "__main__":
    main()
