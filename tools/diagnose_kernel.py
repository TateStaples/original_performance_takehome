"""
Diagnostics over the REAL graded kernel (perf_takehome.py KernelBuilder):

1. Engine slot-utilization rates: slots used / (cycles x SLOT_LIMITS), and
   busy% (cycles with >= 1 slot).
2. Purpose breakdown (Setup / Hash / Idx / Routing / Store): every emitted
   slot is classified from its opcode + which named scratch ranges it
   reads/writes (val{g} = hash chain, st{g} = position/gaddr state,
   nv{g} = node_val routing, k0..sh5 = hash constants, lv = level table).
3. Opcode census: every (engine, opcode) used, vs. the full ISA inventory
   from problem.py -- what the kernel never touches.

Debug slots are counted separately (the ISA retires them for free; the
grader's cycle count ignores debug-only work).

Usage (repo root): python tools/diagnose_kernel.py
"""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import cast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perf_takehome import KernelBuilder
from problem import SLOT_LIMITS, VLEN, Engine, Slot

FOREST_HEIGHT, BATCH_SIZE, ROUNDS = 10, 256, 16

# The full ISA op inventory, straight from problem.py's Machine match arms.
ALU_OPS = ["+", "-", "*", "//", "cdiv", "^", "&", "|", "<<", ">>", "%", "<", "=="]
ISA = {
    "alu": list(ALU_OPS),
    "valu": ["vbroadcast", "multiply_add"] + [f"v{op}" for op in ALU_OPS],
    "load": ["load", "load_offset", "vload", "const"],
    "store": ["store", "vstore"],
    "flow": [
        "select", "add_imm", "vselect", "halt", "pause", "trace_write",
        "cond_jump", "cond_jump_rel", "jump", "jump_indirect", "coreid",
    ],
    "debug": ["compare", "vcompare"],
}

HASH_CONST_NAMES = {"k0", "C0", "C1", "sh1", "kp", "ap", "kq", "aq", "k4", "C4", "C5", "sh5"}
SETUP_LOAD_DESTS = {"forest_values_p", "inp_values_p", "root_nv"}


def opcode_key(engine: Engine, op: str) -> str:
    """valu elementwise ops share alu spellings; prefix to keep them distinct."""
    if engine == "valu" and op in ALU_OPS:
        return f"v{op}"
    return op


def build_diagnostic_kernel() -> KernelBuilder:
    kb = KernelBuilder()
    kb.build_kernel(FOREST_HEIGHT, 2**(FOREST_HEIGHT + 1) - 1, BATCH_SIZE, ROUNDS)
    return kb


def named_range_lookup(kb: KernelBuilder) -> Callable[[int], str | None]:
    """addr -> block name, honoring each named allocation's length."""
    blocks = sorted((addr, name, length) for addr, (name, length) in kb.scratch_debug.items())
    def lookup(addr: int) -> str | None:
        lo, hi = 0, len(blocks)
        while lo < hi:
            mid = (lo + hi) // 2
            if blocks[mid][0] <= addr:
                lo = mid + 1
            else:
                hi = mid
        if lo:
            base, name, length = blocks[lo - 1]
            if addr < base + length:
                return name
        return None
    return lookup


def slot_operands(engine: Engine, slot: Slot) -> tuple[list[int], list[int]]:
    """(reads, writes) as scratch addresses, per problem.py semantics."""
    op = slot[0]
    if engine == "alu":
        _, dest, a1, a2 = slot
        return [a1, a2], [dest]
    if engine == "valu":
        if op == "vbroadcast":
            return [slot[2]], [slot[1] + i for i in range(VLEN)]
        if op == "multiply_add":
            _, dest, a, b, c = slot
            reads = [base + i for base in (a, b, c) for i in range(VLEN)]
            return reads, [dest + i for i in range(VLEN)]
        _, dest, a1, a2 = slot
        reads = [base + i for base in (a1, a2) for i in range(VLEN)]
        return reads, [dest + i for i in range(VLEN)]
    if engine == "load":
        if op == "load":
            return [slot[2]], [slot[1]]
        if op == "vload":
            return [slot[2]], [slot[1] + i for i in range(VLEN)]
        if op == "const":
            return [], [slot[1]]
    if engine == "store":
        if op == "store":
            return [slot[1], slot[2]], []
        if op == "vstore":
            return [slot[1]] + [slot[2] + i for i in range(VLEN)], []
    if engine == "flow":
        if op == "vselect":
            _, dest, cond, a, b = slot
            reads = [base + i for base in (cond, a, b) for i in range(VLEN)]
            return reads, [dest + i for i in range(VLEN)]
        if op == "add_imm":
            return [slot[2]], [slot[1]]
    return [], []


def classify(engine: Engine, slot: Slot, lookup: Callable[[int], str | None]) -> str:
    """Purpose of one slot. Rule order matters; see module docstring."""
    op = slot[0]
    if engine == "debug":
        return "Debug"
    if op in ("const", "vbroadcast", "add_imm", "pause"):
        return "Setup"
    if engine == "store":
        return "Store"
    if engine == "load":
        if op == "vload":
            return "Setup"          # level table + initial value loads
        name = lookup(slot[1])
        return "Setup" if name in SETUP_LOAD_DESTS else "Routing"  # gather
    if engine == "flow" and op == "vselect":
        return "Routing"            # tournament folds
    reads, writes = slot_operands(engine, slot)
    # cast: `set - {None}` drops the None members but pyright can't narrow the
    # element type off a set difference; the cast is output-neutral.
    rnames = cast("set[str]", {lookup(addr) for addr in reads} - {None})
    wnames = cast("set[str]", {lookup(addr) for addr in writes} - {None})
    if rnames & HASH_CONST_NAMES:
        return "Hash"               # hash-stage madds/xors/shifts
    if any(name.startswith("val") for name in wnames):
        return "Hash"               # val fold-in / stage combines
    if any(name.startswith("val") for name in rnames):
        return "Idx"                # parity extraction (val & 1)
    if any(name.startswith("st") for name in wnames):
        return "Idx"                # p := 2p+b / gaddr updates
    if any(name.startswith("st") for name in rnames):
        return "Routing"            # tournament condition extraction
    if "lv" in rnames or {"forest_values_p", "one_vec"} & rnames == {"forest_values_p"}:
        return "Setup"              # level-table diffs, omf
    return "Routing"                # tournament pool combines


def lane_ops(engine: Engine, slot: Slot) -> int:
    """How many scalar-equivalent lane operations this slot performs."""
    if engine in ("valu", "flow") and slot[0] not in ("pause", "add_imm"):
        return VLEN
    return 1


def main() -> None:
    kb = build_diagnostic_kernel()
    lookup = named_range_lookup(kb)
    cycles = len(kb.instrs)

    slot_uses: Counter[Engine] = Counter()
    busy: Counter[Engine] = Counter()
    opcodes: Counter[tuple[Engine, str]] = Counter()
    purpose_engine: defaultdict[str, Counter[Engine]] = defaultdict(Counter)   # purpose -> engine -> slots
    purpose_lanes: Counter[str] = Counter()               # purpose -> lane-ops (non-debug)

    for bundle in kb.instrs:
        for engine, slots in bundle.items():
            if slots and engine != "debug":
                busy[engine] += 1
            for slot in slots:
                slot_uses[engine] += 1
                opcodes[(engine, opcode_key(engine, slot[0]))] += 1
                purpose = classify(engine, slot, lookup)
                purpose_engine[purpose][engine] += 1
                if engine != "debug":
                    purpose_lanes[purpose] += lane_ops(engine, slot)

    print(f"kernel: {cycles} cycles  (fh={FOREST_HEIGHT} bs={BATCH_SIZE} r={ROUNDS})\n")

    print("== engine utilization ==")
    print(f"{'engine':<8}{'slots':>8}{'capacity':>10}{'slot-util':>11}{'busy%':>8}")
    for engine in ("alu", "valu", "load", "store", "flow"):
        capacity = cycles * SLOT_LIMITS[engine]
        print(f"{engine:<8}{slot_uses[engine]:>8}{capacity:>10}"
              f"{100.0 * slot_uses[engine] / capacity:>10.1f}%"
              f"{100.0 * busy[engine] / cycles:>7.1f}%")
    print(f"{'debug':<8}{slot_uses['debug']:>8}{'(free)':>10}")

    print("\n== purpose breakdown (slots per engine; % of engine's used slots) ==")
    engines = ("alu", "valu", "load", "store", "flow")
    header = "".join(f"{engine:>14}" for engine in engines)
    print(f"{'purpose':<9}{header}{'lane-ops':>10}{'lane%':>8}")
    total_lanes = sum(purpose_lanes.values())
    for purpose in ("Hash", "Idx", "Routing", "Setup", "Store"):
        row = ""
        for engine in engines:
            count = purpose_engine[purpose][engine]
            row += f"{count:>8}" + (f" {100.0 * count / slot_uses[engine]:>4.0f}%" if count else "     ")
        print(f"{purpose:<9}{row}{purpose_lanes[purpose]:>10}"
              f"{100.0 * purpose_lanes[purpose] / total_lanes:>7.1f}%")
    print(f"(lane-ops: VLEN-wide slot = {VLEN}, scalar = 1; debug excluded)")

    print("\n== opcode census ==")
    for engine in ("alu", "valu", "load", "store", "flow", "debug"):
        used = {op: count for (entry_engine, op), count in opcodes.items() if entry_engine == engine}
        unused = [op for op in ISA[engine] if op not in used]
        used_summary = "  ".join(f"{op}:{count}" for op, count in sorted(used.items(), key=lambda kv: -kv[1]))
        print(f"{engine:<6} used:   {used_summary if used_summary else '(none)'}")
        print(f"{'':<6} unused: {', '.join(unused) if unused else '(none)'}")

    total = sum(len(ISA[engine]) for engine in ISA)
    used_count = len({k for k in opcodes})
    print(f"\ninstruction types used: {used_count}/{total}")


if __name__ == "__main__":
    main()
