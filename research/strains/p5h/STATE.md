# Strain P5-H — STOKE-style stochastic superoptimizer for the hash

status: SLICES COMPLETE (this funding round) — all campaigns NEGATIVE, no
finds at any size; infrastructure validated + resumable (fresh --seed per
slice). Full analysis: docs/agent-wiki/p5h-stoke-superoptimizer.md
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

CHECKPOINT campaign=t2 slots=12 threads=8 temp=2 opw=0.4 seed=11 secs=420.2 proposals=782663680 best_cost=183.800 best_err=179 best_nonnop=12 zero_hits=0 finds=0
  (t2 = round body myhash(x^y), free-shape MCMC. Best chain plateaued at
  err 179/1024 bits on its battery with all 12 ops live — sub-random but
  far from correct; no battery-perfect candidate ever appeared. The
  avalanche wall: free-shape MCMC cannot descend below ~180 bits.)
CHECKPOINT campaign=s9 slots=12 threads=8 temp=2 opw=0.4 seed=31 secs=480.2 proposals=11578351616 best_cost=336.000 best_err=336 best_nonnop=9 zero_hits=0 finds=0
CHECKPOINT campaign=s9 slots=12 threads=8 temp=4 opw=0.4 seed=32 secs=480.2 proposals=9308127232 best_cost=337.000 best_err=337 best_nonnop=9 zero_hits=0 finds=0
  (REAL sandwich9 target, MCMC+polish, midpoint cost. 20.9B proposals
  total; best 336 = the SAME plateau as the from-scratch planted gate
  (335) — a target KNOWN to contain a solution. The plateau level is
  therefore existence-blind: these negatives do NOT decide the shape.)
CHECKPOINT campaign=t1 slots=11 threads=8 temp=2 opw=0.4 seed=41 secs=480.2 proposals=1496383488 best_cost=4.400 best_err=0 best_nonnop=11 zero_hits=0 finds=0
  (t1 = myhash 11->10, transformation mode: cold chains HELD the correct
  11-op form all slice (best cost 4.4 = err 0 @ 11 ops) and explored its
  rewrite graph with window fusions + arbitrary-const moves. No correct
  10-op neighbor ever appeared — unlike the cal target, whose planted
  redundancy compressed within minutes. The real form shows no slack.)
CHECKPOINT campaign=t2 slots=13 threads=8 temp=3 opw=0.4 seed=12 secs=480.2 proposals=1290919936 best_cost=300.400 best_err=296 best_nonnop=11 zero_hits=0 finds=0
  (13 slots, hotter; zero battery-perfect <=11-op candidates.)
CHECKPOINT campaign=t3 slots=20 threads=8 temp=3 opw=0.4 seed=51 secs=420.2 proposals=529391616 best_cost=333.800 best_err=329 best_nonnop=12 zero_hits=0 finds=0
  (token slice only; the <=19-op composite space is beyond in-budget MCMC.)

## Verdict + next steps (if refunded)

- FIND: none, at any size, on any target. All negatives; evidence weights
  in the wiki doc (s9 negative is WEAK — the planted control proves this
  compute level cannot decide the shape; t1 transformation-mode negative
  is the strongest: the real 11-op form has no local slack).
- Next steps worth funding: (1) hour-scale s9 with basin-hopping +
  low-bit-lexicographic cost; (2) algebraic s9 decision (bit-serial
  lattice over the two sigma layers — z3 whole-formula timed out, but the
  odd-K + invertible-back-half reductions here shrink the unknowns to
  10 params and may make a custom solver feasible); (3) T2 window moves
  spanning 4-5 ops (current max 3) for deeper resegmentations.

## Coordinator pivot (received 2026-08-01, post-slice): sandwich9 is priority 1

New #1 target: the **sandwich9 shape** madd/sigma/madd/sigma/madd (sigma =
shr + xor-const + xor, 3 ops), 9 ops total, 10 free params (3 madd (K,C)
pairs, 2 xor masks, 2 shifts). P5-D CEGIS timed out at 424s; driver's
10,800s z3 rerun timed out at iter=0 — undecided, and z3 cannot decide it,
so stochastic evidence is all we will get. Plan: shape-RESTRICTED chains
(fixed skeleton, mutate only constants/shifts) with a MIDPOINT cost —
since all three multipliers must be odd (myhash is a bijection; an even K
makes the composition non-injective — small new lemma) the back half
m3/sigma2 is analytically invertible, so cost = hamming(fwd_mid(x),
bwd_mid(myhash(x))) which halves the avalanche depth on each side.
Calibration gate: recover a PLANTED sandwich9's params (s9cal) first.
Any find must be cross-checked against research/strains/p5d/STATE.md
section 4b (join-at-4 registry: xor/add closed negative, sub/rsub running).

### s9 calibration ledger (planted = S9_PLANTED in stoke.rs)

- gate 1 (from-scratch, temp 2.0, 240s, 5.45B proposals @22.7M/s): best err
  335/1024 bits, no recovery. From-scratch parameter recovery does not
  happen in minutes — negative s9 evidence will be weak regardless of
  further tuning.
- gate 2 (kicked-planted starts 2/6/12 kicks, temp 2.0, 240s, 5.32B): best
  25. **Autopsy: 8/10 params EXACT (all 3 multipliers, both shifts, C1,
  C3, M1); residual C2+2, M2^6 — a 3-coordinated-bitflip barrier.** MCMC
  locks params; Metropolis cannot cross the coupled low-bit endgame.
- gate 3 (temp 3.0, restart 5M, 300s, 8.27B): best 86, same lock pattern
  (8/10 exact), bigger residue. Hotter did not help.
- Added deterministic endgame POLISH (steepest-descent single bitflips ->
  all-pairs -> low-8-bit triples over C/M, to fixpoint) + double-kick move.
  **polishtest: the exact gate-2 barrier closes 26 -> 0 instantly.** Raw
  random kicks (whole-const replacements) are NOT polish-closable (1/10) —
  that part is MCMC's job by design.
- gate 4 (polish active, seed 24, 240s): best 324 (kick-variance: random
  kicks that replace whole constants make some gate instances hard).
- gate 5 (restart 1M, seed 25, 300s, 6.71B): best 87. **Combined verdict:
  machinery verified (planted 12->10 free-shape PASS, midpoint algebra
  exact, polish closes measured barriers) but full planted-s9 recovery in
  a 5-min slice is unreliable — the s9 landscape has deep coupled-residue
  local minima. Therefore: a FIND on the real target would be decisive;
  a NEGATIVE is weak evidence.**
