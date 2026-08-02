---
title: P7-TAR — tail-aware ring derivation; ringed with-idx exists at 1034 (was "structurally incompatible")
date: 2026-08-02
type: change
status: awaiting-review
task: Make the parity rings coexist with the with-idx tail (`store_final_indices`). Land a donor-liveness assertion first, then re-derive the ring map tail-aware and measure whatever coverage survives.
links: ["[[p7-polish-stack]]", "[[../../research/strains/p7/STATE]]", "[[p3d-l4-final-round-service]]"]
---

# P7-TAR — tail-aware rings

Full measurement ledger: `research/strains/p7/STATE.md`, section
"Tail-aware rings (P7-TAR)". This doc is the change record.

**Headline:** `parity_ring` and the with-idx tail are **not** structurally
incompatible. Ringed with-idx builds and is correct at **1034** cycles
(31/40 rings), against the 1048 ring-free+tail baseline the previous pass
recorded as the honest ceiling. The ring is worth **-14** under the tail.

## What changed

`dev.py` only (+108 lines, 0 deletions). `perf_takehome.py`, `problem.py` and
`tests/` untouched; the graded artifact is still **1006**.

* **`KernelBuilder.audit_ring_donor_liveness()`** — trace-level check that every
  funded ring's borrow is sound. For each ring `(epoch,g)` with borrow window
  `[lo,hi]` (emission span of that group's ring rounds, 0-4 / 11-15) and each
  donor word `w`: every read of `w` at `i>hi` must have its defining write after
  `lo`. A read whose defining write precedes `lo` is a **read-after-borrow** —
  the ring overwrote `w` mid-window, so that read sees a retained parity instead
  of the donor's value. Returns human-readable violations and records the
  implicated ring keys in `_ring_liveness_bad` for a drop-and-rebuild fixpoint.
* **`ring_liveness_assert: bool | None = None`** — `None` means auto-ON exactly
  when `parity_ring` and `store_final_indices` are both live, i.e. only for the
  new dangerous combination. Enables trace recording (emission-neutral:
  `ListScheduler.put` only appends) and asserts at end of build.
* **`parity_ring_drop: tuple[tuple[int,int],...] = ()`** — unfund specific
  `(epoch, group)` rings, applied last in `build_parity_ring_map` so it can
  remove structural, extras and planned rings alike.
* **`tools/p7tar_remine.py`** (new) — the reproducible derivation.
  **`tools/p7tar_best_plan_1034.json`** (new) — its output.

## Decisions & assumptions

1. **Criterion A only ("read-after-borrow"); criterion B rejected on
   evidence.** A stricter "any foreign access inside the window" check was
   implemented first and **fires 200 times on the known-good 1006 mainline** — a
   legitimately SHARED donor's second ring accesses it inside the first ring's
   window, and window-disjointness is what makes that safe, not this check.
   Criterion A gives 0 on the mainline and 200 under the tail: the exact
   discrimination an assert needs. Calibrating the oracle against a
   known-good build before trusting it is the load-bearing step here.
2. **In-window accesses are credited to the ring.** Same assumption
   `tools/audit_ring_windows.py` mines the plan under; checking it from a trace
   alone is not possible, so the assert checks the one criterion that is sound.
   It is checked against the **realized** stream, which is the point — ring
   safety is liveness-timed, so a plan mined on one stream must be re-validated
   on any other.
3. **Auto-ON default scoped to `ring + tail`, not to `ring`.** Trace recording
   costs build time and memory; ring searches build thousands of kernels and
   would pay for a guard against a hazard they cannot hit. Flag-OFF configs
   record no trace, so bit-exactness is preserved by construction rather than
   by luck.
4. **`parity_ring_drop` is a separate lever from `parity_ring_plan` because
   the plan can only ADD.** 6 of the 10 initially-dirty rings are NATIVE
   (structurally derived in `build_parity_ring_map`); no plan entry names them,
   which is precisely why the previous pass's greedy prune over the 20 planned
   entries "kept zero" and concluded incompatibility. The prune was searching a
   space that could not contain the answer.
5. **Re-mine on the tail-inclusive trace instead of hand-excluding the tail's
   registers.** The brief proposed deriving the funding pool by excluding the
   round-15/drain-window `st`/`nv` donors. Mining availability off the realized
   with-idx trace subsumes that: donors whose liveness the tail extends stop
   being available automatically, and an exclusion list cannot go stale as the
   tail changes. This is the substantive correction to the prior model.
6. **A drop-and-rebuild FIXPOINT, not a one-shot subtract.** Dropping rings
   reschedules the stream and surfaces new violations (iteration 0 finds 10
   dirty, iteration 1 finds 5 more, iteration 2 is clean). A single subtract
   would have shipped a miscompile.
7. **Donor candidate classes NOT widened.** `audit_ring_windows.py` restricts
   donors to structural classes whose reads cannot appear/disappear with
   schedule state (`emit_any` races read different addresses per encoding, so
   race-alternative operands are unsafe to borrow — the documented root cause of
   an earlier miscompare). Widening was the obvious way to buy coverage and was
   deliberately declined; the restriction is a soundness invariant, not a
   tuning knob.
8. **The plan is kept as a dev.py flag pair + a tools/ JSON, not ported to
   `perf_takehome.py`.** Per brief; the grader compares values only, so the tail
   is a board variant.

## How it was verified

* **Flag-OFF bit-exactness** vs the HEAD digests recorded in STATE — sha256 of
  the bundle list, cycles, `scratch_next_addr` — 3 configs x {default, explicit
  `store_final_indices=False`}, all 6 identical, re-run after the final edit:
  1006 mainline `f0b92c3ed3295e87`/1533, ring-free 1026 `ae44f09e55b36054`/1533,
  rings+pools(15,4) 1036 `1a7972d2a6dfad23`/1525.
* **Assert discrimination:** 0 violations on the 1006 mainline (no trace even
  recorded), 200 on the same config with the tail on, assert fires with the
  offending ring list.
* **Correctness, one build x 10 seeds**, values AND
  `machine.mem[2054:2310] == ref_mem[2054:2310]`:
  ring-free+tail 1048 → 10/10 and 10/10; prune-derived 25-ring 1036 → 10/10 and
  10/10; **re-mined 31-ring 1034 → 10/10 and 10/10**. Cycles identical on every
  seed (schedule is data-independent).
* **`python3 tests/submission_tests.py`** → `Ran 9 tests`, **OK**,
  **CYCLES: 1006**. `git diff --stat` over `dev.py perf_takehome.py problem.py
  tests/` shows `dev.py | 108 +++`, nothing else.
* **Reproducibility:** `tools/p7tar_remine.py` re-derives from scratch (empty
  plan) and its output compares **equal** to the committed
  `tools/p7tar_best_plan_1034.json`; `--verify` replays it with the assert at
  its auto-ON default and passes.

## Known limitations / follow-ups

1. **31/40 rings, -14 not -20.** Coverage is converged for this donor class:
   the mine loop adds nothing on a second pass, and on the prune-derived variant
   every one of the 15 dropped rings goes dirty on individual re-add (8-80
   violations each), so that drop set is exactly minimal. The 9 unfunded rings
   lack 3 available donor triples.
2. **Landed short of the brief's ~1022-1028 target.** That target assumed most
   of the ring's 20 cycles were recoverable; 14 is what the liveness constraint
   permits. The gap is not slack in the search — it is the 6 epoch-1 native
   rings whose donors are exactly the `st`/`nv` the tail resurrects.
3. **The assert's in-window assumption (decision 2) is unproven, inherited from
   the mining tool.** It is why a *shared*-donor bug could still slip past; a
   check that could distinguish a ring's own accesses from a co-tenant's would
   need ring accesses tagged at emission.
4. Untouched from the prior pass: the 3-op gathered tail (worth ~5 cycles if 9
   scratch words are ever freed), and `store_final_indices` still requiring
   `b3l_safe_leaf_fallback=True`.
5. **Process note:** a mid-run coordinator message asserted my first STATE.md
   append had not landed and asked for a restart from the top. It had landed;
   restarting would have double-appended the ledger. Verified on disk before
   declining, and recorded the discrepancy in STATE.md.
