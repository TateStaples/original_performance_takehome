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

### H-004 [strain: op-reduction] [status: open]
- statement: Fold the idx/state update `p := 2p + b` (one madd per group-round,
  1,000+ madds) into existing ops — e.g. carry position pre-scaled so the
  gather-address madd absorbs it, or derive position bits directly from saved
  parity vectors (synergy with H-001) making the accumulator unnecessary on
  tournament levels.
- predicted: -20..-60 cyc (Idx = 8,592 lane-ops total).
- cost: M. depends: stronger after H-001.
- result:
- log: 2026-07-23 opened.

### H-005 [strain: sweep] [status: testing]
- statement: Grid-search tunables of build_kernel_scheduled: skew shapes
  (block counts x lags, incl. asymmetric lists), l4_gmin pairs, pool_sizes,
  tournament_levels subsets. Grid auto-grows with every new flag other
  strains land (free cross-pollination).
- predicted: -5..-30 cyc (pure placement); zero LLM cost.
- cost: S (background CPU). depends: none.
- result:
- log: 2026-07-23 opened; background process launched iter 1.

### H-006 [strain: flow-balance] [status: open]
- statement: Load-side tricks: vload-batch gathers when 8 walkers' addresses
  are coincidentally contiguous (measure frequency first — the nv-WAR
  instrumentation hook from H-014 measures contiguity too); revisit
  pair-gather IF load stops binding on target rounds (G-3). H-014's result
  says slot DEMAND reduction is the only live load-engine lever.
- predicted: -10..-40 cyc. cost: M. depends: scratch relief — NOTE: 32 words
  now known freeable at zero cost via pool_sizes=(17,3) (H-002 side finding).
- result:
- log: 2026-07-23 opened.

### H-007 [strain: flow-balance] [status: open]
- statement: Move a schedule-aware SUBSET of tournament folds from valu madd
  to flow vselect — not whole levels (graveyard G-4: full L4-on-flow lost by
  serialization) but per-fold placement chosen by which engine is the cycle's
  binding constraint (extend ListScheduler to try both placements).
- predicted: -15..-50 cyc (valu 98% vs flow 30%). cost: M. depends: none.
- result:
- log: 2026-07-23 opened.

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

### H-009 [strain: flow-balance] [status: open]
- statement: Cross-round software pipelining of the hash itself: split the
  12-op hash so stages of round r+1 interleave with stages of round r within
  a group (beyond what group-skewing already gives), reducing pool pressure
  and exposing more same-cycle ILP.
- predicted: -10..-30 cyc. cost: L. depends: none.
- result:
- log: 2026-07-23 opened.

### H-010 [strain: critical-path] [status: open]
- statement: Parity speculation: on rounds where the next level is served
  from scratch both ways cheaply (levels 0..2), compute BOTH children's
  contributions and select late — removes the parity->select dependency
  entirely on those rounds.
- predicted: -10..-25 cyc. cost: M. depends: none.
- result:
- log: 2026-07-23 opened.

### H-011 [strain: flow-balance] [status: open]
- statement: Flow-engine parity extraction (H-001 x H-002 combo): if parity
  vectors are kept (H-001) AND parity-early exists (H-002), the `& one_vec`
  per round disappears from valu into either the early chain or a vselect.
- predicted: -15..-35 cyc. cost: S once parents land. depends: H-001 (the
  parity_early flag from H-002 already exists if a latency use appears).
- result:
- log: 2026-07-23 opened.

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

### H-016 [strain: op-reduction] [status: open]
- statement: Extend fusion_search with meet-in-the-middle (forward-2
  signatures x invertible-backward-2) to push the two 5->4 boundary
  questions to 6->5 (stage1∘f23 span, b2d) and cross-round to depth 5 —
  the only remaining unsearched shortening candidates below global scale.
- predicted: uncertain; each hit -68 cyc. cost: S-M. depends: none.
- result:
- log: 2026-07-23 promoted from op-reduction P-3.

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

### H-018 [strain: flow-balance] [status: open]
- statement: valu madd diet: hunt the lagged p-fold madds and epoch-exit
  conversion madds (feeds H-004's idx-elimination ideas) now that valu
  throughput (not alu, not latency) is the binding constraint.
- predicted: -5..-20 cyc. cost: M. depends: H-001 (in mainline).
- result:
- log: 2026-07-23 promoted from flow-balance P-2.

### H-019 [strain: flow-balance] [status: open]
- statement: Generalize dual placement (H-017's P-4): partial-L4 vsel_auto
  (17 free words fund 2 of 8 W-pair odd tables) and a ListScheduler
  `emit_any(encodings)` primitive unifying the fold race with the alu-split
  race — every multi-encoding op placed wherever it retires earliest.
- predicted: -5..-15 cyc (valu floor 1073 vs 1107 actual = 34 cyc of slack
  to harvest). cost: M. depends: H-017 (in mainline).
- result:
- log: 2026-07-23 promoted from flow-balance P-4.

### H-020 [strain: sweep] [status: open]
- statement: pool-shape x vsel_auto interaction sweep ((16,3) beat (17,3) by
  2): re-run full grid under the 1107 mainline; add vsel_auto level subsets
  and partial-L4 variants to the grid as they land.
- predicted: -2..-8 cyc. cost: S (background). depends: none.
- result:
- log: 2026-07-23 promoted from flow-balance P-5.
