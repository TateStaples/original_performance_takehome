# Hypothesis Backlog

Schema per block: id, strain, statement, predicted (gain + mechanism), cost
(S/M/L in agent-iterations), depends, status: open | testing | accepted |
rejected | blocked(H-x) | superseded(H-x), result (measured @ commit), log.
IDs never reused. Driver-only writes; agents propose follow-ups in their
strain STATE.md and the driver promotes them here.

### H-001 [strain: flow-balance] [status: testing]
- statement: Eliminate/offload tournament condition-extraction ops (`& one_vec`,
  `& 2^k`, `>>`) from valu/alu. Prime variant: keep the last k per-group parity
  VECTORS alive (they are already computed each round for the state update)
  and feed them to vselect directly, instead of packing bits into the position
  accumulator and re-extracting with masks.
- predicted: -40..-120 cyc. Routing+Idx arith on valu/alu today ~3.4k lane-ops;
  every 60 removed ~= 1 cycle; also shortens tournament dep chains.
- cost: M. depends: none. CAUTION: scratch is FULL (1535/1536) — parity rings
  must be traded against pool_sizes/cond pools, not added.
- result:
- log: 2026-07-23 opened; assigned iter 1.

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

### H-003 [strain: op-reduction] [status: testing]
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
- result:
- log: 2026-07-23 opened; assigned iter 1.

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
  are coincidentally contiguous (measure frequency first); revisit pair-gather
  (both children fetched a round early) IF scratch is freed and load is no
  longer the binding engine on the target rounds (see graveyard G-3).
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

### H-014 [strain: critical-path] [status: open]
- statement: Spend the 32 freed words (pool_sizes=(17,3)) on load-side state:
  nv double-buffering so gathers for round r+1 never wait on round r's nv
  consumption (today nv is reused; check ListScheduler WAR stalls on nv+lane).
- predicted: -5..-20 cyc. cost: S-M. depends: none (words available now).
- result:
- log: 2026-07-23 promoted from critical-path follow-ups.
