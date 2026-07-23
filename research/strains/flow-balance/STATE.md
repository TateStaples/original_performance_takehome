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
- H-006 (iter 4): load-side demand reduction, measurement first. DONE:
  REJECTED/closed permanently (honest negative, see iter 4 log). No kernel
  change; measurement tool `tools/measure_gather_dist.py` landed.
- H-023 (iter 5): b3-last final-round fold reversal. DONE: REJECTED
  (honest negative, see iter 5 log). Flags `b3_last`/`b3l_race` landed
  default-off, default stream bit-identical, grader 9/9 @ 1070. The
  reversed fold shortens the post-parity chain as designed (~17 -> ~11)
  and is bit-identical in RESULT to the b3-first tree, but it floods the
  1-slot flow engine (G-4/G-12) and, when raced onto valu, doubles the
  fold ops (sub+madd) -- the drain GREW (66 -> 113/250 empty valu at r15).
Queued: H-007 (subsumed in practice by emit_any — driver may close),
H-009, H-011.

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

- iter 4 (H-006): load-side demand reduction — CLOSED NEGATIVE by
  measurement, no kernel change (perf_takehome.py untouched; grader 9/9 on
  the unchanged mainline). Four independent kill shots, all at the graded
  shape (fh=10, bs=256, r=16):
  1. GATHER-ADDRESS DISTRIBUTION (`tools/measure_gather_dist.py`, 50 random
     instances): lane-order contiguity of a group's 8 gather addresses is
     0.00% at EVERY round (contiguous-SET <= 0.5%, and only at L3 which is
     already tournament-served) -> vload-batched gathers are dead. Within-
     group duplication at the gather levels is the uniform-draw expectation:
     0.86 dup/group (L5), 0.45 (L6), 0.23 (L7), 0.12 (L8), 0.06 (L9), 0.03
     (L10) -> even a hypothetical input-dependent dedup router would save
     <1 load slot per group-round, and NO input-dependent scheme is legal
     (kernel is built before data; grader runs fresh seeds). Cross-group:
     L5's 32 structural nodes are always all hit (256 walkers), L6 63.1/64.
     Only structural facts (2^d distinct nodes at level d) are exploitable.
  2. NO SCRATCH-INDEXED SCRATCH ACCESS (verified in problem.py
     Machine.load/flow, not just isa.md): every scratch operand of every op
     is a literal instruction field; the ONLY data-dependent addressing is
     through MEM (`load`: mem[scratch[addr]]; `store`; `vload/vstore` with
     scalar base). So values parked in scratch can reach walkers only via
     select folds = the tournament; and a mem-table lookup costs exactly
     the 1 load slot/walker the gather already pays. Table service cannot
     beat gathers on load slots without eating the fold tree.
  3. TOURNAMENT WALL RE-MEASURED under the full iter-3 racing stack
     (parity_conds + vsel_auto + emit_any + u_race + l4_race + idx_race):
     l4_gmin=(0,0) [full L4 service, -328 load slots] = 1145 (+75), seeds
     1 and 7 identical. G-9-era cost was 1270 vs 1140 (+130): the wall
     MOVED ~55 cyc — racing service keeps getting cheaper — but the
     pre-registered "try L5-partial if ~1100" threshold is NOT met.
     Decomposition: (0,28)=1096 (+26, epoch 0), (13,0)=1120 (+50, epoch 1),
     additive. Marginal curve around the swept optimum (13,28)=1070:
     (12,28)=1071, (11,28)=1072, (9,28)=1077, (0,28)=1096; other side
     (15,28)=1080, (13,26)=1075. So (13,28) is a true local min and the
     MORE-service side is nearly flat: the first extra groups cost ~+1
     cycle per 8 load slots freed. L5 service was NOT coded, by
     arithmetic: 16 W + 8 U + 4 + 2 + 1 = 31 folds + ~4 conds ~= 35
     valu/flow ops per group-round to free the same 8 load slots — 2x
     L4's exchange rate at a point where L4's own margin already loses.
  4. WINDOWED PROFILE (the sharpest new fact): load runs at 100.0% busy
     for cycles ~100-950 — an 850-cycle fully saturated wall — and valu
     AND alu are also ~100% there. The aggregate 89.8% load util is an
     artifact of setup/tail slack; mid-kernel the machine is TRIPLE-
     saturated (load+valu+alu). Load already IS a wall locally; every
     service variant loses because it relieves load by ADDING valu ops
     inside that same window. Only demand REMOVAL (any engine) or
     end-window shifting can shorten it.
  Pair-gather reopen check (G-3): free scratch at the 1070 config is 6
  words (kb.scratch_ptr 1530/1536; the 17 free at 1107 were spent on
  l4_race odd tables) vs >=256 required — NOT met; loads are slot-
  contention-bound, not latency-bound (G-11), so the vload pair-fetch
  variant (children 2i+1/2i+2 are ADJACENT, one vload/walker is demand-
  NEUTRAL and issueable a round early) buys latency nobody needs, and
  costs 64 live words/group across the boundary (>=512 under skew
  overlap) + 8 scalar flow selects/group-round. Closed without coding.
  VERDICT: H-006 rejected; load-side demand reduction is permanently
  closed EXCEPT through the existing l4_gmin dial, which the standing
  sweeps already re-tune after every accept (P-3 pattern: (22,28) ->
  (20,29) -> (15,29) -> (13,28) as valu was relieved). Endgame note for
  the driver: when op-removal accepts push toward <1000 and load's
  1921-slot demand becomes the strict wall, the dial sheds up to 328
  slots at a price that today starts at ~1 cyc/group and totals +75 —
  and that price FALLS with every valu-relief accept, so no new
  mechanism is needed; H-005/H-022 harvest it for free.

- iter 5 (H-023): b3-last final-round fold reversal — REJECTED, honest
  negative. Flags `b3_last` (False/() off, True = all served-L4 rounds,
  iterable = round numbers) and `b3l_race` (bool, default True) landed in
  `build_kernel_scheduled`, default-off, default stream verified
  BIT-IDENTICAL to HEAD (programmatic kb.instrs compare), grader 9/9 @ 1070.
  MECHANISM (built exactly as chartered, and it is CORRECT — every variant
  passes the frozen grader's fresh-seed check): node_val = E[t*] + b3*D[t*]
  with t* = b0b1b2 the level-3 winner index (all three older bits in `st`
  at round start, b3 = the raw parity riding `nv`, arriving last). Since
  the fold over t is linear and b3-independent, E_vecs and D_vecs are
  folded SEPARATELY by b0,b1,b2 (7 selects each, depth-3 tree) and combined
  by ONE b3-dependent madd. Post-parity chain drops ~17 -> ~11 as designed,
  and NO extra scratch is needed (reuses E_vecs/D_vecs + the 5 tournament
  pool temps; masks recomputed off the idle alu, st left intact for the
  exit). Result bit-identical to the b3-first tree (winner selection is the
  same t*, same node_val) — verified by the grader.
  WHY IT LOSES (the drain did NOT shrink — it GREW):
  * The 14 b0/b1/b2 fold selects have BROADCAST arms (leaf: E_vecs/D_vecs)
    or DEAD-TEMP arms (combine), so they spell only as flow vselects (1
    slot/cyc) or valu sub+madd (2 ops). There is no diff to make them
    1-op valu madds — the b3-first W-madds get that for free from the
    precomputed D_vecs, which fold b3 specifically.
  * Pure flow (`b3l_race=False`): 1104 (+34). The reversed folds of r15's
    4 served groups (28-31) = 56 vselects PIN the flow engine at 1/cyc for
    cycles 1043-1099 (a 56-cycle wall) while valu sits idle — 250 empty
    valu slots at r15 vs the baseline's 66. Textbook G-4/G-12: flow idle
    is anti-correlated with fold readiness, and a served block's folds
    become ready in one narrow window and serialize on the 1-slot engine.
  * Raced (`b3l_race=True`; leaf selects race to valu via a dead-`lv`
    diff temp + sub+madd, combines via `race_sel`, all masks forced to
    exact 0/1 so the multiply-by-cond spelling is sound): 1084 (+14).
    Racing spreads the selects onto the drain-idle valu but each
    runtime/broadcast-arm select is now sub+madd = 2 valu ops: valu census
    6262 -> 6309 slots (floor 1044 -> 1052), still 113 empty valu at r15.
    The "neutral op count (15 vselects vs 8 madds + 7 selects)" premise is
    FALSE once flow can't absorb them: 15 vselects are neutral only if
    flow is free; the valu fallback DOUBLES them.
  * l4_gmin retune under the flag: `b3_last=(15,)`+`l4_gmin=(13,30)` =
    1078 == the *baseline* (13,30) = 1078 (serving fewer r15 L4 groups
    costs +8 with OR without b3_last); b3_last never nets below 1070.
    Sweep: (15,) at gmin r15 in {28,29,30,31} = 1084/1079/1078/1082.
  * Non-final rounds are worse, as the profile predicted (the staircase
    only bites at r15): `b3_last=(4,)` = 1112, `(4,15)`/`True` = 1134 —
    r4 feeds r5 gathers, so deferring b3 delays the epoch-exit gaddr AND
    floods flow (G-1/G-9 territory).
  VERDICT: the r15 drain is chain-LATENCY-bound only while the fold rides
  the 6-slot valu; the moment fold work moves off valu it becomes
  THROUGHPUT-bound on the 1-slot flow engine, and there is no third engine
  with tail slack (alu can't vselect/madd) nor free scratch (6 words) to
  precompute the 8 leaf-diff broadcast tables that would let the b0/b1/b2
  folds ride valu as 1-op madds. The chartered latency win is real and
  unusable. Reopen-if: flow gains parallel slots (never), OR an accept
  frees >=64 scratch words to precompute the leaf-diff tables (then re-cost
  — but even then it is 16 leaf madds + combines vs the b3-first 8 madds +
  7 selects, so likely still valu-heavier), OR a large op-removal accept
  drops valu <90% mid-kernel AND makes the r15 drain the strict binder.
  Flags kept in-tree as negative controls / sweep dimensions.

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
- P-10 [iter 4, graveyard entry for the driver — proposed G-16 text]:
  "Load-side demand reduction beyond the l4_gmin dial (H-006): vload-
  batched gathers (0.00% lane-order contiguity, 50 seeds), input-dependent
  dedup (<1 dup load/group-round at gather levels, and illegal anyway),
  L5/L6 table service (no scratch-indexed scratch read exists; routing =
  31+ folds/group-round = 2x L4's exchange rate; L4-full measured 1145
  (+75) under the full racing stack, vs G-9's +130 — wall moved, sign
  robust), and pair-gather (6 free scratch words vs >=256; loads slot-
  contention-bound per G-11; the demand-neutral vload pair-fetch buys
  non-binding latency for >=512 words + 8 flow selects/group-round).
  Reopen-if: an accept frees >=10% of mid-kernel valu (then the l4_gmin
  dial slides via the standing sweep — no new code), or a sub-960 target
  needs load demand <~1750 (then re-cost L5 at the then-current racing
  exchange rate; today's honest price is ~35 valu/flow ops per 8 slots)."
- P-11 [iter 4 coordination note -> driver/op-reduction/scheduler]: the
  windowed profile shows an 850-cycle mid-kernel window (cycles ~100-950)
  where load, valu AND alu are ALL at 100.0% (flow 30-94%); every free
  slot of the three binding engines lives in setup (0-100) or drain
  (950-1070). Consequences: (a) an op-removal accept on ONE engine only
  moves cycles once the other two shed proportionally — H-016 hash hits
  (alu 10224 + valu 4582 slots) are the right shape, pure-alu or pure-load
  diets are not; (b) after any hash-op removal, load's 1700-slot share of
  that window becomes the strict wall and l4_gmin must slide down in the
  SAME retune (its marginal price is ~1 cyc per 8 slots today and falls
  with valu relief); (c) H-021's scheduling-slack harvest is bounded by
  the drain tail (~120 cycles at <=90% load/valu) more than by mid-kernel
  friction — shortening the pipeline fill/drain (skew shape, store
  placement) is where the last ~26 cycles over the valu floor sit.
- P-12 [iter 5, graveyard entry for the driver — proposed G-17 text]:
  "b3-last final-round fold reversal (H-023): defer the newest parity b3
  to a single final madd by folding E_vecs and D_vecs separately over the
  older bits b0,b1,b2 (`b3_last`/`b3l_race` flags, default-off, bit-exact).
  Post-parity chain shortens ~17 -> ~11 and the result is grader-verified
  bit-identical, BUT the 14 reversed-fold selects have broadcast/dead-temp
  arms with no precomputed diff, so they only spell as flow vselects
  (1-slot, serialize: r15 pins flow 1043-1099, 250 empty valu, +34) or
  valu sub+madd (2 ops each, +47 valu census, +14). The 'neutral op count'
  fails: 15 vselects are neutral only if flow is free. l4_gmin retune ties
  the worse baseline (b3_last=(15,)+(13,30) = 1078 = baseline (13,30));
  non-final rounds worse ((4,) 1112, True 1134 — delays the epoch exit +
  floods flow, G-1/G-9). Confirms G-4/G-12 from the drain side: the moment
  fold work leaves the 6-slot valu it becomes throughput-bound on the
  1-slot flow, and alu can't vselect/madd. Reopen-if: flow gains parallel
  slots (never), OR >=64 scratch words free to precompute the 8 leaf-diff
  tables so the b0/b1/b2 folds ride valu as 1-op madds (re-cost; likely
  still valu-heavier than the b3-first 8-madd tree), OR a large op-removal
  accept drops mid-kernel valu <90% AND the r15 drain becomes the strict
  binder (then the shorter chain pays for the extra valu ops)."
- P-13 [iter 5 -> scheduler/driver]: the r15 drain (13 cyc, 66 empty
  valu, the g28->g31 ~5-cyc staircase) is confirmed UNMOVABLE by fold
  restructuring alone: the last block's served-L4 chains are the binder,
  and any reshaping that trades valu madds for flow selects hits the
  1-slot flow wall. The staircase is fundamentally that r15 has no next
  round to overlap AND its 4 served groups' nv (b3) arrive staggered
  because upstream is throughput-saturated. Two untried angles that do NOT
  fight the flow wall: (a) SKEW-SHAPE so the last block ends on a GATHER
  round (short chain) not served-L4 — but epoch phasing is fixed by
  rounds=16 (only l4_gmin=(.,32) tests it, +16 on gathers > the 13 saved,
  H-021 already measured this negative); (b) do NOT serve L4 at r15 at all
  (l4_gmin=(13,32)) and eat the +16 gather cost — measured worse. So the
  drain tail is genuinely load-bound-elsewhere; the ONLY lever left on it
  is a global op-removal accept (H-016) that lowers the valu floor so the
  whole tail shifts left. No flow-balance mechanism reaches it."
