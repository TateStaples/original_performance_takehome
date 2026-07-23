# Strain: op-reduction

## Charter
Reduce total lane-ops by algebra/search: hash is 49,152 ops (69% of all
work; floor 819 if nothing else existed), Idx is 8,592. Every op removed
per eval is ~68 cycles. Owns code regions: rust_harness/src/problem.rs
(searcher), the fused-hash constants block in perf_takehome.py.

## Frontier
mainline 1070 contains this strain's c5_prexor (H-015); no new kernel
change this iteration. H-016 (iter 4) CLOSED NEGATIVE: the MITM search
answers the last open boundary questions below global scale — no 5-op
form for either 6-op boundary span (b2d, xr5), no 4-op form for the
primed cross-round (xr3p), and H-003's 5->4 negatives survive the
out-of-pool-constant meet space. Combined with H-003/G-10, every
adjacent-segment cut of the 11/12-op hash is now pinned at depth
current-1 (forward-exhaustive to k<=4, MITM shapes at k=5). The strain
has no remaining single-segment shortening candidate; op-count relief
must come from non-adjacent/global identities (SAT-class, P-8) or from
outside the hash (load-side, scheduling).

## Assigned
- H-003 (iter 1): DONE — see iteration log.
- H-015 (iter 2): DONE — implemented, strain frontier 1106; see log.
- H-004 (iter 3): CLOSED (subsumed by idx_race) -> G-15.
- H-016 (iter 4): DONE — closed negative; see iteration log.
Queued: H-012 (floor recalibration).

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

- 2026-07-23 iter 4 (H-016, @283427d base): meet-in-the-middle extension
  of fusion_search (`--mitm`, `--stretch`; helper `hashseg::sigma16`).
  MACHINERY — three engines per boundary target, sharing report/verify
  (every candidate hit re-verified on 10M+ random + structured inputs):
    * engine A: the iter-1 forward-exhaustive searcher (full coverage of
      ALL k<=4 programs over its printed pool, solved-final-op included);
    * engine B: forward DFS to depth 3 probing hash tables of all
      INVERTED 1-op and 2-op suffix chains — links are xor-c, K*y+c with
      K odd (16-K set: stage multipliers, 2^j+-1, -1), plus the 2-op
      xorshift macros y^(y>>s)/y^(y<<s) (s=1..31); link constants from a
      72-value enriched pool (stage consts + pairwise xor/sum/product +
      shifted variants + powers of two; full pool printed per target);
    * engine C: DFS over suffix chains up to 5 ops (caps: <=3 unary
      links; 5-op chains <=1 unary) probing tables of all 0/1/2-op
      forward prefixes.
  The MEET op between a forward value m and a required suffix input r is
  SOLVED over all 2^32, not pooled: xor-by-any-c via xor-normalized
  battery signatures; madd by ANY (K,C) — even K included — via odd-part
  affine canonicalization with 2^t-shifted table keys (t<=12). Both
  normalizations are exact equivalences (proof in `affine_canon`'s
  comment; locked by test `affine_canon_invariance`). End-to-end
  self-tests: engine C rediscovers the 4-op stage4∘stage5 span as
  kf=0 + solved-affine-meet + [XsR(16), XorC(C5)] chain; engine B finds
  a planted forward+suffix split (`mitm_engine_{b,c}_*` tests), plus
  xorshift-inversion and even-K meet-solve unit tests.
  RESULTS — ALL NEGATIVE, all spaces exhausted (no timeouts), 32-probe
  signatures, 4-core box, per-target wallclock in parens:
    * b2d 6->5 — f23(stage1(b)), THE promoted boundary question:
      NO <=5-op program. A: k<=4 FULL, 757.8B candidates (798s);
      B: 359.7M fwd nodes x (1,221 j=1 + 1,425,893 j=2 chains);
      C: 2.118B chain nodes x (1+307+84,334 prefixes). (1758s)
    * xr5 6->5 — stage0(stage5(stage4(d))^n), cross-round one op deeper
      than H-003's xr4: NO <=5-op program. A: k<=4 full at lean pool,
      1.0243T candidates (884s); B: 1.803B nodes x (1,221 + 1,413,281
      chains); C: 2.118B nodes x (2+664+208,429 prefixes). (1944s)
    * xr3p 5->4 — stage0(sigma16(stage4(d))^n'), the c5_prexor
      primed-domain cross-round one op deeper than H-003's xr3:
      NO <=4-op program. A: 578.3B (495s); B: 1.773B nodes; C: 2.104B
      nodes. (1347s)
    * head4u 4->3 — sigma19(stage0(v^n)), the (v,n)->u head cut H-003
      never searched: NO <=3-op program. A full k<=3 410M; B 315K nodes;
      C 336M nodes. (14s)
    * xr4r / head3r / u2er — H-003's three 5->4 negatives re-asked with
      solved meets + the 72-const link space (engine B shapes only,
      engine C skipped for CPU budget): still NO <=4-op program
      (1.715B / 1.743B / 748M fwd nodes).
    * stretch a2d / b2e / c2out 7->6 — interior spans at depth
      current-1, engine A k<=3 (898-906M each) + engine B shapes:
      NO <=6-op program (749M / 759M / 759M fwd nodes).
  Totals: 2.364T engine-A candidates, 9.38B engine-B nodes, 6.68B
  engine-C nodes across 10 boundary questions.
  COVERAGE — the honest boundary of these negatives: at k = current-1
  the engines jointly cover every split [kf-op general prefix over the
  printed ~13-const pool] + [optional solved xor/madd meet] + [j-op
  invertible suffix chain over the printed link pool] EXCEPT kf=4
  (forward-4 enumeration, ~1000x engine A's k=4 cost, out of CPU
  reach). Also uncovered: suffix chains with >3 unary links, link
  constants outside the printed 72-value pools, and/or/shift meets with
  out-of-pool constants (only xor/madd meets are solvable), and
  interior pool constants beyond the printed forward pools. For the
  engine-B-only targets the k<=4 MITM claim is forward<=3 + meet? +
  j<=2 (their j=0 spaces were closed lean by H-003; a2d/b2e/c2out
  additionally have full k<=3 from engine A).
  Kernel port: NONE (port rule requires a strictly shorter sequence;
  none exists in the searched spaces). perf_takehome.py untouched;
  default verified: run_variant.py = {"cycles": 1070, "correct": true},
  submission_tests 9/9 green, cargo fmt/clippy/test clean (49 lib + 9
  fusion_search tests).
  VERDICT: H-016 closed negative, high confidence at the segment level.
  The one-op-removal route via adjacent-segment fusion is DEAD; see P-7
  (the kf=4 gap) and P-8 (global/non-compositional attack) for exactly
  what a reopen would require.

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
- P-7 [op-reduction, iter-4, expensive]: the single MITM gap at
  k = current-1 is the "forward-4 general prefix + 1 tail op" shape;
  closing it costs ~1000x engine A's k=4 runs (~10 CPU-days/target on
  this box) or a canonical-form/commutativity pruning of forward-4
  strong enough to cut 3 orders of magnitude. Only worth reopening with
  a much bigger machine or a real algebraic filter.
- P-8 [op-reduction, iter-4]: cut-based searches (H-003 + H-016) are
  now exhausted; the only tool class left for "11-op hash in 10" is
  GLOBAL/non-compositional: bit-blast the whole 11-op chain into SAT/SMT
  ("exists 10-op program equal on all 2^32 inputs" via CEGIS with the
  machine's op set), or algebraic normal-form reasoning that exploits
  cross-stage structure like KQ = KP<<9 in both f23 madds at once.
  High effort, unbounded payoff (-68/op); park unless the strain has an
  idle iteration.
- P-9 [op-reduction, iter-4, note for the driver]: H-016's negatives
  also close the reopen-if clause of G-10 ("H-016 finds a hit") — G-10
  can be marked fully closed; the graveyard reopen trigger shifts to
  P-8-class global attacks or a HASH_STAGES change.
