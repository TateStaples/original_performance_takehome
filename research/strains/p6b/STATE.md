# Strain P6-B — the ε-AUDIT (Phase-6 R1)

Brief: do ε-APPROXIMATE short hash forms exist — programs of <=10 ops agreeing
with `myhash` on all but a fraction ε of the 2^32 inputs, for ε in the window
[1e-8, 3e-3] that our exact tools reject but a sampling validator would accept?
This decides whether premise P8 can explain the 904/889 frontier.

Status: **FINAL for sub-audits 1, 2, 3.**  Verdict: **NOTHING FOUND WITHIN
~2.5 DECADES; P8 is NOT REFUTED but is NOT SUPPORTED EITHER — it survives only
as a bare possibility in the same unsearched space the exact question lives
in.**  Tools (all read-only, reproduce every number below):
`tools/p6b_eps_frontier.py`, `tools/p6b_eps_realizability.py`,
`tools/p6b_deletion_eps.py`.

---

## 0. THE ORGANISING PRINCIPLE (new, and it is what makes sub-audit 2 exact)

Every exact refutation on record is of the form "*myhash has property X;
every form of shape S lacks X*".  A shape-S form g that is ε-close to myhash
still lacks X **exactly** — so the refutation survives ε iff **myhash is
Hamming-far (in inputs) from the nearest X-satisfying function**:

> **ε_crit(class) = E_min / 2^32,  E_min := min #input-changes that would give
> myhash property X.**  The pair stays refuted for ε < ε_crit and RE-OPENS at
> ε >= ε_crit.

This converts every "does the kill survive ε?" question into an exactly
computable minimum-repair-cost.  All numbers in sec. 2 are computed this way,
not estimated.

---

## 1. SUB-AUDIT 1 — MINING THE STOKE EVIDENCE.  Result: the cascade evidence
## is VACUOUS, but STOKE's battery is itself an ε-ACCEPTING validator and it
## never fired once.

### 1.1 Did any candidate ever reach the 65,536 tier?  **NO — none ever reached
### even the 256 tier, on any real target.**

`zero_hits` (stoke.rs:1269, incremented at :1224 and :1364) counts
battery-perfect candidates *entering* the cascade, i.e. every candidate that
reached tier 1.  Ledger (research/strains/p5h/STATE.md, CHECKPOINT lines):

| campaign | slots | seed | proposals | best_err | zero_hits | finds |
|---|---|---|---|---|---|---|
| t2 (round body) | 12 | 11 | 782,663,680 | 179 | **0** | 0 |
| t2 | 13 | 12 | 1,290,919,936 | 296 | **0** | 0 |
| t1 (myhash 11->10) | 11 | 41 | 1,496,383,488 | 0 @ 11 ops | **0** | 0 |
| t3 (2-round composite) | 20 | 51 | 529,391,616 | 329 | **0** | 0 |
| s9 (real sandwich9) | 12 | 31 | 11,578,351,616 | 336 | **0** | 0 |
| s9 | 12 | 32 | 9,308,127,232 | 337 | **0** | 0 |
| s9 | 12 | 50 | 4,474,568,704 | 333 | (ckpt only) | 0 |
| cal (PLANTED control) | 12 | 3 | 227,500,032 | 0 @ 10 ops | **2** | **2** |

**~2.95e10 proposals on real targets, zero_hits = 0 everywhere.**  Only the
planted calibration ever entered the cascade.  So the charter's argument
("STOKE would have logged a 65k-passer that failed 10M, and none was logged")
is *true but vacuous*: nothing ever got past the chain-local battery, so the
65k->10M tier never adjudicated anything.  Note also the JSON checkpoint
`tools/p5h_ckpt_s9_s12.json` records an **eighth slice (seed=50, 420s, 4.47B
proposals, best 333)** that never got a CHECKPOINT line in p5h/STATE.md.

### 1.2 The genuinely useful fact: the chain battery ACCEPTS the whole ε-window

Battery = `make_battery(camp, 0, 42, true)` (stoke.rs:1292) = `edge_values()`
= 8 specials + 3*32 shift-boundary values + 12 REAL_CONSTS = **116 values**;
for ni=1 targets (t1, s9, cal) that is **B = 116 vectors**, for ni>=2 (t2, t3)
two vectors per edge value, **B = 232**.  An ε-form is battery-perfect
(`err_bits == 0`, stoke.rs:517) with probability (1-ε)^B:

| ε | B=116 (t1/s9) | B=232 (t2/t3) |
|---|---|---|
| 1e-5 | 0.9988 | 0.9977 |
| 1e-4 | 0.9885 | 0.9771 |
| 1e-3 | 0.8905 | 0.7924 |
| 3.3e-3 | 0.6817 | 0.4648 |

**STOKE's objective is ε-BLIND in the target window**: `err_bits` sums
`count_ones` over the battery, so it scores an exact form and an ε<=1e-3 form
*identically at 0* with probability 0.46-0.89.  Consequence: had MCMC ever
*visited* a <=10-op ε-form in [1e-8, 3e-3], `zero_hits` would have ticked with
probability >= 0.46.  It never ticked.  **So the P5-H negatives are already
ε-tolerant negatives** — they are reachability statements about ε-forms just
as much as about exact forms.  The strongest single one is **t1**: cold chains
sat on the correct 11-op form for 480 s / 1.50e9 proposals exploring its
rewrite graph and never produced a <=10-op battery-perfect (hence never an
ε<=1e-3) neighbour.

### 1.3 Per-bit vs per-input: what the checkpoints can and cannot tell

`err_bits` conflates them (1 input wrong with full avalanche ~= 16 bits ==
16 inputs wrong in 1 bit each).  The checkpoints store only the aggregate
(`best_cost`, `best_err`, `best_nonnop`); **the best program's listing is NOT
written to the JSON** (only validated `finds` are), so the best t2/s9 forms
cannot be re-measured for their true per-input ε.  What the aggregate does
give, rigorously, is a *lower* bound on the number of wrong battery vectors,
`ceil(best_err / 32)`:

| campaign | best_err | bits in battery | >= wrong vectors | => ε on battery >= |
|---|---|---|---|---|
| t2 s12 | 179 | 232*32 = 7424 | 6 | 2.6e-2 |
| t2 s13 | 296 | 7424 | 10 | 4.3e-2 |
| t3 s20 | 329 | 7424 | 11 | 4.7e-2 |
| s9 s12 | 333-337 | (midpoint cost, not output bits — see caveat) | 11 | 9.5e-2 |

Caveat: the s9 campaigns minimise the MITM *midpoint* cost
(`s9_err`, stoke.rs:874), not output Hamming, so its row is not an output-ε.
For the free-shape campaigns the reading is sound: **the best form MCMC ever
reached disagrees with the round body on >= 2.6% of its battery — 0.9 decades
above the 3.3e-3 ceiling and 3.4 decades above 1e-5.**  Correcting the
brief's premise: 179/1024 was a mis-sized battery; the true figure is
179/7424 bits = 2.4% bit error, i.e. ε >= 2.6e-2, not ε ~ 0.17.

**Sub-audit 1 verdict: no ε-evidence either way from the cascade (it never
ran), but MCMC's own ε-accepting battery never fired in 2.95e10 proposals.
The searched families contain no MCMC-REACHABLE ε-form; this is a
reachability negative of exactly the same strength as P5-H's exact negatives
(weak for s9 by its own planted control, strongest for t1).**

---

## 2. SUB-AUDIT 2 — THE ε-REFUTATION FRONTIER FOR sandwich9 (exact)

`tools/p6b_eps_frontier.py` (one 2^32 numpy sweep, 48 s; re-derives
N_myhash = 2,172,911,616 = 2^18 * 8289, matching p5i sec 9) and
`tools/p6b_eps_realizability.py` (drives `p5i3_arith.decide_pair` over the
ε-widened N-window).  Key kinematic fact used throughout: **one wrong input
moves N by exactly ±2** (flipping out_0 at x flips the differential D at both
x and x^2^31), so |N_g - N_myhash| <= 2E with E = ε·2^32.

### 2.1 ε_crit per refutation class

| class | pairs | argument | E_min | **ε_crit** |
|---|---|---|---|---|
| sec 1 window (s1+s2<=30) | 435 | out_0 constant on cosets mod 2^(L+1) | N/2 = 1,086,455,808 | **0.2530** |
| sec 2 row-31 | 30 | out_0 must FLIP under x^2^31 for all x | (2^32-N)/2 = 1,061,027,840 | **0.2470** |
| sec 3 (31,1) | 1 | H must be constant | 1,061,027,840 | **0.2470** |
| sec 3 row-32 | 13 | P_{s1} table must be constant | see below | **6.1e-5 .. 0.124** |
| sec 9 diff-count | 68 | 2^(33-s2) \| N_g | ceil(dist/2) | **3.05e-5 .. 0.247** |
| sec 12 realizability | 136 | (q,n_1) unrealizable | window sweep | per-pair |
| sec 5 z3 | 207 | sample-UNSAT, n=34, rung k=8 | *not a full-domain argument* | probabilistic |

sec 1 is monotone: min(#0,#1) over a coarser partition >= the sum over the
refinement, so s1+s2 = 30 (cosets {x, x^2^31}) is the WEAKEST case — every one
of the 435 holds to ε = 0.253.  Same for sec 2/(31,1) at 0.247.

sec 3 row-32, pair (s1, 32-s1), E_min = min(popcount(P_{s1}), 2^{s1}-popcount):

| pair | (30,2) | (29,3) | (28,4) | (27,5) | (26,6) | (25,7) | (24,8) | (23,9) | (22,10) | (21,11) | (20,12) | (19,13) | (18,14) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ε_crit | .124 | 6.2e-2 | 3.1e-2 | 1.5e-2 | 7.5e-3 | 3.9e-3 | 1.8e-3 | 9.8e-4 | 4.3e-4 | 2.1e-4 | 1.2e-4 | **6.1e-5** | **6.1e-5** |

((18,14): both branches cost 2^18 — the const branch needs P_19 constant
(E_min = 262,144) and the anti branch needs P_19 anti-symmetric under
x -> x^2^18, and myhash has P_18 == 0, i.e. ZERO of the 2^18 pairs differ, so
that branch also costs 2^18.  The script's printed "E_min for that branch = 0"
is a mislabel of `min(ones,2^18-ones)`; the correct anti-branch cost is
2^18 - ones = 262,144.)

sec 9, ε_crit = ceil(dist(N, 2^(33-s2)Z)/2)/2^32:
s2=1 -> 0.247;  s2=2..7 -> **2.96e-3**;  s2=8..9 -> **9.46e-4**;
s2=10..14 -> **3.05e-5**.

sec 12 (136 exact kills, all s2>=15), pair stays dead iff EVERY multiple of
2^(33-s2) within 2E of N_myhash is unrealizable — measured, not estimated:

| ε | sec-12 kills still valid | re-opened | inconclusive |
|---|---|---|---|
| 1e-6 | **133 / 136** | 3 | 0 |
| 1e-5 | **117 / 136** | 19 | 0 |
| 1e-4 | **86 / 136** | 50 | 0 |
| 1e-3 | 36 / 136 | 88 | 12 |

(Much more ε-robust than the naive window argument suggests: the realizability
window is centred and narrow, so most neighbouring N values are *also*
unrealizable.)

sec 5 z3 (207 pairs): `p5i_z3pair.battery` = 6 edges + 16 random + 12
structured congruent = **n = 34 fixed inputs**, constrained on `out mod 2^8`.
This is NOT a full-domain refutation: an ε-form escapes a given pair's UNSAT
iff one of the 34 samples lies in its error set, P = 1-(1-ε)^34.
Expected pairs escaping, of 207: **0.007 at 1e-6, 0.070 at 1e-5, 0.70 at
1e-4, 6.9 at 1e-3, 22.0 at 3.3e-3.**  Caveat: 6 of the 34 are edge inputs, so
an ε-form whose error set is carry-pathological could correlate; the bound is
probabilistic over sample randomness, not adversarial.

### 2.2 THE LEDGER, RE-RUN AT EACH ε (961 pairs)

Exact ledger (p5i sec 12.4): 961 = 479 (secs 1-3) + 207 (z3) + 68 (sec 9)
+ 136 (sec 12) + 71 open.  Cross-check by parsing the 457 CHECKPOINT lines in
p5i/STATE.md: 207 REFUTED, and exactly **10** of the 78 sec-9-scope pairs
(s2<=14, t>=1, s1<=30, non-row-32) were z3-refuted => 68 new.  Reconciles.

| ε | secs 1-3 | z3 (207) | sec 9 (68) | sec 12 (136) | **total refuted** | live space |
|---|---|---|---|---|---|---|
| 0 (exact) | 479 | 207 | 68 | 136 | **890** | 71 |
| 1e-6 | 479 | 207 | 68 | 133 | **887** | 74 |
| 1e-5 | 479 | 207 | 68 | 117 | **871** | 90 |
| 1e-4 | **477** | 207 | **20** | 86 | **790** | **171** |
| 1e-3 | 476 | ~200 | 20 | 36 | ~732 | ~229 |

Derivations for the ε=1e-4 row: (18,14) and (19,13) lose sec 3 (ε_crit
6.1e-5) AND sec 9 (3.05e-5) and are in no z3 CHECKPOINT line => 2 re-open from
the 479.  Of the 68 sec-9 kills, the 50 pairs with s2 in 10..14 lose the
congruence; 2 of those ((29,14),(30,13)) are z3-backed, leaving 48 re-opened
=> 20 survive (all s2 in 2..9, ε_crit >= 9.46e-4).

**Answer to the brief's question: 887 / 871 / 790 of 961 remain refuted at
ε = 1e-6 / 1e-5 / 1e-4.**  The charter's "204 pairs re-open under ε" is a
worst-case ceiling; the true count is **3 at 1e-6, 19 at 1e-5, 100 at 1e-4**
(50 from sec 12 + 48 from sec 9 + 2 from sec 3), on top of the 71 that were
never refuted at all.

### 2.3 Are the re-opened pairs searchable?  Sketch + cost.

A relaxed z3 objective ("agree on >= (1-ε) of samples") is a **cardinality**
constraint, not a conjunction: encode 34 Booleans a_i = (g(x_i) == h(x_i)) and
assert `PbGe([(a_i,1)], 34-k)`.  With ε <= 3e-3 and 34 samples the expected
number of allowed misses is 0.1, so the honest relaxation is **k = 1** —
which is 34 separate "which sample is allowed to fail" branches, i.e. **34x
the solve time of an already-560s-per-pair problem** (p5i sec 11's z3 wall).
At the observed wall this is ~5.3 h/pair x 100 pairs = **530 CPU-hours**, and
the *exact* problem at k=0 is already timing out — so a majority-relaxed CEGIS
is strictly harder and is NOT worth running.  **Not run** (correctly: a k=1
relaxation that TIMES OUT decides nothing, and the k=1 relaxation cannot even
express ε<3e-2 faithfully at n=34).  The cheap, faithful alternative is to
re-run the *count* arguments at higher precision (done above) — they are
exact and free.

---

## 3. SUB-AUDIT 3 — CONSTRUCT OR REFUTE A CHEAP ε-FORM.  Result: every
## single-op deletion of the real 11-op form is wrong on >= 99.95% of inputs.

`tools/p6b_deletion_eps.py`.  The reference form (stoke.rs:378-395, constants
at :361) verified to reproduce `myhash` exactly on the sample.  For each of
the 11 ops: delete it (op becomes the identity on one operand; BOTH wirings
tried for the 3 binary ops), then hill-climb **all 12 constants** (384 bit
coordinates, 3 restarts x up to 8 sweeps, primary objective = #disagreeing
inputs, Hamming tie-break for gradient) to MINIMISE disagreement on 4,096
random inputs.

| deleted op | 0 madd | 1 shr19 | 2 xorC | 3 xor | 4 madd33 | 5 madd16896 | 6 xor | 7 madd9 | 8 shr16 | 9 xorC | 10 xor |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **min ε̂** | 1.000 | 1.000 | 1.000 | **0.99951** | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 0.99976 |

Best over all 11 deletions and both wirings: **4094/4096 wrong, ε̂ = 0.9995**;
the residual bit-Hamming sits at 0.487-0.495 (i.e. random) except op-10-wire-0
which reaches 0.25 bit-error while still being wrong on 100% of inputs.
**Gap to the 3.3e-3 acceptance ceiling: 2.5 decades — and to 1e-5, 5 decades.**

Algebraic corroboration for the most "nearly absorbable" deletion (op 9, the
final xor-const): S16(v) = v ^ (v>>16) is a GF(2)-linear involution, so
compensating C11 requires the preceding madd to produce e ^ a with
a = S16(0xB55A4F09) = 0xB55AFA53.  P5-L2's lemma says v^y == v+f(y) only for
y in {0, 2^31}; approximately, e + a == e ^ a on exactly a 2^-popcount(a)
fraction => ε >= 1 - 2^-popcount(0xB55AFA53).  There is no near-miss here by
construction, and the measurement agrees.

Item (b) of the brief (cheaper multiplier) is void — a multiplier costs 1 op
regardless.  Item (c) (round-0-only 30-bit-domain specialisation) is SOUND,
not ε, and belongs to R2 — **noted, not duplicated here.**

---

## 4. THE ε-DOSSIER — VERDICT

**NOTHING WITHIN 2.5 DECADES, in every direction we can measure; but the
question is NOT CLOSED, and the reason it is not closed is exactly the reason
the exact question is not closed.**

1. **Constructive search (STOKE):** 2.95e10 proposals across 7 real-target
   slices with a battery that *accepts* the entire ε-window with probability
   0.46-0.99 — `zero_hits = 0`.  No ε-form was ever visited.  Strongest slice
   (t1, transformation mode around the true 11-op form): no <=10-op ε-near
   neighbour exists in its MCMC-reachable rewrite graph.
2. **Direct construction (deletions):** min measured ε = 0.9995 over all 11
   single-op deletions with all constants re-optimised.  2.5 decades above the
   ceiling.
3. **Exact structures under ε (sandwich9):** ε-tolerance costs us 3 / 19 / 100
   pairs at ε = 1e-6 / 1e-5 / 1e-4.  **887 / 871 / 790 of 961 stay refuted**;
   the 71 never-refuted pairs dominate the live space at the two smaller ε.
   ε-tolerance does NOT open a new frontier — it slightly widens an already
   open one.
4. **What this does and does not say about P8.**  It does NOT refute P8: no
   argument here excludes an ε-form of a shape nobody enumerated (the same
   (S)-gap that keeps P1 alive).  It DOES remove P8's advertised advantage —
   the claim was "four decades of forms exist that WE discard and a sampling
   validator would bless".  **Those four decades are empty of everything we
   can reach**, and every tool we own (STOKE's battery included) already
   *accepts* that band, so the band was never actually being discarded.  The
   only mechanism by which P8 could still explain 904/889 is an ε-form in the
   unsearched non-decomposable space — which is indistinguishable, in
   evidential status, from P1's (S)-gap.

**Recommendation: P8 should be DEMOTED from "the second live premise" to "a
re-labelling of P1's (S)-gap".  Phase-6 effort is better spent on R2 (the
SOUND round-0 30-bit specialisation, ~8.5 cyc) and R3 than on further ε work.
The one cheap ε follow-up that would still add information: re-run 1-2 t1
slices with `--validate-max 10` and an ε-LOGGING cascade (record tier reached,
not just pass/fail), so a future ε-near visit is observable rather than
silently counted.**

### Open / unresolved

- The best t2/s9 programs are unrecoverable (listings not persisted in the
  JSON checkpoints), so their true per-input ε cannot be measured — only the
  `ceil(err/32)` lower bound in sec 1.3.
- The deletion measurement is a LOCAL optimum over 384 bit-coordinates; it is
  an upper bound on min-ε, not a proof.  A z3 MaxSAT over the deletion
  families would make it exact, at unknown (probably prohibitive) cost.
- The 71 never-refuted sandwich9 pairs are unaffected by any of this and
  remain the live exact question.
- Whether the *board* validates on 1 instance or many is still unknown (R4,
  needs user consent).  Nothing in this audit depends on it.
