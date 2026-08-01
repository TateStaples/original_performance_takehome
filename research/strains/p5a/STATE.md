# P5-A: exhaustive budget inversion for 904 (with-idx) / 889 (no-idx)

Status: FINAL (all five questions answered; tools reproducible)
Scout: P5-A, 2026-08-01. Brief: enumerate the feasible worlds — which proved
frames must break, in what combination, for the 904/889 frontier to exist.
Tool: `tools/p5a_budget.py`.

## 0. Inputs (cited)

Capacity at C cycles: alu+valu 60C lane-ops (12 alu + 6 valu x 8 lanes),
load 2C, flow C, store 2C slots. (problem.py SLOT_LIMITS; census convention
of tools/h058_census.py.)

Proved terms in OUR regime:
- hash(k) = 4,224*k lane-ops; k=11 -> 46,464 (RESEARCH.md census table;
  528 vec-ops per hash-op unit: 512 group-rounds + fold-in scaling, the
  "-528 vec-ops per removed op" law from the Phase-5 charter).
- index floor 6,608 lane-ops at today's policy (P3-B,
  research/strains/p3b/STATE.md); 5,888 under b=0 (round-15 L4) policy, but
  P3-D RETRACTED the net credit: the round-15 serving penalty
  (+2.35..2.96 vec-ops/served-gr) cancels most of it. A g-coupled optimistic
  law 8*(448 + 1.31g) reproduces P3-D's derived 5,960 at g=227.
- serving: min folds F(g) by the 2^d - 1 law (P4-B re-proof: lane-uniformity)
  serving the cheapest levels first; inventory per level d: 64 group-rounds
  for d<=4 at 2^d - 1 folds, 32 for d in 5..10. Our shape (g=229):
  1,109-1,139 folds + g omf selects, all flow-eligible at 1 slot else 1
  valu vec-op (P3-A T1; P3-B round 2: omf is fungible, count = g exactly).
- setup ~600 lane-ops + 22 flow + 60 load slots (h058_census.py measured
  616/22/60; brief says use ~600).
- loads: 8 per gathered group-round + 60 setup (measured 1,892 = 229*8+60).
- stores: 46 (never binding; cap 2C).
- Serving SUPPORT arithmetic set to 0 in the base inversion — deliberately
  frontier-favorable; P3-E measured the realizable support residual at ~97
  vec-ops (ring ceiling 62.5%), which is why OUR floor is 944-952 while the
  same terms price at ~937-939 support-free.

## 1. With-idx tail (design; costing in section below)

Contract: final indices (256 words) at mem[mem[5]] = 2054..2309
(problem.py:535,544; header 7 + 2047 forest nodes = 2054). Reference update
(problem.py:519): idx' = 2*idx + (1 if val%2==0 else 2) = 2*idx + 2 - p,
p = post-hash val parity. Round 15 is level 4 (idx in [15,30], gaddr = idx+7
per P3-B bias pin), final level-5 idx in [31,62], never wraps (< 2047).

Minimal per-group compute (32 groups):
- gathered-at-15 group: final = 2*gaddr - 12 - p.
- served-at-15 group: final = 2*pos4 + 32 - p (pos4 from accumulator).
Three vec-ops per group, e.g. p = v&(val, one_vec); pb = v-(p, twelve_vec)
[or +32 variant]; final = madd(gaddr, two_vec, pb). A 2-op form is
IMPOSSIBLE: the needed addend is -p-12 (parity coefficient -1), and P3-B
Lemma 1 (all 2^32 constants) proves the one-op parity output set is exactly
{p, p-2, p*2^31} with coefficient +1 only.

Census delta:
- valu: 96 vec-ops + 1 vbroadcast = 776 lane-ops
- alu: 32 addr adds (group_addrs pattern, perf_takehome.py:1851-1859;
  consts g*8 already cached by the value-store path) = 32 lane-ops
- load: +1 const; store: +32 vstores; flow: 0
- TOTAL alu+valu +808 lane-ops = +13.5 cycles of combined-engine floor.
- Scratch: temps ride dead st_g vectors; 32 addr scalars + 8 const-vec words
  need dead scalar words (k/rec/sh pools are dead by the drain) — scratch is
  1533/1536 so this is reuse, not fresh allocation. CAVEAT: liveness argued,
  not machine-checked.

Realized bound: measured by injection into the captured schedule
(tools/p5a_tail.py, backtrack_sched capture + offline greedy). RESULT: see
section 5.

## 2. Feasibility grid (tools/p5a_budget.py, full output reproducible)

Base: idx = 6,608 (P3-B floor), serving = min folds by 2^d-1 (cheapest
levels first) + g omf selects, SUPPORT-FREE (frontier-favorable), phi = 0
(8 scalar loads per gathered group-round), tail included at 904 only.
Cell = binding engine + overrun in cycles (V = alu+valu, L = load).

C=904 with tail:
g:        0     64    128    192    214    218    229    256    269..512
k=11:  V+8684 V+2148  V+526  V+134   V+93   V+85   L+65  L+150  L+202..+1174
k=10:  V+8614 V+2077  V+456   V+63   V+22   L+15   L+42  L+150  ...
k=9:   V+8543 V+2007  V+386     OK     OK   L+13   L+42  L+150  ...
k=8:   V+8473 V+1937  V+315     OK     OK   L+13   L+42  ...

C=889 no tail: same shape, feasible window k<=9 g in [192,214], overruns
~+3 cycles larger everywhere.

(g < 192 forces L5+ serving: lane-infeasible by hundreds of cycles AND
scratch-infeasible at K=32 — P3-C: no L5-serving design fits SCRATCH 1536.
g > ~218 at 904 / ~214 at 889 is load-infeasible at phi=0: g <= (2C-60-
tail)/8.)

## 3. Minimum miracles (the headline result)

Layered verdicts (every idx law x serving law x k, from the tool):

**904 with-idx:**
- k=11, idx=6,608, ANY serving cost including FREE: INFEASIBLE — lanes over
  by +4.0 cyc. hash 46,464 + idx 6,608 + setup 600 + tail 808 = 54,480 >
  54,240 = 60*904. **No serving innovation whatsoever rescues an 11-op
  hash at 904.**
- k=11 + idx broken to 5,888 (b0): needs phi >= 0.179 load contiguity too
  (at g=259); and the b0 policy's measured round-15 penalty (P3-D
  retraction, +2.35-2.96 vec/served-gr) would re-add ~+9 cyc. => k=11
  needs >= 3 simultaneous breaks, two of them proved floors.
- k=10: ONE extra break — load contiguity phi >= 0.039 at g=226 (about 9
  group-rounds' worth of vload-able gathers) — then feasible with ~66 cyc
  lane slack.
- **k=9: FEASIBLE ENTIRELY IN-REGIME**, g in [191,218], lane slack up to
  55.5 cyc — enough to pay P3-E's ~13-cyc support residual AND the 11-15
  cyc realized regret. A 9-op hash makes 904 REALIZABLE inside our design
  space with no other frame broken.

**889 no-idx:** identical structure: k=11 infeasible (+5.5 cyc, even with
free serving; 46,464+6,608+600 = 53,672 > 53,340); k=10 needs phi >= 0.066
(at g=228); k=9 feasible in-regime, g in [192,214], slack 44.5 cyc.

**Q5 sensitivity bracket:** min k with (i) our serving law: 9 (both
targets); (ii) free-serving fantasy: 10 (both; k=11 still fails on
hash+idx+setup alone). With idx ALSO at 5,888: k=11 squeaks in at 8.0/6.5
cyc slack — but only in the double-fantasy world. **So the gap CANNOT come
from serving innovation alone; the hash term must shorten (k<=10 with load
innovation, k<=9 clean), or the per-walker-per-round evaluation frame
itself must break.**

Corroboration: the public 904-889 = 15 delta matches our independently
derived minimal tail (13.5 cyc census floor + 3-5 chain; section 5) —
consistent with the frontier paying a tail like ours, i.e. their no-idx
core is the real object at ~889.

## 4. No-idx relief for OUR kernel: EXACTLY 0

Derived from zero, as instructed:
- The final index is the level-5 index after round 15; NOTHING in our
  kernel computes it: round-15 index cost measured 0.00 (P3-B attrib),
  mechanism perf_takehome.py:1494/1604-1605.
- Rounds 10-15 index-maintenance ops, itemized by consumer: r10->r11 wrap =
  0 ops (deterministic); r11->r12..r13->r14 = 1 parity/gr each, consumed by
  the NEXT round's tournament (serving position), not by any final-index
  path; r14->r15 = gather-address madds for the 31 round-15 gathered
  groups, consumed by round-15 loads; r15 = 0.
- The only stores are 32 value vstores (val_addrs = group_addrs(
  "inp_values_p"), perf_takehome.py:1863,1991) + 14 setup/priming stores =
  46 measured; nothing targets 2054..2309 (charter bookkeeping discovery:
  inp_indices_p appears only in a debug map).
=> Not one op exists solely for the final-index contract. **Our no-idx
relief is 0; the public 15-cycle delta is entirely the cost OTHERS pay.**
Our 1006 is already a no-idx artifact; with-idx costs us +tail, no-idx
costs us nothing.

## 5. Realized tail cost (injection measurement): +16 cycles

`tools/p5a_tail.py`: backtrack_sched.capture() of the mainline-equivalent
dev build (1031 cycles); offline greedy reproduces the capture EXACTLY
(1031 = 1031, model soundness confirmed); append the 161 tail ops
(1 vbroadcast + 32 x [v&, v-, madd, alu addr, vstore]) in emission order
with real val_g/st_g/one_vec/two_vec operand words (gaddr reads omitted --
provably never binding, produced before round-15 loads which feed the
round-15 hash that produces val_g); re-greedy.

  baseline 1031 -> extended 1047 non-empty cycles. **REALIZED DELTA +16.**

Census delta: +97 valu vec-ops (+776 lane-ops) + 32 alu + 32 store +
0..1 load = **+808 lane-ops = +13.5 cycles of combined floor**; realized 16
= 13.5 floor + ~2.5 drain-chain (last val write is at cycle 1029/1031, and
the last groups' val->p->pb->final->vstore chain extends the drain; early
groups' tails DO ride idle slots from cycle 0 onward).

Cross-checks: public paired with/without deltas run 9-23; the frontier's
own delta is 15; ours measures 16. Board eligibility: mainline 1006 no-idx
+ tail ~= **1022 with-idx** (vs stale 1038 entry) if implemented as-is.

## 6. Conclusions (decision-ready)

1. **904 with-idx at k=11 (our hash) does not exist in any serving world:**
   hash 46,464 + idx floor 6,608 + setup 600 + minimal tail 808 = 54,480 >
   54,240 lane-ops even with serving compute at literal zero. The only k=11
   escapes break >= 3 frames at once (idx floor to <= 5,888 AND phi >= 0.18
   load contiguity AND free-support serving) — two of the three are floors
   proved by enumeration (P3-B) or measurement (P3-E).
2. **The minimum miracle for 904** is ONE frame: hash at 9 ops/round
   (feasible in-regime, 55-cyc slack covering support residual + regret),
   or TWO mild ones: 10-op hash + phi >= 0.039 contiguity (~9 group-rounds
   of vload-able gathers).
3. **The minimum miracle for 889** is the same shape: k=9 clean (44.5-cyc
   slack) or k=10 + phi >= 0.066.
4. **No-idx relief for our kernel is exactly 0** — the 15-cycle public
   delta is entirely the tail cost others pay; we already play the no-idx
   game. Our with-idx entry costs +16 realized (~1022 today).
5. "k" here means EFFECTIVE hash vec-ops per 528-unit; a break of the
   per-walker-per-round evaluation frame (kf>=3 cross-round MITM, batched
   rounds) enters this arithmetic identically as k < 11. P5-B's funded
   hash search and P5-C's serving/load mechanisms are the two live routes;
   this inversion says P5-B needs k<=10 AND P5-C needs only phi ~ 0.04-0.07
   (not a serving-compute revolution) IF k=10 exists; if only k=11 exists,
   the frontier is outside BOTH and the evaluation frame itself must fall.
