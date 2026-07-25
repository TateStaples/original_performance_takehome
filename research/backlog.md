# Hypothesis Backlog

Schema per block: id, strain, statement, predicted (gain + mechanism), cost
(S/M/L in agent-iterations), depends, status: open | testing | accepted |
rejected | blocked(H-x) | superseded(H-x), result (measured @ commit), log.
IDs never reused. Driver-only writes; agents propose follow-ups in their
strain STATE.md and the driver promotes them here.

### H-001 [strain: flow-balance] [status: accepted]
- statement: Eliminate/offload tournament condition-extraction ops (`& one_vec`,
  `& 2^k`, `>>`) from valu/alu. Prime variant: keep the last k per-group parity
  VECTORS alive (they are already computed each round for the state update)
  and feed them to vselect directly, instead of packing bits into the position
  accumulator and re-extracting with masks.
- predicted: -40..-120 cyc. Routing+Idx arith on valu/alu today ~3.4k lane-ops;
  every 60 removed ~= 1 cycle; also shortens tournament dep chains.
- cost: M. depends: none. CAUTION: scratch is FULL (1535/1536) — parity rings
  must be traded against pool_sizes/cond pools, not added.
- result: ACCEPTED iter 1: 1130 (-10) via zero-scratch reformulation (parity
  rides dead nv; p-fold lags one round; L4 >> dies). Prime variant (parity
  rings) infeasible (needs 848+ words). Gain under prediction because alu
  slack absorbed most removed ops; valu is now the binding floor (6634/6 =
  1106 cycle-equivalents vs 1130 actual). Mainline flipped; grader 9/9.
- log: 2026-07-23 opened; assigned iter 1; ACCEPTED iter 1, dispatch flipped.

### H-002 [strain: critical-path] [status: rejected -> graveyard G-8]
- statement: Parity-early — produce bit0 of the hashed value (the only bit the
  next gather address needs) cheaper/earlier than the full 12-op hash, so the
  next round's gather issues before the full hash completes. Full hash still
  computed for the value chain. Mod-2^32 structure: low bit of `a*k+C` (k odd)
  is `a0^C0`; xor-shift stages only pull higher bits DOWN into bit0 — bit0 of
  the final value depends on a small subset of input bits; derive the minimal
  boolean chain and cost it.
- predicted: unblocks full-round L4/L5 tournaments (l4_gmin=(22,28) exists
  only because tournaments stall the r->r+1 load stream) + tightens the skew
  pipeline. Even +2 extra ops/walker pays if it removes the stall.
- cost: M-L. depends: none (enabler for H-008).
- result: REJECTED iter 1. Chain EXISTS (depth 8 vs 10, +1 madd, proved
  irreducible) and landed flag-gated (`parity_early`, commit on branch), but
  kernel is valu-THROUGHPUT-bound: all variants 1145-1198 vs 1140. See G-8.
- log: 2026-07-23 opened; assigned iter 1; rejected iter 1.

### H-003 [strain: op-reduction] [status: rejected -> graveyard G-10]
- statement: Machine-search for further hash fusions: extend
  rust_harness/src/problem.rs with a searcher over op-sequences
  (multiply_add/xor/shift/add compositions) equivalent to (a) the 6-stage hash
  (currently 11 mixing ops via the stage2∘3 fusion), (b) hash including the
  `val^node_val` fold-in (12 ops), (c) hash + parity extraction. Bit-exact
  validation over exhaustive-random inputs; any k-op find < current is a
  direct -4096/60 x (saved ops) cycle win.
- predicted: -68 cyc per saved op/eval. Uncertain (may prove 11 minimal —
  that negative result is valuable too: closes the strain's biggest unknown).
- cost: M. depends: none.
- result: CLOSED iter 1 (negative, high-value). ~400B candidates over every
  adjacent-segment cut of the 11-op chain (+fold-in head, cross-round tail,
  parity): NO shorter form (inexhaustive at global scale, exhaustive per
  segment). Byproducts: 2-op parity extractors (hashseg::PAR_D_*/PAR_E_*),
  and the P-1 C5-commute insight -> promoted as H-015. See G-10.
- log: 2026-07-23 opened; assigned iter 1; closed iter 1.

### H-004 [strain: op-reduction] [status: closed (subsumed by idx_race) -> see G-15]
- statement: Fold the idx/state update `p := 2p + b` (one madd per group-round,
  1,000+ madds) into existing ops — e.g. carry position pre-scaled so the
  gather-address madd absorbs it, or derive position bits directly from saved
  parity vectors (synergy with H-001) making the accumulator unnecessary on
  tournament levels.
- predicted: -20..-60 cyc (Idx = 8,592 lane-ops total).
- cost: M. depends: stronger after H-001.
- result: CLOSED iter 3 (combined with H-018). Agent measured madd_x2
  (madd -> self-add+add/sub, auto-gated): best -2 on pre-idx_race base;
  driver did NOT merge — mechanism subsumed by H-019's idx_race (-5 on
  mainline, same madd families; 7-region semantic conflict for ~0 marginal).
  Patch archived: scratchpad/iter3_op-reduction.patch. THE REAL RESULT is
  the arithmetic ceiling: madd->adds trades 1 valu slot for 16 alu lanes;
  equilibrium 2(6365-x) = 11497+16x caps x~68 (floor -> ~1050); and the
  hash kq-madd conversion is strongly negative (+70). Engine REBALANCING
  is measured-exhausted from both directions (H-019 P-7 concurs) -> G-15.
- log: 2026-07-23 opened; iter 3 closed.

### H-005 [strain: sweep] [status: testing]
- statement: Grid-search tunables of build_kernel_scheduled: skew shapes
  (block counts x lags, incl. asymmetric lists), l4_gmin pairs, pool_sizes,
  tournament_levels subsets. Grid auto-grows with every new flag other
  strains land (free cross-pollination).
- predicted: -5..-30 cyc (pure placement); zero LLM cost.
- cost: S (background CPU). depends: none.
- result:
- log: 2026-07-23 opened; background process launched iter 1.

### H-006 [strain: flow-balance] [status: rejected -> graveyard G-16]
- statement: Load-side tricks: vload-batch gathers when 8 walkers' addresses
  are coincidentally contiguous (measure frequency first — the nv-WAR
  instrumentation hook from H-014 measures contiguity too); revisit
  pair-gather IF load stops binding on target rounds (G-3). H-014's result
  says slot DEMAND reduction is the only live load-engine lever.
- predicted: -10..-40 cyc. cost: M. depends: scratch relief — NOTE: 32 words
  now known freeable at zero cost via pool_sizes=(17,3) (H-002 side finding).
- result:
- log: 2026-07-23 opened.

### H-007 [strain: flow-balance] [status: closed, searched, no material
gap found (2026-07-25)]
- statement: Move a schedule-aware SUBSET of tournament folds from valu madd
  to flow vselect — not whole levels (graveyard G-4: full L4-on-flow lost by
  serialization) but per-fold placement chosen by which engine is the cycle's
  binding constraint (extend ListScheduler to try both placements).
- predicted: -15..-50 cyc (valu 98% vs flow 30%). cost: M. depends: none.
- result: PREMISE RE-CHECKED 2026-07-23, NOT CLOSED, NOT IMPLEMENTED.
  At the current best point (idx_select=True, l4_gmin=(9,30), 1043 cyc):
  valu 97.8% busy, alu 95.6%, flow 76.1% (~24% idle) — flow has LESS
  slack than the original -50cyc-era estimate (was ~30% idle) but still
  meaningfully more than valu/alu. However, today's H-020/H-022 resweep
  (u_race/l4_race/sel_race/vsel_auto subsets) found NO further gain,
  which means the EXISTING racing mechanisms (dual_fold, race_sel,
  race_idx_madd, race_leaf, all via emit_any) are already extracting
  what's extractable from the fold SITES they cover. H-007's actual
  remaining opportunity, if any, is in fold sites NOT YET wired into any
  racing mechanism at all — that requires fold-site archaeology (grep
  for hardcoded single-engine madd/vselect calls in the hash/routing
  code that have no emit_any alternative) before there's anything
  concrete to implement or measure. Did not attempt this in the current
  pass — it's a research task (find candidates), not a quick flag test,
  and deserves focused attention rather than being rushed. Recommend as
  the top pick for a dedicated follow-up session.
- FOLD-SITE ARCHAEOLOGY DONE 2026-07-25: read every bare (non-`emit_any`)
  `multiply_add`/`vsel` call in the hash/tournament/idx code. Findings:
  (1) hash-stage multiply_adds are genuinely single-engine (runtime value
  x non-trivial constant, no select-shaped alternative) — already settled
  by H-004/G-15's arithmetic (madd->alu-adds nets +70). (2) `b3l_fold_diffs`'s
  `E + b3*D` combine IS select-shaped (b3 exact 0/1) but its arms are
  per-instance runtime-folded winners, not static broadcast tables, so
  materializing a free "odd" arm costs an extra vec-add that likely erases
  the gain — checked, no zero-cost alternative. (3) L2/L3 combining selects
  are already wired into `sel_race` and measured negative (G-14). (4) L4
  pair-tournament q0/q1/winner selects are genuinely unraced, but their
  conds are raw 0/2/0/4/0/8 masks (not shifted to exact 0/1), so racing
  needs an extra alu shift first — untested but low-value given G-14's
  consistent pattern against reverse races; a ~1hr confirmatory test would
  formally close this corner if anyone wants it done. (5) The forced-alu
  hash xor/shift ops (`avec(...)`, force_alu=True) were re-tested
  un-forced under the current 1043-cycle engine mix: **1105 cycles, a
  clean +62 regression** — confirms forcing alu to reserve valu for
  madds is still correct; NOT a gap.
  CLOSING: no material fold-site gap survives scrutiny. The existing
  racing mechanisms (dual_fold/race_sel/race_idx_madd/race_leaf/emit_any)
  already cover everything algebraically eligible; the two untested
  corners (#2, #4) are low-probability-of-payoff and cheap enough to
  reopen individually if someone wants them formally closed rather than
  reasoned-closed.
- log: 2026-07-23 opened; premise re-checked same day post-H-029; 2026-07-25
  fold-site archaeology completed, closed with no material gap found.

### H-008 [strain: critical-path] [status: rejected -> graveyard G-9]
- statement: Full-round L4 (and L5) tournament service once parity-early
  removes the tournament->load stall (today only groups >=22/28 are served).
  L5 = 16 more madd-combines/group but removes the 1,536 deepest… (recount:
  levels 5..10 gathers) — recost after H-002 lands.
- predicted: -30..-100 cyc. cost: M. depends: H-002.
- result: REJECTED iter 1, tested WITH its enabler: l4_gmin=(0,0) alone 1270,
  +parity_early(3,) 1284, +parity_early(True) 1339. The stall is the 7-level
  select chain on saturated valu/flow, not parity latency. See G-9.
- log: 2026-07-23 opened.

### H-009 [strain: flow-balance] [status: rejected on evidence, not
implemented]
- statement: Cross-round software pipelining of the hash itself: split the
  12-op hash so stages of round r+1 interleave with stages of round r within
  a group (beyond what group-skewing already gives), reducing pool pressure
  and exposing more same-cycle ILP.
- predicted: -10..-30 cyc. cost: L. depends: none.
- result: REJECTED 2026-07-25 via `tools/sched_profile.py --detail 15`
  against the current 1043-cycle mainline, without a full implementation
  attempt (which would have been cost-L for a premise the profile directly
  refutes). 990/1043 cycles (95%) already run at full 6/6 valu occupancy —
  the steady-state mid-kernel region has essentially ZERO empty valu slots
  to expose more ILP into; the gap-blocker histogram's "blocked-on address
  class" shows the dominant RAW-hazard producers (valu:^, valu:multiply_add)
  cluster almost entirely in two regions: the setup ramp (22 empty slots)
  and the final-round drain (r15 L4: 22, r14-15 L3/4: 13) plus the
  store-drain tail (30) -- all structural pipeline-fill/pipeline-empty
  boundary effects that cross-round software pipelining (an in-kernel,
  steady-state technique) cannot address, not evidence of mid-kernel pool
  contention. This is the same "latency-hiding doesn't help when the
  binding constraint is throughput, not latency" pattern H-002/H-008/H-010
  already established for the position-update side; H-009 is the hash-side
  analog and fails for the identical structural reason.
- log: 2026-07-23 opened; 2026-07-25 rejected via profiling evidence
  (sched_profile.py), no implementation attempted.

### H-010 [strain: critical-path] [status: rejected -> graveyard G-13]
- statement: Parity speculation: on rounds where the next level is served
  from scratch both ways cheaply (levels 0..2), compute BOTH children's
  contributions and select late — removes the parity->select dependency
  entirely on those rounds.
- predicted: -10..-25 cyc. cost: M. depends: none.
- result: REJECTED iter 3, honest zero: auto-raced speculation wins only 1-2
  of 64 sites where status quo was ALREADY zero-valu; hard variants +20..+115;
  per-site zero-net-valu fails globally (speculated xors displace alu-offload
  back onto valu at 88% alu busy). spec_fold flag kept in-tree. See G-13.
- log: 2026-07-23 opened; iter 3 rejected -> strain rotated.

### H-011 [strain: flow-balance] [status: blocked (same root cause as
critical-path P-cp-1)]
- statement: Flow-engine parity extraction (H-001 x H-002 combo): if parity
  vectors are kept (H-001) AND parity-early exists (H-002), the `& one_vec`
  per round disappears from valu into either the early chain or a vselect.
- predicted: -15..-35 cyc. cost: S once parents land. depends: H-001 (the
  parity_early flag from H-002 already exists if a latency use appears).
- result: BLOCKED 2026-07-23. This depends on H-002's `parity_early`
  flag, which (per the P-cp-1 re-check done alongside H-029) is
  structurally incompatible with `c5_prexor` (`assert not pe_levels`,
  perf_takehome.py:932) — not a runtime combination issue, an explicit
  guard. Since c5_prexor is load-bearing mainline (H-015), H-011 cannot
  be tested as a simple flag combo; it needs the same reconciliation
  work P-cp-1 flags before either it or its H-002 dependency can be
  re-measured. Not re-attempted this session for that reason.
- log: 2026-07-23 opened; blocked same day, same root cause as
  critical-path P-cp-1.

### H-012 [strain: op-reduction] [status: open]
- statement: Recalibrate rust_harness floors (lower_bound/breakdown/hybrid)
  after each accepted structural change so `predicted` fields stay honest;
  publish the new floor table in RESEARCH.md.
- predicted: n/a (calibration). cost: S. depends: any structural accept.
- result:
- log: 2026-07-23 opened.

### H-013 [strain: sweep] [status: open]
- statement: After ANY accept that relieves valu (<~95% busy), auto-add
  parity_early combos and l4_gmin=(0,0) to the sweep grid — H-002/H-008's
  rejections are conditional on valu saturation and re-testing is one command.
- predicted: contingent. cost: S. depends: any valu-relief accept.
- result:
- log: 2026-07-23 promoted from critical-path follow-ups.

### H-014 [strain: critical-path] [status: rejected -> graveyard G-11]
- statement: Spend the 32 freed words (pool_sizes=(17,3)) on load-side state:
  nv double-buffering so gathers for round r+1 never wait on round r's nv
  consumption (today nv is reused; check ListScheduler WAR stalls on nv+lane).
- predicted: -5..-20 cyc. cost: S-M. depends: none (words available now).
- result: REJECTED iter 2 by direct measurement: 0/1,936 gathers nv-bound
  (instrumented ready() decomposition; counterfactual moves 0 loads). Load
  is slot-contention-bound (~33 cyc avg backlog). See G-11.
- log: 2026-07-23 promoted; iter 2 measured and rejected.

### H-015 [strain: op-reduction] [status: accepted]
- statement: C5-pre-xor value domain (H-003's P-1): pre-xor all 2047 tree
  values with C5 once (~256 vload+vxor+vstore hidden in the gather-free early
  rounds on the 1.4%-busy store engine; tournament E/D tables derived from
  pre-xored values at preload; initial vals pre-xored at load), then every
  round's stage 5 drops `^C5`: val' = e ^ (e>>16) ^ n' — 3 ops instead of 4.
  Parity flips by C5&1: absorb into omf/rec offset constants (0 extra ops).
  Last round emits true val (+32 vxors).
- predicted: -4096 lane-ops gross ≈ -68 cyc; net -45..-60 cyc -> ~1080-1095.
- cost: M. depends: none. Touches preload + tournament constants + store path.
- result: ACCEPTED iter 2, composed at 1088 (-19 vs 1107). Agent's design
  beat the sketch: NO whole-tree preprocessing (load-floor arithmetic: +254
  vloads -> >=1115 hard floor; only already-loaded sources primed, L4 tree
  words rewritten in mem from primed scratch), parity closed at ZERO ops via
  table REVERSAL. 9/16 rounds elide ^C5 (288 vec xors). Driver fixed a
  vsel_auto arm-order interaction (swapped select arms under the reversed
  tables) and re-tuned composed: va shrinks to (1,2), l4_gmin drifts to
  (15,29) (freed valu funds more L4 service), pools back to (17,4).
- log: 2026-07-23 promoted; iter 2 ACCEPTED composed, dispatch flipped.

### H-016 [strain: op-reduction] [status: closed negative (comprehensive)]
- statement: Extend fusion_search with meet-in-the-middle (forward-2
  signatures x invertible-backward-2) to push the two 5->4 boundary
  questions to 6->5 (stage1∘f23 span, b2d) and cross-round to depth 5 —
  the only remaining unsearched shortening candidates below global scale.
- predicted: uncertain; each hit -68 cyc. cost: S-M. depends: none.
- result: CLOSED iter 4: ALL 10 boundary questions negative — 2.364T
  engine-A candidates + 9.38B fwd-MITM + 6.68B chain-MITM nodes, meet-op
  constants SOLVED over 2^32 (not pooled), incl. the primed-domain
  cross-round (xr3p 5->4) and both 6->5 questions. Adjacent-segment fusion
  is dead at every cut. Coverage boundary honestly stated (kf=4 general
  prefixes ~1000x cost; >3 unary links). G-10 reopen-if updated.
- log: 2026-07-23 promoted; iter 4 closed negative.

### H-017 [strain: flow-balance] [status: accepted]
- statement: madd->vselect flip of tournament FIRST-folds, nearly free under
  parity_conds (H-001's P-1): store odd-value vectors O_vecs at setup (same
  scratch as D_vecs), conds are raw parities, first fold becomes
  vselect(b, O, E) on flow instead of madd(b, D, E) on valu. L4 alone moves
  112 slots off valu (~19 cycle-equivalents); L1-L3 more.
- predicted: -10..-30 cyc (valu now the binding floor at ~1106). cost: S-M.
- depends: parity_conds (in mainline). Watch G-4: only first-folds, chain
  length unchanged (vselect replaces madd at the same depth).
- result: ACCEPTED iter 2: 1107 (-23) via `vsel_auto` schedule-aware racing
  (flow vselect iff its slot strictly beats valu's; 243/448 folds flip; dual
  D+O tables funded by one cond slot). Hard flip REJECTED all 15 subsets
  (1136-1196): flow idle is anti-correlated with fold windows -> G-12.
  L4 retune confirmed: l4_gmin=(20,29), pools (16,3). 17 words now FREE.
- log: 2026-07-23 promoted; iter 2 ACCEPTED, dispatch flipped.

### H-018 [strain: flow-balance] [status: closed (folded into H-004 iter 3)]
- statement: valu madd diet: hunt the lagged p-fold madds and epoch-exit
  conversion madds (feeds H-004's idx-elimination ideas) now that valu
  throughput (not alu, not latency) is the binding constraint.
- predicted: -5..-20 cyc. cost: M. depends: H-001 (in mainline).
- result:
- log: 2026-07-23 promoted from flow-balance P-2.

### H-019 [strain: flow-balance] [status: accepted]
- statement: Generalize dual placement (H-017's P-4): partial-L4 vsel_auto
  (17 free words fund 2 of 8 W-pair odd tables) and a ListScheduler
  `emit_any(encodings)` primitive unifying the fold race with the alu-split
  race — every multi-encoding op placed wherever it retires earliest.
- predicted: -5..-15 cyc (valu floor 1073 vs 1107 actual = 34 cyc of slack
  to harvest). cost: M. depends: H-017 (in mainline).
- result: ACCEPTED iter 3 at 1070 (-17 net): emit_any() unifies all encoding
  races (bit-identical refactor of dual_fold + alu-split); u_race (L4
  U-combines flow-vs-valu) is the enabler (-4 alone), l4_race=3 partial odd
  tables, idx_race alu spellings (-5 composed), l4_gmin drifts again to
  (13,28). sel_race (reverse race) measured negative -> G-14. Composed
  retune confirms va=(1,2); the (1,3) sweep-win was flag-set-specific.
  valu 6262 slots (floor 1044); alu now 93.9% -- BOTH compute engines near
  saturation; placement racing is at its ceiling (P-7: op removal next).
- log: 2026-07-23 promoted; iter 3 ACCEPTED, dispatch flipped.

### H-020 [strain: sweep] [status: re-run under H-029's engine mix,
no further gain found]
- statement: pool-shape x vsel_auto interaction sweep ((16,3) beat (17,3) by
  2): re-run full grid under the 1107 mainline; add vsel_auto level subsets
  and partial-L4 variants to the grid as they land.
- predicted: -2..-8 cyc. cost: S (background). depends: none.
- result: RE-RUN 2026-07-23 under idx_select=True, l4_gmin=(9,30) (the
  current 1043-cyc point). pool_sizes: (16,4) [mainline] beats (16,3)=
  1054, (17,3)=1056, (15,4)=1062, (18,3)=1054, (14,4)=1076; (17,4)/(16,5)
  overflow scratch. vsel_auto: (1,2) [mainline] beats (1,)=1054;
  (1,2,3) overflows scratch. No config beats the current mainline
  choices under the new engine mix — this grid is exhausted again at
  the new local optimum, same conclusion as before, just re-verified.
- log: 2026-07-23 promoted from flow-balance P-5; re-run same day
  post-H-029.

### H-022 [strain: sweep] [status: re-run under H-029's engine mix, no
further gain found]
- statement: grid additions from H-019's P-8: u_race x l4_race subsets x
  idx_race x l4_gmin dense x pools under the 1070 mainline.
- predicted: -1..-5. cost: S. depends: none.
- result: RE-RUN 2026-07-23 under idx_select=True, l4_gmin=(9,30):
  l4_race=3 [mainline] beats 0 (1047), 1 (1044), 2 (1045); 7 overflows
  scratch. u_race=False is worse (1054) — u_race=True [mainline] still
  needed. sel_race=True is worse (1047) — confirms G-14's standing
  negative still holds under the new mix. Every dimension in this grid
  independently confirms the existing mainline choices (u_race=True,
  l4_race=3, sel_race=False, plus idx_race which idx_select supersedes
  in the branch it covers) remain optimal after H-029 — no interaction
  effect surfaced that changes any of these defaults.
- log: 2026-07-23 promoted from flow-balance P-8; re-run same day
  post-H-029.

### H-021 [strain: scheduler] [status: closed (charter measured-complete)]
- statement: NEW STRAIN (rotated in for critical-path). Close the gap between
  actual cycles and the valu floor (1087 vs ~1061 = 26 cycles of scheduling
  friction): ListScheduler lookahead/priority experiments (critical-chain
  first, slack-aware slot assignment), emission-order search beyond skew
  (which the (4,3) sweep already optimized), and per-engine tie-break rules.
  Rust-harness modeling (H-012) to bound what perfect scheduling could give.
- predicted: -10..-26 cyc (bounded by the floor gap). cost: M.
- result: CLOSED iter 4, honest zero with full map: the 26-cycle gap is
  13 cyc latency-bound drain (last block's L4-served groups, ~17-level
  post-parity chain staircase), 9 cyc load-throughput-bound setup ramp,
  4 cyc seams. RAW 141/158 gap-binding hazards; pools fine. NOT scheduling
  friction: emission-order/tie-break/reordering variants all >= 1070
  (stage 1092, stage_all 1161 -- G-5 confirmed at op granularity). Trace
  hook + tools/sched_profile.py landed for future profiling. Successors
  promoted: H-023 (b3-last), H-024 (setup const derivation).
- log: 2026-07-23 opened; iter 4 closed; strain retired (charter done).

### H-022 [strain: sweep] [status: open]
- statement: grid additions from H-019's P-8: u_race x l4_race subsets x
  idx_race x l4_gmin dense x pools under the 1070 mainline.
- predicted: -1..-5. cost: S. depends: none.
- result:
- log: 2026-07-23 promoted from flow-balance P-8.

### H-023 [strain: flow-balance] [status: rejected -> graveyard G-17]
- statement: b3-last final-round L4 tournament (H-021's lead): reverse the
  served-L4 fold order so the newest parity (r14's, arriving last) selects
  LAST instead of first -- post-parity chain drops ~17 -> ~11 levels,
  attacking the measured 13-cycle drain staircase directly. Cost-neutral op
  count (15 selects vs 8 madds + 7 selects) but needs all-8 odd tables
  (scratch: only 6 words free -- fund by dropping l4_race odd tables on
  non-final rounds or trading a pool slot; measure).
- predicted: -5..-8 cyc. cost: M. depends: none.
- result: REJECTED iter 5: chain shortened 17->11 as predicted but the
  staircase GREW (66 -> 113-250 empty slots): the 14 b0/b1/b2 folds have
  broadcast/dead-temp arms spelling only as flow-serial (1-slot) or
  valu-double (sub+madd); no engine has tail slack. Best raced form 1084.
  Premise "neutral op count" fails without ~64 words of leaf-diff tables.
- log: 2026-07-23 promoted; iter 5 rejected.

### H-024 [strain: scheduler->sweep] [status: accepted]
- statement: setup load-slot removal: derive hash-constant scalars from each
  other on alu (kq = kp<<9, aq from ap, etc.) instead of load:const slots;
  frees ~load slots during the 2/2-saturated 20-cycle setup ramp where
  vbroadcasts wait on lv vloads.
- predicted: -3..-9 cyc. cost: S. depends: none.
- result: ACCEPTED iter 5: 1064 (-6) = derive_consts (9/18 consts alu-derived,
  kq=kp<<k4 etc.; 6 arbitrary addends have no 1-op relations, brute-forced)
  + alu_val_addrs (32 serial flow add_imms were booking the 1-wide flow
  engine to ~c40, gating val vloads -- moved to 4 parallel alu chains).
  Ramp friction 49 -> 22 empty valu slots. lazy_val_loads negative (+9),
  kept as control. Retune: optimum unmoved. Dispatch flipped; grader 9/9.
- log: 2026-07-23 promoted; iter 5 ACCEPTED.

### H-025 [strain: op-reduction] [status: open]
- statement: (H-016's P-8) global synthesis attack on "the 11-op hash in
  10": CEGIS/SAT over the machine op set with free 32-bit constants —
  counterexample-guided: synthesize candidate on a few IO pairs (z3 bitvec),
  verify on 10M inputs, add counterexamples, repeat. The ONLY remaining
  tool class for hash op removal; adjacent-segment/MITM spaces exhausted.
- predicted: -68 if a 10-op form exists (unknown); high risk of UNSAT-slow.
- cost: L. depends: none (z3 installable).
- result:
- log: 2026-07-23 promoted from op-reduction P-8.

### H-026 [strain: cross] [status: accepted]
- statement: mem_prime — per-level in-mem C5-priming of deep gather levels
  (marginal-cost refutation of P-4's all-or-nothing arithmetic): L5 = 4
  vload+vxor+vstore in the setup load-lull, eliding r4's ^C5 for 32 groups.
- result: ACCEPTED iter 6, -3 composed (L6 negative: coarse mem model
  serializes priming into first gathers). Part of the 1053 stack.
- log: 2026-07-23 cross-pollination find; dispatch flipped.

### H-027 [strain: cross] [status: accepted]
- statement: b3l_diffs — G-17's reopen-if satisfied by dead-register mining:
  at r15, st of 28 non-served groups + nv of earlier blocks = 52 dead
  vectors; fund 8 leaf-diff tables + 9 private regs per served group
  (privates kill the pool-WAW). b3-last post-parity chain 4 levels -> 1 madd.
- result: ACCEPTED iter 6, -4 composed, census below baseline. G-17 stands
  for the tableless form; bl_last (L2/L3 analog, no tables) measured
  +2..+13 -> negative control (G-12 holds).
- log: 2026-07-23 cross-pollination find; dispatch flipped.

### H-028 [strain: cross] [status: accepted]
- statement: store_pair — scheduler model fix: final vstores were serialized
  1/cycle by the coarse mem-write hazard on a 2-wide store engine; exact
  relaxation pairs disjoint-address same-cycle writes.
- result: ACCEPTED iter 6, -4 composed (masked alone by compute tail).
  Grader-validated (frozen simulator accepts the paired stream).
- log: 2026-07-23 cross-pollination find; dispatch flipped.

### H-029 [strain: flow-balance] [status: accepted, MAINLINE DISPATCH FLIPPED
2026-07-25 (l4_gmin=(9,30), idx_select ported into perf_takehome.py's
steady-gather branch unconditionally): mainline 1053 -> 1043 -> 1041
(composed with H-021's fold_flow tie-break, see H-030). grader 9/9,
6-8 seeds + unseeded correct=true. See end of entry for the flip note.]
[EXTERNAL ATTRIBUTION — see below]
- statement: idx_select — select-vs-add for the gather-mode idx recurrence.
  NOT an in-house finding: ported from a third-party public solution to
  this same take-home, github.com/zhanglistar/original_performance_takehome
  (commit e9b8f4c, their measured 1026 cyc; problem.py/tests confirmed
  byte-identical to ours, so directly comparable). Their `round_gather`
  idx update does `vselect(tmp, parity, hi_const, lo_const);
  madd(idx, idx, two, tmp)` instead of our `madd(st,st,two,ov);
  vec(sgn,st,st,par)` — since the amount to add is just `bias +
  parity_bit` and parity is 0/1, it's a 2-way choice between two
  precomputed constants, which vselect can express but a variable
  add/sub cannot, moving that step off valu/alu onto flow.
- predicted: same op count/instance, but flow-eligible; their engine mix
  (valu 5997/97.4%, flow 873/85.1%) vs ours (valu 6209/98.3%, flow
  637/60.5%) suggested most of their advantage traces to this one
  pattern generalized across every gather round.
- cost: S (turned out zero-scratch: `omf1_vec == omf_vec+1` already, by
  construction, so the two needed constants already existed — no new
  scratch, contra the original cost estimate).
- result: ACCEPTED. Landed as `idx_select: bool = False` in
  `build_kernel_scheduled` (perf_takehome.py), covering the steady-gather
  branch only (not the c5_prexor boundary-crossing branch — follow-up).
  Verified via tools/run_variant.py: 6 seeds + 3 unseeded + debug_compares,
  all correct=true. `idx_select=True` alone: 1053->1052 (engine mix
  shifted alu -736/valu -78/flow +137 as predicted, but wall-clock gain
  small because friction rose, per the standing P-3 pattern). Retuning
  `l4_gmin` (12,30)->(9,30) to match the new engine balance: **1053->1043
  (-10 cyc, -0.95%)**, confirmed correct on all seeds/debug_compares.
  Flag-gated, default off; mainline `build_kernel` dispatch NOT flipped
  yet pending a decision on adopting it as the new default. Do not
  present this as an original finding — the mechanism is theirs, only
  the porting/measurement/zero-scratch adaptation is this session's.
  CAUTION found in follow-up sweeping: `idx_select=True` crashes
  (IndexError, out-of-bounds gather address) for some l4_gmin
  second-coordinate values (0,1,5,10 all crash; 15 and 20-30 are fine,
  non-monotonically) — root cause not yet found, does not affect the
  accepted (9,30) point, but any future l4_gmin sweep under idx_select
  MUST check `correct` at each point, not just cycles. pool_sizes/skew
  re-swept against the new (9,30) point: no improvement, mainline's
  (16,4)/(4,3) already optimal. See flow-balance/STATE.md P-14 for detail.

  ROOT CAUSE (found 2026-07-25): the crash is `depth_first_fold`'s
  final-round fallback (used when `b3l_fold_diffs`'s dead-register pool
  can't fund every served group) transiently reusing `two_minus_fp_vec`'s
  storage (`level_table + 3*VLEN`) as a leaf-fold temp -- corrupting the
  value for any concurrently-scheduled group's steady-gather idx-select
  read (idx_select keeps `two_minus_fp_vec` live across every gather-mode
  round, unlike the pre-idx_select code which only read it at rounds
  preceding the final round). PROVEN safe at (9,30): the final round
  (epoch 1, threshold 30) leaves 30 unserved groups (60 dead-register
  scratch vectors) against only 2 served groups' need (8 diffs + 9
  private each = 26) -- the fallback is provably unreachable, not just
  untriggered-by-luck. A build-time assert enforcing
  `2*unserved >= 8 + 9*served` at the final round now guards this
  invariant in `perf_takehome.py` (fires loudly if a future l4_gmin
  change breaks it, instead of silently corrupting data).

  MAINLINE FLIP (2026-07-25): ported directly into `perf_takehome.py`
  (now a flag-free file — see `dev.py`/`perf_takehome.py` split, [[project_dev_vs_perf_takehome]]),
  replacing the steady-gather branch's `race_idx_madd`+`vec` pair with the
  `vsel`+`multiply_add` form, and changing `l4_gmin` from `(12,30)` to
  `(9,30)`. Verified: grader 9/9 green, 6 seeds + unseeded all
  correct=true, 1053 -> **1043**. `tools/run_variant.py`'s `BASE_KWARGS`
  updated to match (`l4_gmin=(9,30)`, `idx_select_before_madd=True`) so
  `dev.py`-based sweeps track the new mainline. This was the single
  highest-value, lowest-risk item on the standing backlog (already fully
  measured correct before the flip) — see cross/STATE.md P-c1.
- log: 2026-07-23 external-repo comparative investigation (user-directed)
  -> ported as flow-balance P-14 -> implemented and measured same
  session, -10 cyc verified. See flow-balance/STATE.md P-14 for full
  detail (mechanism, engine census at each step, follow-ups).

### H-030 [strain: scheduler] [status: accepted, MAINLINE DISPATCH FLIPPED
2026-07-25]
- statement: re-sweep H-021's `tie_break` modes (dismissed as cycle-identical
  under the ~1070-era engine mix) against the current post-H-029 mainline —
  a lever measured neutral under an old op composition can become live once
  the mainline's engine balance shifts (idx_select moved substantial work
  from valu/alu onto flow, which is exactly what `tie_break="fold_flow"`
  targets: whether exact retire-time TIES in `dual_fold`'s emit_any race
  favor flow or valu).
- predicted: uncertain (H-021 called this exhausted); small if real (a
  tie-break only fires at exact-tie cycles, a narrow slice of placements).
- cost: S (pure reordering — swap which encoding is listed first in
  `dual_fold`'s `emit_any` call; zero new scratch, zero new ops).
- result: ACCEPTED. `tie_break="fold_flow"` (flow-vselect listed first,
  so ties resolve to flow instead of valu): **1043 -> 1041** (-2),
  reproduced on 8 draws (seeds 1,2,3,4,7,42 + 2 unseeded) plus
  `debug_compares=True`, both via `dev.py`/`tools/run_variant.py` and
  directly against `perf_takehome.py`'s flag-free `build_kernel`. Grader
  9/9 green. `tie_break="idx_alu"` alone gives 1042 (-1, smaller);
  combining both is 1042 (worse than fold_flow alone — the two ties
  interact, don't stack). l4_gmin neighbors (9,29)/(8,30)/(10,30)
  re-checked under fold_flow: all >= 1041, (9,30) stays optimal.
  Ported into perf_takehome.py by swapping the flow/valu encoding order
  in `dual_fold` (no new flag machinery needed there — the file is
  flag-free, so this is just the tie-break choice baked in directly).
  `tools/run_variant.py`'s `BASE_KWARGS` updated to
  `tie_break="fold_flow"` so dev.py-based sweeps track mainline.
  A parallel investigation (depth-aware static tie-break using
  `scheduler.tag`'s `(round, group)` as a proxy for remaining-rounds
  priority, gating `dual_fold`/`race_idx_madd` toward flow/alu below a
  threshold) reached 1042 at best and was DOMINATED by the simpler
  `fold_flow` flag alone — the whole measurable effect traced to round 2
  only; every other round (including the expected-interesting drain
  rounds 12-15) contributed nothing, because the drain is latency-bound
  with genuinely idle engines (no contention for a tie-break to resolve)
  and the middle is triply-saturated (valu/alu/flow all busy enough that
  reshuffling a tie just relabels who waits, per H-007's fold-site
  archaeology reaching the same conclusion independently). That
  depth-aware code was NOT ported (dominated by the simpler win); see
  scheduler/STATE.md for the full writeup if a future session wants a
  documented negative to build on.
- log: 2026-07-25 opened as a resweep of H-021 post-H-029; same-day
  accepted and flipped.
