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
outside the hash (load-side, scheduling). H-025 (iter 6) CLOSED
INCONCLUSIVE: CEGIS/z3 global synthesis at k=10 timed out (solver never
reached SAT or UNSAT in a 20-minute budget) and, more importantly, the
same encoding also timed out trying to reconfirm the KNOWN-good k=11
form — i.e. the direct bit-blasted component-synthesis approach hits an
infeasibility wall around k=4 regardless of restriction, well below
k=10/11, so this is a genuine "tool doesn't scale here" result, not
evidence about whether a 10-op form exists. See iteration log for full
detail; P-8/the SAT-class global attack remains formally open, but this
specific tool (Z3 QF_BV component synthesis at 32-bit width) is now
known not to be the way to close it without a fundamentally different
encoding (much smaller bit-width abstraction + lifting, or a
syntax-guided/enumerative synthesizer instead of raw existential SMT).
Iter 6b (H-025 continuation) ran the SAME validated fusion_search.rs
machinery against the whole-hash end-to-end map with zero waypoint
assumption (new `full_hash` MITM target): also NEGATIVE at depth<=7
(kf<=2+j<=5), the same P-7 ceiling as every segment cut, now confirmed
global. k=10 for the whole hash is unresolved beyond this depth-7
boundary; see P-12 for the two concrete (expensive/unattempted) paths
that remain.

## Assigned
- H-003 (iter 1): DONE — see iteration log.
- H-015 (iter 2): DONE — implemented, strain frontier 1106; see log.
- H-004 (iter 3): CLOSED (subsumed by idx_race) -> G-15.
- H-016 (iter 4): DONE — closed negative; see iteration log.
- H-025 (iter 6): DONE — CEGIS/z3 k=10 synthesis attempt, closed
  inconclusive (solver infeasibility, not a proof either way); see
  iteration log.
- H-025 (iter 6b): PARTIAL — enumerative global-MITM sub-attempt (no
  waypoint assumption) CLOSED NEGATIVE at a stated coverage boundary
  (kf<=2 + suffix<=5, i.e. depth<=7 of the 10 needed). See log.
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

- 2026-07-25 iter 6 (H-025, time-boxed CEGIS/z3 attempt): built a
  component-based synthesis encoder (`cegis.py`, scratch-only, not
  committed to the repo — reproducible from this entry) targeting the
  global/non-compositional attack flagged by P-8: does a k-op program
  exist, for k=10, over the machine's real op vocabulary (multiply_add
  as src*K+C; add/sub/xor/and/or each either src OP imm-const OR src OP
  another pool value, selected by a free Bool; shl/shr as src<<S with S
  a bounded-<32 constant), with per-op operand-source selectors (Z3 Int,
  ranging over {input, all prior results}) and per-op constants (free
  32-bit BitVecs) all existentially quantified — solved via CEGIS
  (seed concrete IO pairs, solve, fast-verify candidate against fresh
  random inputs in plain Python, add any counterexample, repeat).
  VALIDATION of the tooling itself (before trusting any TIMEOUT/UNSAT
  read from it): ground-truth myhash + the current 11-op fused form
  cross-checked bit-exact on 200K random inputs (0 mismatches); the
  synthesis encoder's extract-and-verify round trip confirmed correct
  on two trivial synthetic targets (a 1-op x^C form found+verified at
  k=1, a 2-op madd-then-xor form found+verified at k=2) — the machinery
  itself is not the source of the negative results below.
  SCALING CALIBRATION (this is the key finding): UNSAT in <3s up to
  k=3 (0.02s/k=1, 0.3s/k=2, ~2s/k=3, all with 13-15 concrete examples).
  At k=4 the solver already stops resolving: TIMEOUT (result=unknown)
  at 30s, 90s, and 180s budgets, and this persisted even under HEAVY
  restriction (kind vocabulary cut from 8 ops down to just the 3 the
  current hash actually uses [MADD,XOR,SHR], operand-source selectors
  windowed to the most recent 1-2 pool entries instead of the full
  pool, down to as few as 1 seed example + 7 structured edge cases).
  None of these narrowings got k=4 to resolve within the tried budgets.
  Sanity-checked the OTHER direction too: asked the SAME general
  encoder to reconfirm the k=11 form that we KNOW is satisfiable (it's
  the current fused hash, which fits this exact vocabulary op-for-op) —
  TIMEOUT after 600s (2x300s rounds, 19 examples), and even restricting
  kind to just {MADD,XOR,SHR} (unrestricted sources) still TIMEOUT at
  60s. So the solver could not even re-find a solution it already had,
  within these budgets — this is not a "k=10 is unusually hard" signal,
  it's "this encoding+solver combination hits a wall around k=4,
  independent of whether the target is SAT or UNSAT."
  MAIN RUN: k=10, full general vocabulary (all 8 kinds, unrestricted
  operand-source selectors), 12 random + 7 structured seed examples (19
  total), CEGIS loop with 300s per-solve chunks, 1200s (20 min) total
  wall-clock cap as specified in the task brief. Result: 4 solver
  rounds, EVERY round returned Z3 `unknown` (internal solver timeout,
  not UNSAT), 0 candidates ever extracted (so 0 counterexample
  refinements — the loop never got past round 1's initial example set).
  STATUS: TIMEOUT, fully inconclusive — no SAT candidate found, no UNSAT
  proof obtained, at any point in the run.
  COVERAGE CHARACTERIZATION (per the task's honesty requirement): this
  run explored ZERO complete regions of the k=10 search space in any
  exhaustive sense. Z3's `unknown` on a bit-blasted QF_BV existential
  query does not mean "some region was ruled out" — internally it means
  the SAT solver's search (over an unspecified, solver-internal
  variable/clause exploration order) did not terminate in the allotted
  time; no fraction of the space can be honestly quoted as "covered."
  The only defensible statement is: this specific encoding, on this
  specific machine, with a 20-minute budget, did not decide k=10 either
  way, and the calibration runs above show that outcome was expected
  going in (the tool's practical ceiling is ~k=3, not proximity to
  k=10/11). No positive or negative claim about whether a 10-op form
  exists is licensed by this run.
  WHY it likely hits a wall here (diagnosis, not proven): multiply_add's
  src*K with BOTH operands effectively free (K is a fully symbolic
  32-bit BitVec) forces Z3 to bit-blast a genuine symbolic 32x32
  multiplier at every op regardless of whether that op's kind selector
  ends up choosing MADD (the ITE/mux structure builds the term
  unconditionally); combined with per-op source and kind selectors that
  are also free variables, the search space of *syntactically distinct
  but semantically irrelevant* assignments swamps the solver long
  before it can exploit any real algebraic structure. This matches the
  general literature experience that component-based/CEGIS synthesis
  over full 32-bit bit-vector datapaths with unrestricted multiply is
  hard even at small program lengths without either (a) a much smaller
  bit-width abstraction with counterexample-guided lifting to 32 bits,
  or (b) a syntax-guided/enumerative synthesizer with invertibility-
  condition pruning (the style Souper/other superoptimizers use) rather
  than raw existential bit-blasting.
  Kernel port: NONE (no candidate was ever produced). perf_takehome.py
  and dev.py untouched, per task instructions.
  VERDICT: H-025 closed INCONCLUSIVE (tool-infeasibility, not a
  disproof). The k=10 question is still formally open; what's now known
  is that plain CEGIS-over-Z3-QF_BV at 32-bit width is NOT a viable way
  to answer it without a materially different encoding strategy (see
  P-11). Recommend NOT re-running this exact approach without first
  either (a) validating a bit-width-reduced version (e.g. 8/12-bit
  hash-shaped toy function first) to confirm the encoding scales at all
  before spending wall-clock on 32-bit, or (b) switching tools entirely
  to an enumerative/invertibility-based superoptimizer.

- 2026-07-25 iter 6b (H-025 continuation, bounded research agent):
  H-025's statement is "the 11-op hash in 10" via a GLOBAL/non-compositional
  attack (P-8) — every prior tool (H-003/H-016) only ever cut the chain at
  named stage waypoints (b, c, d, e). This iteration took the (b) path from
  iter 6's recommendation: rather than re-architect a new symbolic solver,
  it used fusion_search.rs's ALREADY-invertibility-pruned MITM engines
  (solved xor/madd meets via odd-part affine canonicalization, xorshift
  chain inversion, no symbolic bit-blasting — i.e. these engines already
  ARE the enumerative/invertibility-based superoptimizer P-11 called for)
  and pointed them at a target NEVER previously tried: `full_hash`, the
  whole chain end-to-end (`a -> myhash(a)`) with NO waypoint assumption at
  all. Pool: the 12 hashseg constants + common (zero/one/m1) + 8 shifts;
  link-chain seed = 26 constants (stage consts + pairwise sums/products/
  shifts) building a 72-constant/1284-link pool (same methodology as every
  prior target).
  Ran to completion in 1678.3s (~28 min) on an 8-core box, within a
  30-45 min budget:
    - engine A (forward-exhaustive, full k<=4 over the 16-item pool):
      2,940,520,863,935 candidates, 1290.7s. NO <=4-op program computes
      the whole hash.
    - engine B (forward DFS depth<=3 x inverted 1-2-op suffix chains):
      1,033,714,835 forward nodes, 34.9s.
    - engine C (suffix-chain DFS to 5 ops, <=3 unary links / <=1 at depth
      5, x forward-prefix tables kf=0/1/2): 2,118,285,916 chain nodes,
      351.6s.
    - RESULT: NO program of <= 10 ops in the searched space. Current
      11-op form stands.
  COVERAGE (exact, honest boundary): the combined engines cover every
  program shape expressible as [kf-op forward prefix, kf in {0,1,2}] +
  [optional SOLVED xor/madd meet, free over all 2^32] + [j-op invertible
  suffix chain, j<=5, over the 72-const/1284-link pool, <=3 unary links /
  <=1 at j=5] OR [forward DFS depth<=3 over the full pool] + [suffix
  depth<=2] — i.e. a hard ceiling of depth <= 7 out of the 10 needed,
  identical in kind to H-016's "kf=4 gap" (P-7) but now confirmed to ALSO
  hold with zero segment/waypoint assumption baked in (this rules out an
  entirely different decomposition of the hash reusing none of the known
  stage cuts, not just deeper cuts at the known ones). NOT covered: kf=3/
  4/5 general forward prefixes (P-7's ~1000x-cost gap, unchanged), suffix
  chains with >3 unary links or link constants outside the printed
  72-value pool, and/or/shift meets with out-of-pool constants (only xor/
  madd meets are solved), and any candidate whose interior pool constants
  aren't in the printed forward pool. The k=10 question is NOT closed —
  this narrows the space it could hide in from "everywhere" to "requires
  an >=8-op-deep forward OR backward half," the same unresolved P-7/P-8
  gap, now doubly confirmed.
  Kernel port: NONE (no find). perf_takehome.py/dev.py untouched.
  IMPLEMENTATION NOTE: the new `full_hash` MTarget was implemented and
  verified (build clean, `cargo test --release --bin fusion_search` 9/9
  passing) against a copy of `fusion_search.rs` predating this session's
  repo-wide naming/typing refactor (the agent's worktree was checked out
  from an older commit) — the RESULT is a property of the hash function
  itself (unchanged by the refactor) and is trustworthy, but the specific
  Rust diff was NOT re-applied to the current (renamed) `fusion_search.rs`
  on `main`, since a manual field-name/constant translation risked
  introducing an unverified error. A future iteration should re-implement
  `full_hash` directly against current `main`'s `fusion_search.rs` (same
  design: one new `MTarget` calling `hs::fused_hash` as `a -> myhash(a)`,
  pool = stage constants + shifts, same seed-derivation pattern as the
  neighboring `a2d`/`b2e`/`c2out` targets) to get the result properly
  landed in-tree rather than only documented here.

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
  RE-CHECKED 2026-07-23 after H-029/idx_select + l4_gmin=(9,30) retune
  (load now 1900, down from 1961; valu 6122, floor 1021): reopen
  threshold still NOT met (1900 > ~1850), and redoing the same
  arithmetic with today's numbers confirms it's still a clear reject,
  not just "close": load_after = 1900+254 = 2154 -> floor 1077; valu_after
  = 6122-192 = 5930 -> floor 989. Load would become the binding
  constraint at 1077 — WORSE than the 1043 cycles already achieved
  today, let alone the 989 valu-only floor. The gap actually widened in
  relative terms (load's post-change floor now exceeds achieved cycles,
  not just the valu floor). Stays closed; would need load slots reduced
  by ~180 more (to ~1720) before this is worth even a partial re-cost,
  which is a much bigger ask than the reopen note implied — updating
  the threshold language for future reopen-checks.
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
- P-10 [op-reduction, unassigned, own derivation from a conversational
  design-review session (not yet a driver-run iteration) — NOT from an
  external source; contrast with flow-balance's P-14, which IS ported
  from a third-party repo]: 1-indexed tree addressing to kill
  the idx recurrence's redundant additive term. Diagnosis: the interior
  tournament recurrence `p := 2p+b` (perf_takehome.py's `madd(st,st,
  two_vec,par)`, ~line 1942) is already 1 op/round because it never
  carries a level bias. But the boundary-crossing AND steady-state
  GATHER recurrences (same function, ~lines 1950-1987) cost 2 ops/round
  beyond the parity extraction (a madd for `2x + bias` PLUS a separate
  vec add/sub for `+/-par`), because standard 0-indexed heap addressing
  (`child = 2x+1+b`) has two additive terms competing for multiply_add's
  single `+c` slot. Re-basing the tree to 1-indexed heap addressing
  (root=1, `child = 2x+b`, no constant bias at ANY level) would let the
  gather-mode recurrence collapse to the same 1-op `madd(st,st,two,par)`
  shape the tournament recurrence already gets, since there is no more
  bias term to fight the parity bit for the `+c` slot.
  - predicted: ~1,872-1,875 walker-rounds currently pay the extra op
    (every boundary-crossing + steady-gather round under mainline
    l4_gmin=(12,30), counted by tracing served(r,g)/served(r+1,g) across
    both tournament epochs — matches the measured 1,875 gathers almost
    exactly, as expected since both counts key off the same walker-round
    set). That's ~1,875 lane-ops removable (~20% of Idx's 9,144, ~2.7%
    of the kernel's 68,801 total) — ENCODING-INDEPENDENT (true whether
    the removed op currently rides valu 8-wide or alu scalar). Cycle
    impact is NOT encoding-independent, though: only the fraction
    currently valu-encoded lowers the binding floor. Idx's overall split
    (1,064 alu-slots vs 1,010 valu-slots, i.e. 1,064 vs 8,080 LANE-ops)
    suggests most Idx work defaults to valu (idx_race only diverts to
    alu when timing favors it), so a plausible range is -15..-30 cyc
    (best case ~-30 if the removed step is mostly valu-encoded, worst
    case near 0 if idx_race happens to already park most of it on alu).
  - cost: M. Requires re-deriving every compile-time offset constant
    keyed to the current 0-indexed layout: rec_vecs (boundary base
    offsets), the tournament tables' base addresses (evens/diffs/E_vecs/
    D_vecs), and the mem-priming addresses (l4_mem_primed/mem_prime).
    Mechanical but touches setup broadly.
  - depends: none structurally, BUT interacts with c5_prexor's
    complement-position bookkeeping (`negtwo_vec`, the elide(r,g)-gated
    sign flip on `par`, `omf_vec`/`omf1_vec`) — that scheme ALREADY
    injects a second term into this same update for its own reasons
    (tracking the bitwise complement of position on elided rounds).
    Whether 1-indexing cleanly collapses THAT combined algebra to one
    term, or just relocates the second term, is unverified — needs a
    by-hand re-derivation of the c5_prexor boundary/gather formulas
    under 1-indexed addressing before costing this for real, not just
    the plain (non-c5_prexor) case argued above.
  - status: RECONSIDERED 2026-07-23, LIKELY REJECTED ON PREMISE (not
    fully implemented/measured — this is a by-hand re-derivation, not a
    ground-truth test, so treat as strong-but-not-final). While
    implementing and shipping H-029/idx_select (which targets exactly
    this steady-gather update), it became clear the "1 extra op" this
    proposal blames on the 0-indexed heap's `+1` bias is not actually
    caused by that bias. The real formula is
    `madd(st,st,two,ov); vec(sgn,st,st,par)` where `ov` (`omf_vec` or
    `omf1_vec`, or `rec_vecs[key]` at the boundary) is a LEVEL-TRANSITION
    CONSTANT already folding in far more than a bare "+1" (base pointer,
    epoch offsets, the c5_prexor complement adjustment). Re-basing to
    1-indexed addressing changes what `ov` numerically equals, but
    `madd`'s `+c` slot is occupied by `ov` either way, and `par` (a
    genuine per-lane RUNTIME value, not a compile-time bias) still needs
    a separate combining step regardless of `ov`'s value — the 2-additive-
    terms problem this proposal set out to fix isn't actually about
    which indexing scheme is used, it's inherent to combining a
    compile-time constant and a runtime per-lane bit in one madd. H-029
    solves the SAME problem a different way (select between two
    already/cheaply-precomputed constants, when the two possible `ov+par`
    outcomes are each expressible as a fixed vector) — with NO indexing
    change needed. This suggests P-10's predicted -15..-30 cyc would
    NOT materialize even if fully implemented, because the op count
    doesn't actually drop; 1-indexing was solving the wrong culprit.
    Recommend closing this proposal without implementing it UNLESS
    someone finds a flaw in this re-derivation — the risk (re-deriving
    every tree-layout constant, uncertain c5_prexor interaction) is not
    worth spending against a benefit that no longer looks real.
- P-11 [op-reduction, iter-6, H-025 follow-up]: P-8's global synthesis
  attack is still open, but plain Z3 QF_BV component-based CEGIS at
  32-bit width is now known NOT to scale for it (H-025: solver hits
  `unknown` around k=4, can't even reconfirm a known-SAT k=11). A
  reopen should NOT just re-run more wall-clock on the same encoding —
  that's very unlikely to help given the k=4 wall and the failure to
  reconfirm k=11. Two concrete alternative directions if this strain
  gets picked up again: (a) bit-width-reduced synthesis — synthesize
  against an 8- or 12-bit truncated/toy analog of the hash first to
  validate an encoding scales at all, then use counterexample-guided
  lifting to 32 bits, rather than attempting 32-bit existential search
  cold; (b) an enumerative/invertibility-condition-based superoptimizer
  (Souper-style) instead of raw bit-blasted SMT — constrains multiply_add
  and shift's symbolic operands with cheap forward/backward propagation
  rather than letting Z3 discover the whole structure by search. Either
  is a materially different (and nontrivial, multi-hour-plus) effort;
  do not treat "add more solver timeout" as a fix.
- P-12 [op-reduction, iter-6b]: with H-016's per-cut kf<=2/j<=5 ceiling now
  confirmed to also hold GLOBALLY (no waypoint assumption, via the new
  `full_hash` MITM target — not yet ported to current `main`'s
  `fusion_search.rs`, see iter 6b's implementation note), the ONLY
  concrete remaining moves for "11 in 10" are: (a) extend engine C's
  forward-table builder to kf=3 (cost estimate from P-7: ~1000x the kf=2
  cost, i.e. likely >1 CPU-day per target on an 8-core box — not
  attempted, out of any single iteration's reasonable budget), or (b) fix
  CEGIS's scaling wall by making `multiply_add` NOT unconditionally
  bit-blast a symbolic 32x32 multiplier — e.g. encode op-kind as a hard
  case-split (one z3.Solver branch per kind, most of which are linear/
  cheap) rather than a single mux'd expression the solver must reason
  about uniformly regardless of which kind is selected; this is a real,
  actionable fix to try before another CEGIS run, not just "more
  timeout." Absent either, H-025/G-10 stay open only in the "unreachable
  at current tooling scale" sense — treat as effectively closed for
  practical purposes unless one of (a)/(b) is actually funded.
