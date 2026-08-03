# Lower-Bound Audit — Summary of Record

*Anthropic Original Performance Take-home · research phases 1–7 · 2026-07-23 → 2026-08-03*

This document summarizes every lower bound the project has claimed, how each
was proved, how each was audited, which fell, and what survives. The one-line
history: **every bound that mattered was wrong at least once, and only
measurement or an adversarial audit found it.** Detailed derivations live in
`research/RESEARCH.md` and `research/strains/*/STATE.md`; refutation records
in `research/graveyard.md` (G-1..G-39).

## 1. The capacity side (verified from simulator source, never overturned)

| resource | per cycle | note |
|---|---|---|
| alu | 12 scalar lane-ops | |
| valu | 6 slots × 8 lanes = 48 lane-ops | combined compute = **60 lane-ops/cyc** |
| load | 2 slots | the only data-dependent addressing (`mem[scratch[addr]]`) |
| store | 2 slots | cannot compute; `src` compile-time |
| flow | 1 slot | the only vector op is `vselect` (lane-aligned, cond ≠ 0) |
| debug | 64 slots | writes nothing the kernel can read |

Capacity at cycle count C: `60C` lane-ops, `2C` loads, `C` flow slots.
At the leaderboard frontier (904 with-idx / 889 no-idx): **54,240 / 53,340
lane-ops total.**

## 2. The demand side — bounds and their fates

### 2.1 Hash: 46,464 lane-ops at k=11 ops/round — the dominant term

- Exact law (settled after two corrections): **hash(k) = 512·k + 176
  vec-ops**; the census already nets ~336 C5-elision vec-ops, so one op
  removed = **4,096 lane-ops (~68 cycles)**, not 4,224.
- k=11 is the shortest known form. Search record over nine phases, all
  negative: segment-exhaustive fusion (~400B), boundary MITM (2.36T),
  full-hash MITM depth ≤7 (2.9T), kf3-full-shape + chains (≥4 × 2.1B nodes),
  kf4 shards, join-at-4 fan-out MITM ×4 join types (63 slices), round12
  y-fanout (46/48), vocabulary gap (`// % cdiv`) exhaustive, arbitrary-const
  MCMC (30B+ proposals; engine *proved* able to rediscover the real 11- and
  12-op forms from scratch), CEGIS (span7→5 all-UNSAT; 9-op deletion shapes
  9,285+ shift-combos UNSAT), sandwich9 ~895/961 pairs dead by two exact
  theorems + realizability arithmetic + z3, shape-complete enumeration of all
  458,161 candidate 9-op shapes with 49.23% of 2.87M instances mass-killed.
- **A lower-bound *proof* is formally barred** (P3-F): bit-dependency,
  degree, and alternation invariants all saturate at 1–2 ops (explicit
  witnesses). Unconditionally provable: N ≥ 2. N ≥ 11 holds only under a
  stage-respecting hypothesis — the "(S)-gap," which is exactly the space
  enumeration cannot reach (1.145 × 10¹² wiring shapes at n=10) and ~28% of
  the shape queue is undecidable at any feasible compute.
- **Status: k=11 stands for every reachable space; unprovable globally.**

### 2.2 Index maintenance: 6,608 lane-ops floor

- Charter originally claimed 8,192 (2 vec-ops × 512). **Wrong by 24%**
  (P3-B): only 448/512 group-rounds emit index work (wrap and final round
  are free by level-alignment); cost is transition-dependent (1 op when the
  successor is served, 2 when gathered, k when packing).
- Proof grade: 1,548,224 structural one-op forms enumerated (0 solutions);
  the complete single-op parity set over **all 2³² constants** is
  {p, p−2, p·2³¹}; carrying the address is the *unique* zero-extra-op affine
  representation (all rebiasings +1,280 lane-ops; memory-table advance
  +1,280 loads — circular without base+displacement addressing).
- Audited by: P4-B/P4-C adversarially; P6-A premise table (violation would
  need a 77–87% cut — "very low"); the hybrid/offload question closed by
  fungibility (dominance theorem: offload ties or loses at every cycle
  target; flow never has an idle slot at any load-feasible shape).
- **Status: survived every audit unchanged.**

### 2.3 Routing / serving: 1 load or 2^d−1 selects per lane-set

- Original proof: no permute, no scratch-indexed read. **Audit upgraded the
  proof** (P4-B): the per-lane reachable set is ≤16 at every level, but it is
  *never lane-uniform* (0/256 group-rounds share an ancestor at any level
  ≥3) — tournaments read broadcast vectors, so the width is forced by
  lane-uniformity, not by the missing shuffle.
- Serving-shape optimum closed by exhaustion (~405k designs): L1–L3 full,
  partial L4, gather L5–L10 — the shipped shape. Cross-checked against
  corsix's published cost table (ours is slightly cheaper: T1 difference
  tables make interiors 1 op vs his "flow or 2 valu").
- **Status: survived; proof sharpened.**

### 2.4 Load: 8 scalar loads per gathered group-round

- vload requires contiguity; measured natural contiguity **0.003** vs the
  0.039 needed; every sorting route dies to the rank lemma (prefix sums ≈
  160 vec-eq + 512 stores/pass); the sorted-children merge property is real
  (0/1400 violations) but unaffordable.
- **Status: survived (P6-A: violation "impossible — 0 loads still fails").**

### 2.5 The realized floors — where the audits drew blood

| claimed floor | fate |
|---|---|
| engine slot floors as scoring metric | **retired** (G-26): schedule is RAW-bound; freeing all 7,051 vector ops bought 30 cycles |
| 931.6 "ideal floor" (H-044) | **wrong by ~80** — double-subtracted gather combines, dropped setup (H-058) |
| 1,015 / 1,081-style load-count floors | **artifacts** — hold the gather count fixed; corsix publicly confirmed sub-1000 is legit |
| C1* at 939 (two models converging) | **phantom, twice**: G-38 measured the round-15 premise at +164 realized; P3-D retracted (945-946); P3-E ring-coverage cap made it 948 |
| C1* implementable (T2 −2,072 lane-ops) | **phantom** (G-39, built and measured): Horner-at-exit costs exactly the upkeep it deletes; P3-A's 35-exit count was really 63; the never-read set is 1 group-epoch |
| Phase-3 structural floor **944–952**, realized ~965–970 | **stands** — three independent models converged *after* their shared-frame errors were removed; independently validated by a 966 no-idx entrant sitting exactly at the predicted realized ceiling |
| shipped 1006 as local optimum | **verified at the shipped stream itself** (P7): 31-axis retune = 0 moves; emission enumeration inherited at the bit-identical config |

### 2.6 The frontier inversion (what 904/889 *require*)

- **k=11 is infeasible at both targets even with serving, index, and setup
  priced at zero** (P5-A; hardened +2.1/+4.3 by P5-F's re-derivation; all
  six premises audited — three "impossible as explanations even when free,"
  the rest verified from source).
- k=10 + every legitimate trim: still short by 13–15 (P5-E — the ~170-vec
  trim does not exist; the hash slider correction went adverse).
- **Conclusion: the frontier runs effective k ≤ 9.75 — or something outside
  every frame nine phases have named.** The ε-approximate-validator escape
  was investigated and is **empty** (the MCMC battery was ε-blind, so its
  29.5B negatives already cover ε ≤ 3×10⁻³; deletion forms measure ε ≈ 1).
  The 2-round composite ≤19 is **refuted for all decomposable mechanisms**
  (seam-cancellation theorem; madd↔σ commutation only at K ≡ ±1 mod 2^s,
  failed by both real pairs).

## 3. Audit machinery — the rules the errors bought

1. **Score against realized cycles, not engine floors** (a lower floor
   measured worse three separate times).
2. **A relaxation oracle must hold the program fixed** (adaptive scheduler
   races make freed builds emit different programs — produced a phantom −13).
3. **Convergence between models is not evidence when the models share a
   frame** (the 939 died to this twice); only measurement breaks the tie.
4. **Calibrate per-site, not per-level** (the defect class found three times).
5. **Guard every theorem numerically before mass application** — the w=14
   form-guards caught **three false theorems** that would have over-killed.
6. **Plant positive and negative controls in every searcher** before
   trusting its negatives (STOKE's controls later *upgraded* its negatives
   when the engine rediscovered the real forms from scratch).
7. **Seam-cancellation screening** for any representation-change proposal
   (every GF(2)-linear conjugation yields an op-identical chain).

Corrections tally: the ledger records **seven+ major self-corrections**,
each found by audit or measurement, none by re-argument.

## 4. Current standing

| | ours (verified) | frontier | gap |
|---|---|---|---|
| no-idx | **1006** (graded, 9/9) | 889 | −117 |
| with-idx | **1034** (dev flag pair, values+indices 10/10) | 904 | −130 |

Open audit surfaces still being worked: the (S)-gap (t3 composite wave B —
the first properly-configured search of that space), the scheduler-
conservatism audit (P7-C, in flight — whether our dependency model demands
more separation than the simulator's true commit semantics), and the
finite grind tails (sandwich9 ~66 pairs, template stragglers, fleet 46/48).

**Bottom line: the lower-bound structure is internally consistent, has
survived adversarial audit at every load-bearing joint, and says the
leaderboard frontier is doing something no reachable search can exhibit.
The bounds are honest; the mystery is real.**
