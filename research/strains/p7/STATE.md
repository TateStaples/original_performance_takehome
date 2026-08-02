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
