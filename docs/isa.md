# Machine ISA Specification

This documents the instruction set of the custom VLIW/SIMD simulator defined
in `problem.py` (`class Machine`). It's the target architecture for the
kernel you write in `perf_takehome.py`'s `KernelBuilder.build_kernel` — every
cycle counted by the benchmarks is a cycle of this simulator.

## 1. Overview

- **VLIW (Very Long Instruction Word):** each step of the program is one
  *instruction bundle* that can pack operations onto several independent
  **engines** simultaneously. Each engine can execute multiple **slots**
  (independent operations) in the same cycle, up to a per-engine limit.
- **SIMD:** in addition to scalar operations, several engines have vector
  variants that operate on a fixed-width vector of `VLEN` elements at once.
- **Single core:** `N_CORES = 1`. The simulator supports multiple cores
  (`Core.id`, `coreid` op, per-core `pc`/state/scratch) as a holdover from an
  older multi-core version of this take-home, but this version pins
  `N_CORES = 1` — multicore is intentionally disabled.
- All values are 32-bit words; every arithmetic result is taken `mod 2**32`.

## 2. Execution model

A **program** is a Python list of *instruction bundles*. Each bundle is a
dict mapping an engine name to a list of *slots* for that engine this cycle:

```python
{"valu": [("*", 4, 0, 0), ("+", 8, 4, 0)], "load": [("load", 16, 17)]}
```

Each cycle, `Machine.step` executes **every filled slot on every engine** in
the bundle. Two ordering rules matter:

1. **Reads see the start-of-cycle state.** All slots read from `core.scratch`
   as it was before the cycle began; writes are buffered in
   `scratch_write` / `mem_write` and only applied to `core.scratch` / `self.mem`
   after every slot in the bundle has executed. So two slots in the same
   bundle can, e.g., swap two scratch values or all read the same
   soon-to-be-overwritten register safely — there's no intra-bundle hazard.
2. **The program counter advances once per bundle**, regardless of how many
   engines/slots fired. `core.pc` increments before the bundle executes, so
   `flow` jump ops override that increment for the *next* bundle.

**Cycle counting:** `self.cycle` increments once per bundle **only if the
bundle contains at least one non-`debug` slot**. A bundle that's pure
`debug` (e.g. a `comment`) costs zero cycles. This is what the benchmark
numbers (e.g. `CYCLES: 147734`) actually count.

**Core lifecycle** (`CoreState`): `RUNNING → PAUSED` (on a `("pause",)` flow
op, only if `machine.enable_pause` is set) `→ RUNNING` (when `Machine.run()`
is called again) `→ STOPPED` (on `("halt",)`, or when `pc` runs past the end
of the program). `Machine.run()` resumes any paused cores and then executes
bundles until every core is `STOPPED`.

## 3. Storage

| Space | Size | Notes |
|---|---|---|
| **Memory** (`self.mem`) | problem-dependent, flat `list[int]` | Shared across cores. Holds the input, is mutated in place, and the graded result is read back out of it at the end. |
| **Scratch** (`core.scratch`) | `SCRATCH_SIZE = 1536` words, per core | Plays the role of registers *and* addressable constant/working memory — there is no separate register file. `KernelBuilder.alloc_scratch` hands out addresses into this space by bumping a pointer; it's your job not to run past `SCRATCH_SIZE`. |

Both are flat arrays of 32-bit words (mod 2**32); there's no separate
address space for "registers" vs "RAM" scratch — everything not in `self.mem`
lives in `core.scratch`.

## 4. Addressing convention

Within a slot tuple, **every number is a scratch address** (an index into
`core.scratch`) — the engines dereference it via `core.scratch[x]` — **except**:

- `load`'s `("const", dest, val)` — `val` is a literal, not an address.
- `flow`'s `("add_imm", dest, a, imm)` — `imm` is a literal.
- `flow`'s jump target `addr` in `("jump", addr)` / `("cond_jump", cond, addr)`
  / `("cond_jump_rel", cond, offset)` — these are program-counter values /
  offsets, not scratch addresses (`jump_indirect` is the exception *within*
  the exception: its `addr` operand *is* a scratch address, holding the jump
  target).

Except for `store` (whose first operand is the memory address, not a
destination) and a couple of `flow` ops, **the first operand of a slot is
its destination.**

## 5. Engines & slot limits

| Engine | Slots/cycle (`SLOT_LIMITS`) | Purpose |
|---|---|---|
| `alu` | 12 | Scalar integer arithmetic/logic/compare |
| `valu` | 6 | Vector (`VLEN`-wide) arithmetic/logic/compare, broadcast, fused multiply-add |
| `load` | 2 | Scalar/vector memory reads, and loading constants |
| `store` | 2 | Scalar/vector memory writes |
| `flow` | 1 | Control flow, select/mux, pause/halt, misc |
| `debug` | 64 | Assertions against a reference trace + comments; **free** (doesn't consume a cycle) and ignored entirely by the submission grader |

`VLEN = 8` — the width of every vector op.

A bundle that fills more slots on an engine than its limit fails an assertion
(`assert len(slots) <= SLOT_LIMITS[name]`), so packing is bounded but real:
in principle a single cycle could retire 12 `alu` + 6×8 `valu` + 2 `load` +
2 `store` + 1 `flow` ops simultaneously.

## 6. Per-engine op reference

### `alu` — scalar ALU

Slot shape: `(op, dest, a1, a2)` → `scratch[dest] = (scratch[a1] OP scratch[a2]) % 2**32`

| `op` | Semantics |
|---|---|
| `+` `-` `*` | add / subtract / multiply |
| `//` | floor divide (`a1 // a2`) |
| `cdiv` | ceiling divide, `(a1 + a2 - 1) // a2` |
| `^` `&` `\|` | bitwise xor / and / or |
| `<<` `>>` | bitwise shift left / right |
| `%` | modulo |
| `<` | `1` if `a1 < a2` else `0` |
| `==` | `1` if `a1 == a2` else `0` |

### `valu` — vector ALU (8-wide)

| Slot | Semantics |
|---|---|
| `(op, dest, a1, a2)` | for `i` in `0..VLEN`: `scratch[dest+i] = alu(op, scratch[a1+i], scratch[a2+i])` — any scalar `alu` op, applied lanewise to 8 consecutive scratch slots |
| `("vbroadcast", dest, src)` | `scratch[dest+i] = scratch[src]` for all 8 lanes — splat a scalar into a vector |
| `("multiply_add", dest, a, b, c)` | `scratch[dest+i] = (scratch[a+i]*scratch[b+i] + scratch[c+i]) % 2**32` — fused multiply-add, 8-wide |

Vector operands must occupy `VLEN` **contiguous** scratch slots starting at
the given address — there's no gather/strided vector access.

### `load` — reads from memory / constants

| Slot | Semantics |
|---|---|
| `("load", dest, addr)` | `scratch[dest] = mem[scratch[addr]]` |
| `("load_offset", dest, addr, offset)` | `scratch[dest+offset] = mem[scratch[addr+offset]]` — convenient when `dest`/`addr` are the base of a block you're indexing manually |
| `("vload", dest, addr)` | `scratch[dest+i] = mem[scratch[addr]+i]` for `i` in `0..VLEN` — 8 contiguous words, `addr` is a **scalar** base address |
| `("const", dest, val)` | `scratch[dest] = val % 2**32` — the only way to get a literal into scratch |

### `store` — writes to memory

| Slot | Semantics |
|---|---|
| `("store", addr, src)` | `mem[scratch[addr]] = scratch[src]` |
| `("vstore", addr, src)` | `mem[scratch[addr]+i] = scratch[src+i]` for `i` in `0..VLEN` — 8 contiguous words, `addr` is a **scalar** base address |

### `flow` — control flow, select, misc

| Slot | Semantics |
|---|---|
| `("select", dest, cond, a, b)` | `scratch[dest] = scratch[a] if scratch[cond] != 0 else scratch[b]` — branchless scalar mux |
| `("vselect", dest, cond, a, b)` | same, 8-wide lanewise |
| `("add_imm", dest, a, imm)` | `scratch[dest] = (scratch[a] + imm) % 2**32` — add a literal without a separate `const` |
| `("jump", addr)` | `pc = addr` (unconditional) |
| `("jump_indirect", addr)` | `pc = scratch[addr]` (computed jump — `addr` here *is* a scratch address) |
| `("cond_jump", cond, addr)` | `pc = addr` if `scratch[cond] != 0` |
| `("cond_jump_rel", cond, offset)` | `pc += offset` if `scratch[cond] != 0` |
| `("halt",)` | stop this core |
| `("pause",)` | pause this core (if `machine.enable_pause`) — used to sync with the reference kernel's `yield` points for step-by-step debugging; the submission grader runs with pausing disabled |
| `("trace_write", val)` | append `scratch[val]` to this core's `trace_buf` |
| `("coreid", dest)` | `scratch[dest] = core.id` (multicore leftover; always `0` here) |

Only **one** `flow` slot is allowed per cycle — it's the tightest engine, so
batching multiple `select`/branch decisions into one cycle isn't possible;
`vselect` is the way to get more branching decisions done per flow-slot.

### `debug` — assertions and annotations (free, ignored when grading)

Not a real compute engine — slots here never advance the cycle counter (see
[§2](#2-execution-model)). `tests/frozen_problem.py`'s `Machine` still knows
how to execute `debug` slots, but `tests/submission_tests.py` runs with
`machine.enable_debug = False`, which skips them entirely. Useful while
developing:

| Slot | Semantics |
|---|---|
| `("compare", loc, key)` | assert `scratch[loc] == value_trace[key]` against a reference value recorded while running `reference_kernel2` |
| `("vcompare", loc, keys)` | same, 8-wide: assert `scratch[loc:loc+VLEN] == [value_trace[k] for k in keys]` |
| `("comment", text)` | no-op; shows up as a label in the Perfetto/trace viewer |

## 7. Tracing & debug info

`Machine(..., trace=True)` emits a Chrome Trace Event Format `trace.json`
(one JSON object per line, wrapped in `[...]`) recording, per cycle, which
slot on which engine fired and (via `DebugInfo.scratch_map`) human-readable
names for named scratch addresses. This is purely a debugging aid — it has
no effect on cycle counts or correctness, and is unrelated to the ISA itself.
See `watch_trace.py`/`watch_trace.html` for the intended viewer (`ui.perfetto.dev`).

## 8. Reference: constants

```python
SLOT_LIMITS = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1, "debug": 64}
VLEN = 8
N_CORES = 1
SCRATCH_SIZE = 1536
```
