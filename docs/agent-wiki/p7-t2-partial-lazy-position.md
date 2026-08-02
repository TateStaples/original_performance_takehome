---
title: P7 milestone 1 — T2-partial (lazy position accumulator) + T1 difference tables
date: 2026-08-02
type: change
status: awaiting-review
task: Implement milestone 1 of the C1*-class design in dev.py behind default-OFF flags — T2-partial (retained-parity serving at the ring-coverage cap) + T1 (difference-table interiors) — re-mine the ring plan for the new stream, run the gates, and report measured cycles.
links: ["[[p3d-l4-final-round-service]]", "[[INDEX]]"]
---

# P7 milestone 1: T2-partial + T1

**Headline: implemented, gates green, and the mechanism does not pay.**
T2-partial measures **1006 → 1008 (best mode) / 1011**, with a census
delta of **−2 valu vec-ops out of 5,966**. T1 was not built: it is already
implemented at setup everywhere it applies, and its 8-op residue needs 64
scratch words against 3 free. The ring re-mine on the new stream finds
**0** new rings, closing P3-E §1.4's "st-deletion returns ~11 rings"
route. Full record with all tables: `research/strains/p7/STATE.md`.

## What changed

**`dev.py`** (only file modified):

* `build_kernel_scheduled(...)` gains one kwarg,
  `lazy_position_exit: bool | str = False`, with modes `False` (inert) /
  `True` (elide upkeep, Horner at the exit) / `"early"` (Horner at the top
  of the exit round) / `"dead-only"` (restrict to group-epochs whose
  accumulator has no reader at all).
* `horner_position(state_vec_, ring_, nbits)` added beside
  `fold_position`. Rebuilds the packed position `p = b0…b_{nbits−1}` from
  the retained parity vectors by Horner. Spellings are matched op-for-op
  to the upkeep path (plain `madd` for the seed step, `fold_position` for
  the rest) so the alu-offload race is preserved and the experiment
  isolates the emission point rather than the engine choice.
* `lazy_position_ok(epoch, g)` added after the ring-plan builder — the
  eligibility predicate.
* Four guarded call sites: the L2 ringed seed madd, the L3 ringed
  `fold_position`, the exit conversion (`is_served_without_gather(r, g)`
  branch), and the `dffold` fallback inside the b3-last L4 path (which
  reads `st` for its masks and therefore has to materialise the position
  itself).

No changes to `tests/`, `problem.py`, `perf_takehome.py`, or the
`build_kernel()` dispatch. The `b3l` assert, `l4_gmin`'s epoch split
(G-38) and the adaptive engine races (G-36) are untouched.

## Decisions & assumptions

* **Eligibility excludes served-L4-with-an-exit group-epochs.** A served
  L4 round consumes the newest parity `b3` out of `nv` (the W-folds
  overwrite it), so a 4-bit exit cannot be rebuilt from the 3-slot ring.
  Those cases are also net-zero on ops (see below), so nothing is lost.
* **Horner spellings deliberately mirror the upkeep spellings.** The first
  version used plain `madd` throughout and measured 1010/1011 partly
  because `fold_position`'s `race_idx_madd` alu-offload was lost. Matching
  the spellings removed that confound; the result is the same conclusion
  with a clean attribution.
* **`b3l_setup_diff_tables` was added to the signature and then removed**
  rather than shipped unimplemented — T1 turned out to be unbuildable at
  this configuration (below), and a dead flag is worse than none.
* **Ring plan is NOT re-mined into the config**, because the re-mine
  returns the empty set. The existing 40-ring plan audits clean on the new
  stream (`OK over 40 rings`), so it is not stale.

## Why the model was wrong (the load-bearing finding)

P3-A's T2 priced 232 removed sites against +2 vec-ops × 35 exits. But
building the position by Horner at the exit costs `d−1` madds for a
`d`-bit position — **exactly the number of steady folds it replaces**.
T2 deletes ops only where the accumulator is *never read*.

At the real shape (`period` 11, `l4_gmin=(6,31)`) there are **63 exits,
not 35**, and exactly **one** group-epoch (g=31, L4 served at round 15,
the last round) has no reader. P3-A's 35 assumed L4 service concentrated
in epoch 1 / round 15 — **the exact configuration G-38 measured as
negative**. T2's value and G-38's finding are in direct opposition.

The upkeep-site arithmetic reproduces P3-A's own measured census exactly
(40 `pos.seed` = the 40 funded rings; 114 `pos.fold` = 24 non-ringed L2 +
64 L3 + 26 served-L4-epoch-0; 154 total), which is what makes the
correction trustworthy.

`cond.mask`'s 78 sites are a *ring-coverage* prize (they live on the 24
uncovered group-epochs), not a T2 prize — and §3.3 of the strain doc shows
T2 buys no coverage.

## How it was verified

* `python3 perf_takehome.py Tests.test_kernel_cycles` → `CYCLES: 1006`, `OK`.
* Flag-OFF bundle stream bit-identical on 3 configs (sha256 over the
  bundle list + slot counts + `scratch_next_addr`): 1006-ring
  `8a6f08bd3101451a`, ring-free `5a748c89ff01b3b1`, pools(15,4)
  `7b8f518f6e807e30` — default and explicit-OFF match on all three.
* Flag-ON value-trace compare (`debug_compares=True`, dev's `vcompare`
  against `reference_kernel2`'s trace), 10 seeds: **10/10** for both
  `lazy-exit` and `lazy-early`; final `inp_values` equal to reference on
  every seed; frozen grader `correct: true` at every measured point.
* Cycles, 3 profiles × 4 modes (frozen grader, seed 1):

  | profile | off | dead-only | exit | early |
  |---|---|---|---|---|
  | mainline, 40 rings, gmin (6,31) | **1006** | 1008 | 1011 | 1008 |
  | structural rings only | **1017** | 1017 | 1022 | 1017 |
  | rings + pools (15,4) | 1036 | 1036 | **1034** | 1036 |

* Ring re-mine (`tools/audit_ring_windows.py` driven on the real 1006
  stream): baseline / `early` / `exit` all report `OK over 40 rings`,
  **0 new rings**, and a byte-identical 24-entry unfunded set.

## Known limitations / follow-ups

1. `parity_ring_extras=(0,1)` collides with the mined plan
   (`AssertionError: parity_ring_plan entry (0,13) already ring-funded`).
   Pre-existing; blocks probing coverage above 40 by that route.
2. `early`/`dead-only` lower the valu floor to 994 yet realize 1008 —
   the 1006 emission order was mined for the baseline stream and the
   relocation desynchronises it (regret 11 → 14). A full emission-order
   re-mine was out of budget; upside is bounded by the census delta
   (≤1 cycle below 1006).
3. `lazy_position_exit` is silently inert with no ring coverage. A
   reviewer may prefer an explicit assert.
4. Untouched and still unpriced against measurement: T3 (`add_imm`→alu),
   serve-profile re-optimisation, emission re-mine, with-idx tail.
