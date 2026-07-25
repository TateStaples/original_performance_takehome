"""
Read the top of perf_takehome.py for more introduction.

This file is separate mostly for ease of copying it to freeze the machine and
reference kernel for testing.
"""

from __future__ import annotations

from copy import copy
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, TextIO
import random

# One of the machine's execution engines. Each is a key in an `Instruction`
# dict and has a per-cycle slot budget in `SLOT_LIMITS`.
Engine = Literal["alu", "valu", "load", "store", "flow", "debug"]

# A single ISA operation: a heterogeneous tuple whose first element is the
# opcode string (e.g. "load", "multiply_add", "+") and whose remaining
# elements are its operands -- usually scratch addresses (int), but some
# opcodes carry an immediate value or a list of trace keys.
Slot = tuple[Any, ...]

# One VLIW bundle: for each engine used this cycle, the list of slots that
# engine executes in parallel.
Instruction = dict[Engine, list[Slot]]

# A whole compiled kernel: the ordered stream of bundles the machine runs.
Program = list[Instruction]


class CoreState(Enum):
    RUNNING = 1
    PAUSED = 2
    STOPPED = 3


@dataclass
class Core:
    id: int
    scratch: list[int]
    trace_buf: list[int]
    pc: int = 0
    state: CoreState = CoreState.RUNNING


@dataclass
class DebugInfo:
    """
    We give you some debug info but it's up to you to use it in Machine if you
    want to. You're also welcome to add more.
    """

    # Maps scratch variable addr to (name, len) pair
    scratch_map: dict[int, tuple[str, int]]


def cdiv(a: int, b: int) -> int:
    return (a + b - 1) // b


SLOT_LIMITS: dict[Engine, int] = {
    "alu": 12,
    "valu": 6,
    "load": 2,
    "store": 2,
    "flow": 1,
    "debug": 64,
}

VLEN = 8
# Older versions of the take-home used multiple cores, but this version only uses 1
N_CORES = 1
SCRATCH_SIZE = 1536
BASE_ADDR_TID = 100000


class Machine:
    """
    Simulator for a custom VLIW SIMD architecture.

    VLIW (Very Large Instruction Word): Cores are composed of different
    "engines" each of which can execute multiple "slots" per cycle in parallel.
    How many slots each engine can execute per cycle is limited by SLOT_LIMITS.
    Effects of instructions don't take effect until the end of cycle. Each
    cycle, all engines execute all of their filled slots for that instruction.
    Effects like writes to memory take place after all the inputs are read.

    SIMD: There are instructions for acting on vectors of VLEN elements in a
    single slot. You can use vload and vstore to load multiple contiguous
    elements but not non-contiguous elements. Use vbroadcast to broadcast a
    scalar to a vector and then operate on vectors with valu instructions.

    The memory and scratch space are composed of 32-bit words. The solution is
    plucked out of the memory at the end of the program. You can think of the
    scratch space as serving the purpose of registers, constant memory, and a
    manually-managed cache.

    Here's an example of what an instruction might look like:

    {"valu": [("*", 4, 0, 0), ("+", 8, 4, 0)], "load": [("load", 16, 17)]}

    In general every number in an instruction is a scratch address except for
    const and jump, and except for store and some flow instructions the first
    operand is the destination.

    This comment is not meant to be full ISA documentation though, for the rest
    you should look through the simulator code.
    """

    def __init__(
        self,
        mem_dump: list[int],
        program: Program,
        debug_info: DebugInfo,
        n_cores: int = 1,
        scratch_size: int = SCRATCH_SIZE,
        trace: bool = False,
        value_trace: dict[Any, int] = {},
    ) -> None:
        self.cores: list[Core] = [
            Core(id=i, scratch=[0] * scratch_size, trace_buf=[]) for i in range(n_cores)
        ]
        self.mem: list[int] = copy(mem_dump)
        self.program = program
        self.debug_info = debug_info
        self.value_trace = value_trace
        self.enable_prints = False
        self.cycle = 0
        self.enable_pause = True
        self.enable_debug = True
        # Pending writes buffered during a bundle and committed at end of cycle
        # (created fresh in `step`; declared here only for their types).
        self.scratch_write: dict[int, int]
        self.mem_write: dict[int, int]
        # Open trace file when tracing, else None.
        self.trace: TextIO | None
        if trace:
            self.setup_trace()
        else:
            self.trace = None

    def rewrite_instr(self, instr: Instruction) -> Instruction:
        """
        Rewrite an instruction to use scratch addresses instead of names
        """
        named_instr: Instruction = {}
        for engine, slots in instr.items():
            named_instr[engine] = []
            for slot in slots:
                named_instr[engine].append(self.rewrite_slot(slot))
        return named_instr

    def print_step(self, instr: Instruction, core: Core) -> None:
        # print(core.id)
        # print(core.trace_buf)
        print(self.scratch_map(core))
        print(core.pc, instr, self.rewrite_instr(instr))

    def scratch_map(self, core: Core) -> dict[str, list[int]]:
        values_by_name: dict[str, list[int]] = {}
        for addr, (name, length) in self.debug_info.scratch_map.items():
            values_by_name[name] = core.scratch[addr : addr + length]
        return values_by_name

    def rewrite_slot(self, slot: Slot) -> tuple[Any, ...]:
        return tuple(
            self.debug_info.scratch_map.get(field, (None, None))[0] or field
            for field in slot
        )

    def setup_trace(self) -> None:
        """
        The simulator generates traces in Chrome's Trace Event Format for
        visualization in Perfetto (or chrome://tracing if you prefer it). See
        the bottom of the file for info about how to use this.

        See the format docs in case you want to add more info to the trace:
        https://docs.google.com/document/d/1CvAClvFfyA5R-PhYUmn5OOQtYMH4h6I0nSsKchNAySU/preview
        """
        self.trace = open("trace.json", "w")
        self.trace.write("[")
        tid_counter = 0
        self.tids: dict[tuple[int, Engine, int], int] = {}
        for core_index, core in enumerate(self.cores):
            self.trace.write(
                f'{{"name": "process_name", "ph": "M", "pid": {core_index}, "tid": 0, "args": {{"name":"Core {core_index}"}}}},\n'
            )
            for engine, limit in SLOT_LIMITS.items():
                if engine == "debug":
                    continue
                for slot_index in range(limit):
                    tid_counter += 1
                    self.trace.write(
                        f'{{"name": "thread_name", "ph": "M", "pid": {core_index}, "tid": {tid_counter}, "args": {{"name":"{engine}-{slot_index}"}}}},\n'
                    )
                    self.tids[(core_index, engine, slot_index)] = tid_counter

        # Add zero-length events at the start so all slots show up in Perfetto
        for core_index, core in enumerate(self.cores):
            for engine, limit in SLOT_LIMITS.items():
                if engine == "debug":
                    continue
                for slot_index in range(limit):
                    tid = self.tids[(core_index, engine, slot_index)]
                    self.trace.write(
                        f'{{"name": "init", "cat": "op", "ph": "X", "pid": {core_index}, "tid": {tid}, "ts": 0, "dur": 0}},\n'
                    )
        for core_index, core in enumerate(self.cores):
            self.trace.write(
                f'{{"name": "process_name", "ph": "M", "pid": {len(self.cores) + core_index}, "tid": 0, "args": {{"name":"Core {core_index} Scratch"}}}},\n'
            )
            for addr, (name, length) in self.debug_info.scratch_map.items():
                self.trace.write(
                    f'{{"name": "thread_name", "ph": "M", "pid": {len(self.cores) + core_index}, "tid": {BASE_ADDR_TID + addr}, "args": {{"name":"{name}-{length}"}}}},\n'
                )

    def run(self) -> None:
        for core in self.cores:
            if core.state == CoreState.PAUSED:
                core.state = CoreState.RUNNING
        while any(core.state == CoreState.RUNNING for core in self.cores):
            has_non_debug = False
            for core in self.cores:
                if core.state != CoreState.RUNNING:
                    continue
                if core.pc >= len(self.program):
                    core.state = CoreState.STOPPED
                    continue
                instr = self.program[core.pc]
                if self.enable_prints:
                    self.print_step(instr, core)
                core.pc += 1
                self.step(instr, core)
                if any(engine != "debug" for engine in instr.keys()):
                    has_non_debug = True
            if has_non_debug:
                self.cycle += 1

    def alu(self, core: Core, op: str, dest: int, a1: int, a2: int) -> None:
        a1 = core.scratch[a1]
        a2 = core.scratch[a2]
        match op:
            case "+":
                unwrapped_result = a1 + a2
            case "-":
                unwrapped_result = a1 - a2
            case "*":
                unwrapped_result = a1 * a2
            case "//":
                unwrapped_result = a1 // a2
            case "cdiv":
                unwrapped_result = cdiv(a1, a2)
            case "^":
                unwrapped_result = a1 ^ a2
            case "&":
                unwrapped_result = a1 & a2
            case "|":
                unwrapped_result = a1 | a2
            case "<<":
                unwrapped_result = a1 << a2
            case ">>":
                unwrapped_result = a1 >> a2
            case "%":
                unwrapped_result = a1 % a2
            case "<":
                unwrapped_result = int(a1 < a2)
            case "==":
                unwrapped_result = int(a1 == a2)
            case _:
                raise NotImplementedError(f"Unknown alu op {op}")
        unwrapped_result = unwrapped_result % (2**32)
        self.scratch_write[dest] = unwrapped_result

    def valu(self, core: Core, *slot: Any) -> None:
        match slot:
            case ("vbroadcast", dest, src):
                for lane in range(VLEN):
                    self.scratch_write[dest + lane] = core.scratch[src]
            case ("multiply_add", dest, a, b, c):
                for lane in range(VLEN):
                    product = (core.scratch[a + lane] * core.scratch[b + lane]) % (2**32)
                    self.scratch_write[dest + lane] = (product + core.scratch[c + lane]) % (
                        2**32
                    )
            case (op, dest, a1, a2):
                for lane in range(VLEN):
                    self.alu(core, op, dest + lane, a1 + lane, a2 + lane)
            case _:
                raise NotImplementedError(f"Unknown valu op {slot}")

    def load(self, core: Core, *slot: Any) -> None:
        match slot:
            case ("load", dest, addr):
                # print(dest, addr, core.scratch[addr])
                self.scratch_write[dest] = self.mem[core.scratch[addr]]
            case ("load_offset", dest, addr, offset):
                # Handy for treating vector dest and addr as a full block in the mini-compiler if you want
                self.scratch_write[dest + offset] = self.mem[
                    core.scratch[addr + offset]
                ]
            case ("vload", dest, addr):  # addr is a scalar
                addr = core.scratch[addr]
                for lane in range(VLEN):
                    self.scratch_write[dest + lane] = self.mem[addr + lane]
            case ("const", dest, val):
                self.scratch_write[dest] = (val) % (2**32)
            case _:
                raise NotImplementedError(f"Unknown load op {slot}")

    def store(self, core: Core, *slot: Any) -> None:
        match slot:
            case ("store", addr, src):
                addr = core.scratch[addr]
                self.mem_write[addr] = core.scratch[src]
            case ("vstore", addr, src):  # addr is a scalar
                addr = core.scratch[addr]
                for lane in range(VLEN):
                    self.mem_write[addr + lane] = core.scratch[src + lane]
            case _:
                raise NotImplementedError(f"Unknown store op {slot}")

    def flow(self, core: Core, *slot: Any) -> None:
        match slot:
            case ("select", dest, cond, a, b):
                self.scratch_write[dest] = (
                    core.scratch[a] if core.scratch[cond] != 0 else core.scratch[b]
                )
            case ("add_imm", dest, a, imm):
                self.scratch_write[dest] = (core.scratch[a] + imm) % (2**32)
            case ("vselect", dest, cond, a, b):
                for lane in range(VLEN):
                    self.scratch_write[dest + lane] = (
                        core.scratch[a + lane]
                        if core.scratch[cond + lane] != 0
                        else core.scratch[b + lane]
                    )
            case ("halt",):
                core.state = CoreState.STOPPED
            case ("pause",):
                if self.enable_pause:
                    core.state = CoreState.PAUSED
            case ("trace_write", val):
                core.trace_buf.append(core.scratch[val])
            case ("cond_jump", cond, addr):
                if core.scratch[cond] != 0:
                    core.pc = addr
            case ("cond_jump_rel", cond, offset):
                if core.scratch[cond] != 0:
                    core.pc += offset
            case ("jump", addr):
                core.pc = addr
            case ("jump_indirect", addr):
                core.pc = core.scratch[addr]
            case ("coreid", dest):
                self.scratch_write[dest] = core.id
            case _:
                raise NotImplementedError(f"Unknown flow op {slot}")

    def trace_post_step(self, instr: Instruction, core: Core) -> None:
        # You can add extra stuff to the trace if you want!
        assert self.trace is not None
        for addr, (name, length) in self.debug_info.scratch_map.items():
            if any((addr + offset) in self.scratch_write for offset in range(length)):
                val = str(core.scratch[addr : addr + length])
                val = val.replace("[", "").replace("]", "")
                self.trace.write(
                    f'{{"name": "{val}", "cat": "op", "ph": "X", "pid": {len(self.cores) + core.id}, "tid": {BASE_ADDR_TID + addr}, "ts": {self.cycle}, "dur": 1 }},\n'
                )

    def trace_slot(
        self, core: Core, slot: Slot, engine: Engine, slot_index: int
    ) -> None:
        assert self.trace is not None
        self.trace.write(
            f'{{"name": "{slot[0]}", "cat": "op", "ph": "X", "pid": {core.id}, "tid": {self.tids[(core.id, engine, slot_index)]}, "ts": {self.cycle}, "dur": 1, "args":{{"slot": "{str(slot)}", "named": "{str(self.rewrite_slot(slot))}" }} }},\n'
        )

    def step(self, instr: Instruction, core: Core) -> None:
        """
        Execute all the slots in each engine for a single instruction bundle
        """
        ENGINE_HANDLERS: dict[Engine, Callable[..., None]] = {
            "alu": self.alu,
            "valu": self.valu,
            "load": self.load,
            "store": self.store,
            "flow": self.flow,
        }
        self.scratch_write = {}
        self.mem_write = {}
        for engine, slots in instr.items():
            if engine == "debug":
                if not self.enable_debug:
                    continue
                for slot in slots:
                    if slot[0] == "compare":
                        loc, key = slot[1], slot[2]
                        expected = self.value_trace[key]
                        actual = core.scratch[loc]
                        assert actual == expected, (
                            f"{actual} != {expected} for {key} at pc={core.pc}"
                        )
                    elif slot[0] == "vcompare":
                        loc, keys = slot[1], slot[2]
                        expected = [self.value_trace[key] for key in keys]
                        actual = core.scratch[loc : loc + VLEN]
                        assert actual == expected, (
                            f"{actual} != {expected} for {keys} at pc={core.pc} loc={loc}"
                        )
                continue
            assert len(slots) <= SLOT_LIMITS[engine]
            for slot_index, slot in enumerate(slots):
                if self.trace is not None:
                    self.trace_slot(core, slot, engine, slot_index)
                ENGINE_HANDLERS[engine](core, *slot)
        for addr, val in self.scratch_write.items():
            core.scratch[addr] = val
        for addr, val in self.mem_write.items():
            self.mem[addr] = val

        if self.trace:
            self.trace_post_step(instr, core)

        del self.scratch_write
        del self.mem_write

    def __del__(self) -> None:
        if self.trace is not None:
            self.trace.write("]")
            self.trace.close()


@dataclass
class Tree:
    """
    An implicit perfect balanced binary tree with values on the nodes.
    """

    height: int
    values: list[int]

    @staticmethod
    def generate(height: int) -> Tree:
        n_nodes = 2 ** (height + 1) - 1
        values = [random.randint(0, 2**30 - 1) for _ in range(n_nodes)]
        return Tree(height, values)


@dataclass
class Input:
    """
    A batch of inputs, indices to nodes (starting as 0) and initial input
    values. We then iterate these for a specified number of rounds.
    """

    indices: list[int]
    values: list[int]
    rounds: int

    @staticmethod
    def generate(forest: Tree, batch_size: int, rounds: int) -> Input:
        indices = [0 for _ in range(batch_size)]
        values = [random.randint(0, 2**30 - 1) for _ in range(batch_size)]
        return Input(indices, values, rounds)


# a := (a `op1` const) `op3` (a `op2` const)
HASH_STAGES: list[tuple[str, int, str, str, int]] = [
    ("+", 0x7ED55D16, "+", "<<", 12),
    ("^", 0xC761C23C, "^", ">>", 19),
    ("+", 0x165667B1, "+", "<<", 5),
    ("+", 0xD3A2646C, "^", "<<", 9),
    ("+", 0xFD7046C5, "+", "<<", 3),
    ("^", 0xB55A4F09, "^", ">>", 16),
]


def myhash(value: int) -> int:
    """A simple 32-bit hash function"""
    binary_ops: dict[str, Callable[[int, int], int]] = {
        "+": lambda x, y: x + y,
        "^": lambda x, y: x ^ y,
        "<<": lambda x, y: x << y,
        ">>": lambda x, y: x >> y,
    }

    def wrap_to_uint32(x: int) -> int:
        return x % (2**32)

    for op1, val1, op2, op3, val3 in HASH_STAGES:
        value = wrap_to_uint32(
            binary_ops[op2](
                wrap_to_uint32(binary_ops[op1](value, val1)),
                wrap_to_uint32(binary_ops[op3](value, val3)),
            )
        )

    return value


def naive_kernel(forest: Tree, inp: Input) -> None:
    """
    Reference implementation of the kernel.

    A parallel tree traversal where at each node we set
    cur_inp_val = myhash(cur_inp_val ^ node_val)
    and then choose the left branch if cur_inp_val is even.
    If we reach the bottom of the tree we wrap around to the top.
    """
    for round in range(inp.rounds):
        for batch_i in range(len(inp.indices)):
            idx = inp.indices[batch_i]
            val = inp.values[batch_i]
            val = myhash(val ^ forest.values[idx])
            idx = 2 * idx + (1 if val % 2 == 0 else 2)
            idx = 0 if idx >= len(forest.values) else idx
            inp.values[batch_i] = val
            inp.indices[batch_i] = idx


def build_mem_image(forest: Tree, inp: Input) -> list[int]:  # TODO: see if we can play with this
    """
    Build a flat memory image of the problem.
    """
    header = 7
    extra_room = len(forest.values) + len(inp.indices) * 2 + VLEN * 2 + 32
    mem = [0] * (
        header + len(forest.values) + len(inp.indices) + len(inp.values) + extra_room
    )
    forest_values_p = header
    inp_indices_p = forest_values_p + len(forest.values)
    inp_values_p = inp_indices_p + len(inp.values)
    extra_room_p = inp_values_p + len(inp.values)

    mem[0] = inp.rounds
    mem[1] = len(forest.values)
    mem[2] = len(inp.indices)
    mem[3] = forest.height
    mem[4] = forest_values_p
    mem[5] = inp_indices_p
    mem[6] = inp_values_p
    mem[7] = extra_room_p

    mem[header:inp_indices_p] = forest.values
    mem[inp_indices_p:inp_values_p] = inp.indices
    mem[inp_values_p:] = inp.values
    return mem


def myhash_traced(
    value: int, value_trace: dict[Any, int], round: int, batch_i: int
) -> int:
    """A simple 32-bit hash function"""
    binary_ops: dict[str, Callable[[int, int], int]] = {
        "+": lambda x, y: x + y,
        "^": lambda x, y: x ^ y,
        "<<": lambda x, y: x << y,
        ">>": lambda x, y: x >> y,
    }

    def wrap_to_uint32(x: int) -> int:
        return x % (2**32)

    for hash_stage_idx, (op1, val1, op2, op3, val3) in enumerate(HASH_STAGES):
        value = wrap_to_uint32(
            binary_ops[op2](
                wrap_to_uint32(binary_ops[op1](value, val1)),
                wrap_to_uint32(binary_ops[op3](value, val3)),
            )
        )
        value_trace[(round, batch_i, "hash_stage", hash_stage_idx)] = value

    return value


def reference_kernel2(
    mem: list[int], value_trace: dict[Any, int] = {}
) -> Iterator[list[int]]:
    """
    Reference implementation of the kernel on a flat memory.
    """
    # This is the initial memory layout
    rounds = mem[0]
    n_nodes = mem[1]
    batch_size = mem[2]
    forest_height = mem[3]
    # Offsets into the memory which indices get added to
    forest_values_p = mem[4]
    inp_indices_p = mem[5]
    inp_values_p = mem[6]
    yield mem
    for round in range(rounds):
        for batch_i in range(batch_size):
            idx = mem[inp_indices_p + batch_i]
            value_trace[(round, batch_i, "idx")] = idx
            val = mem[inp_values_p + batch_i]
            value_trace[(round, batch_i, "val")] = val
            node_val = mem[forest_values_p + idx]
            value_trace[(round, batch_i, "node_val")] = node_val
            val = myhash_traced(val ^ node_val, value_trace, round, batch_i)
            value_trace[(round, batch_i, "hashed_val")] = val
            idx = 2 * idx + (1 if val % 2 == 0 else 2)
            value_trace[(round, batch_i, "next_idx")] = idx
            idx = 0 if idx >= n_nodes else idx
            value_trace[(round, batch_i, "wrapped_idx")] = idx
            mem[inp_values_p + batch_i] = val
            mem[inp_indices_p + batch_i] = idx
    # You can add new yields or move this around for debugging
    # as long as it's matched by pause instructions.
    # The submission tests evaluate only on final memory.
    yield mem
