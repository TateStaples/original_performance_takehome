# Strain: flow-balance

## Charter
Move work off the saturated valu/alu engines (98.2%/94.6%) onto the 30%-idle
flow engine and the load/store slack; exploit placement freedom the current
kernel leaves unused. Owns code regions: tournament select/cond blocks in
emit_group_round, ListScheduler placement policy.

## Frontier
**1107** (flag-gated, MAINLINE CANDIDATE) @ `vsel_auto=(1,2,3)` +
`pool_sizes=(16,3)` + `l4_gmin=(20,29)` on top of mainline
(tournament_levels=(1,2,3), alu_offload=True, parity_conds=True, skew=(4,3)).
Correct (fresh random data each measure); scratch 1519/1536 (17 free);
default path + build_kernel dispatch verified BIT-IDENTICAL to the 1130
mainline; all 9 submission tests green. l4_gmin=(18,29) ties at 1107.

## Assigned
- H-001 (iter 1): parity-vector conds — kill cond-extraction masks. DONE, accepted at strain level (1130).
- H-017 (iter 2): madd->vselect first-fold flip. DONE: hard flip REJECTED
  (all 15 level-subsets lose, +6..+66), but the schedule-aware AUTO variant
  (= H-007's mechanism applied to first-folds) WINS: 1130 -> 1107 (-23).
Queued: H-007 (extend auto-placement beyond first-folds), H-006 (load-side), H-009, H-011.

## Iteration log
(append-only)
- iter 1 (H-001): parity_conds — 1140 -> 1130 (-10), correct, zero scratch.
  The prime variant (per-group parity rings) is infeasible: needs 848+ words,
  1 free. Landed a zero-scratch reformulation instead: newest parity rides
  nv[g] (dead between served rounds), the p := 2p+b accumulator madd LAGS one
  round into the next tournament block (madd(st,st,two,nv) before nv is
  clobbered), older-bit conds extract from the round-START-ready lagged st,
  and at L4 b2 lands at bit0 (raw 0/1 for the U-madds — the >> dies). The L2
  b0-copy moved to flow as vselect(c,st,st,st) (pure copy). Op deltas: alu
  -1144 lane-slots, valu -81 slots, flow +64; alu 94.6->87.0%, valu 98.2->
  97.8%. WHY ONLY -10 (predicted -40..-120): the eliminated ops were mostly
  absorbed by alu slack, and valu THROUGHPUT is now the binding floor —
  6634 valu slots / 6 = 1106 cycle-equivalents vs 1130 actual. Chain
  shortening (madd conds ready at round start, ~2 links off each tournament
  round) bought little because the schedule is throughput- not latency-bound
  at current l4_gmin. Verdict: mainline-candidate (strictly <1140, gated,
  default untouched).

- iter 2 (H-017): madd->vselect first-fold flips. Two flags landed in
  `build_kernel_scheduled`, both default-off, default stream verified
  bit-identical, grader 9/9:
  * `vsel_folds` (hard flip, levels {1,2,3,4}; level tables store odd
    VALUES instead of diffs — same scratch minus the setup subtracts):
    REJECTED. Every subset loses: (1,)=1136 (2,)=1138 (3,)=1148 (4,)=1149
    (1,2)=1138 ... True=1196 (vs 1130). Windowed profile shows why: flow's
    64% idle is ANTI-correlated with tournament rounds (flow sits at
    66-92% exactly in the fold windows, near 0% in gather stretches), and
    a skew block's 8 groups' folds become ready in the same ~2-cycle
    window, serializing on the 1-slot flow engine while each fold heads
    that group's 12-op hash chain. Full flip: valu 6634->6203 slots but
    flow 402->962 (80.4%, local windows at 100%) -> +66 cycles. G-4's
    serialization mechanism, now measured precisely. l4_gmin re-sweep
    under (4,) moves the optimum to LESS L4 service ((24,30)=1143) —
    opposite of P-3's hope; skew re-sweeps all lose too.
  * `vsel_auto` (schedule-aware per-fold placement, levels {1,2,3}: keep
    BOTH diff and odd tables — funded by one cond-pool slot, (17,3)
    measured == (17,4) == 1130 — and emit each first-fold on flow ONLY if
    its earliest slot strictly beats valu's): ACCEPTED at strain level.
    (1,)=1129 (2,)=1125 (3,)=1125 (1,2)=1122; (1,2,3)+pools(16,3)=1117;
    tie-break rules: cs<cm best (cs+1<cm: 1120, cs<=cm: 1119). P-3
    CONFIRMED under auto: l4_gmin optimum shifts to serve MORE epoch-0 L4
    groups — (20,29)=(18,29)=**1107** (-23). skew (4,3) stays best;
    (8,2)/[0,3,6,9] within +2 at earlier tunings. In the 1107 schedule 243
    of 448 candidate folds flip (the greedy takes flow only where it's
    locally free); valu 6634->6439 slots (96.9%), flow 402->645 (58.3%),
    valu floor now 6439/6 = 1073 cycle-equivalents vs 1107 actual.
  Scratch: 1519/1536 (17 words FREE — first headroom since iter 0).
  Verdict: `vsel_auto=(1,2,3), pool_sizes=(16,3), l4_gmin=(20,29)` is a
  mainline candidate (-23); `vsel_folds` kept in-tree as the measured
  negative control (driver may graveyard the hard-flip variant).

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
- P-1 [-> strengthens H-007, cost S]: madd->vselect flip for tournament
  first-folds, now nearly free under parity_conds: replace D_vecs (odd-even
  diffs) with O_vecs (odd values) at setup — SAME scratch — and emit
  W[t] = vselect(b3, O[t], E[t]) on flow instead of madd(b3, D[t], E[t]) on
  valu; conds are raw parities (nv), ready at round start. l4 alone moves
  8 madds x 14 group-rounds = 112 slots off the binding valu engine (~19
  cycle-equivalents); L1/L2/L3 first-folds add 448 more candidates. Flow is
  at 35.6% (1-slot engine, ~730 free slots). G-4's serialization loss does
  not directly apply (W's are dependency-independent), but per-group flow
  serialization must be schedule-aware — flip a SUBSET, largest-win-first.
- P-2 [-> H-004, cost M]: valu madd diet. valu throughput is the floor now
  (6634/6 = 1106). Biggest remaining Idx/Routing madds: the lagged fold
  madd(st,st,two,nv) per tournament round (~384 slots) and the epoch-exit
  gaddr conversions. Attack: absorb the fold into the exit conversion
  (st kept as parities-in-registers until exit, exit becomes a 2-3 madd
  Horner chain — op-neutral at L3 but frees the per-round fold), or absorb
  2p+b into the gather-address madd on the r->r+1 boundary.
- P-3 [sweep, cost S]: re-run the l4_gmin/skew grid AFTER any madd->flow
  flip lands: serving more l4 groups costs valu madds today, so (22,28) may
  shift once W-folds ride flow; l4_gmin=(32,32) (no l4 service) measured
  1180 and (0,0) measured 1253 under parity_conds — the optimum sits in a
  valu-vs-stall trade that P-1 directly relaxes.
  [iter 2: CONFIRMED for vsel_auto — (22,28) -> (20,29), part of the -23.]
- P-4 [-> H-007 proper, cost M]: generalize dual placement. `dual_fold`
  races valu-vs-flow per op at emission; the same try-both-engines pattern
  applies wherever two encodings exist: (a) partial-L4 auto — the 17 free
  words fund odd tables for 2 of the 8 W-pairs (8 words/pair), each pair =
  15 group-round folds; (b) reverse races (mandatory vselect -> madd when
  flow is locally full) work only where conds are 0/1 AND both arms'
  diffs are precomputable — L3's q0/q1 conds are 0/1 under parity_conds
  but their arms are runtime values, so this needs a scheduler-level
  mechanism, not tables; (c) fold `_sched_vec`'s alu-split race and
  `dual_fold` into one ListScheduler `emit_any(encodings)` primitive.
- P-5 [sweep, cost S]: the 1107 config has 17 free scratch words and CP=2
  after the two pool trades — re-sweep pool_sizes shapes under vsel_auto
  ((16,3) beat (17,3) by 2 at (20,28); interaction is nontrivial), and add
  vsel_auto subsets x l4_gmin x skew to the standing sweep grid.
- P-6 [graveyard candidate]: hard `vsel_folds` (any level subset) — keep
  measured evidence: flow idle is anti-correlated with fold readiness;
  reopen only if flow gains slots (never) or fold conds become ready
  round-early (H-002-class latency change landing WITH valu relief).
