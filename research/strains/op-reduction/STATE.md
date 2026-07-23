# Strain: op-reduction

## Charter
Reduce total lane-ops by algebra/search: hash is 49,152 ops (69% of all
work; floor 819 if nothing else existed), Idx is 8,592. Every op removed
per eval is ~68 cycles. Owns code regions: rust_harness/src/problem.rs
(searcher), the fused-hash constants block in perf_takehome.py.

## Frontier
strain frontier 1106 (-24 vs mainline 1130) @ iter-2 commit:
`c5_prexor=True` + retuned `l4_gmin=(18,28)`; flag-only at frozen mainline
tunables = 1119 (-11). MAINLINE CANDIDATE. valu stays the binding engine:
97.9% busy, 6496 slots = 1082.7 cycle-equivalents at 1106 actual (+23
friction, same as mainline's +24) — the elision gain is fully banked.
H-003 (iter 1): no shorter form for the 11/12/13-op hash exists within the
searched spaces (all adjacent-segment cuts at depth <= current-1, fold-in
head to depth 4, cross-round tail to depth 4; ~400B candidate programs).

## Assigned
- H-003 (iter 1): DONE — see iteration log.
- H-015 (iter 2): DONE — implemented, strain frontier 1106; see log.
Queued: H-004 (fold p:=2p+b away), H-012 (floor recalibration).

## Iteration log
(append-only)
- 2026-07-23 iter 1 (H-003, @42d565e base): built
  `rust_harness/src/bin/fusion_search.rs` + `problem.rs::hashseg` —
  exhaustive-in-pool superoptimizer over the machine's ops (multiply_add
  and add/sub/mul/xor/and/or/shl/shr; div/mod/lt/eq excluded). Interior
  operand constants come from per-target pools (stage constants + their
  products/shifts/inverses); the FINAL op's constants are SOLVED over all
  2^32 values from the probes (xor/add/sub/and/or/shift amounts, and
  madd's full (K,C) pair via odd-difference inversion mod 2^32); 32-probe
  duplicate pruning; every find re-verified on 10M+ random + structured
  inputs. Self-tests make the searcher rediscover the stage2+3 fusion.
  NEGATIVE results (no program of <= current-1 ops in space; exhaustive
  within stated pools/depths only, NOT a global minimality proof):
    * every adjacent-segment cut of the 11-op chain: stage0∘1 4->3,
      stage1-tail∘f23 4->3, f23∘stage4 4->3, stage4∘5 4->3, sigma19∘madd
      3->2, stage1 3->2, f23 3->2, stage5 3->2, and the 3-stage span
      stage1-tail∘f23∘stage4 5->4 (u2e);
    * form (b) fold-in: (v^n)-head 2->1 and 5->4 at depth 4 (130.6B
      candidates), cross-round tail stage0(stage5(e)^n) 5->4 (126.3B);
    * full hash <= 3 ops (sanity), parity-from-c <= 3 (rich pool) and
      <= 4 (lean pool, 66.2B candidates).
  Totals: ~400B complete candidate programs across 18 target/depth
  questions, all runs exhausted (no timeouts).
  Global exhaustive search at depth <= 10 for the whole hash is
  combinatorially out of reach (~10^28 even with small pools); the
  compositional cut coverage above is the honest strongest statement.
  POSITIVE finds (both verified bit-exact vs myhash on 10M+ inputs and
  locked in as problem.rs tests parity_from_d_is_bit_exact /
  parity_from_e_is_bit_exact, plus a universal carry-free-bit31 proof in
  the comments):
    * parity (myhash&1) from the f23 output d in 2 ops:
      (d*0x80048000 + 0x23628000) >> 31   [vs 5 ops via the value chain]
    * parity from the stage4 output e in 2 ops:
      (e*0x80008000 + 0x80000000) >> 31   [vs 4 ops]
  These do NOT shorten form (c) as a single-output program (parity would
  cost +1 net op/eval if added beside the full hash) — their value is
  CRITICAL-PATH: parity is ready 2-3 dependency levels before the full
  hash, exactly what H-002 needs; no kernel change made here (owned by
  critical-path strain).
  Also identified analytically: the final `^C5` commutes across the round
  boundary through the fold-in xor — pre-xoring every tree node value
  (and the initial vals) with C5 removes 1 op/eval in steady state
  (12 -> 11 with fold-in); the xr3 search confirms the resulting 4-op
  boundary is minimal-in-space. See P-1.
  Kernel port: NONE (port rule requires a strictly shorter sequence for
  (a)/(b)/(c) as defined; none exists in the searched spaces). Default
  verified unchanged: run_variant.py = 1140, submission_tests green,
  cargo fmt/clippy/test green.

- 2026-07-23 iter 2 (H-015, @3df7a9e base): implemented `c5_prexor`
  (default-off; requires parity_conds; asserts C5 odd, maxT>=2, no
  parity_early). MEASURED: flag-only 1119 (-11); + l4_gmin=(18,28) 1106
  (-24); grader 9/9 green at unchanged default 1130; default stream
  bit-identical to 3df7a9e (programmatic bundle compare over dispatch,
  mainline kwargs, run_variant BASE, parity_conds=False, parity_early=(3,)).
  DESIGN (differs from the P-1 sketch in two load-bearing ways):
  * NO whole-tree preprocessing: +254 vloads would push the load engine
    from 1992 to ~2246 slots -> >=1115-cycle floor, sinking the -68 gross.
    Instead only SOURCES that are free to prime are primed: the 30
    lv-scratch tree words (4 vxors after the existing vloads), the
    broadcast tables derived from them, a primed-root broadcast (1 alu
    xor + 1 vbroadcast), and the 16 level-4 tree words REWRITTEN IN MEM
    from the already-primed lv scratch (2 add_imm + 2 vstores at setup;
    in-place is safe: the coarse mem_write hazard lands ~cycle 10, far
    before the first gather). Elide set = rounds whose NEXT round folds a
    primed source = {0,1,2,3,10,11,12,13,14} x all 32 groups = 288 vec
    xors removed (levels 5..10 gather the true tree and keep `^C5`; last
    round keeps it so stored values are true; round 0 folds the TRUE
    root+vals, so initial vals need no pre-xor).
  * Parity correction is ZERO-op via table REVERSAL, not omf/rec-only:
    C5 odd => parities exit elided rounds inverted, and every round
    feeding a tournament is elided, so the accumulator st uniformly
    carries the bitwise COMPLEMENT p'=~p. Selecting with all-inverted
    index bits from a REVERSED table equals true selection, so the whole
    tournament fold emission (L1/L2/L3/L4 madds+vselects) is UNTOUCHED —
    only the setup lists change: pair order reversed, base=odd',
    diff=even'-odd' (diffs are NOT xor-invariant; recomputed from primed
    scalars). Epoch exits from complement-st use one madd by a negtwo
    vector + rec offsets fp + (2^Ln-1 + 2^(L+1)-2 + [par inverted]),
    then +par / -par — same op count as before. Gather-round exits are
    untouched (true domain on both sides).
  Costs: 19 scratch words (negtwo + primed root + store addr) traded for
  one cond-pool slot (CP 4->3, measured free: (17,3) == (17,4) == 1130);
  scratch 1522/1536. Op census delta at frozen tunables: valu -153 slots
  (6634->6481), alu -1031 (offloaded xors gone), load +1, store +2.
  VALIDATION: debug-compare builds run with enable_debug=True against the
  reference trace — under c5_prexor only true-domain values are compared
  (node_val on round 0 + gather levels >=5; hashed_val on rounds 4..9 and
  the FINAL round = the stored values), 448 vcompares all pass at the
  graded shape; primed-domain intermediates are intentionally not
  compared (debug slots cannot compute val^C5) and are covered by the
  end-to-end grader. 5-seed correctness at both configs; alt shapes
  (r=12, r=11, bs=64, h=4, h=3/maxT=2, h=5) all correct with debug on.
  SWEEP under the flag: l4_gmin strongly retunes (18,28)=1106,
  (17,28)/(16,28)/(19,28)=1108-9 vs (22,28)=1119 — cheaper tournaments
  (post-elision) shift the gather/serve balance; skew (4,3) stays best
  ([0,4,7,10]=1118 next); pool_sizes (17,4) stays best.

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
- P-1 [op-reduction]: C5-pre-xor value domain. Pre-xor all 2047 tree node
  values with C5 once (a preprocessing pass over levels >= 4 hidden in the
  early compute-bound rounds: ~256 vload+vxor+vstore; tournament D/E
  scratch tables for levels 0..3 derived from pre-xored values at preload
  for free; initial vals pre-xored at load: 32 vxors), then every round
  computes val' = e ^ (e>>16) ^ n' (3 ops) instead of
  e ^ (e>>16) ^ C5 ^ n (4 ops): -4096 lane-ops ≈ -68 cyc gross. Costs:
  parity comes out C5_0-inverted (absorb into the accumulator offset
  constants omf/rec — re-derive, 0 extra ops), last round must emit true
  val (+32 vxors), preprocessing loads/stores compete with nothing early
  (levels 0-3 are gather-free). Predicted net -45..-60 cyc. Medium cost,
  touches preload + tournament constants + store path.
- P-2 [critical-path handoff, feeds H-002/H-008]: use parity_from_d
  (2 ops after the f23 xor, i.e. ready at hash-depth 9 instead of 12
  counting the fold-in) to issue the next gather 3 levels earlier; net
  +1 valu op/eval (2 new ops replace the 1-op `&1`), pays iff it removes
  the tournament/load stall H-002 targets. Constants exported as
  hashseg::PAR_D_K/PAR_D_C (and PAR_E_* one stage later at the same +1).
- P-3 [op-reduction, small]: extend fusion_search with meet-in-the-middle
  (forward-2 signature set + invertible-backward-2) to push the two
  5->4 boundary questions to 6->5 (stage1∘f23 span, b2d) and the
  cross-round boundary to depth 5 — the only remaining unsearched
  shortening candidates below global scale.
- P-4 [op-reduction, iter-2 follow-up]: deep-tree pre-xor (levels 5..10,
  the part of H-015 NOT taken). Would elide rounds 4..9 too (+192 vec
  xors, valu floor 1083->~1051) but costs +254 vloads: load engine goes
  1961->2215 slots => >=1108-cycle hard floor at 2/cycle — unprofitable
  TODAY by arithmetic alone (no experiment needed). Reopen-if: total load
  slots drop below ~1850 (e.g. L5 tournament serving or batched gathers),
  then re-cost; the c5_prexor plumbing (primed_nv/elide) already supports
  it by flipping primed_nv for gather levels + an omf sign variant.
- P-5 [sweep handoff, iter-2]: l4_gmin retunes under c5_prexor —
  (18,28) is -13 vs the frozen (22,28); add c5_prexor=True x l4_gmin
  {16..22} x {26..30} to the sweep grid (H-005/H-013). skew/pool_sizes
  stay at mainline optima.
- P-6 [flow-balance interaction note, for H-017]: c5_prexor keeps the
  (evens, diffs)/(E_vecs, D_vecs) list API but the entries become
  (odd', even'-odd') in REVERSED pair order, and all tournament
  conditions arrive INVERTED. H-017's madd->vselect first-fold flip
  composes iff its O_vecs derivation goes through the same setup lists
  (vselect(b', X, Y) with X=even', Y=odd' — i.e. swap arms relative to
  the true-domain form; the reversal already handles the older bits).
