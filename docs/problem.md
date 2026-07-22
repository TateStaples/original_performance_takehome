# Problem Statement

Anthropic's Original Performance Take-Home. You optimize a kernel that runs
on the custom VLIW/SIMD simulator described in [`isa.md`](./isa.md); your
score is the number of simulated clock cycles it takes to run one fixed
workload correctly.

## 1. The task

> Optimize the kernel (in `KernelBuilder.build_kernel`) as much as possible
> in the available time, as measured by `test_kernel_cycles` on a frozen
> separate copy of the simulator.

Concretely: rewrite `KernelBuilder.build_kernel` in `perf_takehome.py` so
that it emits a **program** (a list of instruction bundles, per `isa.md`)
that computes the correct output for the workload below, in as few cycles as
possible. Nothing outside `perf_takehome.py` should need to change, and
`tests/` must not be modified (see [§6](#6-rules--anti-cheating)).

## 2. The workload

### 2.1 The tree

`Tree.generate(height)` builds an **implicit perfect binary tree**: a flat
array of `2**(height+1) - 1` random 30-bit node values, indexed like a binary
heap — node `i`'s children live at `2*i+1` and `2*i+2`. The benchmark uses
`height=10` → 2047 nodes.

### 2.2 The batch

`Input.generate(forest, batch_size, rounds)` builds `batch_size` independent
"walkers": each starts at the tree's root (`indices[j] = 0`) with its own
random 30-bit starting value (`values[j]`). The benchmark uses
`batch_size=256`, `rounds=16`.

### 2.3 The per-round update (`reference_kernel` / `reference_kernel2`)

For `rounds` rounds, for every walker `j` in the batch, independently:

```python
node_val = tree.values[idx]
val = myhash(val ^ node_val)
idx = 2*idx + (1 if val % 2 == 0 else 2)   # step to left or right child
idx = 0 if idx >= len(tree.values) else idx  # past the last row -> back to root
```

i.e. each walker does a pseudo-random descent of the tree: mix its running
value with the value at its current node, hash the result, and let the
hash's parity choose the left or right child for next round. Falling off the
bottom of the tree wraps back to the root. After all rounds, the graded
output is the final `indices` and `values` arrays.

There are two equivalent reference implementations in `problem.py`:
`reference_kernel` (operates on `Tree`/`Input` objects directly) and
`reference_kernel2` (operates on the flat memory image described below, and
is what your kernel is actually checked against — it also `yield`s at the
start and end so a step-by-step harness can pause your kernel at matching
points via the `("pause",)` flow op).

### 2.4 `myhash`

A fixed 6-stage, non-cryptographic 32-bit integer mixing function
(`HASH_STAGES` in `problem.py`), each stage of the form:

```
a = (a op1 val1) op2 (a op3 val3)     # e.g. (a + 0x7ED55D16) ^ (a << 12)
```

alternating `+`/`^` with shifts against fixed constants, all mod `2**32`.
It's deliberately just an avalanche/bit-mixing function (no data dependence
between hash stages beyond `a` itself) — enough that a walker's path through
the tree is effectively unpredictable without actually computing it, but
each stage is cheap scalar/vector-friendly arithmetic.

### 2.5 Memory layout (`build_mem_image`)

Your kernel receives the whole problem as one flat `list[int]` memory image.
The first 8 words are a header of pointers/sizes, followed by the tree
values, then the indices array, then the values array, then some scratch
room:

| Offset | Meaning |
|---|---|
| `mem[0]` | `rounds` |
| `mem[1]` | `n_nodes` (length of the tree's values array) |
| `mem[2]` | `batch_size` |
| `mem[3]` | `forest_height` |
| `mem[4]` | `forest_values_p` — pointer to the tree values array |
| `mem[5]` | `inp_indices_p` — pointer to the walkers' indices array |
| `mem[6]` | `inp_values_p` — pointer to the walkers' values array |
| `mem[7]` | `extra_room` — pointer past all the above, free scratch space in memory |

`KernelBuilder.build_kernel`'s very first job is reading these 7 header
values (`rounds` through `inp_values_p`) out of memory into named scratch
slots, since it only knows their *addresses* (`0`..`6`) at build time, not
their values.

## 3. What you're given (`KernelBuilder`, in `perf_takehome.py`)

`KernelBuilder` is a minimal, un-optimized assembler-by-hand:

- `alloc_scratch(name, length)` — bumps a pointer to hand out fresh scratch
  addresses (optionally named, for debugging), asserting you stay under
  `SCRATCH_SIZE`.
- `scratch_const(val, name)` — memoized: emits a `("load", ("const", ...))`
  bundle the first time a literal is needed and reuses the same scratch slot
  for every later use of that value. Note this emits the constant load
  **immediately**, at Python build-time, the first time your code *asks* for
  that constant — not in the position it's logically first *used* in the
  emitted program. In the shipped baseline this means dozens of constants
  used deep inside the round/batch loop all end up hoisted to the very front
  of the program.
- `build_hash(...)` — emits the 6 `myhash` stages as scalar `alu` ops (plus
  matching `debug` `compare`s against the reference trace).
- `build(slots)` — the only "instruction scheduler" provided: it puts
  **one slot in its own bundle**, i.e. no packing across engines and no
  packing multiple ops onto the same engine. This is the main thing to
  improve — see [`isa.md` §5](./isa.md#5-engines--slot-limits) for how much
  headroom each engine has per cycle.
- `build_kernel(forest_height, n_nodes, batch_size, rounds)` — the target of
  your rewrite. As shipped, it's a direct scalar transliteration of
  §2.3/2.4/2.5 above: read the header, then for every `(round, i)` pair,
  compute addresses with `alu`, `load`/`store` one word at a time, and run
  the hash and branch logic entirely in scalar ops — never touching `valu`,
  never packing more than one op per cycle.

Every value written to a named scratch slot is checked against the reference
trace via an interleaved `("debug", ("compare", ...))` bundle — free during
grading, but a live correctness check while you develop (see §5).

## 4. What "the kernel" must preserve

Your rewritten `build_kernel` must still, for the given
`(forest_height, n_nodes, batch_size, rounds)`:

1. Emit a program that a `Machine` can run to leave the correct final
   `indices`/`values` arrays in memory at `inp_indices_p`/`inp_values_p`
   (checked by value, not by which instructions you used to get there).
2. Start with a `("flow", ("pause",))` matching `reference_kernel2`'s first
   `yield`, and end with one matching its second — `perf_takehome.py`'s own
   test harness (not the submission grader) uses these to step the machine
   in lockstep with the reference and catch divergences early via the
   `debug`/`compare` trace. (The submission grader ignores pauses and debug
   entirely, so this only matters for your own debugging loop.)
3. Stay within `SCRATCH_SIZE = 1536` scratch words and the engine slot
   limits in `isa.md`.

Anything else — instruction order, algorithm, use of `valu`/vectorization,
how many bundles you emit, whether you keep using `KernelBuilder.build` at
all — is entirely up to you.

## 5. Testing & debugging loop

```
python perf_takehome.py                              # run everything in perf_takehome.py
python perf_takehome.py Tests.test_kernel_cycles      # just the timed run (forest_height=10, rounds=16, batch_size=256)
python perf_takehome.py Tests.test_kernel_trace       # same, but also writes trace.json
python watch_trace.py                                 # serve a hot-reloading Perfetto view of trace.json
```

`test_kernel_cycles`/`test_kernel_trace` run your kernel step-by-step
against `reference_kernel2`, pausing at both yields and asserting equality
of the relevant memory ranges each round — and every `debug`/`compare`
bundle your kernel emits is checked live, so a wrong intermediate value
fails fast with the exact `(round, i, field)` it diverged on, rather than
only failing the final memory comparison.

## 6. Rules & anti-cheating

Validate with **`python tests/submission_tests.py`** — this is the actual
grader, running against `tests/frozen_problem.py` (a frozen copy of the
simulator) so you can't improve your score by changing simulator semantics.

- **`tests/` must be unchanged.** Before submitting: `git diff origin/main tests/`
  should print nothing.
- **`N_CORES = 1` is intentional**, not a bug — this version of the
  take-home has multicore disabled. Do not "fix" it.
- Solutions under ~1300 cycles submitted without care have historically
  turned out to be from an agent quietly weakening the test harness rather
  than actually optimizing the kernel — don't do that, and watch for an
  agent doing it to you.

### Benchmarks (cycles; lower is better)

| Score | Who |
|---|---|
| 147,734 | This repo's starting baseline (`BASELINE` in `perf_takehome.py`) |
| 18,532 | Starting point given in the (harder, 2-hour) take-home this repo is based on |
| 2,164 | Claude Opus 4, many hours in a test-time compute harness |
| 1,790 | Claude Opus 4.5, casual Claude Code session (~best human, 2 hours) |
| 1,579 | Claude Opus 4.5, 2 hours in Anthropic's test-time compute harness |
| 1,548 | Claude Sonnet 4.5, many more than 2 hours of test-time compute |
| 1,487 | Claude Opus 4.5, 11.5 hours in the harness |
| 1,363 | Claude Opus 4.5, improved test-time compute harness |

`tests/submission_tests.py`'s `SpeedTests` encode this table directly as
pass/fail thresholds so progress shows up as a pass rate. Beating 1,487
cycles is the bar the README suggests is worth emailing Anthropic about.
