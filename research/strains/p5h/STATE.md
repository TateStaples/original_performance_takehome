# Strain P5-H — STOKE-style stochastic superoptimizer for the hash

status: IN PROGRESS (calibration phase)
binary: `rust_harness/src/bin/stoke.rs` (new, auto-discovered by cargo;
Cargo.toml untouched)

## Why this search class (from P5-G)

The 904/889 frontier was reached by automated agent-search harnesses, not
human derivation. If an effective-k<=9.5 hash form exists it was found
MECHANICALLY, and the class that finds such things is MCMC/stochastic
superoptimization. Our exhaustive MITM has two named blind spots MCMC covers
natively: fan-out shapes (P5-D enumerates separately) and ARBITRARY
CONSTANTS — every MITM to date used a 12-const structured pool; any form
with a magic constant outside it is invisible to all prior coverage.

## Search design

- Programs: fixed slot count (Nop-augmented, so shorter forms emerge inside
  a slot budget), regs r0..r9 (r0..r_{ni-1} = inputs, dst restricted to
  non-input regs — no expressiveness loss at this reg count), 12 MUTABLE
  32-bit constants per program. Output = result of last non-nop op.
- Opcodes: add sub mul xor and or shl shr lt eq madd (ISA-exact semantics
  incl. shift>=32 -> 0, mirrors isa.rs::AluOp::apply). div/mod excluded
  (P3-F), cmpsel excluded (G-24).
- Cost = hamming-error over battery (bits) + 0.4 * nonnop-op-count.
- Moves: opcode flip 3/19ths (scaled), operand flip, const perturbation
  (bitflip / random32 / +-1 / <<1 >>1 / INTERESTING table), swap, dst flip,
  nop toggle, full replace, and **window-replace** (rewrite a 2-3-op window
  with FEWER random madd/xor-heavy ops, dst-pinned to the window's output
  register) — the coordinated move that crosses fusion plateaus.
- Metropolis per-chain with a temperature LADDER (base*{.25,.5,1,2} by
  chain id%4); chains id%4==0 are coldest and start/restart at the exact
  real form (transformation mode); id%4==3 hottest incl. random starts.
- Chain-local battery: 8 edge + 24 random vectors; failed cascade
  candidates inject their counterexample into the chain battery (cap 96).
- Validation cascade: battery-perfect -> 256 -> 65,536 -> ~200 edge
  (incl all shift boundaries 2^k, 2^k-1, ~2^k) -> 10^7 random. Only a
  full-cascade pass is a FIND. A global validate-bar drops to each find's
  size so only strictly smaller candidates pay the cascade afterwards.
- Seeds: the REAL forms (T1: fused 11-op myhash; T2: xor + 11 = 12;
  T3: 24-op double round) with kicks/truncation; plus random programs.

## Calibration protocol (gate before real budget)

Planted target: the 10-op function sigma16(stage4(f23(stage1(stage0(x)))))
(full fused hash minus stage5's const xor). Seed: 12-op program with
stage0's madd re-expanded to shl+add+add. Gate: MCMC must re-fuse to a
validated 10-op program in minutes.

### Calibration ledger

- cal slice 0 (pre-tuning, single-op moves only, temp 3.0 flat, 120s,
  78.8M proposals): **FAIL** — stuck at err ~571 bits (sub-random plateau
  ~ avalanche wall), zero battery-perfect candidates. Diagnosis: hamming
  gives no gradient through the hash's avalanche; single-op moves cannot
  cross the fusion plateau; temp 3.0 melts correct programs.
- Tuning: added window-replace (dst-pinned), temp ladder, exact-seed cold
  chains, validate gating. Cal seed keeps 4097 in a spare const slot (real
  campaigns' pools contain all their madd multipliers; calibration must not
  be strictly harder in the const dimension than the task it calibrates).
- cal slice 1 (150s, temp 2.0 ladder, seed 2): **PARTIAL PASS** — two
  VALIDATED 11-op forms at 10,065,992 vectors each, including re-fusion
  via `madd(4097, x, r_uninit=0)` + `add(C)` (also discovered the
  uninitialized-register-as-zero trick unprompted). 12->11 fusion works;
  11->10 (fold add's C into the madd addend) not yet landed in-slice.
  Bug found+fixed: ckpt JSON path was cwd-relative (silently unwritten);
  validate-bar added.
- cal slice 2 (seed 3): **PASS.** Validated 10-op form found at t=150s
  (stopped at --max-ops gate), via the 11-op intermediate. 227.5M proposals,
  ~1.5M/s, zero_hits=2 finds=2, both at 10,065,992 vectors.
  `CHECKPOINT campaign=cal slots=12 threads=8 temp=2 opw=0.4 seed=3
  secs=150.1 proposals=227500032 best_cost=4.000 best_err=0 best_nonnop=10
  zero_hits=2 finds=2`
  **CALIBRATION GATE CLEARED — machinery verified end-to-end (planted
  compression recovered, cascade validation, checkpointing).**

## Run protocol

Foreground slices <= 8 min, never detached. Slice command:

```
rust_harness/target/release/stoke {cal|t1|t2|t3} \
  --slots N --seconds S --threads 8 --temp 2.0 --opw 0.4 \
  --max-ops <win-size> --validate-max <interesting-size> --seed K \
  --ckpt-dir /Users/tatestaples/Code/original_performance_takehome/tools
```

Checkpoints: tools/p5h_ckpt_<camp>_s<slots>.json (best program + cost +
all validated finds with listings). Resume = rerun with a fresh --seed
(chains are restart-based; no long-lived RNG state worth preserving).
Append a CHECKPOINT line per slice below.

## Campaign ledger (append CHECKPOINT lines)

(cal lines above; t1/t2/t3 pending calibration gate)
