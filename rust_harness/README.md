# rust_harness

A fast, strongly-typed development harness for the `perf_takehome.py` kernel
task (see `../docs/isa.md` and `../docs/problem.md`). **This does not
replace grading** — `python tests/submission_tests.py` is still the only
thing that decides your score, and `tests/` is still off-limits. This crate
exists to make the *iterate → check → repeat* loop while developing the
kernel algorithm much faster and much harder to get subtly wrong:

- **Faster**: the naive baseline's exact benchmark workload
  (`forest_height=10, batch_size=256, rounds=16`, 147,734 cycles) runs in
  ~12ms in release mode here, vs. ~0.7-1s in Python — see
  `tests/matches_python_baseline.rs` for the measured comparison. That's the
  difference between a debug loop you run constantly and one you avoid.
- **Harder to get wrong**: `isa.rs` models each engine's slots as its own
  Rust enum (`AluSlot`, `LoadSlot`, `FlowSlot`, ...) inside a `Bundle`
  struct, instead of Python's `dict[Engine, list[tuple]]`. You cannot put a
  `FlowSlot` in the `load` engine's list, cannot typo an opcode string, and
  cannot pass the wrong number of operands — the compiler catches all of
  that. `Scratch(u16)` is a newtype, not a raw integer, so a scratch address
  and a literal `u32` can no longer be swapped by accident. Slot-limit
  overflows (`isa::slot_limits`) fail at `Bundle::push_*` time with a
  `CapacityError`, not as an `assert` deep inside a 150,000-cycle run.

## Layout

| Path | What |
|---|---|
| `src/isa.rs` | Typed ISA: engines, opcodes, `Bundle`, slot limits. Port of `problem.py`'s instruction set — see `docs/isa.md`. |
| `src/machine.rs` | The simulator: staged bundle writes, cycle counting, pause/halt. Port of `Machine` in `problem.py`. |
| `src/problem.rs` | `myhash`/`HASH_STAGES`, `Tree`/`Input` generation (local PRNG, **not** Python-RNG-compatible — see below), `build_mem_image`, a pure-Rust reference implementation (`reference_run`). |
| `src/builder.rs` | Typed port of `KernelBuilder`, plus `build_kernel_naive` — a line-for-line port of the shipped Python baseline, cross-validated against Python in `tests/matches_python_baseline.rs`. **Fork this to optimize.** |
| `src/bridge.rs` | Converts a typed `Program` into the exact JSON shape `KernelBuilder.instrs` expects, for the Python bridge. |
| `src/bin/gen_kernel.rs` | CLI: builds a kernel and prints/writes the bridge JSON. |
| `src/bin/simulate.rs` | CLI: runs a kernel against a fixture and reports cycle count + correctness — the Rust-side equivalent of `perf_takehome.py Tests.test_kernel_cycles`. |
| `tests/fixtures/*.json` | Golden workload + expected output (+ optional per-step trace) exported from the real `problem.py` by `../tools/export_fixtures.py`. Checked in; regenerate only if `problem.py` itself changes. |
| `tests/*.rs` | Integration tests, including the trust-building one against the real baseline. |

## Why fixtures instead of matching Python's RNG

`Tree.generate`/`Input.generate` in `problem.py` use Python's `random`
module. Reimplementing Mersenne Twister to bit-match it wasn't worth it: for
Rust-only property tests (`problem.rs`'s own unit tests), any reasonably
random tree exercises the algorithm the same way, so a small local PRNG
(`problem::Rng`, SplitMix64) is enough. For anything that needs to be
*the actual graded workload* — the baseline cycle count, the real memory
image — `tools/export_fixtures.py` runs the real Python generation once and
dumps the input/output memory (and, for the `small` fixture, a full
per-step value trace) to JSON. `tests/matches_python_baseline.rs` loads that
and is the thing that actually proves this port is faithful.

## Workflow

1. **Iterate in Rust.** Edit `builder.rs` (or add new functions alongside
   `build_kernel_naive`). Run:
   ```
   cargo test small_fixture     # milliseconds; every debug::Compare checked
   cargo test                   # also re-checks the full benchmark workload
   ```
   A wrong intermediate value fails fast with the exact `(round, i, field)`
   key it diverged on, same as Python's own debug-compare harness but
   without the interpreter overhead.

2. **Check performance** without Python at all:
   ```
   cargo run --release --bin simulate -- tests/fixtures/baseline.json
   ```

3. **When you're happy, validate against the real grader.** This shells out
   to `gen_kernel`, loads its output into an actual `KernelBuilder.instrs`,
   and runs it through `tests/frozen_problem.py` — the literal simulator
   `tests/submission_tests.py` uses — without modifying anything in `tests/`:
   ```
   python ../tools/load_rust_kernel.py
   ```
   If that prints `CORRECT: True` and a cycle count you're happy with, wire
   the result into `perf_takehome.py`'s `KernelBuilder.build_kernel` (either
   by hand-porting the logic you landed on, or by having `build_kernel` call
   `tools.load_rust_kernel.gen_kernel_json` + `instrs_from_json` itself) and
   run the real `python tests/submission_tests.py` to confirm.

## Regenerating fixtures

Only needed if `problem.py` changes:
```
python ../tools/export_fixtures.py
```
