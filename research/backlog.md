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
- ADAPTIVE-RACE FOLLOW-UP 2026-07-26 (prompted by an external solution's
  `vec_flex_op`/`emit_hash_combine`/`emit_hash_shift`, which reroutes hash
  xor/shift ops from valu to alu per-instance at schedule time, gated on
  `mandatory_alu_ready` being low AND `valu_ready` count being high --
  opportunistic, not blanket). Item #5 above only tested BLANKET
  un-forcing (always alu, never valu); this closes the remaining gap by
  testing genuinely adaptive per-instance racing on the SAME sites, using
  our own `emit_any`-based mechanism (`_sched_vec`'s existing
  `allow_alu`/race path, the same one `vec()` already uses elsewhere --
  only `avec()`'s stage1 xor-shift call sites were hardcoded to the
  `force_alu=True` branch instead). Added flag `hash1_avec_race` (dev.py):
  when True, `avec` uses `allow_alu=alu_offload, force_alu=False` (race:
  scalarize to alu only when valu is backed up that cycle) instead of
  `force_alu=alu_offload` (always scalarize). Measured at mainline
  (l4_gmin=(9,30), 1038 cyc): **1098 cycles, a clean +60 regression**
  (debug_compares=True and 5 seeds all correct, all +60). Re-checked at a
  different l4_gmin=(15,30) point (1060 baseline there) to rule out a
  pool-size artifact: 1091, still +31 -- regression is robust across the
  l4_gmin dimension, not a local tuning effect. CONCLUSION: adaptive
  per-instance racing is NOT a rescue here -- it regresses almost as
  badly as blanket un-forcing (+60 vs +62). The reason force_alu is
  needed for these specific ops is structural (always keep valu clear
  ahead of the same-stage madds that immediately follow), not merely "is
  valu busy this exact cycle" -- so the adaptive gate doesn't capture the
  real constraint the way it does for `vec()`'s general sites. H-007
  stays closed; this specific corner (adaptive-vs-blanket force-alu on
  stage1 avec) is now also closed, no material gap.
- log: 2026-07-23 opened; premise re-checked same day post-H-029; 2026-07-25
  fold-site archaeology completed, closed with no material gap found;
  2026-07-26 adaptive-race follow-up tested and rejected (+60 cyc), no
  further reopen expected without a new mechanism idea.

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

### H-025 [strain: op-reduction] [status: seven sub-attempts made, none
closes k<=10 -- three independent CEGIS attempts all inconclusive (each
narrowing the diagnosis further), enumerative MITM closed-negative at a
stated depth<=7 coverage boundary (now landed+reverified on main), kf=3
closed infeasible for the FULL/global 23-item target only, closed
NEGATIVE (genuinely searched, not infeasible) at kf<=3 for every one of
the six real individual segment targets, kf=4 closed infeasible at the
segment scale (a CPU-time wall, not memory)]
- statement: (H-016's P-8) global synthesis attack on "the 11-op hash in
  10": CEGIS/SAT over the machine op set with free 32-bit constants —
  counterexample-guided: synthesize candidate on a few IO pairs (z3 bitvec),
  verify on 10M inputs, add counterexamples, repeat. The ONLY remaining
  tool class for hash op removal; adjacent-segment/MITM spaces exhausted.
- predicted: -68 if a 10-op form exists (unknown); high risk of UNSAT-slow.
- cost: L. depends: none (z3 installable).
- result: CLOSED INCONCLUSIVE (time-boxed, 2026-07-25). Built a
  component-based CEGIS synthesizer (kind selector + operand-source
  selectors + free 32-bit constants, all existentially quantified over
  Z3 QF_BV; myhash + the current 11-op fused form cross-checked
  bit-exact on 200K samples first; encoder round-trip validated on 2
  trivial synthetic targets). Scaling calibration: UNSAT in <3s through
  k=3; k=4 already TIMEOUT (result=unknown) at 30-180s budgets even
  under heavy restriction (kind vocab cut to the 3 actually-used ops,
  windowed operand sources, as few as 8 examples). Cross-check: the SAME
  encoder also TIMED OUT trying to reconfirm the KNOWN-satisfiable k=11
  form (600s, full generality; still TIMEOUT at 60s restricted to
  MADD/XOR/SHR) — i.e. the tool can't even re-find a solution it
  already has. Main run: k=10, full vocabulary, 19 seed examples, 20 min
  (1200s) budget as specified -> 4 solver rounds, every round Z3
  `unknown`, 0 candidates ever extracted, 0 counterexample refinements
  possible. STATUS: TIMEOUT, fully inconclusive (no SAT found, no UNSAT
  proof; "unknown" from a bit-blasted solver licenses no coverage
  claim). Diagnosis: multiply_add's fully-symbolic constant forces an
  unconditional symbolic 32x32 multiplier per op regardless of which
  kind ends up selected, and combined with free source/kind selectors
  this swamps the solver well before k=10 -- the practical ceiling for
  this direct encoding is ~k=3, not k=10/11. See op-reduction/STATE.md's
  iter-6 log entry for full detail and P-11 for what a real reopen would
  need (bit-width-reduced synthesis + CEGIS lifting, or an
  enumerative/invertibility-based superoptimizer instead of raw
  existential bit-blasting -- NOT just more solver timeout).
  perf_takehome.py/dev.py untouched.
  ITER 6b (2026-07-25, same session, second sub-attempt): P-11's
  recommended enumerative/invertibility approach turned out to already
  exist -- `fusion_search.rs`'s engines B/C (solved xor/madd meets,
  xorshift-chain inversion, no symbolic bit-blasting) ARE that design.
  Added one new MITM target, `full_hash`: the whole chain `a ->
  myhash(a)` end-to-end, with NO waypoint assumption (every prior target
  cut at a named stage boundary -- this had never been tried). Ran to
  completion in 1678.3s (~28 min): engine A full k<=4 exhaustive
  (2,940,520,863,935 candidates), engine B fwd<=3 x suffix<=2
  (1,033,714,835 nodes), engine C suffix<=5 x kf<=2 forward prefixes
  (2,118,285,916 nodes). **CLOSED NEGATIVE at that stated coverage: no
  <=10-op program found** (ceiling = depth<=7 of the 10 needed, the same
  kf=4-gap shape as H-016/P-7, now confirmed with zero waypoint/segment
  assumption baked in -- rules out an entirely different hash
  decomposition, not just deeper cuts at the known stage boundaries). k=10
  remains open beyond depth 7; closing further needs kf=3+ forward tables
  (~1000x cost, P-7) or a CEGIS fix (case-split op-kind instead of one
  uniform mux, P-12), neither attempted. IMPLEMENTATION NOTE: verified
  (build clean, 9/9 tests) against a pre-refactor copy of
  `fusion_search.rs` (the agent's worktree predated this session's
  naming/typing pass); the result is a property of the hash function
  itself and stands, but the Rust diff was NOT re-applied to current
  `main`'s renamed `fusion_search.rs` (manual constant-name translation
  risked an unverified error) -- see op-reduction/STATE.md iter 6b for
  the exact re-implementation note for a future pass.
  ITER 7 (2026-07-25, bounded research agent, worktree fast-forwarded
  from stale 5da6061 to main@92be85c first): two parts, both actually
  RUN, not estimated.
  (1) Re-ported `full_hash` for real onto current main's renamed
  `fusion_search.rs` (current identifiers: `hs::fused_hash`,
  `STAGE0_ADD_CONSTANT`/`STAGE0_MULTIPLIER`/`STAGE1_XOR_CONSTANT`/
  `F23_P_MULTIPLIER`/`F23_P_CONSTANT`/`F23_Q_MULTIPLIER`/
  `F23_Q_CONSTANT`/`STAGE4_ADD_CONSTANT`/`STAGE5_XOR_CONSTANT`; same
  pool/seed methodology as `a2d`/`b2e`/`c2out`: 23-item forward pool [12
  hashseg consts + common(3) + 8 shifts], 16-item engine-A pool, 26-item
  link seed -> the file's fixed 72-const/1284-link cap). Build clean,
  9/9 tests. RAN to completion (2220.2s, ~37 min): engine A k<=4 =
  2,868,020,060,885 candidates (1568.9s, same order of magnitude as iter
  6b's 2,940,520,863,935/1290.7s); engine C = 2,118,285,916 chain nodes
  (405.0s) -- IDENTICAL node count to iter 6b's figure (link pool
  matched exactly, cross-validating the port); engine B = 6,935,605,852
  forward nodes (245.0s), larger than iter 6b's reported 1,033,714,835
  because this port's engine B searches the fuller 23-item forward pool
  (per iter 6b's own pool spec) rather than an unspecified leaner one --
  a coverage SUPERSET, not a weakening. **RESULT UNCHANGED: no <=10-op
  program found at the same depth<=7 boundary**, now actually landed and
  reverified in-tree on main rather than only documented.
  (2) P-12 kf=3 scoping, ACTUALLY ATTEMPTED rather than estimated cold:
  implemented real kf=3 support in `build_fwd_tab` (diagnostic-only,
  gated behind a new `--kf-scale` probe, not wired into engine C or any
  verified target -- zero risk to (1)'s result) and measured real
  wall-clock/memory at increasing pool sizes on the same 8-core/24GB
  box: pool=4..16 items took 0.1s/1.0s/4.8s/13.9s/33.1s/81.2s/284.3s
  (55.9K/437K/2.0M/6.3M/17.5M/40.6M/85.6M table entries respectively),
  with the log-log growth exponent ACCELERATING from ~6.8 (pool 4->6)
  down to ~5.2 (8->12) then back up to ~10.0 (14->16) -- not a fixed
  polynomial degree, getting worse as pool grows. At the REAL 23-item
  pool used by every target (kf<=2 independently reconfirmed identical
  to run (1): 611,535 kf=2 entries, 0.531s), kf=3 was KILLED after ~10
  min with RSS still climbing unboundedly past 8GB (freed ~16GB
  system-wide on kill -- nowhere near converging). **CLOSED INFEASIBLE:
  kf=3 is a MEMORY wall, not the ~1000x-CPU-time wall P-7 estimated** --
  a pool small enough to finish in minutes (<=12 items) is too
  impoverished to contain the real multi-stage hash constants needed for
  meaningful coverage of ANY span (even the smallest 6-op sub-span needs
  ~13 items to be non-trivial); no pool size is simultaneously
  tractable-in-hours and representative. Recommend NOT re-attempting kf=3
  without a fundamentally different table representation (external/
  streaming dedup, or a proven order-of-magnitude algebraic
  canonicalization) -- more wall-clock will hit the same memory wall this
  iteration hit in ~10 minutes. P-12(b) (CEGIS case-split fix) is now the
  more promising remaining lever, untried. perf_takehome.py/dev.py
  untouched throughout.
  ITER 8 (2026-07-25, bounded research agent, user-authorized "push and
  don't stop"): attempted P-12(b)'s CEGIS case-split fix for real. Built
  `scratchpad/cegis.py` (straight-line DAG, window=3 operand selectors,
  op KIND fixed per position in Python -- the case split -- rather than
  as a free Z3 selector). CALIBRATION FOUND THE ITER-6 DIAGNOSIS WAS ONLY
  PART OF THE STORY: case-splitting just "is this position MADD or not"
  (leaving the other 8 kinds free at non-MADD positions) is NOT
  sufficient -- still `unknown` at 30s on the known-good k=11 sequence.
  Isolated the real cost via probes: it's generic component-CONNECTIVITY
  search (which selector feeds which op), not specifically the multiply
  -- leaving 5+ non-MADD positions' kind simultaneously free reproduces
  the same wall with ZERO madds involved. The fix that actually helps is
  case-splitting the ENTIRE kind sequence (only selectors+constants
  free): SAT in 0.2-1.9s at 3 samples -- a real, measurable improvement.
  BUT a second, independent wall appears: CEGIS's own counterexample-
  refinement loop stalls once it needs a 5th concrete sample (`unknown`
  at up to 180s), IDENTICALLY for the intact known-good k=11 structure
  and every k=10 variant tried (used the task-authorized near-structure
  fallback: 11 single-position deletions of the known template; 7 of 11
  examined before budget ran out, all hit the same wall). Every SAT
  candidate found at 3-4 samples was a degenerate small-support fit,
  refuted by bulk numpy verification within 1-8M random inputs -- zero
  candidates ever reached the required >=50M-input gate. Zero UNSAT,
  zero verified SAT. CONCLUSION: this is a genuinely new, more precise
  characterization of why CEGIS doesn't scale here (connectivity search
  + a 5-sample refinement wall, not merely "multiply bit-blasting"), but
  still fully inconclusive -- H-025 remains open. Four concrete untried
  next moves recorded (structured/non-random seed samples, explicit
  selector symmetry-breaking, a solver/tactic swap to CVC5 or a
  dedicated synthesis engine, or a narrower structural template).
  perf_takehome.py/dev.py untouched.
  ITER 9 (2026-07-25, same session, second CEGIS fix attempt): rebuilt
  the tool with BOTH of iter 8's untried fixes (structured, non-random
  seed samples chosen to maximize early discriminating power; explicit
  selector domain-tightening + symmetry-breaking on commutative ops).
  CALIBRATION: NEGATIVE -- neither fix moved the wall. SAT at n=3-4
  samples, `unknown` at n=5, identically for structured and random
  seeds, across every timeout budget/solver tactic/selector-representation
  variant tried (BitVec instead of Int selectors, explicit bit-blast
  tactic). DEEPER DIAGNOSIS (the real finding): pinning EVERY selector to
  its known-good value (zero connectivity search left, only the
  multiply_add K/C constants free) still hits a wall -- just pushed from
  n=5 to n=8. This CONTRADICTS iter 8's own diagnosis: the bottleneck is
  NOT primarily selector-connectivity search, it's the nonlinear
  chained-modular-multiply constant-solving itself (4 free (K,C) pairs
  in series), which connectivity search compounds but did not cause.
  Per its own go/no-go rule, stopped after a 2-of-11 spot-check (both
  hit the wall) rather than repeating the full 11/880-variant sweep with
  fixes already shown not to help. THREE independent iterations (6, 8, 9)
  now agree, via three different specific mechanisms, that CEGIS/Z3
  QF_BV component synthesis at 32-bit width is the wrong tool class for
  this problem in essentially any encoding tried so far. A reopen needs
  a solver/engine swap (CVC5, or a dedicated synthesis engine like
  Rosette/Sketch) or a materially narrower template (fixed per-stage
  constants for at least some positions) -- not more tuning of this
  approach. perf_takehome.py/dev.py untouched.
  ITER 10 (2026-07-25/26, bounded research agent, user-authorized "push
  and don't stop"): targeted re-check of whether iter 7's kf=3 "memory
  wall" verdict, reached only against synthetic prefixes of `full_hash`'s
  23-item pool, actually holds for the much smaller pools real individual
  segment targets use. Precisely counted every `mitm_targets()` pool: the
  smallest STILL-OPEN targets are `b2d`/`xr5`/`xr3p` at 13 items, then
  `a2d`/`b2e`/`c2out` at 15. Added a `--kf-scale-target <name>` probe
  (builds kf=0..=3 tables against a NAMED target's real pool, with an
  in-process RSS-sampling thread) and ran it against every one of these:
  ALL completed in 17-120s at 3.5-11.2GB peak transient RSS -- no
  memory-wall behavior anywhere, sharply contrasting iter 7's real
  23-item-pool attempt (killed after ~10 min, RSS still unboundedly
  climbing past 8GB). Then wired kf=3 into the REAL, verified engine C
  search via an opt-in `--kf3` flag (default `--mitm` behavior confirmed
  byte-identical to before) -- cheap to add since an extra table adds no
  new DFS nodes, only cheap lookups (confirmed: kf<=3 chain-node counts
  came back byte-identical to the original kf<=2 runs). RAN THE FULL
  kf<=3-extended search to completion for the three smallest still-open
  targets: b2d (760.9s), xr5 (921.7s), xr3p (592.2s). **ALL THREE STILL
  NEGATIVE at this deeper kf<=3 boundary** -- genuinely searched (not
  merely estimated) one op-depth past iter 4's original kf<=2 ceiling.
  CONCLUSION: iter 7's "kf=3 is a memory wall" is correct ONLY for the
  full/global 23-item `full_hash` pool; for every real individual segment
  target (pool<=15) it is tractable and now genuinely CLOSED NEGATIVE at
  kf<=3, not infeasible. `a2d`/`b2e`/`c2out` were not extended because
  their `enable_engine_c` flag is `false` (an iter-4 CPU-budget decision
  predating this measurement) -- flipping it and timing their chain DFS
  for the first time is a concrete, not-yet-taken next step. No
  <=(current_ops-1)-op program found for any of the three; nothing to
  port. perf_takehome.py/dev.py untouched (only fusion_search.rs changed:
  the new `--kf-scale-target` probe, the opt-in `--kf3` flag, and a
  parameterized `max_kf`). Build clean; 9/9 tests unchanged.
  ITER 11 (2026-07-26, bounded research agent, worktree fast-forwarded
  from stale 5da6061 to main@994e41b via `git merge main` first): closed
  both of iter 10's flagged next steps.
  (1) Enabled + timed engine C for `a2d`/`b2e`/`c2out` for the first time
  ever. Added an opt-in `--force-engine-c` CLI flag rather than
  permanently flipping each target's `enable_engine_c=false` -- it forces
  engine C on for a named target while leaving every other target and
  the flag-less default run byte-identical (reconfirmed: `head4u` with
  no flags reproduced iter 4's exact 410,492,695-candidate/336,272,337-node
  counts). Ran all three to completion at kf<=2 (parity baseline) then
  kf<=3: a2d (376.7s / 480.5s, peak RSS 375MB / 12.06GB), b2e (386.8s /
  454.6s, 361MB / 12.64GB), c2out (386.8s / 452.9s, 361MB / 13.04GB).
  Every kf<=3 fwd-table build produced an IDENTICAL chain-node count to
  its own kf<=2 run (2,118,285,916), confirming -- same as iter 10's
  b2d/xr3p cross-check -- that adding a table adds lookups, not new DFS
  nodes. **ALL THREE STILL NEGATIVE at kf<=3**: no <=6-op program for any
  of the three 7-op interior spans. Sub-finding: these three's FULL runs
  were actually cheaper than b2d/xr5/xr3p's (377-481s vs 592-922s)
  because `max_chain_ops` caps engine C's depth at 5 for both groups
  while these three's leaner `engine_a_kmax=3` (vs 4) makes engine A
  faster -- the iter-4 CPU-budget guess that skipped engine C here was
  wrong in the conservative direction. Every one of the six real segment
  targets (b2d/xr5/xr3p/a2d/b2e/c2out) is now closed negative at kf<=3.
  (2) kf=4 at the segment scale: added a kf=4 arm to `build_fwd_tab`
  (one more chaining level than kf=3) and extended the diagnostic
  `--kf-scale-target` probe to kf<=4. Ran it on `b2d` (the cheapest kf=3
  build of all six, 31.6s at iter 10) with a real, blocking 2850s
  (47.5-min) timeout. **kf=4 DID NOT COMPLETE** -- killed mid-build by
  the timeout, never printing a result. Confirmed via an in-process RSS
  sampler that this is a CPU-TIME wall, not a memory wall (RSS held
  steady in a 3.9-5.9GB band the entire run, nowhere near the 24GB box
  limit, unlike iter 7's unbounded-climb memory wall for `full_hash`'s
  kf=3). kf=3->kf=4 costs at least ~90x at this exact pool (2850s and
  still unfinished vs kf=3's 31.6s) -- a much steeper jump than
  kf=2->kf=3's growth at the same pool size. kf=4 was therefore never
  wired into any real, verified engine C search; CLOSED INFEASIBLE at
  current tooling/budget (a reopen needs a fundamentally different
  forward-table representation or a much larger, unverified wall-clock
  allowance). perf_takehome.py/dev.py untouched throughout; only
  fusion_search.rs changed (`--force-engine-c` flag, `build_fwd_tab`'s
  kf=4 arm, the probe's kf<=4 extension). Build clean; `cargo test
  --release --bin fusion_search`: 9/9 passing, unchanged.
- log: 2026-07-23 promoted from op-reduction P-8; 2026-07-25 closed
  inconclusive (CEGIS) + closed negative (enumerative MITM, iter 6b);
  2026-07-25 iter 7 landed the MITM re-port on main and closed the kf=3
  scoping question infeasible (memory-bound) for the full/global target;
  2026-07-25 iters 8-9: two independent CEGIS fix attempts, both
  inconclusive but each narrowing the diagnosis further; 2026-07-25/26
  iter 10 corrected the kf=3 verdict to closed NEGATIVE (genuinely
  searched, not infeasible) for the three smallest real individual
  segment targets (b2d/xr5/xr3p); 2026-07-26 iter 11 closed the
  remaining three segment targets (a2d/b2e/c2out) negative at kf<=3 too
  (all six now covered) and closed kf=4 at the segment scale infeasible
  (a CPU-time wall, confirmed not memory-bound).

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

### H-031 [strain: scheduler] [status: accepted, MAINLINE DISPATCH FLIPPED
2026-07-25]
- statement: driver-requested drill-down on the 3 named friction regions
  (setup ramp / final-round drain / store-drain tail) at the 1041
  mainline. Store-drain finding: the scheduler's coarse one-pseudo-
  location memory model makes every final `vstore` wait for
  `last_mem_read_cycle` (the last gather anywhere in the WHOLE kernel,
  address-oblivious) via `ready()`'s `mem_write` branch — nobody had
  checked this side of the coarse model before (H-028/`store_pair` only
  fixed the mem_write-vs-mem_write side). Direct trace measurement: group
  0's hash chain finishes at cycle 696 but its store is placed at cycle
  1025 (a 329-cycle wait from this gate alone); the store engine sits
  idle for ~989 cycles despite results being ready throughout.
- predicted: n/a (found via direct instrumentation, not a prior backlog
  entry).
- cost: S (two new params on `ListScheduler.ready`/`.emit`
  (`ignore_mem_read_hazard`, default False in `dev.py`, all existing
  callers unaffected) wired unconditionally into `perf_takehome.py`'s
  single final-store call site, which is the only site that can prove
  disjointness).
- result: ACCEPTED and FLIPPED: **1041 -> 1038** (-3), verified correct on
  8 draws (seeds 1-7, 42, unseeded) + `debug_compares=True`, grader 9/9
  green. The relaxation is provably safe here: `build_mem_image` lays out
  `forest_values_p` (gather source) and `inp_values_p` (store target) as
  disjoint static ranges, gather addresses never leave the forest range,
  and the only reads of the store's OWN target range (each group's
  one-time initial vload) finish at setup (~c40), long before any store's
  earliest possible ready cycle (>=696). `store_order="rev"`/"tail_first"`
  combined with the relaxation both regress to 1053 (reversing emission
  order violates the WAW gate's monotone-in-emission-order requirement,
  since `last_mem_write_cycle` is a single scalar, not per-address);
  `store_order="finish_asc"` (sort by each group's already-known finish
  cycle) measured identical to natural order — the natural skew-ascending
  group layout already tracks finish order closely enough. l4_gmin
  neighbors re-checked, default (9,30) stays optimal. Setup ramp and
  final-round drain were re-profiled and RE-CONFIRMED structural (no new
  lever): ramp is tight against a counted 43-load-op/2-wide floor (=22
  cycles, matches measured exactly, 6 remaining arbitrary hash constants
  already proven to have no 1-op algebraic relation per H-024); the
  drain's idle alu/load/flow slots are too small (a few per cycle) to
  host any relocatable work, unlike the store-drain's ~989 idle cycles.
  See scheduler/STATE.md's H-031 section for full per-region detail.
- log: 2026-07-25 opened (driver-scoped drill-down), accepted and flipped
  same session.

### H-033 [strain: scheduler] [status: rejected, real negative -- verified
correct, measured worse at every configuration tried]
- statement: the biggest remaining unattempted lever -- replicate the
  external repo's collect-then-schedule scheduler architecture (flat task
  DAG, backward critical-path-priority pass, global forward
  priority-greedy pass) instead of this codebase's streaming,
  immediate-placement `ListScheduler`, to see if it closes any of the
  gap to their 1026-cycle result.
- predicted: uncertain (this session's own floor analysis found
  scheduling/placement tricks are largely exhausted on this kernel, but
  a genuinely different architecture was explicitly flagged as the one
  thing not yet tried).
- cost: L (explicitly authorized as a large effort: "push and don't
  stop"). depends: none.
- result: REJECTED. Built a real, working `PriorityScheduler` (flat task
  DAG + backward longest-path-to-sink priority/fanout pass + global
  forward greedy pass over a re-evaluated ready set every cycle) as an
  additive alternative to `ListScheduler` in `dev.py` (a `collect_tasks`
  bookkeeping mode on the existing scheduler avoided rewriting the
  ~2000-line builder body against a second interface). Verified CORRECT:
  60/60 across 6 shapes x 5 seeds with full per-value debug_compares, plus
  6 seeds at the full graded shape; one real WAR-edge soundness bug found
  and fixed en route (tracking only the latest reader per address, sound
  for streaming placement, is UNSOUND once cycles are re-derived from
  scratch -- needed an edge to every reader since the last write).
  MEASURED WORSE at every priority-heuristic configuration tried (tested
  in a worktree based on an older commit, so absolute numbers are
  relative to that checkpoint's own 1053 baseline, not today's 1038):
  full priority+downstream 1053->1097 (+44, worst); priority-only +28;
  downstream-only +13 (least bad); even a "no reprioritization, strict
  emission order over a re-evaluated ready set" control is +19 -- so the
  regression isn't really about which priority heuristic was chosen, it's
  inherent to the from-scratch global re-derivation itself. 84%+ of the
  extra cycles land in the final-round drain, not the ramp or the
  saturated middle. Root mechanism (well-supported, not exhaustively
  proven): correctness under arbitrary global rescheduling requires a WAR
  hazard edge to EVERY past reader of a scratch address, a strictly
  larger constraint set than `ListScheduler`'s single-per-address-cycle-
  floor approximation -- and this denser edge set binds harder in the
  resource-starved drain (few groups left, few ready tasks, this
  workload's small 16/4 temp/cond pools reused densely across 32 groups)
  than in the wide, already-saturated parallel middle. CONCLUSION: the
  external repo's architecture, correctly replicated, does not help this
  specific kernel's op-mix/pool-size regime -- the streaming scheduler's
  simplifying approximation is a genuine asset here, not just a
  limitation, for this workload's shape. NOT ported (regression). Full
  design, ablation table, and untried follow-ups (distinct-descendant
  downstream count, regional priority, hybrid drain/middle scheduling) in
  `research/strains/scheduler/STATE.md`'s H-033 section.
- log: 2026-07-25 opened (user-authorized large effort); same session,
  implemented, verified correct, measured and rejected.

### H-035 [strain: op-reduction] [status: rejected -> graveyard G-21 (fold algebraically impossible; best case 4x short of the 892 gap; idx_boundary_select landed flag-gated, cycle-neutral, -283 alu/valu slots)]
- statement: fold the position/idx recurrence into the hash's existing
  multiply_add slots. Idx = 7,448 lane-ops (~14.5/group-round) at 1038; the
  recurrence p <- 2p + b and addr = base_d + p are affine, and the hash
  already issues 2,950 madds whose a*b+c shape can carry an extra affine
  term with the right operand arrangement (constants pre-scaled so the
  hash's own multiply doubles p for free, position carried in a biased/
  scaled domain like c5_prexor did for values). Driving Idx 7,448 -> ~1,000
  yields ~6,400 lane-ops = the entire measured gap to the 892 leaderboard
  point (see RESEARCH.md floors, 2026-07-27). The "gather-address madd
  absorbs it" note (H-002 area) sketched this; the 892 analysis promotes it
  from nice-to-have to the single largest open lever.
- predicted_gain: up to -100 cyc composed (floor 1,015 -> ~910); even 1/3
  of it is the biggest available accept. cost: L. depends: none.
  Touches: idx-state block (st/va recurrence) + hash madd operand tables.
- reopen-context: H-029 (idx_select) showed the recurrence is malleable;
  c5_prexor (H-015) proved the carry-work-in-a-transformed-domain trick.

### H-036 [strain: op-reduction] [status: closed negative -> graveyard G-20 (340K-candidate re-derivation probe + conjugation closures; hash op-count boundary now closed by 3 independent tool classes)]
- statement: alternative algebraic DECOMPOSITIONS of myhash (not fusions).
  H-016/H-025 closed fusion/MITM/CEGIS over the CURRENT step sequence
  (2.36T candidates, kf<=3 closed, kf=4 CPU-walled) but never searched
  re-derivations: replace stage subsequences with different op bases
  (e.g. exploit that only val%2 feeds routing; multiply distribution over
  the xor-shift structure; shared subexpressions ACROSS the 6 stages given
  known constants; valu-madd-canonical forms that turn 2-op stages into
  1 madd). Target: -1.5 ops/hash average = -6,144 lane-ops ~= the 892 gap.
  Justification for reopening a closed-adjacent area: 892 exists on the
  leaderboard, and 46,656 of 60,841 lane-ops are hash — no non-hash-only
  path reaches 892 unless Idx folds nearly to zero (H-035).
- predicted_gain: -1 op/hash = -68 cyc on the floor. cost: L (search
  tooling exists from H-016/H-025). depends: none. Touches: hash block only.
- guard: every candidate must be bit-exact on all 2^32 inputs or carry a
  domain argument (values are arbitrary 32-bit words — no input structure).

### H-037 [strain: flow-balance] [status: closed negative -> graveyard G-19 (premise false: load_offset is a compile-time alias of load)]
- statement: load_offset is the ONLY unused load opcode (census 2026-07-27).
  ("load_offset", dest, addr, offset) reads mem[scratch[addr+offset]] into
  scratch[dest+offset] — per-lane gather where the +offset indexing is free.
  Check whether the 8 per-lane gathers of a group can drop their per-lane
  address arithmetic (the va/st address adds on alu/valu) by keeping a base
  vector whose lanes are pre-offset, saving addr-setup lane-ops at ZERO
  load-slot cost. Same slot count, fewer address ops; also screen vs the
  -116 loads needed for 892 (this does not reduce loads, only their
  feeding arithmetic).
- predicted_gain: small, -5..-15; cheap to close. cost: S. depends: none.
  Touches: gather-address emission only.

### H-038 [strain: op-reduction] [status: closed negative -> graveyard G-24 (~1.586T cmpsel candidates; hash op-count closed by 4th tool class — FINAL entry)]
- statement: extend the hash program search vocabulary with compare/select
  ops -- the ONE gap both G-10 (fusion) and G-20 (re-derivation) explicitly
  name as unsearched. Op set: current base + alu `<`/`==` + flow select
  (1/cyc) + valu lanewise compares; search short programs (depth <=5-6)
  for stage subsequences and the two-round DAG, reusing H-016/H-025/H-036
  tooling. Long shot but it is the only remaining sanctioned reopening of
  hash op-count (G-20 reopen-if).
- predicted_gain: -1 op/hash = -68 floor cyc if anything exists; P(hit)
  low. cost: M (tooling exists). Touches: tools/ only unless a hit.

### H-039 [strain: flow-balance] [status: rejected -> graveyard G-22 (crossover behind L5; corrects H-026 mechanism; the "-116 loads" claim below is RETIRED — no supply-side mechanism exists; byproduct: front 0-60 load window reachable via dead-reg staging)]
- statement: routing lane-op + load-count reduction via mem_prime
  generalization -- the last non-hash lane-op mass (Routing 6,249 lane-ops,
  1,848 loads). H-026's c5_primed_gather_levels=(5,) mechanism trades
  setup stores (store engine 98% idle) for steady-state gather work.
  Generalize to more levels / larger tables; quantify the scratch and
  setup-load budget honestly (G-16 closed DEMAND-side dedup; this is the
  SUPPLY-side table transform, distinct mechanism). Also the only visible
  path toward the -116 loads the 892 gap needs.
- predicted_gain: -10..-40 if a second level primes profitably. cost: M.
  Touches: mem layout prologue + gather emission (disjoint from H-038).

### H-040 [strain: cross] [status: testing]
- statement: characterize the 892 leaderboard point externally. G-21+G-20
  close both internal levers; the lane-op arithmetic says 892 is not
  reachable in the current program organization. Determine: which board
  (with/without indices), whether the variant differs (problem params,
  grading), any public writeups/repos/commits by entrants. Pure
  research/web task, no kernel edits.
- predicted_gain: strategic (redirects or retires the 892 target). cost: S.

### H-041 [strain: flow-balance] [status: rejected -> graveyard G-23 (we already run the frontier balance; conversion activates only below ~950 after ~400 valu + ~600 alu removal; L5 dead 3 ways; occupancy tool landed)]
- statement: convert more gather levels to selection trees over preloaded
  node values, with the engine mix rebalanced JOINTLY (corsix, 971 with-idx:
  ">280 gathers can be gainfully replaced", then valu:load:flow held at
  7.5:2:1 in every individual cycle; instruction selection and scheduling
  as one search problem). We already do this for shallow levels (tournament)
  and primed level 5 (H-026); the frontier result says push it much further
  and rebalance globally rather than per-feature. First step: measure
  per-cycle valu/load/flow occupancy histogram of the 1038 build and count
  gathers by level; compare against the >280-convertible bound.
- predicted_gain: the with-idx frontier is 940 (-98 from us); this is its
  named primary lever. cost: L. Touches: tournament/gather emission + mix.
- source: H-040 (strains/cross/STATE.md), corsix writeup.

### H-042 [strain: scheduler] [status: PARKED (user directive 2026-07-27: algo-side research first — fitting/allocation deferred; also H-041 occupancy data caps beam recovery at ~12 cyc, ramp 0-100 ~4 + drain 950-1038 ~8, steady window 99.3-99.8% packed and NOT beamable)]
- statement: replace greedy bundle packing with a small beam/anneal search
  over candidate bundles (wallace, austinwallace.ca/kernel: beam width 2,
  3 candidates over the first 25 cycles already paid at 1,137). Our
  scheduler strain was retired on "the 26-cyc gap is latency/throughput-
  bound, not order-fixable" — that verdict predates the select-tree mix
  (H-041); re-scoped as: beam over PACKING CHOICES (which ready op goes to
  which engine-slot, including select-vs-gather instruction choice), not
  merely order. Prereq: H-041's mix makes the choice space rich enough to
  matter; run after/with it.
- predicted_gain: unknown, evidence it beats greedy at the frontier.
  cost: M-L. Touches: scheduler only.
- source: H-040, wallace writeup. reopen-context: supersedes G-15's
  "rebalancing exhausted" ONLY in the joint selection+scheduling sense.

### P-17 [note] set-form l4_gmin crash hazard
- set specs {0,31}/{0,1} crash (IndexError) via the known idx_select/
  two_minus_fp_vec fallback hazard, now reachable through set-form sweeps.
  Future set sweeps must check `correct` per point. Fix only if set-form
  compositions ever become a live lever (today they tie at best, G-23).

### H-043 [strain: algo] [status: testing]
- statement: deep-read the frontier writeups and extract the GRAPH-SHRINK
  mechanisms item-by-item: corsix.org/content/anthropics-compiler-challenge
  (971/994) and austinwallace.ca/kernel (1,137/1,152), plus any linked
  code/repos. G-23 quantified that the frontier removed ~400 valu + ~600
  alu slots relative to us BEFORE gather conversion pays — and nothing
  open here explains where that reduction comes from (hash closed G-20,
  idx closed G-21, routing at floor). Map every disclosed technique onto
  our ledger: already-done / closed-negative-here (cite G-id; flag any
  claim that contradicts a closure — that closure is then suspect) /
  genuinely new. Rank the new ones by ideal-machine gain.
- predicted_gain: strategic; the gap is 98 cyc and unexplained. cost: S-M.
- source: G-23's successor-task clause; user directive (algo-first).

### H-044 [strain: algo] [status: testing]
- statement: IDEALIZED-MACHINE cost model (user directive 2026-07-27:
  assume INFINITE SCRATCH + PERFECT SLOT ALLOCATION; algorithm research
  first, fitting later). Build the model + tool: for a candidate
  algorithm (op multiset + dependency structure), ideal cycles =
  max(ceil(alu_slots/12 + valu_slots/6 combined optimally), load/2,
  store/2, flow/1, dependency span). Then SOLVE the serving-strategy
  question per tree level under infinite scratch: full-forest preload
  (2047 words) makes gathers optional everywhere; selects can also be
  valu madds (b + cond*(a-b)) not just flow vselects — find the min-cost
  mix (gather vs select-tree vs madd-select vs primed tables) per level,
  and the resulting global ideal floor. Deliverable: the ideal floor of
  (a) our current algorithm, (b) the best serving mix, (c) sensitivity —
  which op-count reductions actually move the ideal floor (so algo
  research can target ONLY those).
- predicted_gain: strategic compass for all subsequent algo work.
  cost: M. Touches: tools/ only (new file), no kernel changes.

### H-043 [strain: algo] [status: closed ANSWERED -> see strains/cross/STATE.md]
- result: frontier hash IS our 11-op form (corsix diagram-2 SVG decoded,
  fused constants verified) — G-10/G-20/G-21/G-23 all CONFIRMED. The
  ~400-valu-slot gap = valu->flow select EXPORT (exits the 60-lane-op
  budget) + the select-tree/load rebalance it unlocks, found via joint
  per-cycle selection x scheduling. amirhirsch (HN) independently derives
  our ~1,014-1,024 floor. No public 940/958/1002 material exists.
- SCOPE-HOLE FLAGS: G-22 was rejected on placement friction, which the
  idealized regime removes — its -144 lane-ops/level-pair is real
  (reopened as H-046). Same class: G-18's vload variant.

### H-045 [strain: algo] [status: testing — RE-SCOPED by H-044 to the full modeled prize]
- statement: FLOW-SATURATION BUILD, the complete H-044 prescription:
  (1) retain parity vectors as tournament conds instead of re-extracting
  (~2,000 lanes deleted — the infinite-scratch enabler; scratch
  liberation is the gating prerequisite), (2) serve 25->31 L4 group-
  rounds, (3) prime L4(half)/L5/L6 (H-046 mechanism, already flag-gated
  from G-22), (4) ~930 selects spelled on a bubble-free flow engine
  (100% busy vs 76.8%), 253 valu-first selects, madd-only spill,
  (5) load ~1,863 slots at ~100% util. Modeled endpoint: 931.6 ideal;
  940 needs no new algebra. idx_boundary_select (-283 slots, landed)
  is the first installment.
- predicted_gain: the entire 1038->~940 path per the LP. cost: XL
  (this is a reorganization, not a knob). depends: H-044 (done).

### H-046 [strain: algo] [status: open] (reopens G-22 under algo-first)
- statement: idealized C5-priming generalization — G-22's measured -144
  lane-ops per level-pair is real op removal; it lost only on placement
  friction (waves displacing the critical path), which perfect allocation
  removes. Estimate -400..-700 lane-ops (ideal -7..-12). Also re-examine
  G-18's vload variant under the same lens.
- predicted_gain: ideal -7..-12. cost: S (mechanism already landed,
  flag-gated). depends: only matters composed with H-045/N-4.

### H-047 [strain: algo] [status: open] (H-043's N-4)
- statement: L5+ select-trees under infinite scratch — activates only
  after H-045/H-046 free compute (G-23 joint condition); fixpoint ~950-960
  per H-043's estimate; at 940 the load budget (2x940=1,880 < 1,900)
  FORCES at least one more level off the load engine, so the frontier
  provably does this.
- predicted_gain: path from ~988 to ~950. cost: L. depends: H-045, H-044.
- note: H-042 (joint selection-during-scheduling beam = H-043's N-3) stays
  PARKED as the fitting-side converter of these ideal gains; unpark when
  the algo side lands.

### H-044 [strain: algo] [status: closed ANSWERED -> strains/algo/STATE.md, tools/ideal_floor.py]
- result: LP-based ideal-floor model (validated: reproduces 1014-1021 for
  the as-built census). BEST SERVING MIX UNDER INFINITE SCRATCH: C=931.6
  — serve L1-L3 + 31/64 L4, prime L4(half)/L5/L6, 918 selects on flow +
  253 valu-first, gather L5-L10; drives valu=alu=load=flow floors exactly
  equal (independently derives corsix's 7.5:2:1). 940 NEEDS ZERO NEW
  ALGEBRA: the reorganization suffices. With the as-built mix pinned, 940
  is unreachable by ANY compute removal (load floor 951 binds).
  Gap decomposition: 1038 -(24 friction)-> 1014 -(63 overhead+flow-shift)->
  951 -(20 mix)-> 932. Sensitivity at optimum: ~97 lane-ops/cyc (not 60);
  loads LIVE again (~0.15 cyc/load — G-22's verdict was mix-relative);
  key enabler: tournament conds are FREE under infinite scratch (path
  bits = last d parity vectors, already materialized; as-built re-extracts
  ~2,000 lanes). Flow-disabled control: 1040 (G-4/G-12/G-14 confirmed
  model-side). 892 under our rules needs ~0.93 more ops/hash removed —
  consistent with H-040.

### H-045 result addendum [status: PARTIAL ACCEPT — strain frontier 1034, mainline flip pending F-1 port]
- landed: parity_ring (cond retention via dead-window cross-block register
  borrowing, 480 words at zero net allocation), b3l ring-mask rewiring,
  parity_ring_extras (default off). Frontier: parity_ring + l4_gmin=(7,30)
  = 1034 (-4), correct on 6 seeds + debug_compares. Superadditive slices
  confirm H-044's coupled-prize direction; gmin slid 9->7; mem_prime (5,6)
  crossed to neutral.
- blockers quantified: full cond retention needs >=384 more ring words
  (mid-schedule has ZERO dead registers — everything live); flow
  saturation unreachable by spelling (select readiness anti-correlated
  with flow bubbles, third confirmation) — the flow leg is H-042/N-3
  joint scheduling, not flags. idx_boundary_select REJECTS composed
  (+3..+5).
- follow-ups: F-1 port parity_ring+gmin(7,30) to perf_takehome.py
  (mainline 1034); F-2 scratch thresholds (24w = +1 ring; 384w = full
  retention ~ 16 ideal cyc); F-5 unpark H-042 re-scoped.

### H-048 result addendum [status: PARTIAL ACCEPT — frontier 1032; SUPPLY SOLVED, CONVERSION IS THE BLOCKER]
- audit tool (tools/audit_ring_windows.py): 384 audited-safe ring words
  exist TODAY (= the F-2 full-retention threshold) — adjacent blocks'
  windows are emission-disjoint, lv re-funds rings nearly everywhere,
  ringed donors free their own st8-12. Only desert: the e0-tail/e1-head
  overlap chain. Constant dedup: zero (no duplicates).
- winner: parity_ring + l4_gmin=(8,30) + 4-ring plan (96 words) = 1032;
  gains come from relief-funded gmin slide, not rings per se; rings
  beyond ~4-6 cost more in borrow-hazard serialization than they recover
  -> the remaining 12 rings are H-042's job (schedule hazards off the
  critical path), not a word hunt (F-8).
- SOUNDNESS finding: trace liveness is UNSOUND for emit_any-raced
  operands (only the race winner's reads appear; schedule shifts flip
  races) — proven by real miscompare. Borrowing restricted to structural
  classes (st/nv/lv/root_nv_vec). Applies to ALL future borrowing.
- follow-ups: F-6 mainline flip 1032 (derive plan addresses from named
  vectors, not raw numbers); F-7 re-audit after any emission change.

### H-042 result addendum [status: PARTIAL ACCEPT — frontier 1031; per-site selection space measured-EXHAUSTED]
- mechanism: flow_spelling_plan (offline-searched per-site encoding forcing
  at emit_any race sites; correct BY CONSTRUCTION — all encodings
  equivalent, so H-048's liveness unsoundness doesn't apply). Driver:
  tools/spelling_plan_search.py (0.1s/build exact objective).
- frontier: 1032 4-ring config + flow_spelling_plan=((354,1),) = 1031
  (6 seeds + debug_compares). Plan-space optimum: greedy fixpoint,
  ~2,000-eval plateau walks, full aux space, and an independent random
  basin all converge to 1031.
- KEY MEASUREMENTS: (a) the LP's valu->flow direction NEVER pays on
  relieved configs — what pays is UNDOING greedy's myopic flow grabs in
  ramp/drain (the winning flip is flow->valu); (b) 0/155 flow-lost sites
  have a bubble within retire-delta<=3 — the anti-correlation is
  structural (round cadence creates bubbles exactly when selects aren't
  ready); (c) full 16-ring retention (384 words) now TIES 1031 with 2
  flips — complete cond retention converts to ZERO cycles, closing F-8:
  ring hazards neutralized, ring benefit also ~0 at this emission order;
  (d) F-1-form (7,30 no rings) + 2 flips = 1032 — matches the 4-ring
  frontier with zero borrowed words.
- verdict: residual flow prize (~55 modeled cyc) is EMISSION-ORDER-shaped:
  requires beam/interleave over emission order (F-11) or the H-047
  restructure. Per-site selection under fixed order is done.

### H-049 [strain: scheduler] [status: testing] (H-042's F-11 successor)
- statement: EMISSION-ORDER search. H-042 proved per-site selection under
  fixed emission order is exhausted at 1031 and the residual modeled flow
  prize (~55 cyc) is emission-order-shaped: flow bubbles occur exactly
  when no select is ready (structural cadence anti-correlation, 0/155
  sites with a bubble within retire-delta<=3). Attack the ORDER: beam /
  interleave search over group-round emission sequence (wallace precedent:
  beam width 2 over the ramp paid at his scale), using H-042's
  instrumentation (spelling_plan_search's 0.1s/build exact objective) as
  the evaluation loop, with spelling plans re-derived per candidate order.
  Targets from occupancy: ramp 0-100 (~4 cyc), drain 950-1031 (~8 cyc),
  and cadence-shifting interleaves that de-synchronize round boundaries
  from flow-bubble windows in the steady state.
- predicted_gain: unknown; bounded above by ~55 modeled; ramp+drain ~12
  measured-recoverable. cost: XL. depends: H-042 tooling (landed).

### H-050 [strain: scheduler] [status: folded into H-049's move set] (external 1018 analysis)
- statement: dynamic schedule-time valu->alu binding deferral (external
  repo's SCHED_FLEX_ALU: op carries both spellings, scheduler binds
  per-cycle on slack). The ONLY portable mechanism in their 1026->1020->
  1018 diffs — the rest is catch-up to our H-015/H-026 op-removals plus
  their-scheduler knob tuning (their architecture loses here per H-033).
  Static rebalancing is triple-closed (G-14/G-15, H-007 +60); only the
  dynamic form is untested. Their 1018 < our 1021 valu floor puts mild
  reopen-pressure on G-15 in its dynamic form only.
- predicted_gain: -2..-6 (valu binder 1021 -> toward 1014). Routed to the
  running H-049 agent (beam move set + optional post-pass) 2026-07-27.
- analysis doc: scratchpad external_1018_analysis.md (session 5cfbd141).

### H-051 [strain: scheduler] [status: closed negative -> graveyard G-25 (packing axis proven exhausted: interval LB 1015, 170k trials never beat greedy 1031; regret profile localizes all 18 cycles; NEW r9-11 epoch seam routed to H-049)]
- statement: bounded-backtrack (branch-and-bound) scheduler: schedule
  forward maintaining an ADMISSIBLE lower bound on remaining cycles
  (per-engine remaining-slots/limits + dependency span from the current
  frontier + H-044 fungibility bound); when the partial schedule exceeds
  LB + N (regret budget), backtrack and try a different packing choice.
  Incumbent = greedy 1031. Key prerequisite measurement: the REGRET
  PROFILE of the greedy schedule (where along the 1031 cycles the 17
  cycles over the 1014 floor are lost) — localizes backtrack points and
  is valuable even if full B&B thrashes. Feasibility risk: ~19k slots
  over ~1031 cycles is astronomical for naive B&B; bound looseness
  mid-schedule may cause thrash — use bounded-discrepancy/checkpointed
  restarts, not exhaustive search.
- predicted_gain: bounded above by ~17 (to the as-built-mix floor);
  complements H-049 (order moves) — B&B explores packing choices at
  fixed order. cost: XL.

### H-049 result addendum [status: PARTIAL ACCEPT — frontier 1023 (-8); order+spelling+packing TRIANGULATED closed below ~1023]
- winner: emission_plan (512-entry, tools/h049_best_plan.json) on the ring
  stack, flow_spelling_plan DROPPED (order search absorbs the spelling
  prize — re-search fixpoint at zero flips, including dynamic valu<->alu
  aux forcing per H-050); gmin (8,30) stable at every frontier (no P-3).
- coverage: 57 structured-family evals ALL >=1032 (the (4,3) diagonal is
  locally optimal at every structured granularity; several reorders are
  ring-liveness INCORRECT — every candidate needs sim-verification);
  ~245k sim-verified local-search evals; wins live in ramp/drain-seam
  windows (~9 paying moves). H-051's r9-11 epoch seam: 55k targeted
  evals, ZERO — order-resistant, chain-bound.
- TRIANGULATION (with H-042 spelling, G-25 packing/LB-1015): below ~1023
  requires op-count/chain changes (H-047 restructure or chain
  shortening), not placement/selection/order.
- follow-ups: F-12 mainline port (NOTE: must REVERT F-9's (13,29)
  multiply_add pin — spelling plan is now empty); F-13 restart-portfolio
  walks (still descending ~1-2/round); F-14 regret re-profile at 1023.

### F-14 result (regret re-profile at 1023, driver-run 2026-07-27)
- LB for the 1023 op stream: engine valu 1010, staircase 1011 (any
  packing); CP rose to 489 (order plan trades span for engine balance).
  Final regret 13 (was 18 at 1031): ramp 4 (c=0-7, CP/vbroadcast),
  epoch-seam cluster 5 (c=881-927, r9-11 — persisted, reshaped), drain 4
  (c=996-1014, cpLB>=engLB — CP-bound). H-049's -8 = both mid seams
  erased + drain 7->4.
- implication: ALL residual friction is dependency-chain-bound. Two
  op-stream levers remain: (a) H-047 re-scope — serving-mix change (LP
  wants 31/64 L4 served + L4/L5/L6 priming at the balanced mix) with the
  full plan-search toolchain (emission/spelling/ring plans) re-run per
  candidate mix; (b) H-052 (queued) — targeted chain shortening at the
  three regret sites (r9-11 group-24-31 hash+fold RAW staircase; ramp
  vbroadcast chains; final-round drain chains).

### H-052 [strain: algo] [status: open]
- statement: targeted dependency-chain shortening at the F-14 regret
  sites. The 13 residual cycles are chain-bound, not slot-bound. Sites:
  (1) r9-11 epoch seam (5 cyc): groups 24-31's r9/r10 hash+fold chains
  — restructure fold order / break RAW staircase (e.g. tree-reduce
  folds, alternate fold operand association); (2) ramp (4 cyc):
  vbroadcast RAW on setup loads — earlier constant materialization or
  alu-side broadcast alternatives; (3) drain (4 cyc): final-round
  chains — deeper b3l-style folds or store-side restructure.
  DRAIN MECHANISM (user proposal 2026-07-27, G-18 re-scoped): pair-preload
  via a DEINTERLEAVED left/right layout so both candidates are indexed by
  the walker's CURRENT position and hoist a full round ahead of the parity,
  resolving with ONE vselect (flow) and zero alu/valu. G-18 closed the
  GENERAL form on throughput (+3,472 loads -> +1,648 cyc; vload variant
  transposes, +16 alu moves/group-round). But the drain is now CP-bound
  (cpLB >= engLB from c=996 at 1023), where the mechanism's real property
  is LATENCY, and the tail has load slack. BUDGET: (valu 1010 - load 946)
  x 2 = 128 extra loads ~= 16 group-rounds before load becomes the binder.
  Apply ONLY to the drain's critical staircase groups; measure the chain,
  not the slot count. Store engine (19/2046) can pre-transform values in
  mem (mem_prime pattern) so the preload returns post-C5 values.
- predicted_gain: bounded by 13; realistic 3-6. cost: M-L.

### H-053 [strain: flow-balance] [status: REJECTED -> graveyard G-26 (broadcast class worth 0; free_slot_oracle proves ALL compute free = 993, so the engine-floor framing is retired)]
- statement: convert BINDER work into load work using the idle store
  engine (38/2046 slots used; scalar `store` opcode entirely unused).
  Census at 1023: valu 6,056 (floor 1009, BINDING), alu 11,793 (983),
  load 1,892 (946), flow 786 (768). Balance point: migrating X~95 valu
  slots to load equalizes at floor ~993 (-16). Lead candidate: the 59
  `vbroadcast` slots — pure data movement (splat scalar to 8 lanes),
  which memory does natively as 8 scalar stores (FREE) + 1 vload
  (1 load slot). Ceiling ~-10 floor for the broadcast class alone.
  Mandate is broader: audit EVERY valu/alu slot for "movement or
  re-derivation of a value memory could supply" (the parity_ring pattern
  generalized), not just vbroadcast.
- why it may beat the naive arithmetic: broadcasts are setup-phase and
  G-22 measured ~90 dependency-dead free load slots in cycles 0-60, so
  the loads may land in existing slack without moving the load floor.
- risk: the ramp is CP-bound (4 of 13 residual cycles at c=0-7); a
  store->load round trip adds dependency depth + a mem hazard edge, and
  could lengthen the region we can least afford. Measure the regret
  profile (tools/backtrack_sched.py), not just the floor.
- NOTE what is NOT migratable: v- (93) subtracts two gathered tree
  values; v^/v&/v>> are runtime hash/mask work; madd is compute. Memory
  supplies values, it does not compute.
- predicted_gain: -5..-16 floor, unknown realized. cost: M.

### H-047 result addendum [status: PARTIAL ACCEPT — frontier 1022 (-1); serve-more CLOSED by floor measurement; F-17 retargets the whole loop]
- winner (driver-verified 1022 on main): parity_ring, l4_gmin=(7,30),
  4-ring plan, c5_primed_gather_levels=(5,6), mem_prime_region_hazards,
  mem_prime_dead_reg_staging, flow_spelling_plan=(), emission_plan=
  tools/h047_best_plan_1022.json. NOTE the artifact's params block does
  NOT carry the flag set — the full config above is required.
- PREMISE CONFIRMED: G-22's mem_prime(5,6) converts +1 (fixed order) ->
  -1 (per-candidate order re-search). Clean 2x2 attribution: BOTH legs
  required; priming deletes ~184 alu slots -> funds the P-3 gmin slide
  -> valu 6056->6049 (floor 1011->1010); order search recovers the same
  12-cyc residual. Serve+1 alone ties; prime alone 1024.
- SERVE-MORE CLOSED at floor level (no walks needed): at greedy
  spellings every added L4 serve RAISES the floor (+7.2 valu slots per
  serve); gmin(7,27) floor 1018, set-form e0 floor 1015. Hard blocker:
  any e1<27 CRASHES (omf1_vec/b3l private-register wall) -> F-16.
- **F-17, the strategic result**: the flowmax probe (force every
  flow-capable race site to flow, legal per H-042 soundness) shows the
  LP mechanism is REAL at stream level — mp56+(7,30) all-flow reaches
  any-packing floor **990**, i.e. a FLAG-REACHABLE op stream 33 cycles
  below today's realization, with valu 995 / flow 989 (corsix's balanced
  ratio emerges). Its actual schedule is 1104: the entire 33-cycle
  remainder is locked behind the select-readiness x flow-bubble
  anti-correlation. ALL future flow-cadence/emission mechanisms must be
  evaluated on the floor-990 stream (mp56 + gmin(7,30..27) + flow-heavy
  spellings) — baseline-mix evaluation understates the prize by ~15
  floor cycles.
- F-18: e1 composition plateau ({29,30}/{27,30} tie) = free DOF for
  H-052's drain restructure.

### H-055 [strain: algo] [status: testing] (F-20 successor; absorbs H-052 + the user's drain mechanism)
- statement: SHORTEN THE ALTERNATING valu<->load CHAIN. H-054's shadow
  prices are decisive: flow 0, store 0, alu -2, valu -6, load -7 alone,
  but **valu8+load4 = -181** (841 cycles). c100-c800 runs valu/alu/load
  all at 100% simultaneously. The critical structure alternates vector
  compute with gathers: parity -> address madd -> gather -> hash ->
  parity. Every prior axis (spelling G-24-adjacent, packing G-25, order
  H-049 residual, flow G-27, compute-migration G-26) is closed; this
  alternation IS the remaining structure.
- primary mechanism (user proposal, 2026-07-27): DEINTERLEAVED left/right
  pair-preload. Because both children are indexed by the walker's CURRENT
  position, the loads hoist a full round ahead of the parity, and the
  step becomes parity -> vselect, DELETING the address-madd link from
  between the parity and the gather — i.e. it removes one valu<->load
  alternation per level. G-18 closed the GENERAL form on load throughput
  (+3,472 loads); the point now is that load throughput relief and valu
  relief are superadditive (-181), so the trade must be re-measured
  JOINTLY, not on the load axis alone.
- secondary sites (H-052's regret targets at 1022): ramp 4 cyc
  (vbroadcast RAW on setup loads), r8-r15 seam 5 cyc, drain 4 cyc
  (CP-bound, rounds 14-15 — the F-18 e1 composition plateau
  {29,30}/{27,30} is free DOF here).
- pre-screens available (run BEFORE prototyping): tools/h054_shadow.py
  (20 s, ceilings any candidate), tools/free_slot_oracle.py,
  tools/h054_oracle.py, tools/backtrack_sched.py regret.
- predicted_gain: unknown but this is where the -181 joint signal lives;
  the free-compute bound is 993 and CP-bound regions dominate it.

### H-056 [strain: algo] [status: testing] (post-convergence: re-open the ORGANIZATION)
- statement: every axis WITHIN the current program organization is now
  closed with evidence (G-16/18/20/21/22/24/25/26/27/28/29 + H-047's
  serve-more floor closure); envelope is 1020 -> 1006 and unreachable by
  order/packing. The one untested surface is the ORGANIZATION ITSELF:
  the (32 groups x 8 lanes x 2 epochs, skew=(4,3), 11-round period,
  block=8) decomposition. Every prior organization experiment (uneven
  blocks / external-repo 13-block shape / skew sweeps, commit f76753c
  and the sweep phases) was measured under a GREEDY emission order and
  the pre-H-042 spelling regime — both of which no longer exist.
- why this is a justified reopen, not a re-run: H-047 proved the exact
  pattern — G-22's mem_prime(5,6) flipped from +1 to -1 once the order
  was re-searched per candidate. F-13 then proved orders are MIX-SPECIFIC
  (each mix's plan scores ~1027 on the other), so ANY organization
  change must carry its own order search or it is being measured wrong.
- method: for each organization candidate (skew shape, block size/evenness,
  group count, epoch split, round-period phase), run the standing
  pre-screens FIRST (h054_shadow for the resource ceiling, backtrack_sched
  for LB+regret, free_slot_oracle if op classes move), then an emission
  order walk seeded fresh (radius +/-8..32 per G-29's saturation finding)
  ONLY for candidates whose LB is at or below 1006. Report LB even for
  cycle-negative candidates — a lower-LB stream is the input to the next
  order round.
- predicted_gain: unknown; this is the only surface left below 1006.
  cost: XL.

### F-25 result addendum [ACCEPTED — frontier 1011; ALSO a mainline soundness fix]
- winner artifact tools/f25_best_plan.json: H-056 organization + ring plan
  RE-MINED for it (23 audited plan rings / 552 words, closed-loop
  re-checked at this exact order) + l4_gmin re-slid to (6,30) + order
  re-walked. flow_spelling_plan re-derived = EMPTY (H-047/H-054's verdict
  transfers to this organization). Driver-verified 1011 correct on TEN
  seeds.
- **RING PLANS ARE ORDER-SPECIFIC (new soundness fact).** Borrow windows
  are timed against the emission order, so an order change invalidates
  the plan. The CURRENT MAINLINE (1015) carries H-048's 4-ring plan
  through H-056's organization change and DRIVER-CONFIRMED shows
  LIVE-ACROSS violations (ring (0,6), donor st9). The grader does not
  catch it (correct on every seed tested). Caveat: the audit window is a
  superset of real ring accesses, so violations may be false positives —
  but that plan is worth ZERO cycles at that order (() also = 1015,
  audits OK over 20 rings), so removing it is free de-risking. The 1011
  config audits CLEAN (0 violations over 43 rings), so the F-29 port
  resolves this.
- STANDING RULE: after ANY order or organization change, re-mine and
  re-audit the ring plan (audit -> add -> re-audit fixpoint), and never
  carry a plan across orders.
- how the ~6 predicted cycles converted: 4, and not by the predicted
  mechanism. Op deletion at a 1-move optimum with a 68% plateau converts
  at ZERO; the causal chain is rings -> floor (LB 1003 -> 998) -> floor
  funds the serving slide (-1) -> the changed stream reopens the order
  landscape (-3).
- f18_exhaust1 at 1015: 25,637 moves, zero (H-056's order was a genuine
  strict 1-move optimum). At 1011: 25,641 moves, zero. Plans are
  all-or-nothing: leave-one-out of ring (0,25) goes correct:FALSE.
- follow-ups: F-29 port 1011 (order + 23-ring map + gmin(6,30)); F-30
  walk the LB-995/fungible-992 (7,31)+23-ring stream (unwalked); F-31
  decide whether any `anon`-class word is schedule-independent (last
  third of full retention); F-32 subsumed by F-29.

### F-24 result [TIE at 1011 by an independent route; CORRECTS the LB-992 claim; new axis found]
- **CORRECTION to H-056's headline: the "LB 992 stream" prize DOES NOT
  EXIST.** h056_screen already computes ENERGETIC STAIRCASE bounds
  (equally valid for any packing); H-056 ranked on lb_total alone and
  missed them. gmin>=16 streams: LB 992/991 but **energetic 1011**, and
  realized 1069-1070. gmin 16 buys ~50 valu slots for 66-88 extra loads
  — it lowers the slot floor while RAISING the release staircase. Zero
  further budget; re-confirmed at the new organization (LB 993 /
  energetic 1011 / realized 1054, and a walk found ZERO moves).
  STANDING RULE: screen on max(lb_total, energetic), never lb_total.
- **Greedy cycles predict walk outcome far better than LB.** LB-996/997
  streams walk to 1018-1019; greedy-1019/1022 streams (LB 1000-1002)
  walk to 1011-1015. A plain measure is 0.20 s vs ~4 s for an LB screen,
  so rank organizations on GREEDY CYCLES and LB-screen only survivors
  (29,296 organizations in ~28 min this way).
- **NEW AXIS: the lag diagonal should be NON-UNIFORM.** Every H-056
  candidate used lags = s*b. F-24's winner is 8 blocks of 4 with lags
  (0,3,6,6,10,10,13,14), zip/default/asc -> 1011 (LB 1000 / energetic
  1002 / fungible 997 / cp 490), correct on 7 seeds + debug_compares,
  ring audit clean (0/24), gmin (7,30) still optimal, port dry-run
  grades 1011. Artifact tools/f24_best_plan_1011.json (+ a second
  independent diagonal at 1012). The diagonal search was STILL producing
  new bests when budget ran out (greedy 1022->1021->1020->1019).
- NOT ADDITIVE AS TESTED with F-25/F-29's 1011: gmin(6,30) does not
  transfer (1015 here), the 23-ring plan asserts out at this order, and
  a re-mined 20-ring plan costs +5 before re-walking and only ties after
  37k evals. Not ported (tie, no gain).
- f18_exhaust1 at F-24's 1019 plan: 94% neutral (vs G-29's 55%) — order
  search on a fixed organization saturates almost instantly.

### H-057 [strain: algo] [status: testing] (the joint chain on F-24's diagonal)
- statement: run the FULL F-25 recipe on F-24's non-uniform-diagonal
  organization: re-mine the ring plan at that order (audit -> add ->
  re-audit fixpoint, structural donors only), re-slide l4_gmin on the
  resulting retention relief, then re-walk the order — the exact chain
  that earned F-25 -4 at a WORSE organization (LB 1003 -> 998 -> slide
  -> re-walk). F-24 stopped before this. Also continue the non-uniform
  diagonal search itself (still descending: greedy 1022->1019).
- predicted_gain: F-25's chain was worth -4 from a worse base; F-24's
  diagonal has LB 1000 / energetic 1002 vs the current 1011 realized.
- method: rank on GREEDY CYCLES, LB-screen survivors on
  max(lb_total, energetic).

### H-057 result [ACCEPTED — frontier 1006 (-5); the CHAIN is the lever, not the diagonal]
- winner tools/h057_best_plan_1006.json: F-24's diagonal (8 blocks of 4,
  lags (0,3,6,6,10,10,13,14), zip/default/asc) + 20-ring re-mined plan +
  gmin (6,31) + re-walked order + empty spelling. Driver-verified 1006
  correct on 8 seeds; ring audit clean (0 violations / 40 rings).
- **F-25's causal mechanism reproduced on a DIFFERENT organization**:
  rings buy FLOOR only (LB 1000->995) at +5 realized cost, the floor
  funds a serving slide, the changed stream re-opens the order landscape.
  Stage table: 1011 base -> 1016 (rings) -> 1014 (gmin (6,31)) -> 1010
  (walk) -> 1006 (walk/re-mine/walk x2). **The chain is worth -5 on
  F-24's diagonal and -7 on the second one (which F-24 had walked to only
  1014 without it) — the CHAIN is the lever, not the diagonal.**
- **NEW SEARCH AXIS: ROUND windows, not position windows.** Position
  windows (both/all/ramp/mid/drain) plateaued at 1010 for 62k evals over
  10 re-seeded chains at every jump set 1..64. EVERY step below 1010 came
  from `--window r:11-15` (epoch-1 round window) or `drain`.
- **Ring soundness is SEARCH-SHAPING, not just a check.** ~half the
  walked orders invalidate their own plan (1008 order: 80 violations/40
  rings) — and the unsound points are the FASTER ones, correct:true on
  all 7 seeds. Re-mining them costs 1-3 cycles but yields a
  differently-conditioned stream that re-walks lower. Path:
  1010 clean -> 1008 dirty -> re-mine 1011 -> walk 1007 dirty ->
  re-mine 1008 clean -> walk 1006 clean. ALSO: always RE-MINE FROM EMPTY
  — mining from a carried plan yields an unsound set where mining from
  () yields a clean one.
- **ORGANIZATION SEARCH CLOSED**: 52,361 more organizations screened
  (elitist perturbation over diagonals x uneven blocks x wave/group order
  x interleave, k in {6,8,10,16}, 2 seeds) -> ZERO below greedy 1019.
  With F-24's 29,296 that is ~82k organizations. F-24's "still
  descending" was its first 44 seeds descending, not the search.
- **Greedy ranking INVERTS under the chain**: the greedy-1019 diagonal
  walks to 1007, the greedy-1021 one to 1006. Screen on greedy, but walk
  more than the top candidate.
- spelling re-derived at 1006 (flow + aux) = EMPTY, fifth independent
  confirmation. Spend: 280,528 walk evals / 48 chains, 52,361 org
  screens, ~150 mine+audit fixpoints.
- follow-ups: F-33 port 1006 (dispatched); F-34 finer ROUND windows
  crossed with the re-mine loop (the live axis); F-35 make the walk
  audit-aware so it can keep the currently-discarded fast-but-dirty
  points (re-mine in-loop instead of rejecting).

### F-37 [strain: algo] [status: open] — THE ONLY LIVE ORDER AXIS
- statement: simultaneous k-entry displacements confined to ROUNDS 12-15
  (the only rounds that pay, per G-30's productivity map), k in 2..4,
  seeded at the 1006 plan. The 7,487-move exact-1006 plateau enumerated
  by f18_exhaust1 is the raw material to compose across: single moves
  are provably empty, so any remaining order win must be a strictly
  paired/tripled escape, and it must live in rounds 12-15.
- predicted_gain: unknown; this is the last untried order structure.
  cost: M-L. Use the audit-aware loop (tools/f35_loop.py) with the
  GROW-then-PRUNE fixpoint, branch-and-return around the best clean point.

### F-38 [strain: algo] [status: open] — basin-width probe
- statement: 0 of 12 perturbed restarts re-found 1006 (best 1008), weak
  evidence of a narrow basin. Characterize it: how much perturbation is
  recoverable, and does a wider/multi-start portfolio find a DIFFERENT
  1006-or-better basin? Cheap; informs whether further order search on
  this mix is worth any budget at all.
