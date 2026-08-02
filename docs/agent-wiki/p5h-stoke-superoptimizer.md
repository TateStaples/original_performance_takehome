---
title: "P5-H: STOKE-style stochastic superoptimizer for the hash"
date: 2026-08-02
type: research
status: partial
task: "Build/run an MCMC superoptimizer over 9-11-op programs with arbitrary-constant moves; campaigns: sandwich9 (coordinator priority), myhash 11->10/9, round body <=10, 2-round <=19"
links: ["[[p5b-kf3-global-mitm]]", "[[p5d-fanout-suffix-search]]", "[[p3f-hash-10op-question]]"]
---

# P5-H: STOKE-style stochastic superoptimizer

Working record: `research/strains/p5h/STATE.md` (slice ledger, gate autopsies).
Binary: `rust_harness/src/bin/stoke.rs` (auto-discovered; Cargo.toml untouched).
Checkpoints: `tools/p5h_ckpt_{cal,t1,t2,t3,s9,s9cal}_s*.json`.

## What was built (all verified by planted controls)

1. **Free-shape STOKE** over straight-line programs: fixed slot count with
   Nop augmentation, regs r0..r9, ISA-exact ops (add sub mul xor and or shl
   shr lt eq madd; shift>=32 -> 0 per `isa.rs::AluOp::apply`), and — the
   coverage MITM never had — **12 mutable 32-bit constants per program**.
   Cost = battery hamming + 0.4*opcount; Metropolis with per-chain
   temperature ladder (x{.25,.5,1,2}); moves incl. **dst-pinned
   window-replace** (rewrite 2-3-op window with fewer ops, preserving the
   window's output register) — the move that crosses fusion plateaus.
   Transformation mode: cold chains start/restart at the real fused forms.
2. **Validation cascade** (no near-miss can be reported): chain battery
   (8 edge + 24 random, counterexample-injecting) -> 256 -> 65,536 ->
   ~200 edges incl. all shift boundaries -> 10^7 random. Only full passes
   are FINDs; a global validate-bar keeps the cascade off the hot path.
3. **sandwich9 shape-restricted engine** (coordinator's priority): skeleton
   madd/sigma/madd/sigma/madd, 10 params. Two exact accelerations:
   **odd-multiplier lemma** (myhash is a bijection => all three K odd,
   prunes 7/8 of K-space) and **midpoint cost** — K3 odd + sigma2 bijective
   make the back half analytically invertible, so cost compares at the
   middle madd (MITM-style, halves avalanche depth per side). Plus a
   deterministic **endgame polish** (single-bitflip steepest descent ->
   all-pairs -> low-8-bit triples over C/M params, to fixpoint).

## Calibration (gates before budget)

- **Free-shape gate PASS**: planted 12-op expansion of a 10-op function
  (stage0 madd re-expanded to shl+add+add) re-fused to a validated 10-op
  form in 150 s — after tuning (first attempt with single-op moves/flat
  temp 3.0 FAILED at an err~571 avalanche plateau; window-replace + cold
  seed chains + ladder fixed it). It independently discovered
  `madd(4097, x, r_uninit=0)` — using an uninitialized register as zero.
- **s9 planted gate: the decisive autopsy.** From kicked starts MCMC locks
  **8/10 params exactly** (all 3 multipliers, both shifts, C1/C3/M1) but
  stalls at err 25-87 on coupled low-bit residues (measured barrier:
  C2+2 with M2^6 — 3 coordinated bitflips). The polish closes exactly that
  barrier (26 -> 0 instantly in `s9polishtest`). But **from-scratch
  recovery of the planted sandwich9 never happened** in 4-5 min slices
  (best 335 of ~1024), and even kicked recovery is variance-dominated
  (kick kinds that replace whole constants are unrecoverable in-slice).

## Campaign results (all NEGATIVE; no find at any size)

| target | slices | proposals | best err (bits) | battery-perfect | validated finds |
|---|---|---|---|---|---|
| s9 = sandwich9 vs myhash | 2 x 8 min | 20.9 B | 336 | 0 | 0 |
| s9cal (planted control) | 5 gates | ~25 B | 25 (kicked) / 335 (scratch) | 0 | 0 |
| t1 = myhash 11->10 | 1 x 8 min | 1.50 B | 0 @ 11 ops (held); no 10-op neighbor | 0 at <=10 | 0 |
| t2 = round body <=11 | 2 slices | 2.07 B | 179 | 0 | 0 |
| t3 = 2-round <=19 | 1 x 7 min | (token slice) | — | 0 | 0 |
| cal (planted control) | 2 slices | 0.31 B | 0 | 2 | 2 (10 & 11 ops) |

**Sharpest single result**: in transformation mode the cold chains SAT ON
the correct real 11-op hash for a full slice, exploring its rewrite graph
with fusion moves and arbitrary constants, and no correct 10-op neighbor
ever appeared — while the same machinery compresses a planted-redundant
cousin within minutes. The real form has no local slack.

## Evidence calculus (what these negatives mean)

- The **s9 negative is WEAK by construction**: the real target's best-336
  plateau is statistically identical to the from-scratch planted gate's
  best-335 — on a target KNOWN to contain a solution. The plateau level is
  existence-blind. MCMC (like z3, which timed out twice) does NOT decide
  sandwich9. Deciding it needs either much larger compute (hours x many
  chains with basin-hopping) or algebra (e.g., bit-serial lattice/Groebner
  treatment of the two sigma layers).
- The **t1/t2 negatives are weak-moderate**: transformation-mode evidence
  says no SHORT rewrite path from the known form exists (window moves
  cover 1-3-op resegmentations with free constants); a 10-op form reachable
  only by global rewiring would be missed.
- **Coverage vs MITM** (why this tool class was still worth building):
  MCMC reaches arbitrary constants (MITM: 12-const pool), arbitrary
  fan-out wiring (MITM suffixes: chains only), and long-range reorderings
  natively; MITM's guarantee (exhaustiveness in-region) is what MCMC
  lacks. The two are complementary; both now report negative on 11->10/9.

## Resume protocol

`stoke <camp> --slots N --seconds S --threads 8 --temp T --restart-after R
--seed K --ckpt-dir .../tools` — chains are restart-based; fresh `--seed`
per slice is the resume mechanism; checkpoint JSONs carry best
program/params + all validated finds. Append CHECKPOINT lines to
`research/strains/p5h/STATE.md`. Never run detached.

## Dead ends and cautions

- Hamming cost through the full hash is an avalanche wall (~sub-random
  plateau, no gradient): do not fund flat-temperature single-op-move MCMC.
- opw must stay small (0.4) or correct programs melt at hot ladder rungs.
- Any future find MUST be cross-checked against the proven-empty registry
  in `research/strains/p5d/STATE.md` section 4b before being announced.
