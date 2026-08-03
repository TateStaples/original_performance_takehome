---
title: P7 milestone 1 — T2-partial + T1 are RELOCATIONS, not deletions; the C1* op prize is ~2 vec-ops, not ~1,300 lane-ops
date: 2026-08-02
type: change
status: awaiting-review
task: Implement milestone 1 of the C1*-class design in dev.py behind default-OFF flags (T2-partial retained-parity serving at the ring-coverage cap + T1 difference-table interiors), re-mine the ring plan, gate, and report.
links: ["[[../p3a/STATE]]", "[[../p3e/STATE]]", "[[../p3b/STATE]]", "[[../../RESEARCH]]", "[[../../graveyard]]"]
---

# P7-milestone-1

**VERDICT. Milestone 1 is a REJECT on measurement, and the reason is
structural, not tuning.** T2-partial was implemented faithfully, is
bit-exact-when-OFF, is correct on 10 value-trace seeds when ON, and
measures **1006 → 1008 / 1011** at the mainline. Its census delta is
**−2 to −3 valu vec-ops out of 5,966** (−0.05%), not the −1,300 lane-ops
the P3-A/P3-E model priced. The ring re-mine on the new stream finds
**0 new rings** (identical to the baseline mine), so the second-order
"st-deletion returns ~11 rings" route (P3-E §1.4) is falsified too.

T1 was NOT built: it is already implemented at setup for every table it
can apply to, and the residual 8 ops it would move are a relocation that
costs 64–72 scratch words the machine does not have (3 free).

---

## 1. What the models got wrong: T2 pays for what it deletes

P3-A's T2 priced `cond.mask` (78 sites) + `pos.fold` (114) + `pos.seed`
(40) = **232 sites removed**, against **+2 vec-ops × 35 exits = +70
added**, net −162 sites ≈ −1,512 lane-ops.

The `+2 × 35` term is where it breaks. Building the position by Horner at
the exit costs `d−1` madds for a `d`-bit position — **exactly the number
of steady folds it replaces**. The accumulator upkeep and the Horner
rebuild are the same ops in a different place. T2 therefore deletes ops
**only on group-epochs whose accumulator is never read at all.**

Exit accounting at the real shape (height 10, 16 rounds, `period` = 11,
`l4_gmin=(6,31)`), verified against P3-A's own census three ways:

| group-epoch class | count | upkeep madds | exit? | Horner madds | net under T2 |
|---|---|---|---|---|---|
| epoch 0, L4 gathered (g<6) | 6 | 2 (seed+L3) | yes, r3, 3-bit | 2 | **0** |
| epoch 0, L4 served (g≥6) | 26 | 3 (seed+L3+L4) | yes, r4, 4-bit | 3 | **0** (and b3 is clobbered — ineligible) |
| epoch 1, L4 gathered (g<31) | 31 | 2 | yes, r14, 3-bit | 2 | **0** |
| epoch 1, L4 served at r15 (g=31) | 1 | 2 | **no** (r15 = last round) | 0 | **−2** |

Total upkeep sites = 32·2 + 26 + 32·2 = **154**, which reproduces P3-A's
measured `pos.seed` 40 + `pos.fold` 114 exactly (40 = the 40 funded rings;
114 = 24 non-ringed L2 + 64 L3 + 26 served-L4-epoch-0). Exits = **63**,
not 35. P3-A's 35 assumed L4 service concentrated in epoch 1 (round 15) —
**the exact configuration G-38 measured as NEGATIVE.** T2's value and
G-38's finding are in direct opposition: T2 pays only where G-38 says not
to serve.

`cond.mask`'s 78 sites are not a T2 prize either — they are the mask
extractions on the **24 uncovered** group-epochs, i.e. a *ring-coverage*
prize, reachable (or not) independently of T2. See §4.

## 2. What was built

`dev.py`, one new kwarg, default OFF, three modes:

```
lazy_position_exit: bool | str = False
    False        inert (bit-exact with the pre-P7 file)
    True         elide the L2 seed madd + L3 fold_position on every
                 eligible ring-covered (epoch, group); rebuild the packed
                 position by Horner at the gather-exit boundary
    "early"      same set, Horner emitted at the TOP of the exit round
                 (off the pre-gather dependency chain)
    "dead-only"  restrict to the group-epochs whose accumulator has NO
                 reader (L4 served at the final round) — the strict subset
                 where the flag can only DELETE, never relocate
```

Supporting pieces: `horner_position()` next to `fold_position()`
(spellings matched op-for-op to the upkeep path — plain `madd` for the
seed step, `fold_position` for the rest, so the alu-offload race is
preserved and the experiment isolates the emission POINT), and
`lazy_position_ok(epoch, g)`.

**Eligibility is deliberately narrow for soundness.** A served L4 round
consumes the newest parity `b3` out of `nv` (the W-folds overwrite it), so
a 4-bit exit cannot be reconstructed from the 3-slot ring — those
group-epochs are excluded (and they are net-zero anyway, per §1). Serving
L4 at the FINAL round is fine (nothing reads `st` after it). The `dffold`
fallback inside the b3-last path reads `st` for its masks, so a lazy group
materialises the position there instead.

## 3. Measurements

All on the 1006 mainline stream (`tools/h061_common.kwargs()`:
`BASE_KWARGS` + `h059_curve.MIX` + `h057_best_plan_1006.json` order,
`l4_gmin=(6,31)`, 40 funded rings), frozen grader, seed 1.

### 3.1 Gates

* `python3 perf_takehome.py Tests.test_kernel_cycles` → **CYCLES: 1006**, OK.
* Flag-OFF bundle stream **bit-identical** on 3 configs (sha256 of the
  bundle list, plus slot counts and `scratch_next_addr`):

| config | bundles | digest (default) | digest (explicit OFF) |
|---|---|---|---|
| 1006 ring mainline | 1006 | `8a6f08bd3101451a` | `8a6f08bd3101451a` |
| ring-free | 1026 | `5a748c89ff01b3b1` | `5a748c89ff01b3b1` |
| rings + pools (15,4) | 1036 | `7b8f518f6e807e30` | `7b8f518f6e807e30` |

* Flag-ON value-trace compare (`debug_compares=True`, dev's vcompare against
  `reference_kernel2`'s trace), 10 seeds each: **10/10 pass** for
  `lazy-exit` and `lazy-early`; final `inp_values` equal to reference on
  every seed; frozen grader `correct: true` at every point below.

### 3.2 Serve/coverage profiles × modes

| profile | off | dead-only | exit | early |
|---|---|---|---|---|
| P1 mainline, 40 rings, gmin (6,31) | **1006** | 1008 | 1011 | 1008 |
| P2 structural rings only (`parity_ring_plan=()`) | **1017** | 1017 | 1022 | 1017 |
| P3 rings + pools (15,4) | 1036 | 1036 | **1034** | 1036 |

Census at P1 (alu slots / valu slots / flow slots / alu+valu lane-ops):

| mode | alu | valu | flow | lane-ops | binder floor | realized |
|---|---|---|---|---|---|---|
| off | 11,761 | 5,966 | 797 | 59,489 | 995 | 1006 |
| dead-only | 11,761 | 5,963 | 798 | 59,465 | 994 | 1008 |
| exit | 11,769 | 5,970 | 808 | 59,529 | 995 | 1011 |
| early | 11,745 | 5,964 | 798 | 59,457 | 994 | 1008 |

**The predicted −2 vec-ops landed exactly** (5,966 → 5,964 at `early`;
5,963 at `dead-only`, the extra one being a flow/copy shift). Everything
else moved by less than 0.15%. Two modes lower the valu floor by 1 and
still cost +2 realized: the 1006 emission order was mined for the
baseline stream, and the relocation desynchronises it (regret 11 → 14).
The single positive cell (P3/exit, −2) is on a base that is already 30
cycles worse; it is a scheduling coincidence, not a mechanism.

### 3.3 Ring re-mine (the brief's order-specificity rule)

`tools/audit_ring_windows.py` driven on the actual stream (its `CONFIG`
replaced by `h061_common.kwargs(...)` so the mined windows come from the
1006 emission order, not the tool's own `l4_gmin=(7,30)` default):

| stream | funded-ring safety recheck | new rings mined | unfunded remaining |
|---|---|---|---|
| baseline (flag OFF) | **OK over 40 rings** | **0** | 24 |
| `lazy_position_exit="early"` | **OK over 40 rings** | **0** | 24 |
| `lazy_position_exit=True` | **OK over 40 rings** | **0** | 24 |

The unfunded set is byte-identical across all three:
`(0,20..27), (0,30), (0,31), (1,0..7), (1,10..15)`.

**P3-E §1.4's downward/upward caveat is settled: T2 frees no ring
donors.** `st` is not actually released — it is still written by the exit
conversion, which lands *inside* the epoch's ring window (rounds 0–4 /
11–15), and the covered epoch-0 groups that would matter (g≥6) are
ineligible because their L4 is served. The plan is not stale: it audits
clean on the new stream, and re-mining from empty adds nothing.

## 4. T1 — already done, and the residue is unaffordable

T1's premise ("interiors spelled sub+madd get precomputed difference
tables") does not hold against the code:

1. **The L1–L3 and L4 tables are already difference tables.** `dev.py`
   builds them at setup as ONE scalar `alu` subtract on the loaded forest
   word plus a `vbroadcast` (`d = alloc_scratch(); emit("alu", ("-", d,
   s1, s0)); broadcast_vec(d)`). There is no runtime subtract to remove.
2. **Tournament interiors are not constant-armed, in any tree order.**
   Folding 2^d constants costs 2^d−1 two-way nodes; exactly 2^(d−1) of
   them (the leaf layer) have constant arms, and that layer is already the
   madd-with-precomputed-diff form. The remaining 2^(d−1)−1 combine
   RUNTIME values (`race_sel`, `u_combine`) whichever bit is folded first —
   b3-first and b3-last both give 4 constant leaves + 3 runtime combines at
   L4. P3-A's "removes race_sel sub+madds, ~−160 lane-ops" is not
   realizable; those subtracts are the *chosen spelling* of a runtime
   two-way select that the scheduler races onto the idle engine, not an
   artifact of the tree shape.
3. **The one true residue is 8 ops.** `make_newest_parity_last_diffs`
   computes the 8 b3-last leaf diffs with `vec("-")` at round 15 into dead
   registers, because there is nowhere to keep them from setup. Hoisting
   them needs 8 broadcast vectors = **64 words** (72 with their scalar
   sources); `scratch_next_addr` measures **1,533 of 1,536** on the
   mainline — **3 free**. And even funded it is another relocation: 8
   setup `vbroadcast`s replace 8 round-15 subtracts, on an engine
   (`vbroadcast` is valu-only) where the subtract was alu-splittable.

An unimplemented `b3l_setup_diff_tables` kwarg was added and then removed
rather than shipped dead.

## 5. Consequence for the C1* stack

The charter's component-1 estimate (−2,072 lane-ops at full coverage,
~−1,300 at 62.5%) does not survive contact. Restated honestly:

* T2's deletable prize = 2 × (ring-covered group-epochs whose accumulator
  is never read) = 2 × (covered ∧ L4-served-at-round-15). At
  `l4_gmin=(6,31)` that is **1 group = 2 vec-ops**. To make it large you
  must serve L4 broadly at round 15 — **G-38 measured that as negative**,
  and G-38's measurement did not depend on the accumulator.
* T2's second-order prize (freeing donors → more coverage → deleting the
  78 `cond.mask` sites) is **measured at zero** (§3.3).
* T1's prize is 8 relocatable ops behind a 64-word scratch wall.

The remaining C1* components (T3 `add_imm`→alu, serve-profile
re-optimisation, emission re-mine, with-idx tail) are untouched by this
result and are still unpriced against measurement.

## 6. Files

* `dev.py` — `lazy_position_exit` kwarg, `horner_position()`,
  `lazy_position_ok()`, four call-site guards. Default OFF and bit-exact.
* scratchpad harnesses (not committed): `p7_run.py` (digests/census),
  `p7_verify.py` (10-seed value-trace gate), `p7_sweep.py` (profiles ×
  modes), `p7_mine.py` (ring re-mine driver).

## 7. Open issues

1. `parity_ring_extras=(0,1)` collides with the mined plan
   (`AssertionError: parity_ring_plan entry (0,13) already ring-funded`).
   Pre-existing, not caused by this change — but it means "extras" and
   "mined plan" cannot currently be combined to probe higher coverage.
2. The `early`/`dead-only` modes lower the valu floor to 994 but realize
   1008. Whether a re-mined *emission order* recovers those 3 cycles of
   regret is untested (a full order re-mine was out of budget). Upside is
   bounded by the census delta, i.e. ≤1 cycle below 1006.
3. `lazy_position_exit` is dead code at any configuration with no ring
   coverage; it is asserted nowhere. Harmless, but a reviewer may prefer
   an explicit `assert parity_ring_slices` when the flag is on.

---

# P7 — Polish stack (milestones a/b/c)

status: in-progress ledger, appended as each gate lands
task: (a) spelling/dual_fold re-tune at the SHIPPED config, (b) emission-order
re-mine, (c) the with-idx tail (`store_final_indices`, default OFF).

## (a) Spelling / dual_fold re-tune at the shipped 1006 config — ZERO, and
## the brief's "1049 -> 1047" does NOT transfer

**The brief's cited win is at a different stream.** `tools/p4c_retune.py
--gmin "(6,31)" --rounds 1` descends from `run_variant.BASE_KWARGS` with only
`l4_gmin` overridden. Reproduced exactly:

```
l4_gmin=(6, 31)  as-shipped-flags = 1049 (correct=True)
  iter0 pair_tournament_first_fold_race: 3 -> 0   1049 -> 1047
RETUNED = 1047 (was 1049, friction 2) evals=75
```

That 1049 stream is NOT what `perf_takehome.py` ships. The shipped stream is
`tools/h061_common.kwargs()` = BASE_KWARGS + `h059_curve.MIX` (rings, gmin
(6,31), c5-primed (5,6), mem-prime flags) + the h057 1006 emission order.
The 2 cycles `ptff 3->0` buys at 1049 are friction the shipped config has
already absorbed.

**Re-tune run AT the shipped config: 0 cycles.** Coordinate descent over 31
axes (p4c's 18 plus 13 it never swept: `shallow_tournament_reverse_select_race`,
`reverse_newest_parity_fold_at_shallow_levels`, `gather_load_offset`,
`idx_boundary_select`, `parity_conds`, `c5_prexored_value_domain`,
`flow_first_fold_levels`, `hash1_avec_race`, `temp_pool_coloring`,
`vec_reclaim_margin`, `parity_early`, `mem_prime_ignore_l4_hazard`,
`store_order`, `group_window`, `emit_order`), 126 evaluated moves, 3 rounds
requested, terminated at iteration 0 with **no improving move**:

```
shipped-1006 base = 1006 (correct=True)
  [iter0 done] best=1006 evals=126
RETUNED = 1006 (was 1006, friction 0) plan delta: {}
```

`skew` and `l4_gmin` are pinned (dev.py:1625 asserts the ring funding map is
derived for the (4,3)/32-group shape; the ring plan is gmin-specific).

Axis sensitivity spot-check (so the zero is not a silent all-exceptions
result): pool (15,4) = 1036, (17,4) = out of scratch, `alu_offload=False` =
1212, `tie_break=()` = 1010, `flow_race_bias=1` = 1009,
`reverse_newest_parity_fold=()` = 1012, `idx_select_before_madd=False` = 1024,
`emit_order='round'`/`store_order='round'` = 1006 (inert under an explicit
`emission_plan`). The axes are live; the config is a strict single-move
optimum.

**Spelling plan search at the shipped config: also 0.** `flow_spelling_plan`
is EMPTY in the shipped MIX, so it was a genuinely unexplored lever.
`tools/spelling_plan_search.py` re-pointed at `h061_common.kwargs()` (site
numbering is emission-order specific, so a plan mined at any other order is
meaningless here): start 1006, one full sweep of reverse flips + forward
flips + drops, **fixpoint at 1006 with plan size 0**.

**ACCEPTED CHANGE: none. `perf_takehome.py` is UNTOUCHED** (still 1006).

## (b) Emission-order re-mine — ZERO, and it is closed a priori

(b) was scoped as "re-mine on top of (a)'s accepted config". (a) accepted
nothing, so the config is bit-identical to the one G-30/G-31 already closed by
enumeration: 25,550 single-entry moves zero below 1006 (f18_exhaust1), then
438,247 multi-move evals zero below 1006 with the k=2 interacting space
EXHAUSTED (f37). G-32 records the same closure for the spelling and packing
axes at this mix. No new moves can have opened, because nothing about the
stream changed. Not re-run; **0 cycles, by inheritance from an exhaustive
enumeration at the identical config.**

Ring-plan audit obligation for (a)/(b): vacuous — no accept, so the shipped
plan is unchanged and still the one it was mined for.

## (c) The with-idx tail (`store_final_indices`) — IN PROGRESS

See the "with-idx tail" section appended below as gates land.

### (c) gate log — measurements so far

Config vocabulary: "ring-free" = `h061_common.kwargs(rings=False)` = **1026**
(structural rings only); "ringed mainline" = `h061_common.kwargs()` = **1006**
(the shipped stream, 40 funded rings, h057 order).

| build | base | with-idx | delta | values | indices vs `ref_mem[2054:2310]` |
|---|---|---|---|---|---|
| ring-free, index vstores in the DRAIN block | 1026 | **1048** | +22 | OK | **256/256 exact** |
| ring-free, index vstores INSIDE round 15 | 1026 | 1071 | +45 | OK | 256/256 exact |
| ringed mainline | 1006 | **build FAULTS** | — | — | — |

* The tail is CORRECT: the new check compares
  `machine.mem[iip:iip+256]` against `reference_kernel2`'s final
  `mem[inp_indices_p:...]` (iip measured = 2054, ivp = 2310, matching the
  brief's mem[2054..2309]); 0 of 256 words differ, values still exact.
* Drain-block stores beat in-round stores by 23 cycles, so the drain form is
  the one being kept. (In-round stores were tried to shorten `st`/`nv`
  liveness for the ring plan's sake; it did NOT fix the ring fault and cost
  23 cycles, so the trade is strictly bad.)
* +22 on the ring-free base is above the +16 the model predicted. Op census
  for the tail: 4 vec-ops/group for the 31 groups that GATHER at round 15
  (st holds the true level-4 gather address) and 6 for the one SERVED group,
  + 32 flow add_imm + 32 vstores = ~130 vec-ops. Equalising the added
  lane-ops across valu/alu predicts a floor of ~1008 from 995, i.e. ~+13
  floor and ~+22 realized once the drain's regret is added.

### (c) open blocker: the ringed mainline needs a ring re-mine

With `parity_ring` on, the with-idx build **faults at cycle ~878 on a
round-8 gather of group 28** (`state_vecs[28]` = scratch 761, which the mined
plan hands to `(0,19)` as a ring donor). This is NOT the tail's liveness: the
fault is in EPOCH 0, hundreds of cycles before any tail op, and it survived
moving the index stores into round 15 (which shortens `st`/`nv` liveness
back to nearly where it was). It is the documented G-30/F-35 failure mode —
**ring borrow windows are liveness-TIMED and order-specific, and the tail
shifts the whole schedule by ~30-45 cycles, so the mined plan goes dirty.**
Fixing it is a ring re-mine (grow-then-prune, F-35), not a code fix.

### (c) two build-time hazards found and fixed (both would have shipped wrong answers)

1. **Never allocate scratch ahead of the state allocations.** The first
   version loaded `inp_indices_p` from the header (1 word). That shifted every
   later scratch address by one and silently re-pointed the ENTIRE
   `parity_ring_plan`, whose donors are absolute addresses — gather addresses
   corrupted at cycle 123. The tail now derives the index region
   arithmetically (`add_imm(addr, val_addrs[g], -batch_size)`), relying on
   `build_mem_image`'s `inp_values_p == inp_indices_p + batch_size` (the same
   invariant `bcast_via_mem` already uses). ZERO new scratch — which the
   1533/1536 occupancy required anyway.
2. **`make_newest_parity_last_diffs`'s dead-register pool is built ENTIRELY
   out of `st` and `nv`** — exactly the two registers the tail keeps live
   through round 15. Unguarded, 16 groups' final indices came back as a single
   broadcast constant (their donated `st`s). The pool is now empty under
   `store_final_indices`, so the served group falls back to `dffold`; that
   fallback aliases `omf1_vec`, so the flag additionally requires
   `b3l_safe_leaf_fallback=True` (asserted with that message). The b3l assert
   itself is untouched and still fires.

### (c) FINAL — the tail is correct and costs +22, but it FORFEITS the ring

**Shipped form: index vstores in the drain block, right after each group's
value vstore.** `store_final_indices=True` (default OFF) +
`b3l_safe_leaf_fallback=True`.

| config | base | with-idx | delta |
|---|---|---|---|
| ring-free (`parity_ring` off) | 1026 | **1048** | **+22** |
| ringed mainline (40 planned + ~20 native rings) | 1006 | INCORRECT | — |
| ringed, `parity_ring_plan=()` (native rings only) | 1017 | INCORRECT (1041) | — |

**`parity_ring` and the with-idx tail are structurally incompatible, and
pruning cannot fix it.** A greedy prune over all 20 planned entries (add-back
from empty, correctness in the objective) kept ZERO: even with the plan
emptied, the ~20 NATIVELY derived rings still miscompile. The reason is not
timing noise — the ring funds retained parities out of registers it believes
are dead, and its liveness model says a group's `st` dies at its round-15
gather issue and its `nv` at the round-15 fold-in xor. **Those are exactly the
two registers the tail resurrects**, in every group. Shortening the
resurrection (computing AND storing the index inside round 15 instead of at
the drain) does not help either — still incorrect, and 23 cycles worse
(1071 vs 1048), because round 15 is the busiest region and the drain's store
engine is idle. F-35's rule applies: planned rings are prunable, natively
derived ones are a property of the ORDER and unrepairable.

So the honest **with-idx-eligible number today is 1048**, not 1006+22: the
tail costs +22 of its own AND forfeits the ring's 20 cycles. Recovering the
ring for a with-idx build needs the ring DERIVATION (not just the plan) made
tail-aware, and by construction that leaves far fewer donors — the ceiling is
close to the ring-free base anyway.

**Gates**
* Flag-OFF bit-exact vs `git show HEAD:dev.py`, sha256 of the bundle list +
  bundle count + `scratch_next_addr`, on 3 configs, default AND explicit
  `store_final_indices=False`:

  | config | HEAD | new default | new explicit OFF |
  |---|---|---|---|
  | 1006 ring mainline | (1006, `f0b92c3ed3295e87`, 1533) | identical | identical |
  | ring-free | (1026, `ae44f09e55b36054`, 1533) | identical | identical |
  | rings + pools (15,4) | (1036, `1a7972d2a6dfad23`, 1525) | identical | identical |

* Tail correctness, 10 seeds, ring-free with-idx build (one build, 10 inputs):
  values exact 10/10 AND `machine.mem[2054:2310]` == `ref_mem[2054:2310]`
  10/10. Cycles 1048 on every seed (the schedule is data-independent).
* `python3 tests/submission_tests.py` → **Ran 9 tests, OK, CYCLES: 1006**.
  `perf_takehome.py` NOT MODIFIED (no accept in (a)/(b) to port, and the tail
  is a board variant, not a grader improvement — the grader compares values
  only).
* Scratch unchanged at 1533/1536 with the flag on: the tail allocates NOTHING.

**Files:** `dev.py` only — `store_final_indices` kwarg; `emit_final_index()` /
`emit_final_index_store()`; a `pre_madd` hook in `b3l_fold_diffs`;
`should_fold_b3` extended for a served final round; the dead-register-pool
guard in `make_newest_parity_last_diffs`; `final_index_store_cycles` folded
into the trailing `pause` gate.

**Open issues**
1. Ringed with-idx is unavailable (above). Reopen only with a tail-aware ring
   derivation; expect it to be worth much less than 20 cycles.
2. The gathered-group tail is 4 vec-ops where 3 would do; the missing op is a
   `(1 - 2*fp)` broadcast, 9 scratch words against 3 free. Worth ~5 cycles if
   9 words are ever freed.
3. `store_final_indices` requires `b3l_safe_leaf_fallback=True` whenever any
   group is L4-served at round 15 (asserted). At `l4_gmin=(6,31)` that is one
   group; the fallback alone measures 1006 (free) at the mainline.
4. `tools/h042_plan.json` (empty plan, written by the spelling search at the
   shipped config) was deleted rather than committed — it encodes "no plan",
   and a stray plan file in tools/ invites a stale-plan accident.

## Tail-aware rings (P7-TAR) — status: done (awaiting review)

**Builder started:** 2026-07-28. Objective: make parity rings coexist with `store_final_indices`
tail. Baseline claims to re-verify: ring-free+tail = 1048, ringed no-tail = 1006, target
with-idx eligible ~1022-1028.

Plan: (1) land liveness assertion on ring donor borrows FIRST (converts silent miscompile
into diagnosable reject), (2) re-derive ring map with tail-aware reduced donor set,
(3) measure at whatever coverage survives.

Results appended below after every gate.

**Note (coordinator sync):** a mid-run message claimed the STATE header append never
landed and asked for a restart. Verified on disk: it DID land (`grep -c` = 1). No restart,
no double-append. Recorded so the ledger is not silently rewritten.

### P7-TAR gate 1 — the liveness assert LANDED (and it reframes the problem)

`KernelBuilder.audit_ring_donor_liveness()` + `ring_liveness_assert` kwarg
(default `None` = auto-ON exactly when `parity_ring` AND `store_final_indices`
are both live) + `parity_ring_drop` kwarg.

**Criterion (the one that is sound to check from a trace alone):** for each
funded ring `(epoch,g)` with borrow window `[lo,hi]` = the emission span of that
group's ring rounds (0-4 / 11-15), and each donor word `w`: every read of `w`
at `i>hi` must have its defining write AFTER `lo`. A read whose defining write
precedes `lo` is a **read-after-borrow** — the ring overwrote `w` inside the
window, so that read observes a retained parity. Silent miscompile, hence assert.

| build | rings | A-violations |
|---|---|---|
| 1006 ring mainline (no tail) | 40 | **0** |
| same + `store_final_indices` | 40 | **200** |

* An in-window access is credited to the ring (same assumption
  `tools/audit_ring_windows.py` mines under). A stricter "foreign in-window
  access" criterion was also implemented and **rejected**: it fires 200 times on
  the KNOWN-GOOD 1006 mainline, because a legitimately SHARED donor's second
  ring accesses it inside the first ring's window. Window-disjointness governs
  that case, not this check.

**The reframing.** The 200 violations implicate only **10 of the 40 rings**,
all in epoch 1 plus one epoch-0:

* NATIVE (structural, no plan entry names them): (1,16) (1,17) (1,18) (1,24)
  (1,25) (1,31)
* PLANNED: (0,28) (1,28) (1,29) (1,30)

So "`parity_ring` and the with-idx tail are structurally incompatible" is
**too strong**. 30 of 40 rings are clean under the tail. The previous greedy
prune kept zero because it could only remove PLANNED entries — and 6 of the 10
dirty rings are native, which `parity_ring_plan` cannot express. That is the
lever `parity_ring_drop` adds.

**Gate — flag-OFF bit-exactness (sha256 of the bundle list, 3 configs x
{default, explicit False}), all 6 identical to the HEAD values:**

| config | cycles | sha | scratch |
|---|---|---|---|
| 1006 ring mainline | 1006 | `f0b92c3ed3295e87` | 1533 |
| ring-free | 1026 | `ae44f09e55b36054` | 1533 |
| rings+pools(15,4) | 1036 | `1a7972d2a6dfad23` | 1525 |

Trace recording is emission-neutral (`ListScheduler.put` only appends) and is
NOT enabled on any flag-OFF config, so the searches pay nothing.

### P7-TAR gate 2 — RINGED WITH-IDX EXISTS: 1036, correct, 25/40 rings

Derivation = **drop-and-rebuild fixpoint**: build with the tail, run the
liveness audit, add every implicated ring to `parity_ring_drop`, rebuild,
repeat until the audit is clean. Dropping rings changes the schedule, so new
violations surface — the fixpoint is what handles that (it is NOT a one-shot
subtract).

| iter | dropped | rings | cycles | violations | newly dirty |
|---|---|---|---|---|---|
| 0 | 0 | 40 | 1033 | 200 | (0,28)(1,16)(1,17)(1,18)(1,24)(1,25)(1,28)(1,29)(1,30)(1,31) |
| 1 | 10 | 30 | 1033 | 96 | (0,19)(0,29)(1,9)(1,21)(1,22) |
| 2 | 15 | 25 | 1036 | **0** | — |

Converges in 3 iterations. Final drop set (15 rings):
`((0,19),(0,28),(0,29),(1,9),(1,16),(1,17),(1,18),(1,21),(1,22),(1,24),(1,25),(1,28),(1,29),(1,30),(1,31))`

**Correctness gate — one build, 10 seeds, values AND indices:**

| build | rings | cycles | values | indices vs `ref_mem[2054:2310]` |
|---|---|---|---|---|
| ring-free + tail (prior baseline, re-measured) | 0 | **1048** | 10/10 | 10/10 |
| **tail-aware ringed + tail** | **25** | **1036** | **10/10** | **10/10** |

**With-idx eligible is 1036, not 1048.** The ring is worth **-12** under the
tail (vs -20 without it), recovered from a strain the previous pass recorded as
closed. Scratch unchanged at 1533; the tail still allocates nothing.

Honest framing of the delta vs the brief's ~1022-1028 target: that target
assumed most of the ring's 20 cycles were recoverable. 12 of 20 is what the
liveness constraint actually permits at this coverage — 25/40 rings, and the
6 native casualties are the epoch-1 blocks whose donors are exactly the `st`/`nv`
the tail resurrects.

### P7-TAR gate 3 — re-mining ON THE TAIL STREAM beats pruning: 1034, 31 rings

Two derivations were run, both to a clean liveness fixpoint:

| derivation | rings | cycles | values | indices |
|---|---|---|---|---|
| ring-free + tail (baseline) | 0 | 1048 | 10/10 | 10/10 |
| **prune**: inherited 1006 plan, drop the dirty 15 | 25 | 1036 | 10/10 | 10/10 |
| **re-mine**: empty plan, 6 native drops, 17 fresh entries | **31** | **1034** | **10/10** | **10/10** |

Add-back on the prune result: all 15 dropped rings were tried individually for
re-add; **every one goes dirty** (8-80 violations each). The 15-drop set is
exactly minimal — pruning an inherited plan tops out at 25 rings.

Re-mining wins because it mines availability from the **realized tail-inclusive
trace**, so donors whose liveness the tail EXTENDS simply stop being available;
no hand-built exclusion list was needed. That is the substantive correction to
the previous pass's model: the fix is not "subtract the tail's registers from
the donor pool", it is "mine on the stream you will actually run".

Native-only skeleton (empty plan) is 14 rings / 1043; the 17 mined entries add
the other 17 rings and -9 cycles.

The `ring_liveness_assert` default (auto-ON for ring+tail) ran on the 1034 build
and passed — the correctness gate and the assert agree.

### P7-TAR FINAL — coverage converged; 1034 is the with-idx-eligible number

Add-back and re-mine are both at a fixpoint, so 31/40 is the ceiling for the
sound donor classes:
* mine loop: a second mining pass on the clean 31-ring trace adds NOTHING;
* prune variant: all 15 of its dropped rings go dirty on individual re-add.

Donor candidate classes were deliberately NOT widened. `audit_ring_windows.py`
restricts donors to structural classes whose reads cannot appear/disappear with
schedule state (`emit_any` races read different addresses per encoding); that
restriction is a soundness invariant and widening it is how the earlier (1,1)
miscompare happened.

**Final gates**
* Flag-OFF bit-exact, 3 configs x {default, explicit False}, re-run after the
  last edit: all 6 digests identical to HEAD (see gate 1 table).
* `python3 tests/submission_tests.py` -> **Ran 9 tests, OK, CYCLES: 1006**.
* `git diff --stat dev.py perf_takehome.py problem.py tests/` -> `dev.py | 108 +++`
  only. **`perf_takehome.py` untouched.**
* Ringed with-idx (31 rings): values 10/10, indices 10/10, **1034** cycles.
* `tools/p7tar_remine.py` re-derives the plan from an EMPTY plan and reproduces
  `tools/p7tar_best_plan_1034.json` byte-identically; `--verify` replays it with
  the liveness assert at its auto-ON default and passes.

**Ledger correction.** The prior section's "`parity_ring` and the with-idx tail
are structurally incompatible, and pruning cannot fix it" is **withdrawn**. The
prune genuinely could not fix it — but only because `parity_ring_plan` can only
ADD, so a prune over the 20 planned entries can never remove the 6 NATIVE dirty
rings, and the native rings are what made even `parity_ring_plan=()` miscompile.
With a subtract lever and a re-mine on the realized stream, 30-31 of 40 rings
are sound under the tail.

| board number | before | after |
|---|---|---|
| with-idx eligible | 1048 | **1034** |
| graded (values-only) artifact | 1006 | 1006 (untouched) |

**status: done — awaiting review.** Doc: `docs/agent-wiki/p7-tail-aware-rings.md`

---

## gmin cascade (P7-G) — the screen's 10-cycle lead INVERTS at the full stream

**Builder started:** 2026-08-03. Question: does `l4_gmin=(9,30)` (or `(8,31)`),
which led the driver's ring-free screen (`gmin_sweep_noring.json`: (6,31)=1049,
(8,31)=1045, (9,30)=1039), beat the shipped mainline once it gets a ring plan
DERIVED AT THAT GMIN? Tool: `tools/p7g_remine.py` = the P7-TAR derivation
parameterized over `--gmin`/`--tail`/`--order` (`p7tar_remine.py` imported,
never modified; its module-global `build` is re-pointed, so
`derive`/`fixpoint`/`mine` stay bit-identical).

### P7-G gate 1 — ring-free screen on the REAL base already inverts the ranking

The screen's "ringless base" is `BASE_KWARGS + l4_gmin` (1049 at (6,31)), which
carries **no emission plan**. The strain's ring-free base is
`h061_common.kwargs(gmin, rings=False)` = **1026** at (6,31). On that base
(seed 1, `correct=True` everywhere):

| gmin | (6,31) | (8,31) | (9,31) | (9,30) | (10,31) |
|---|---|---|---|---|---|
| ring-free cycles | **1026** | 1028 | 1028 | 1030 | 1032 |

### P7-G gate 2 — full cascade: derived ring plan per gmin, tail OFF and ON

Derivation from an EMPTY plan at each gmin (liveness fixpoint + mine off the
realized trace, to convergence). **Control:** re-deriving at the shipped
(6,31) reproduces the mainline to within 1 cycle, and at `--tail on`
reproduces `tools/p7tar_best_plan_1034.json` **byte-identically** — so the
gaps below are not derivation loss.

| gmin | tail | ring-free | natives only | derived | rings | 10-seed verify |
|---|---|---|---|---|---|---|
| **(6,31)** | off | 1026 | 1017 | **1007** (shipped plan 1006) | 39 | 10/10 values |
| (8,31) | off | 1028 | 1018 | **1015** | 38 | 10/10 values |
| (9,30) | off | 1030 | 1023 | **1023** (mining REGRESSES to 1027) | 20 | 10/10 values |
| **(6,31)** | on | — | 1043 | **1034** | 31 | 10/10 values+indices |
| (8,31) | on | — | 1042 | **1041** | 30 | 10/10 values+indices |
| (9,30) | on | — | 1052 | **1049** | 30 | 10/10 values+indices |

Plans: `research/strains/p7/p7g_plan_{6_31,8_31,9_30}_{off,on}.json`
(deliberately not in `tools/` — (c) open issue 4). Verify replays with
`ring_liveness_assert` at its auto-ON default and checks values AND, under the
tail, the 256 final indices vs `reference_kernel2`; 6/6 configs PASS.

**Nothing beats 1006, and nothing beats 1034.** Best non-shipped candidate is
(8,31) at 1015 (+9) / 1041 (+7).

### P7-G gate 3 — WHERE the 10 cycles went: the h057 emission order

Layer-by-layer attribution (ring-free until the last column):

| gmin | bare BASE+gmin | + h059 MIX flags, no order | + h057 order | + derived rings |
|---|---|---|---|---|
| (6,31) | 1049 | 1049 | **1026** (−23) | **1007** (−19) |
| (8,31) | 1043 | 1045 | **1028** (−17) | **1015** (−13) |
| (9,30) | 1038 | 1039 | **1030** (−9) | **1023** (−7) |

* Column 2 reproduces the driver's screen (1049/1045/1039) — so the screen was
  measuring the ORDERLESS stream.
* The h059 MIX flags are gmin-neutral (±2, ranking unchanged): NOT the absorber.
* The **h057 emission order is the absorber and it is not a constant offset**
  (−23/−17/−9). It re-ranks the three candidates by itself, before rings.
  Rings then compound in the same direction (−19/−13/−7).

**This is why the mainline sits at (6,31).** On a raw stream (6,31) is the
WORST of the three (1049 vs 1038); it wins because the two expensive
order-specific layers were co-optimized with it, and they are worth more than
the raw serve-profile difference. Corollary for future screens: a serve-profile
screen run without the emission plan measures a different optimum than the one
the stream actually has.

### P7-G gate 4 — the steelman: re-mine the emission order AT (9,30). It gets WORSE.

If the h057 order is the absorber, the fair question is whether (9,30) with its
OWN order beats (6,31) with h057. Measured, not argued
(`tools/emission_order_search.py`, `EOS_OVERRIDES` = h059 MIX flags ring-free at
`l4_gmin=(9,30)`, `parity_ring=False`):

* `phase1` (structured families + pairwise compositions): 53 evals, best
  **1039 = the default order, params {}** — no structured family beats default.
* `local` (`--window all`, `EOS_JUMPS=1,2,4,8,16,32`, 4 workers, 23,556 evals /
  1500 s): 1039 -> **1035**; 4 descents, last at t~190 s, flat for 1300 s after.
* Full cascade on that order (`p7g_remine --order`): natives 1037, mining adds
  nothing -> **1037**, 10/10 seeds
  (`research/strains/p7/p7g_plan_9_30_off_neworder.json`, order artifact
  `p7g_order_9_30_local1035.json`).

| (9,30) with... | ring-free | + derived rings |
|---|---|---|
| inherited h057 order | **1030** | **1023** |
| order mined AT (9,30) | 1035 | 1037 |

The inherited order is BETTER for (9,30) than a freshly mined one, so the gap
is not order staleness. **Asymmetry disclosed:** h057 is the product of a far
larger search (G-30/G-31/F-37: 25,550 single-entry moves + 438,247 multi-move
evals, k=2 exhausted). A 25-minute descent is a screen, not a matched search;
what it establishes is that the 17-cycle gap is not cheaply recoverable, not
that no order exists.

### P7-G FINAL — no port

`perf_takehome.py` UNTOUCHED (`git diff --stat dev.py perf_takehome.py
problem.py tests/` empty); `python3 tests/submission_tests.py` -> Ran 9 tests,
OK, CYCLES: 1006. Board numbers unchanged: graded 1006 at (6,31), with-idx
1034 at (6,31). Best non-shipped candidate measured: (8,31) at 1015 / 1041.

New tool: `tools/p7g_remine.py` (gmin/tail/order-parameterized P7-TAR
derivation + `--verify`). `tools/p7tar_remine.py` unmodified. `dev.py`
unmodified — every lever needed already existed.
Doc: `docs/agent-wiki/p7-gmin-cascade.md`.
