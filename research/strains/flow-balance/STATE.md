# Strain: flow-balance

## Charter
Move work off the saturated valu/alu engines (98.2%/94.6%) onto the 30%-idle
flow engine and the load/store slack; exploit placement freedom the current
kernel leaves unused. Owns code regions: tournament select/cond blocks in
emit_group_round, ListScheduler placement policy.

## Frontier
**1070** (flag-gated, MAINLINE CANDIDATE) @ `u_race=True` + `l4_race=3` +
`idx_race=True` + `l4_gmin=(13,28)` + `pool_sizes=(16,4)` on top of the 1088
mainline (tournament_levels=(1,2,3), alu_offload=True, parity_conds=True,
c5_prexor=True, vsel_auto=(1,2), skew=(4,3)). Correct (fresh random data
every measure, incl. 3 repeats of the winner); default path + build_kernel
dispatch verified BIT-IDENTICAL to the 1088 mainline (programmatic instr
compare vs `git show HEAD:perf_takehome.py`); all 9 submission tests green.
skew=[0,3,6,9] and l4_race=(0,1,7) tie at 1070.

## Assigned
- H-001 (iter 1): parity-vector conds — kill cond-extraction masks. DONE, accepted at strain level (1130).
- H-017 (iter 2): madd->vselect first-fold flip. DONE: hard flip REJECTED
  (all 15 level-subsets lose, +6..+66), but the schedule-aware AUTO variant
  (= H-007's mechanism applied to first-folds) WINS: 1130 -> 1107 (-23).
- H-019 (iter 3): generalize dual placement (emit_any). DONE: 1088 -> 1070
  (-18) via u_race + l4_race=3 + idx_race + retune; emit_any primitive
  landed and dual_fold/_sched_vec unified through it bit-identically.
Queued: H-007 (subsumed in practice by emit_any — driver may close), H-006
(load-side), H-009, H-011, H-018 (idx-madd REMOVAL, now the bigger lever).

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

- iter 3 (H-019): emit_any generalized dual placement. Four pieces landed
  in one pass, all default-off, default stream verified bit-identical,
  grader 9/9:
  * `ListScheduler.emit_any(encodings)`: place ONE of several alternative
    encodings of the same computation, whichever retires earliest (ties ->
    earliest-listed). Encodings are sequences of micro-ops with
    trial-local RAW/WAW/WAR + slot-occupancy tracking, so "1 valu madd" vs
    "1 flow vselect" vs "8 alu lane-ops" vs "valu sub + valu madd" all
    race under one mechanism. `dual_fold` (H-017) and `_sched_vec`'s
    alu-split race now route through it — refactor verified BIT-IDENTICAL
    (same 1088 stream) by construction of the tie-break rules (valu-first
    for folds; alu-keeps-ties behind the `cv > c0` gate for the split).
  * `u_race` (-4 alone, the big enabler): each served-L4 U-combine is
    dst := b2 ? Wa : Wb with runtime arms and an EXACT 0/1 cond, so it has
    a 1-op flow spelling racing the 2-op valu sub+madd (sub also
    alu-splittable; the valu path clobbers the dead Wa). 1088 -> 1084.
  * `l4_race` (partial-L4 vsel_auto): odd-value tables for the FIRST N
    W-pairs (8 words each; select arm = the EVEN word under c5_prexor —
    tables are reversed and odd-based). 22 words were free at the 1088
    mainline -> 2 pairs fit; the 3rd pair is funded by TP 17->16 (8 words,
    measured free at this point). 1088 -> 1086 alone; pairs (0,1,2) and
    (0,1,7) tie composed. Funding MORE pairs via a cond-pool trade is DEAD:
    pool_sizes=(17,3) alone costs +30 (1118), so 4+ pairs never pay.
  * `idx_race`: the Idx madd family (lagged p := 2p+b folds, epoch-exit
    gaddr conversions incl. the c5 K-2p' form, gather-mode 2*gaddr+omf)
    gets an alu spelling — per-lane << then +/-, 16 slots over 2 dependent
    levels — raced against the single valu madd. NEUTRAL alone (1088: the
    madd almost always retires no later), -5 composed at the stacked point
    (alu absorbs Idx work exactly where L4 service floods valu).
  * `sel_race` (REVERSE race, flow->valu for L2 copy/final select and L3
    q0/q1): measured NEGATIVE everywhere (+1..+3 on every base tried).
    The symmetric race does not pay: flow's fold-window serialization is
    already what vsel_auto/u_race exploit from the valu side, and adding
    2-op valu spellings for 1-op flow selects only steals valu slots the
    W/U-combines want. Kept in-tree as the measured negative control.
  * Composed + retune: u_race + l4_race=3 + idx_race, l4_gmin (15,29) ->
    (13,28) (P-3 pattern AGAIN: racing relieves valu, so serving more L4
    groups pays), pool_sizes (17,4) -> (16,4): **1070** (-18). Engine
    deltas at 1070 vs 1088: valu 6365 -> 6262 slots (97.5%, floor 1044),
    alu 11497 -> 12057 (88.1 -> 93.9%), flow 558 -> 662 (51.3 -> 61.9%),
    load 89.4 -> 89.8%. The three compute engines are converging — alu is
    now within 6% of saturation, so pure placement racing is near its
    ceiling; ~26 cyc of scheduling slack remain above the valu floor.
  Verdict: mainline candidate `u_race=True, l4_race=3, idx_race=True,
  l4_gmin=(13,28), pool_sizes=(16,4)` (-18); H-019's emit_any is the
  scheduler-level primitive H-007 asked for (driver may close H-007 as
  subsumed).

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
- P-7 [iter 3 -> H-018/H-004, cost M]: alu is the NEW near-binding engine
  (93.9% at 1070; valu 97.5%, load 89.8%). emit_any has largely equalized
  placement across valu/alu/flow, so the next wins must REMOVE lane-ops,
  not move them: the hash's 10.7k alu + 4.5k valu slots (68% of lane-ops)
  are the only pool big enough — H-016's MITM search, or H-004/H-018 idx
  elimination (1057 valu Idx slots at 1070; idx_race showed they only
  RELOCATE for -5, removing them is worth up to ~29 cyc).
- P-8 [sweep, cost S]: add u_race x l4_race(N and index subsets) x
  idx_race x l4_gmin x pool_sizes to the standing grid under the 1070
  config; l4_gmin moved (15,29)->(13,28) this iter, and every new race
  flag has shifted it — re-tune after ANY engine-mix change.
- P-9 [graveyard candidate]: `sel_race` (reverse flow->valu race for
  0/1-cond selects): +1..+3 on every base measured (1088 mainline, u_race,
  l4_race stacks). Reopen only if valu gains real headroom (<90%) while
  flow saturates locally — i.e. the exact inverse of today's profile.
