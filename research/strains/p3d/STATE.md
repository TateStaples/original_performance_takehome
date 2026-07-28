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
