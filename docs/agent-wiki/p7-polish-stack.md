---
title: P7 polish stack — retune 0, emission re-mine 0, with-idx tail +22 (and it forfeits the ring)
date: 2026-08-02
type: change
status: awaiting-review
task: Phase-7 polish, three sequenced milestones — (a) spelling/dual_fold re-tune at the shipped config, (b) emission-order re-mine on the accepted config, (c) the lean with-idx tail behind a default-OFF dev.py flag.
links: ["[[../../research/strains/p7/STATE]]", "[[../../research/graveyard]]", "[[p3d-l4-final-round-service]]"]
---

# P7 polish stack

Full measurement ledger: `research/strains/p7/STATE.md`, section
"P7 — Polish stack (milestones a/b/c)". This doc is the change record.

## What changed

`dev.py` only (139 insertions, 3 deletions). `perf_takehome.py`, `problem.py`
and `tests/` are untouched; the graded artifact is still **1006**.

* **`store_final_indices: bool = False`** — new kwarg, default OFF and
  bit-exact when off.
* **`emit_final_index(g, st, vl, pv)`** — the lean with-idx tail, emitted at
  the point round 15 currently `return`s. Gathered groups (31/32 at the
  shipped `l4_gmin=(6,31)`) cost 4 vec-ops; the one served group costs 6.
* **`emit_final_index_store(g)`** — retargets the group's dead `val_addrs[g]`
  at the index region with one `add_imm` and vstores `st`.
* **`b3l_fold_diffs(..., pre_madd=)`** — hook so the newest-parity position
  fold can run before the fold's last madd destroys `nv`.
* **`should_fold_b3`** — a served FINAL round now folds b3 when the tail needs
  the position.
* **`make_newest_parity_last_diffs`** — guard: the dead-register pool is
  unfundable under the tail.
* **`final_index_store_cycles`** — folded into the trailing `pause` gate.

## Decisions & assumptions

1. **Re-tuned at `h061_common.kwargs()`, not `run_variant.BASE_KWARGS`.** The
   brief's "1049 -> 1047" is a different stream; the shipped stream adds
   `h059_curve.MIX` and the h057 order. Porting a delta mined at 1049 would be
   the F-29/H-049 mistake. Reproduced the 1049 result to prove the gap.
2. **Widened the axis set** from p4c's 18 to 31 rather than only raising
   `--rounds`: a coordinate descent that is flat in one round is flat in all,
   so new axes were the only way to buy information.
3. **`skew` and `l4_gmin` excluded** — dev.py:1625 pins skew for the ring
   funding map, and G-38 pins the gmin epoch split.
4. **(b) not re-run.** Its premise ("the re-tune may open new moves") is void
   when the re-tune accepts nothing: the config is bit-identical to the one
   G-30/G-31 closed by exhaustive enumeration. Recorded as inheritance, not as
   a measurement of mine.
5. **The tail derives `inp_indices_p` arithmetically** instead of loading
   header word 5. Loading it needs one scratch word, and `parity_ring_plan`
   names donors by ABSOLUTE address — one word ahead of the state allocations
   re-points the whole plan (found the hard way: gathers corrupt at cycle
   123). `build_mem_image` guarantees the adjacency; `bcast_via_mem` already
   relies on it.
6. **4 vec-ops/group, not 3.** The 3-op form needs a `(1 - 2*fp)` broadcast =
   9 scratch words; occupancy is 1533/1536. The 4-op form uses only vectors
   that are already live (`omf`, `one`, `two`).
7. **Index stores go in the drain block**, not inside round 15: measured 1048
   vs 1071. The store engine is idle at the drain and round 15 is not.
8. **The served-group path reuses the round-4 exit identity** rather than open
   -coding a Horner rebuild, with a constant correction (`k - 60`) so it works
   off whichever `rec_k` the config happens to have allocated.
9. **`b3l_safe_leaf_fallback` is required, not auto-enabled.** The tail forces
   the dffold fallback, which aliases `omf1_vec`; an explicit assert with that
   message is better than silently flipping a second flag. The b3l assert
   itself is untouched.

## How it was verified

* Flag-OFF bit-exactness vs `git show HEAD:dev.py` — sha256 of the bundle
  list, bundle count, `scratch_next_addr` — on 3 configs (1006 ring mainline
  `f0b92c3ed3295e87`, ring-free 1026 `ae44f09e55b36054`, rings+pools(15,4)
  1036 `1a7972d2a6dfad23`), default and explicit `False`: all identical.
* Tail correctness on 10 seeds: final values exact 10/10 AND
  `machine.mem[2054:2310] == ref_mem[2054:2310]` 10/10.
* `python3 tests/submission_tests.py` → Ran 9 tests, **OK**, **CYCLES: 1006**.
* Re-tune: 126 evaluated moves, zero improving; axis-sensitivity spot checks
  confirm the axes are live.
* Spelling search at the shipped config: fixpoint at 1006, plan size 0.

## Known limitations / follow-ups

1. **Ringed with-idx does not exist.** `parity_ring`'s dead-register funding
   and the tail want the same registers (`st`, `nv`). Greedy prune of all 20
   planned entries kept zero; even native-rings-only miscompiles. Needs a
   tail-aware ring derivation, which by construction leaves few donors.
2. The 3-op gathered tail is worth ~5 cycles if 9 scratch words are ever
   freed.
3. (b) rests on inheritance from G-30/G-31 rather than a fresh search.
