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

import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perf_takehome import KernelBuilder
from problem import SLOT_LIMITS, VLEN

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


def opcode_key(engine, op):
    """valu elementwise ops share alu spellings; prefix to keep them distinct."""
    if engine == "valu" and op in ALU_OPS:
        return f"v{op}"
    return op


def build():
    kb = KernelBuilder()
    kb.build_kernel(FOREST_HEIGHT, 2**(FOREST_HEIGHT + 1) - 1, BATCH_SIZE, ROUNDS)
    return kb


def named_range_lookup(kb):
    """addr -> block name, honoring each named allocation's length."""
    blocks = sorted((a, n, ln) for a, (n, ln) in kb.scratch_debug.items())
    def lookup(addr):
        lo, hi = 0, len(blocks)
        while lo < hi:
            mid = (lo + hi) // 2
            if blocks[mid][0] <= addr:
                lo = mid + 1
            else:
                hi = mid
        if lo:
            base, name, ln = blocks[lo - 1]
            if addr < base + ln:
                return name
        return None
    return lookup


def slot_operands(engine, slot):
    """(reads, writes) as scratch addresses, per problem.py semantics."""
    op = slot[0]
    if engine == "alu":
        _, dest, a1, a2 = slot
        return [a1, a2], [dest]
    if engine == "valu":
        if op == "vbroadcast":
            return [slot[2]], [slot[1] + i for i in range(VLEN)]
        if op == "multiply_add":
            _, d, a, b, c = slot
            rd = [x + i for x in (a, b, c) for i in range(VLEN)]
            return rd, [d + i for i in range(VLEN)]
        _, d, a1, a2 = slot
        rd = [x + i for x in (a1, a2) for i in range(VLEN)]
        return rd, [d + i for i in range(VLEN)]
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
            _, d, c, a, b = slot
            rd = [x + i for x in (c, a, b) for i in range(VLEN)]
            return rd, [d + i for i in range(VLEN)]
        if op == "add_imm":
            return [slot[2]], [slot[1]]
    return [], []


def classify(engine, slot, lookup):
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
    rnames = {lookup(a) for a in reads} - {None}
    wnames = {lookup(a) for a in writes} - {None}
    if rnames & HASH_CONST_NAMES:
        return "Hash"               # hash-stage madds/xors/shifts
    if any(n.startswith("val") for n in wnames):
        return "Hash"               # val fold-in / stage combines
    if any(n.startswith("val") for n in rnames):
        return "Idx"                # parity extraction (val & 1)
    if any(n.startswith("st") for n in wnames):
        return "Idx"                # p := 2p+b / gaddr updates
    if any(n.startswith("st") for n in rnames):
        return "Routing"            # tournament condition extraction
    if "lv" in rnames or {"forest_values_p", "one_vec"} & rnames == {"forest_values_p"}:
        return "Setup"              # level-table diffs, omf
    return "Routing"                # tournament pool combines


def lane_ops(engine, slot):
    """How many scalar-equivalent lane operations this slot performs."""
    if engine in ("valu", "flow") and slot[0] not in ("pause", "add_imm"):
        return VLEN
    return 1


def main():
    kb = build()
    lookup = named_range_lookup(kb)
    cycles = len(kb.instrs)

    slot_uses = Counter()
    busy = Counter()
    opcodes = Counter()
    purpose_engine = defaultdict(Counter)   # purpose -> engine -> slots
    purpose_lanes = Counter()               # purpose -> lane-ops (non-debug)

    for bundle in kb.instrs:
        for engine, slots in bundle.items():
            if slots and engine != "debug":
                busy[engine] += 1
            for slot in slots:
                slot_uses[engine] += 1
                opcodes[(engine, opcode_key(engine, slot[0]))] += 1
                p = classify(engine, slot, lookup)
                purpose_engine[p][engine] += 1
                if engine != "debug":
                    purpose_lanes[p] += lane_ops(engine, slot)

    print(f"kernel: {cycles} cycles  (fh={FOREST_HEIGHT} bs={BATCH_SIZE} r={ROUNDS})\n")

    print("== engine utilization ==")
    print(f"{'engine':<8}{'slots':>8}{'capacity':>10}{'slot-util':>11}{'busy%':>8}")
    for e in ("alu", "valu", "load", "store", "flow"):
        cap = cycles * SLOT_LIMITS[e]
        print(f"{e:<8}{slot_uses[e]:>8}{cap:>10}"
              f"{100.0 * slot_uses[e] / cap:>10.1f}%"
              f"{100.0 * busy[e] / cycles:>7.1f}%")
    print(f"{'debug':<8}{slot_uses['debug']:>8}{'(free)':>10}")

    print("\n== purpose breakdown (slots per engine; % of engine's used slots) ==")
    engines = ("alu", "valu", "load", "store", "flow")
    hdr = "".join(f"{e:>14}" for e in engines)
    print(f"{'purpose':<9}{hdr}{'lane-ops':>10}{'lane%':>8}")
    total_lanes = sum(purpose_lanes.values())
    for p in ("Hash", "Idx", "Routing", "Setup", "Store"):
        row = ""
        for e in engines:
            n = purpose_engine[p][e]
            row += f"{n:>8}" + (f" {100.0 * n / slot_uses[e]:>4.0f}%" if n else "     ")
        print(f"{p:<9}{row}{purpose_lanes[p]:>10}"
              f"{100.0 * purpose_lanes[p] / total_lanes:>7.1f}%")
    print(f"(lane-ops: VLEN-wide slot = {VLEN}, scalar = 1; debug excluded)")

    print("\n== opcode census ==")
    for e in ("alu", "valu", "load", "store", "flow", "debug"):
        used = {op: n for (ee, op), n in opcodes.items() if ee == e}
        unused = [op for op in ISA[e] if op not in used]
        used_s = "  ".join(f"{op}:{n}" for op, n in sorted(used.items(), key=lambda kv: -kv[1]))
        print(f"{e:<6} used:   {used_s if used_s else '(none)'}")
        print(f"{'':<6} unused: {', '.join(unused) if unused else '(none)'}")

    total = sum(len(ISA[e]) for e in ISA)
    used_n = len({k for k in opcodes})
    print(f"\ninstruction types used: {used_n}/{total}")


if __name__ == "__main__":
    main()
