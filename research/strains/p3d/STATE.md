---
title: "P3-D: adjudicating P3-A vs P3-C — is the ~937.5 cell self-consistent?"
date: 2026-07-28
type: research
status: final
task: "Build ONE joint model in which index cost is DERIVED from the served-level profile (P3-B's transition rule) rather than swept as a free parameter; re-run the enumeration; decide whether a simultaneous sub-940 design exists."
links: ["[[../p3a/STATE]]", "[[../p3b/STATE]]", "[[../p3c/STATE]]", "[[../../RESEARCH]]", "[[../../graveyard]]"]
---

# P3-D: the joint serving/index adjudication

**VERDICT: SELF-CONSISTENT.** The joint optimum, with index derived from the
design and every leg of the trade priced in one model, is **C = 939**, with
the identical census to P3-A's C1\*. The brief's suspicion is REFUTED, but
not because P3-C's pricing of "serve more L4" was wrong — it was right. It is
refuted because **P3-B's 5,888 index floor is not bought by serving MORE L4
at all. It is bought by serving the SAME NUMBER of L4 group-rounds in the
OTHER epoch.**

Tool (mine, new, read-only): `tools/p3d_joint.py`.

## 1. The mechanism the two prior models both missed

`level(r) = r mod 11` over 16 rounds, so level 4 occurs at **round 4** and at
**round 15**. Round 15 is the LAST round: `_round_stage_generator` returns
before emitting any transition, and `perf_takehome.py:1494` states it in
source — *"st folds to b0b1b2b3 for epoch-exit gaddr **unless last round
(nothing reads st after)**"*.

Consequence, per group-round, measured by `tools/p3d_joint.py`:

| where the served L4 group-round sits | folds | loads | index madds |
|---|---|---|---|
| round 4 (epoch 1) | 15 | -8 | **0** — the address the round would have packed (4 loose bits, 3 madds) is simply packed one round later at round 5 (5 loose bits, 4 madds). Exact cancellation. |
| round 15 (epoch 2) | 15 | -8 | **-3** — there is no successor, so no address is ever needed. |

Four uniform schedules, exactly costed (`p3d_joint.py` output):

```
serve L1-L3 only, gather all L4        index 6656 lane-ops  folds/grp 22  loads 2108
serve L4 in epoch 1 only               index 6656 lane-ops  folds/grp 37  loads 1852
serve L4 in epoch 2 only (round 15)    index 5888 lane-ops  folds/grp 37  loads 1852
serve L4 both epochs                   index 5888 lane-ops  folds/grp 52  loads 1596
```

Rows 2 and 3 have **identical fold counts and identical load counts** and
differ by 768 lane-ops of index. So the 6,608 -> 5,888 index step is FREE:
it is a re-assignment, not a purchase. P3-C's frontier (L4x27 970.8 ->
L4x28 972.3 -> L4x29 973.8) correctly prices serving *more*; it never
priced serving the *same amount somewhere else*, because its `index_cost`
is level-indexed and expectation-smeared (`d.p(succ)`), which cannot
express "round 15 but not round 4".

**Corollary (actionable, census-only):** the shipped kernel does the
dominated thing. `l4_gmin = (6, 31)` (perf_takehome.py:669) serves 26 L4
group-rounds at round 4 and **1** at round 15. Moving those 26 to round 15
saves 26 x 3 = 78 vec-ops = **624 lane-ops of index at zero fold and zero
load cost**. The implementation blocker is the assert at
perf_takehome.py:729-736, `2*final_unserved >= 8 + 9*final_served`, which
caps the final round at 5 served groups (register funding for
`b3l_fold_diffs`). That is an allocation/scratch constraint, admissible
under LOOP.md 0b's idealized-machine frame, and it is exactly the shape
G-33 warns about — do not restate it as a structural limit.

## 2. The joint model

`tools/p3d_joint.py`. A design is a per-GROUP schedule over 16 rounds
(2^14 = 16,384 schedules; level-0 rounds are the root constant: 0 folds,
0 loads). 32 groups, mixtures of two schedules, 81 Pareto-minimal
(madds, folds, gathers) triples.

Index is DERIVED, never a parameter:
* 1 parity extract per paying transition (r -> r+1, r = 0..14, skip r = 10
  whose successor is level 0; no transition out of round 15) = exactly 14
  per group = 448. Design-invariant.
* a GATHERED round materialises an address: `madds = (#loose parity bits
  since the last materialised address) - 1` if the base is the level-0 root
  constant, else `#loose bits`. A SERVED round emits no madd; its bit stays
  loose.
* 1 flow-eligible two-way constant choice (`omf +/- par`) per gathered
  group-round (P3-A's `idx_sel = g`; P3-B section 9 proved it exact).

Feasibility at C, with fold nodes freely flow-or-valu (P3-A T1):
`BASE + madds + folds + g <= 8.5C - 2` and `BASE + madds <= 7.5C` and
`8g + 60 + k <= 2C`.

**Validation.** The model reproduces P3-B's independently-derived index
floors exactly, with no fitting:

| policy | p3d_joint | P3-B |
|---|---|---|
| shipped serving policy | 826 vec / 6,608 lane-ops | 826 / 6,608 |
| b=0 (all round-15 L4 served) | 736 vec / 5,888 lane-ops | 736 / 5,888 |
| P3-A's C1\* (29 of 32 round-15 L4 served) | 745 vec / 5,960 lane-ops | P3-A: 745 / 5,960 |

## 3. THE JOINT OPTIMUM

```
C = 939   alu+valu 56,296 lane-ops | load 1,878 | flow 939 | store 94
          floors 938.3 / 939.0 / 939.0
          index DERIVED = 448 extracts + 297 madds = 745 vec = 5,960 lane-ops
          folds 1,139   gathered 227   served 221   store-bcast k = 2
          29 groups: SSSS GGGGGGG SSSSS   (madds 9, folds 37, gath 7)
           3 groups: SSSS GGGGGGG SSSSG   (madds 12, folds 22, gath 8)
                     r0..r10          r11..r15        S=served G=gathered
```

i.e. every group serves L1-L3 in both epochs and gathers L5-L10; L4 is
gathered at round 4 by all 32 groups and served at round 15 by 29 of them.
This is **bit-identical to P3-A's C1\*** (`tools/p3a_opt.py`: C=939, s=221,
g=227, folds=1139, alu+valu 56,296, load 1,878, flow 939). P3-A's
`exits = 32 + max(0, 32 - n4)` is precisely this per-round accounting in
closed form.

### Sensitivity (each row is the min feasible C over the whole space)

| assumption changed | min C |
|---|---|
| T1+T2+T3, setup 70 vec (P3-A's baseline) | **939** |
| shipped setup 83 vec | 940 |
| `add_imm` stays on flow (T3 off) | 941 |
| shipped 4% fold-spelling overhead (`race_sel` sub+madd interiors) | 943 |
| + support arithmetic 62 vec (P3-C's `mask_rate` only) | 945 |
| + support arithmetic 160 vec (P3-C's full as-built calibration) | **953** |
| + support arithmetic 259 vec (no parity ring at all) | 962 |

**Support headroom at C = 940 is 16 vec-ops (128 lane-ops).** T2 must
cover essentially 100% of served group-rounds.

## 4. ERROR ATTRIBUTION

**P3-A — SURVIVES.** Its index is derived, not swept
(`tools/p3a_opt.py:64-66`: `exits = 32 + max(0, 32-n4)`;
`idx_valu = g + 2*exits`), and both legs of the L4 trade are charged in the
same `evaluate()` call (`folds = sum(n * (2**L - 1))`, `loads = 8*g + 60`).
Reproduced exactly by an independent per-round derivation. Two imprecisions,
neither binding at its optimum:
1. the exit surcharge is hardcoded `+2`, correct for a 4-bit pack from the
   root but 1 short for the 5-bit pack that arises if L4 is served in
   epoch 1 — the model implicitly assigns served L4 to round 15, where +2
   is exact, and round 15 is provably the dominant assignment, so the case
   never arises;
2. `HASH_CORE + FOLDIN = 5,792 vec` (46,336 lane-ops) vs the charter's
   "Hash 46,464" is a BUCKETING difference, not a 128-op error —
   `tools/p3a_mech.py` totals to 59,489 exactly, matching `h058_census`.

**P3-C — DOES NOT SURVIVE on the 946.0 / 937.4 rows.** Two independent
defects, both hiding the design:
1. **`idx_slack` is a free additive constant.** `p3c_design_cost.py`
   computes `sl = lane_ops/VLEN - iv` once against the SHIPPED design and
   adds it to `index_cost()` for EVERY design in the 405k enumeration. At
   the 5,888 target the constant is negative and is granted to designs that
   cannot produce it — e.g. "serve L1-L3, gather all L4" genuinely costs
   6,656. The 946.0 and 937.4 rows are not designs; they are the shipped
   design with a discount.
2. **`index_cost` is level-indexed with expectation smearing.** Using
   `d.p(succ)` for both the r=3 and r=14 L3->L4 transitions and `d.p(pred)`
   for the r=4 L4->L5 transition credits a served L4 group-round with
   -2 vec-ops of index, where the true values are 0 (round 4) and -3
   (round 15). The dominance of round-15 serving is invisible to it.

Net: at as-built support the joint model reads **953** where P3-C reads
964.8 (-11.8); at support-free it reads **939** where P3-C reads 950.6
(-11.6). Roughly 78 vec-ops of that is the round-15 index credit the model
cannot see; the rest is P3-A's T3 + store-broadcast + setup-70 levers,
which P3-C does not model at all. **P3-C's served-level-SET conclusion
still stands** (L1-L3 full + partial L4 is optimal; L5+ loses by 30-47);
its per-EPOCH resolution is what fails.

**The brief's suspicion — that both models swept index and serving
independently — is HALF right.** P3-C did (defect 1, mechanically
verifiable in its source). P3-A did not.

## 5. Secondary questions

### T2 coverage (P3-C's open assumption behind 946.0)

The retained-parity ring must hold 4 loose bits at the joint optimum
(epoch 2 serves L4), so per live group: P0..P3 + val + nv = 6 vectors,
vs the packed `st` design's 3. Using P3-C's scratch model
(`24K + 16*table_entries + 285`, which reproduces the measured 1,533 at
K=32/te=30 exactly):

| K | packed `st` | T2 ring (6 vec/group) |
|---|---|---|
| 32 | 1,533 | **2,301 — over by 765** |
| 24 | 1,341 | 1,917 — over by 381 |
| 16 | 1,149 | **1,533 — fits, 3 words spare** |
| 11 | 1,029 | 1,293 |

So 100% coverage is scratch-feasible, and only at **K <= 16**. P3-C's
census-neutrality claim for K is correct as stated (K enters only the
scratch term of its model). Three caveats, in decreasing severity:
* **G-33 / H-059 measured that every W < 32 LOSES on realized cycles**
  (W=24 -> 1045, W=16 -> 1097) because the valu floor RISES as liveness
  falls — the 5.93/6 occupancy is what funds the alu_offload race. That is
  a realized-cycles finding and is out of scope for the Phase-3 census bar,
  but it is a strong prior against ever realizing this design.
* K < 32 is charter frame #4 and has never been tested. It remains the
  largest untested assumption, exactly as P3-A said.
* headroom at 940 is 16 vec-ops, so coverage must be ~95-100%. Phase-1
  shipped 20-43 rings (H-045/H-048); the gap between "20 rings" and "100%
  coverage" has NOT been costed, and at 160 vec-ops of support the design
  is 953, not 939.

### T3 (`add_imm` -> alu): LEGAL, correctly priced, load-bearing

* flow `add_imm(dest, a, imm)` writes ONE scratch word (problem.py:332) —
  scalar, as P3-A says.
* alu `+` takes two SCRATCH operands (problem.py:243-276): **there is no
  alu immediate form.** Each immediate must occupy a scratch word, and
  `load const` (problem.py:309) is the only constant materialiser — a LOAD
  slot, on the engine that is saturated at 1,878/1,880.
* the workaround is already in the kernel: perf_takehome.py:1053 —
  *"va addresses (ivp + 8g) on the ramp-idle alu as four parallel +32
  chains, not 32 serial add_imm on the 1-wide flow engine"*. The four
  `add_imm` sites (perf_takehome.py:1102, 1114, 1164, 1209) all use
  immediates in arithmetic progression (`1+blk`, `2**L4-1+blk`,
  `2**d-1+off`), so one live stride constant funds the chain. Setup slack
  is >= 494 cycles (G-37), so chain latency is free.
* pricing: 20 alu slots = 20 lane-ops; P3-A charges `ADDIMM_ALU_VEC = 3`
  vec = 24 lane-ops. Conservative by 4.
* load-bearing confirmed independently: with T3 off the joint optimum is
  941, not 939.

## 6. THE 940 ANSWER

**Yes — a simultaneous sub-940 design exists, and P3-A's C1\* is it.** But
its margin is one cycle and it needs FOUR legs at once:

| leg | if it slips | cost |
|---|---|---|
| T2 parity ring at ~100% coverage | 62 vec of support | +6 cyc |
| setup at 70 vec (shipped 83) | | +1 cyc |
| T3 `add_imm` -> alu | | +2 cyc |
| ideal fold spelling (no `race_sel` subtracts) | 4% overhead | +4 cyc |

Any two of these slipping puts the floor above 940. And 939 is a FLOOR:
shipped regret is 11-15 cycles, and at this design load and flow bind
EXACTLY, so realized would be ~950-960 (both P3-A and P3-C say this
independently, and G-36 says a lower floor is not automatically a win).

**Under the Phase-3 acceptance bar as written, C1\* passes and is now
confirmed by an independent joint model. Under a realized-940 bar, it does
not.**

## 7. Dead ends / what I did not do

* did not re-derive hash, wrap, or the served-level shape (closed).
* did not schedule anything; no realized-cycle claim is made here.
* mixtures of 3+ group-schedules were not enumerated (only pairs). With
  two constraints binding at the optimum, pairs are sufficient by LP
  vertex-counting; a third binding constraint could in principle admit a
  3-way mixture, worth at most ~1 cycle. Untested.
* the "serve round 15 instead of round 4" re-assignment is a CENSUS
  finding. Its realized-cycle effect is unknown and the shipped allocator
  caps final-round serving at 5 groups; do not treat 624 lane-ops as 10
  cycles.

---

# ADDENDUM (P3-D, after G-38): reconciliation with the measurement

**Headline: my index prediction was exactly right; my "identical folds"
premise was wrong; and C1\* does NOT survive. Corrected joint floor 945-946,
not 939. 940 is NOT cleared.**

Tool: `tools/p3d_attrib.py` — monkeypatches `dev.ListScheduler.put`, builds
`l4_gmin=(6,31)` and `(32,6)` ring-free with `reverse_newest_parity_fold=()`
at both ends (the builder's exact apples-to-apples pair), and DIFFS every
emitted slot by (call-site chain, engine, opcode). Reproduces G-38's
aggregates exactly: alu 11841->10737, valu 6059->6169, flow 843->820,
load 1892->1900, alu+valu 60,313 -> 60,089 (-224).

## 1. The +110 valu is NOT new work — 138 vec-ops of it is a spelling swap

Top two site pairs in the diff, both `vec("^", vl, vl, nvsrc)` (the hash
fold-in, dev.py:3213 and :3218):

```
 +784 lane   +98 slots  valu ^   <lambda>:1873 <- _round_stage_generator:3213
 -784 lane  -784 slots  alu  ^   <lambda>:1873 <- _round_stage_generator:3213
 +320 lane   +40 slots  valu ^   <lambda>:1873 <- _round_stage_generator:3218
 -320 lane  -320 slots  alu  ^   <lambda>:1873 <- _round_stage_generator:3218
```

1,104 alu slots -> 138 valu vec-ops. Identical op count, identical lane-ops
(1,104 -> 1,104). **This accounts for the ENTIRE -1104 alu delta and +138 of
the +110 valu.** It is the `alu_offload` retire race re-equilibrating —
H-053's "freeing valu RAISES valu, lowers alu", run backwards. G-38 read the
two engine counters as if they were work; they are a spelling.

Consequence: G-38's inference #3 ("the index work that disappears is
alu-hosted; alu had ~90 cycles of slack") is **false**. The index work that
disappears is valu-hosted. The alu drop is hash xor moving OFF alu.

## 2. The index credit is real and is exactly the predicted number

```
 -184 lane  -23 slots  valu multiply_add  race_idx_madd:1977 <- _round_stage_generator:3301
 -192 lane  -24 slots  valu -             <lambda>:1873      <- _round_stage_generator:3305
 -160 lane  -20 slots  valu multiply_add  race_idx_madd:1977 <- fold_position:1982
  -48 lane  -48 slots  alu  +             race_idx_madd:1977 <- fold_position:1982
  -48 lane  -48 slots  alu  <<            race_idx_madd:1977 <- fold_position:1982
                                                   TOTAL  -632 lane-ops
```

dev.py:3301-3305 is the epoch-exit gaddr reconstruction. **Predicted -624,
measured -632.** The `-3 madds per group-round moved to round 15` credit is
CONFIRMED by direct call-site attribution. G-38's "the saving is -224, not
-624" conflated the credit with an unrelated cost.

## 3. The genuine residual: +488 lane-ops of SERVING work

```
 +168 lane  +21 slots  valu multiply_add  _sched_madd:790 <- <lambda>:1891
 +120 lane  +15 slots  valu multiply_add  dual_fold:1916  <- <lambda>:3118
  +72 lane   +9 slots  valu multiply_add  dual_fold:1916  <- _round_stage_generator:2972
  +64 lane   +8 slots  valu multiply_add  dual_fold:1916  <- _round_stage_generator:2921
  +40 lane   +5 slots  valu multiply_add  dual_fold:1916  <- _round_stage_generator:2971
  +24 lane   +3 slots  valu multiply_add  race_sel:1940   <- _round_stage_generator:3146
                                                   TOTAL  +488 lane-ops
```

All `first_fold` / `dual_fold` / `w_fold` / `race_sel` — the L1-L3 tournament
and the L4 pair tournament. **No alu counterpart at any of these sites**, so
this is genuinely more ops, not a re-spelling. **Serving an L4 group-round at
round 15 costs ~2.35 vec-ops MORE of fold machinery than serving one at round
4** (~2.96 after correcting for `(32,6)` serving 26 where `(6,31)` serves 27
— that is also the whole of the +8 loads, so load-neutrality per group-round
IS confirmed).

My model charged both positions the same `2^d - 1 = 15` nodes. That premise
is falsified. Why round 15 is dearer is not fully closed; the strongest
candidate is that the L4 pair tournament's shared inputs (`st` folded to
b0b1b2b3, the L3 winner) are by-products the group needs ANYWAY at round 4
because it continues to round 5, whereas at round 15 nothing else consumes
them (`perf_takehome.py:1494`: st is not folded on the last round), so they
must be materialised for the tournament alone.

## 4. DOES C1\* SURVIVE? NO.

`tools/p3d_joint.py` re-solved with a per-round-15-served-L4 penalty:

| penalty (vec-ops/gr) | provenance | min feasible C | census | r15 served |
|---|---|---|---|---|
| 0.00 | P3-D as written | **939** | 56,296 / 1,878 / 939 | 29 |
| 2.35 | measured, uncorrected | **945** | 56,654 / 1,890 / 945 | 28 |
| 2.96 | measured, serve-count corrected | **946** | 56,719 / 1,892 / 946 | 27 |
| 4.00 | pessimistic | 948 | 56,840 / 1,896 / 948 | 14 |

**CORRECTED VERDICT: C1\* does not clear 940.** At 940 it is over by
254-319 alu+valu lane-ops (4.2-5.3 cycles) and over on load and flow too.
The corrected joint floor is **945-946**. Note the optimizer still serves
27-28 at round 15 — the index credit is real and still worth taking, it is
just no longer worth 9 cycles.

This lands on **946.0**, which is exactly P3-C's best-case cell. The two
models now agree, from opposite directions.

## 5. Artifact or intrinsic? Partly open — but it does not rescue 940

* It is **NOT** the `depth_first_fold` / `leaf_dead_temp_a/b=None`
  degradation. The apples-to-apples pair ran `reverse_newest_parity_fold=()`
  (b3_last OFF) at BOTH ends, so the safe-fallback path is not taken in
  either build. That artifact is real but it is in the `safe b3l` rows
  (1358 cycles), not the 1190 row.
* It **is** partly a spelling knob. dev.py:3118 chooses
  `w_fold = vsel | dual_fold | madd` from `flow_first_fold_level_set` and
  `pair_tournament_race_pair_indices`, and `dual_fold` emits 2 valu ops where
  `madd` emits 1. Those knobs were tuned at `l4_gmin=(6,31)` and were NOT
  re-tuned at `(32,6)`; +15 of the +61 vec-ops sit on `dual_fold` at that one
  site. An implementation that re-tunes the pair-index set at round 15 would
  recover some of it. **But even recovering ALL of the dual_fold rows
  (+296 of the +488) leaves penalty ~1.2 vec-ops/gr -> C = 942**, still
  above 940. There is no re-tune that restores 939.

## 6. What this changes in the main body above

* Section 1's "identical folds, identical loads" is **WRONG on folds**
  (right on loads). Read it as: identical fold NODE COUNT in the abstract
  `2^d - 1` model, +2.4-3.0 vec-ops/gr in every measured spelling.
* Section 1's actionable corollary (move the 26 to round 15 for -624
  lane-ops) is **retracted** — G-38 is correct as a mainline verdict. The
  -632 lane-op index credit exists but is paid back 77% by fold machinery
  and, on realized cycles, is catastrophic (1026 -> 1190) for reasons
  (drain-window placement, ring plan invalidation) that are outside the
  census frame entirely.
* Section 3's JOINT OPTIMUM row stands as the *model's* answer at penalty 0
  and is superseded by the penalty-2.35/2.96 rows.
* Section 6's "THE 940 ANSWER: yes" becomes **NO**: 945-946, on all three
  engines, with the round-15 index credit taken and priced.

## 7. Methodology note (LOOP.md 0a, again)

I priced a design in undifferentiated lane-ops and asserted a spelling-level
equivalence (`2^d - 1` nodes wherever the level occurs) that I never
measured. The index half of the prediction was exact; the half I assumed was
wrong by 77% of the credit. **The lesson is not "engine floors are the wrong
metric" — it is that a census model must be calibrated per SITE, not per
LEVEL, whenever the same level occurs at two different points in the
schedule.** Both P3-A's and P3-C's models share this defect and both are
now known to be optimistic on round-15 service.
