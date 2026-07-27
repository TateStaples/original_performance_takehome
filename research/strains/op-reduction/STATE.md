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
Iter 7 (H-025 re-port + P-12 kf=3 scoping) landed `full_hash` for real on
current `main`'s renamed `fusion_search.rs` (iter 6b's copy was never
applied) and RE-CONFIRMED the depth<=7 negative directly on this
codebase (9/9 tests green; 2,868B engine-A candidates, 1284-link/72-const
suffix pool byte-identical in derivation to iter 6b's). It also actually
attempted P-12's kf=3 extension (not just estimated it): implemented kf=3
in `build_fwd_tab` behind a diagnostic-only `--kf-scale` probe and
measured real wall-clock/memory cost at increasing pool sizes. VERDICT:
kf=3 is memory-bound, not CPU-bound, at any pool rich enough to matter --
entries hit 85.6M (284s) at a 16-const toy pool and the growth exponent
was still ACCELERATING (~5.2 -> ~10) as pool size approached the 23-const
pool every real target needs; the real-pool kf=3 attempt was killed after
~10 min with RSS still climbing past 8GB unbounded (freed ~16GB on kill).
No pool size is both tractable in hours and rich enough to represent the
actual hash-stage constants. See P-12 for the updated verdict and the
iteration log entry below for full numbers.

Iters 8-9 (H-025, two independent CEGIS case-split fix attempts) each
found and fixed a real limitation of the prior encoding (iter 8: fixing
op-KIND per position, not just is-madd; iter 9: structured seed samples +
selector domain-tightening/symmetry-breaking), and each still hit a wall
-- but a DIFFERENT, more precise one each time (iter 8: CEGIS refinement
stalls at ~5 concrete samples; iter 9: even with connectivity fully
pinned, the wall is the nonlinear chained-multiply-constant solving
itself, one to two samples later). Three independent iterations (6, 8, 9)
now agree CEGIS/Z3 QF_BV component synthesis at 32-bit width is the wrong
tool class for this problem in essentially any encoding tried so far --
a reopen needs a solver/engine swap (CVC5, or a dedicated synthesis
engine like Rosette/Sketch) or a materially narrower template (fixed
per-stage constants for at least some positions), not more tuning of the
same approach.
Iter 10 (targeted re-scoping of iter 7's kf=3 verdict) found iter 7's
closing language OVERGENERALIZED: iter 7 only ever tested kf=3 against
prefixes of `full_hash`'s own 23-item pool, never against any actual
individual segment target's real (smaller) pool. Precisely counted every
`mitm_targets()` pool: the still-open boundary targets are `b2d`/`xr5`/
`xr3p` at 13 items each and `a2d`/`b2e`/`c2out` at 15. Built a real kf=3
forward-table probe against each target's actual pool: CHEAP everywhere
(17-120s, 3.5-11.2GB peak, on the same box) -- NOT a memory wall at all.
Ran the full kf<=3-extended search to completion for b2d (760.9s), xr5
(921.7s), and xr3p (592.2s): all three STILL show no shorter program, now
confirmed at a genuinely deeper coverage boundary than before. The memory
wall iter 7 found is real but applies ONLY to the full 23-item
`full_hash` pool -- not to any individual segment target. See the iter 10
log entry and updated P-12 for full detail.
Iter 11 closed both of iter 10's flagged next steps. (1) `a2d`/`b2e`/
`c2out`'s chain-DFS cost (never timed before, since their
`enable_engine_c=false` was an untested iter-4 CPU-budget guess) turned
out CHEAPER than b2d/xr5/xr3p's (377-481s vs 592-922s, via a new opt-in
`--force-engine-c` flag that leaves default behavior untouched) -- ran
to completion at kf<=2 and kf<=3 for all three: ALL STILL NEGATIVE, no
<=6-op form for any of the three 7-op interior spans. Every real
individual segment target (all six: b2d/xr5/xr3p/a2d/b2e/c2out) is now
closed negative at kf<=3. (2) kf=4 at the segment scale (probed on
`b2d`, the cheapest kf=3 build) did NOT complete within a 47.5-minute
wall-clock budget -- a genuine CPU-time wall (confirmed NOT a memory
wall: RSS stayed in a stable 3.9-5.9GB band throughout) -- CLOSED
INFEASIBLE at current tooling/budget; kf=4 was never wired into a real
search. See iter 11 log entry for full detail.

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
- H-025 (iter 7): DONE — `full_hash` re-ported and re-verified for real on
  current main (depth<=7 negative reconfirmed); P-12's kf=3 extension
  actually attempted and CLOSED as memory-infeasible at any pool rich
  enough to be meaningful. See log.
- H-025 (iter 8): DONE — CEGIS case-split fix attempt (fixed op-kind
  sequence, not just is-madd); measurably helped early-round solving but
  CEGIS refinement itself walled at ~5 concrete samples regardless of k.
  See log.
- H-025 (iter 9): DONE — rebuilt CEGIS with structured seeds + selector
  domain-tightening/symmetry-breaking; CLOSED NEGATIVE at calibration
  (wall unmoved; deeper diagnosis reframes the bottleneck as nonlinear
  multiply-constant solving, not connectivity search). Stopped before
  the full k=10 sweep per its own go/no-go rule. See log.
- H-025 (iter 10): DONE — corrected iter 7's overgeneralized kf=3 verdict.
  kf=3 is tractable (not a memory wall) at every real individual segment
  target's own pool (9-15 items); the memory wall is specific to the
  full 23-item `full_hash` pool. Ran the real kf<=3-extended search to
  completion for b2d/xr5/xr3p (the smallest still-open boundary targets):
  all three STILL closed negative at this deeper boundary. See log.
- H-025 (iter 11): DONE — enabled + timed engine C for a2d/b2e/c2out for
  the first time (opt-in `--force-engine-c` flag, default unchanged);
  all three closed negative at kf<=3, cheaper than b2d/xr5/xr3p's runs.
  Probed kf=4 at the segment scale (b2d, cheapest case): CLOSED
  INFEASIBLE -- a genuine CPU-time wall (not memory), didn't finish in
  47.5 min. See log.
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

- 2026-07-25 iter 7 (H-025 re-port + P-12 kf=3 scoping, bounded research
  agent, worktree fast-forwarded to main@92be85c first since it started
  stale at 5da6061 -- same trap iter 6b's agent hit): two parts.

  PART 1 (re-port `full_hash` for real): added the `full_hash` MTarget to
  current main's `fusion_search.rs` (`mitm_targets()`, next to
  `a2d`/`b2e`/`c2out`) using the CURRENT renamed identifiers throughout
  (`hs::fused_hash`, `STAGE0_ADD_CONSTANT`/`STAGE0_MULTIPLIER`/
  `STAGE1_XOR_CONSTANT`/`F23_P_MULTIPLIER`/`F23_P_CONSTANT`/
  `F23_Q_MULTIPLIER`/`F23_Q_CONSTANT`/`STAGE4_ADD_CONSTANT`/
  `STAGE5_XOR_CONSTANT`, the file's existing `c1_xorshift19`/
  `c5_xorshift16`/etc. helper locals). Pool/seed/shifts reconstructed to
  match iter 6b's documented shape exactly: 12 hashseg consts (10 raw +
  C1i/C5i) + common(3) + 8 shifts = 23-item forward pool;
  engine_a_pool_override = common(3) + same 12 hashseg consts + 1 shift =
  16 items; seed = 26 constants (9 raw stage consts + 17 already-defined
  cross-stage helper locals reused verbatim from the neighboring
  targets) -> capped at the file's fixed 72-constant/1284-link pool
  (LINK_CONSTANT_POOL_CAP), same for every target. `stretch: true` (kept
  out of the default `--mitm` sweep, matching a2d/b2e/c2out).
  Build clean; `cargo test --release --bin fusion_search`: 9/9 passing
  (unchanged count -- no test added, matching iter 6b's choice).
  RAN FOR REAL: `fusion_search --mitm full_hash`, 2220.2s (~37 min) total
  on the same 8-core box:
    - engine A (k<=4, 16-item pool): 2,868,020,060,885 candidates,
      1568.9s. Same order of magnitude as iter 6b's 2,940,520,863,935/
      1290.7s (slower here mostly because a second background job, the
      kf-scale probe below, was sharing the box's 8 cores for part of
      this run).
    - link pool: 72 constants, 16 odd Ks, 1284 links -- from the
      26-constant seed, EXACTLY matching iter 6b's printed pool size.
    - engine B (fwd DFS depth<=3 x suffix<=2 tables): 6,935,605,852
      forward nodes, 245.0s -- LARGER than iter 6b's 1,033,714,835/34.9s.
      Root cause (an honest deviation, not a bug): engine B always
      searches the target's `pool` field, and this port's `pool` is the
      full 23-item forward pool (per the "12 hashseg + common + 8
      shifts" spec quoted in iter 6b's own writeup) rather than whatever
      leaner pool iter 6b's pre-refactor copy actually used for engine B
      specifically -- iter 6b's own text does not pin down a separate
      leaner engine-B pool, so this port used the one it documented.
      Coverage-wise this is a SUPERSET (more forward nodes checked, not
      fewer), so it does not weaken the negative result.
    - engine C (suffix chain DFS<=5 x kf=0/1/2 prefix tables: 1, 829,
      611,535 prefixes): 2,118,285,916 chain nodes, 405.0s -- chain-node
      count is IDENTICAL to iter 6b's reported 2,118,285,916 (this side
      of the search depends only on the link pool, which matched
      exactly, cross-validating the reconstruction).
    - RESULT: NO program of <= 10 ops found. Current 11-op form stands.
  COVERAGE: same depth<=7-of-10 boundary as iter 6b (kf<=2 forward +
  suffix<=5, or forward-DFS-3 + suffix<=2), now landed and verified
  in-tree on current main rather than only documented. Kernel port: NONE.
  perf_takehome.py/dev.py untouched.

  PART 2 (P-12 kf=3 feasibility scoping -- actually investigated, not
  just estimated): P-12 estimated kf=3 at ~1000x kf=2's cost, "likely >1
  CPU-day per target." Rather than trust that cold, implemented genuine
  kf=3 support in `build_fwd_tab` (same chaining rule as the existing
  kf<=2 code: op2 must use temp1, op3 must use temp2) gated behind a new
  diagnostic-only `--kf-scale` CLI probe -- NOT wired into engine C or
  any verified target, zero risk to the Part-1 result. Measured real
  wall-clock and memory on the same 8-core/24GB box, at increasing
  prefixes of `full_hash`'s own 23-item pool:
    pool=4:  kf3=55,929 entries,      0.102s
    pool=6:  kf3=437,189 entries,     0.996s
    pool=8:  kf3=1,977,727 entries,   4.758s
    pool=10: kf3=6,341,693 entries,   13.889s
    pool=12: kf3=17,491,440 entries,  33.102s
    pool=14: kf3=40,610,167 entries,  81.231s
    pool=16: kf3=85,638,360 entries,  284.266s
    pool=23 (the real forward pool): kf<=2 confirmed IDENTICAL to the
      real run (611,535 kf=2 entries, 0.531s -- cross-validates both
      runs), but kf=3 was KILLED after ~10 minutes with RSS still
      climbing past 8GB unbounded (killing it freed ~16GB system-wide,
      confirming it was mid-blowup, not near done) -- to protect the box
      and the concurrently-running Part-1 verification.
  Fitted growth exponent (log-log slope of consecutive points): ~6.8 at
  pool 4->6, decaying to ~5.2-5.3 through pool 8->12, then RE-ACCELERATING
  to ~6.3 (12->14) and ~10.0 (14->16) -- i.e. not a fixed polynomial
  degree; cost gets WORSE per additional pool item as pool grows, so
  extrapolating from small pools understates the true cost at pool=23.
  Both time and memory are driven by the same quantity (table entry
  count), so the memory wall and the time wall are the same wall.
  VERDICT: kf=3 is NOT tractable in a 2-6 hour window at any pool rich
  enough to be a meaningful test of the real hash. A pool small enough to
  finish in minutes (<=12 items, 33s) is too impoverished to contain the
  actual multi-stage hash constants needed for genuine coverage of ANY
  span -- even the smallest existing sub-span targets (b2d, 6 ops) already
  need a ~13-item pool to be non-trivial, and the full hash needs all 23.
  There is no pool size simultaneously tractable-in-hours AND
  representative of the real function; the constraint that would need to
  relax is the table's per-entry memory footprint / dedup strategy
  (e.g. external-memory or streaming dedup, or an algebraic
  canonicalization proven to cut table size by 2-3+ orders of magnitude),
  not more wall-clock. Recommend NOT attempting kf=3 again without such a
  representation change; "just let it run longer" will hit the same
  memory wall this iteration hit in ~10 minutes, not resolve it.
  Kernel port: NONE. perf_takehome.py/dev.py untouched.

- 2026-07-25 iter 8 (H-025, CEGIS case-split fix attempt, bounded research
  agent, user-authorized "push and don't stop"): built `scratchpad/cegis.py`
  (z3), a fresh CEGIS/SMT synthesis tool for "the 11-op hash in <=10 ops."
  MODEL: straight-line DAG y_0=x, y_1..y_k, each position's operand
  source(s) selected from the last `window=3` produced values (free Z3 Int
  selectors -- the real hash never reaches back >2 steps, so window=3 is
  lossless), with the op KIND fixed per position in Python (the case
  split, not a Z3 selector): madd (K,C free BitVec32) or one of xor/add/
  and/or/shl/shr (1 free const) or xor2/add2 (2 chain sources, no const).
  CEGIS loop: seed IO pairs, solve, bulk-verify candidate on up to 1M
  random inputs via a numpy myhash_np (cross-checked against myhash at
  import), add first mismatch as a new sample, repeat.
  CALIBRATION FOUND THE ORIGINAL DIAGNOSIS WAS INCOMPLETE: three configs
  tried at k=11 on the known-good fused-hash kind sequence:
  1. OLD encoding (kind fully free, incl. madd, so an unconditional
     free-times-free multiply term exists everywhere): `unknown` at 60s,
     zero progress -- reproduces iter 6's diagnosed failure.
  2. THE ORIGINALLY-DIAGNOSED FIX (case-split ONLY is-madd-or-not; the
     other 8 kinds still a free Z3 selector at non-madd positions):
     STILL `unknown` at 30s -- NOT sufficient, a genuine negative
     surprise. Isolating why: fixing madd's source-selector too (kind
     still free elsewhere) ALSO times out; fixing every selector+kind via
     equality (no search left) solves in 0.15-0.76s. The real cost was
     never specifically "free multiply" -- it's generic component-
     CONNECTIVITY search (which Int selector feeds which op) compounding
     with ANY downstream nonlinearity: leaving 5+ non-madd positions'
     kind simultaneously free reproduces the same wall with ZERO madds
     involved (n_free=4 solves in 7.6s, n_free=5 times out at 15s).
  3. THE ACTUAL FIX: full kind SEQUENCE case-split (every position's
     exact op fixed in Python, only selectors+constants free): SAT in
     0.2-1.9s at 3 samples, ~21-115s at 4 samples, but consistently
     `unknown` (180s timeout) once refinement reaches 5 samples -- a
     large real improvement over configs 1/2 (which never produce a
     single candidate), but does not fully close even the k=11
     reconfirmation end-to-end.
  K=10 SEARCH: full 9^10 kind-sequence enumeration (~3.5e9) is infeasible
  even with fast per-query solving; used the task-authorized near-
  structure fallback (the 11 single-position deletions of the known
  11-op template). 7 of 11 deletion baselines examined (budget-limited;
  the other 4 plus the full 880-variant Hamming-1 neighborhood were not
  reached). EVERY branch hit the identical wall: round 0 (3 samples) and
  usually round 1 (4 samples) produce a concrete SAT candidate fast, every
  such candidate is refuted by the bulk numpy check within ~1-8M random
  inputs (degenerate small-support fits, not real matches), and round 2
  (5 samples) times out at up to 180s. Zero UNSAT, zero verified SAT.
  Per-branch data: scratchpad/cegis_k10_deletions.json (7 branches, all
  `unknown`, 71-118s each), scratchpad/cegis_k10_main.json (an earlier
  20s-round-timeout pass, also all `unknown`).
  NEW SCALING LIMIT (the actual finding): the originally-diagnosed bug
  (free kind selector => unconditional free multiply) is real and the
  deeper fix (full kind-sequence case-split) measurably helps early-round
  solving, but CEGIS refinement itself hits an INDEPENDENT wall at ~5
  simultaneous concrete-sample constraints, REGARDLESS of k (identical
  for the intact known-correct k=11 structure and every k=10 deletion
  variant) -- Z3's default QF_BV bit-blasting tactic cannot decide a
  5-copy instance of this program template within 60-180s, because the
  operand-selector space is large enough that 3-4 concrete IO constraints
  are essentially never sufficient to pin down the true 32-bit function.
  Kernel port: NONE. No candidate reached the >=50M-input verification
  gate (nothing survived even the ~1-8M quick check), so there is no find
  to report.
  WHAT A REOPEN NEEDS (none attempted this iteration): (a) structured
  (non-random) seed samples chosen to break selector symmetries early;
  (b) explicit symmetry-breaking constraints on the selector Int
  variables (many distinct assignments are semantically identical, and
  Z3 currently pays to distinguish them); (c) a solver/tactic swap (CVC5,
  or a dedicated synthesis engine like Rosette/Sketch, instead of Z3's
  general QF_BV default); (d) a much narrower structural template (fewer
  free selectors total). H-025 stays open with this precise, corrected
  boundary recorded (the multiply-bit-blast theory from iter 6 was only
  PART of the story; connectivity search and CEGIS's own refinement-round
  scaling are the deeper, now-identified bottleneck).

- 2026-07-25 iter 9 (H-025, CEGIS fix-attempt #2, bounded research agent,
  user-authorized "push and don't stop"): rebuilt `scratchpad/cegis.py`
  from scratch (iter 8's file did not survive into this worktree) with the
  SAME validated core (full kind-sequence case-split; window=3 operand
  selectors) PLUS both iter-8-diagnosed fixes built in from construction
  time, not bolted on: (1) structured seed samples -- 0, 0xFFFFFFFF,
  powers of two at low/mid/high bit positions, all-ones-with-one-bit-
  cleared, ~10 samples from the first solve instead of climbing from 3;
  (2) per-position domain tightening (each selector's Z3 range is the
  position's actual [i-window, i-1] window, collapsing to a fixed Python
  int with NO Z3 variable at all when only one source is valid) +
  symmetry-breaking (selA <= selB on commutative xor2/add2). Encoding
  correctness self-tested: the K=11 known-good template + its ground-truth
  concrete assignment reproduces `myhash` bit-exact over 500K random
  inputs before any Z3 was invoked.
  CALIBRATION RESULT: NEGATIVE -- neither fix moved the wall. Structured
  seeds direct at n=10 hit `unknown` at 90s (worse than climbing). Testing
  the SAME fixed model (domain-tightening + symmetry-breaking always on)
  at increasing sample counts with BOTH structured and random seeds
  reproduces the IDENTICAL wall iter 8 found: SAT at n=3 (1.3-8.1s), SAT
  at n=4 (11-33s), `unknown` at n=5 regardless of seed choice, timeout
  budget (tried up to 240s), solver tactic (explicit
  simplify->propagate-values->solve-eqs->bit-blast->sat gave the same
  `unknown` at 240s), or selector representation (re-ran with small
  BitVec(4) selectors instead of Int, to rule out Int/BV theory-
  combination overhead as the cause -- identical n=5 wall).
  DEEPER DIAGNOSIS (the actual new finding this iteration): pinned EVERY
  selector to its known-good ground-truth value (zero connectivity search
  left, only the multiply_add K/C pairs and xor/shift constants free) and
  the wall was still there, just pushed from n=5 to n=8 (SAT at n=3 in
  0.12s, SAT at n=5 in 18.3s, `unknown` at n=8, 60s cap). This CONTRADICTS
  iter 8's diagnosis that the bottleneck is primarily selector/
  connectivity search: even with connectivity fully solved, the wall
  reappears one to two samples later, from the chained-modular-multiply
  constant-solving alone (4 free (K,C) multiply_add pairs in series,
  32-bit width, each new IO sample adds another simultaneous system-of-
  congruences constraint over all four). The connectivity search
  compounds an already-hard nonlinear-BV constant-solving problem; it is
  not the primary cause on its own.
  K=10 SPOT CHECK (2 of 11 single-position-deletion variants only, NOT
  the full sweep -- see go/no-go note below): both hit `unknown` at 60s
  with all 10 structured seeds asserted at once (results in
  `scratchpad/cegis_k10_iter9.jsonl`). Consistent with the calibration
  wall; no SAT candidate, no UNSAT, nothing to bulk-verify.
  GO/NO-GO CALL: per this iteration's own mandate ("if the fixes don't
  measurably help the calibration case, don't spend the full time budget
  on k=10"), STOPPED HERE rather than running the full 60-90 minute
  11/880-variant sweep -- neither prescribed fix, nor the two additional
  levers tried (BitVec selectors, explicit bit-blast tactic), produced
  any measurable improvement on the calibration wall, so repeating the
  full sweep would almost certainly just reproduce iter 8's all-`unknown`
  result at higher wall-clock cost with nothing new to show for it.
  Kernel port: NONE. No candidate reached bulk verification, let alone the
  >=50M-input gate.
  UPDATED CONCLUSION FOR A FUTURE REOPEN: this iteration's pinned-selector
  experiment reframes iter 8's (a)/(b) reopen items (structured seeds,
  symmetry-breaking) as NOT the load-bearing fix -- both are now tried and
  both are negative. The wall is the nonlinear nature of solving several
  simultaneous free-multiply-constant nonlinear-BV congruences
  under Z3's default (and its explicit bit-blast) tactics, not the
  selector search. That reframes iter 8's remaining items (c) and (d) as
  the only ones not yet falsified: (c) a solver/tactic swap (CVC5 in
  particular, since its nonlinear-BV/`bvmul`-heavy heuristics differ
  materially from Z3's, or a dedicated program synthesis engine like
  Rosette/Sketch/Souper-for-BV rather than raw existential SMT) and (d) a
  much narrower structural template that removes free multiply constants
  entirely for at least SOME positions (e.g. only synthesize which stage
  BOUNDARIES fuse, treating each stage's OWN constants as fixed/known --
  a partial-restart between full-freedom synthesis and the
  already-exhausted MITM/adjacent-cut searches). Absent one of those, more
  wall-clock on this exact encoding is not expected to help -- this is the
  third independent iteration (6, 8, 9) landing on that same conclusion by
  three different specific mechanisms (raw scaling wall; connectivity-
  search cost; now nonlinear-multiply-constant cost), which is fairly
  strong evidence CEGIS/Z3 QF_BV component synthesis at 32-bit width,
  in essentially any encoding variant tried so far, is the wrong tool
  class for this problem -- (c)/(d) above are real alternatives, not more
  tuning of the same approach.

- 2026-07-25 iter 10 (H-025/P-12 targeted re-scoping, bounded research
  agent, user-authorized "push and don't stop"): re-examined whether iter
  7's kf=3 "memory wall" verdict, reached ONLY against synthetic prefixes
  of `full_hash`'s 23-item pool, actually holds for the much smaller pools
  every REAL individual segment target uses.

  STEP 1 (precise pool census, counted directly from `mitm_targets()`'s
  `pool: mk(&[...])` lists): `head4u`=9 items -- the smallest of all, but
  already fully closed by engine A's exhaustive k<=3 search, so any deeper
  kf question there is moot. The smallest STILL-OPEN boundary targets:
  `b2d`/`xr5`/`xr3p` at 13 items each; next, `a2d`/`b2e`/`c2out` at 15;
  `full_hash` at 23 (the one iter 7 actually tested).

  STEP 2 (real-pool kf=3 table-construction probe): added
  `run_kf_scale_target_probe` (`--kf-scale-target <name>`, diagnostic-only)
  that builds `build_fwd_tab` at kf=0..=3 using the NAMED target's actual
  pool verbatim, with in-process RSS sampling for early-warning safety
  (same discipline as iter 7). Ran on every still-open target with
  pool<=15:
    * head4u (pool=9): kf=3 = 11,053,166 entries, 17.4s, peak RSS 3.53GB.
    * b2d (pool=13): kf=3 = 25,108,399 entries, 31.6s, peak RSS 8.07GB.
    * xr3p (pool=13, 2-input): kf=3 = 60,807,194 entries, 96.2s, peak
      RSS 10.10GB.
    * xr5 (pool=13, 2-input): kf=3 = 72,747,570 entries, 119.5s, peak
      RSS 11.23GB.
    * a2d (pool=15): kf=3 = 60,055,880 entries, 74.5s, peak RSS 8.85GB.
    * b2e (pool=15): kf=3 = 40,037,130 entries, 57.4s, peak RSS 10.43GB.
    * c2out (pool=15): kf=3 = 40,201,721 entries, 57.4s, peak RSS 10.42GB.
  Every one completed comfortably inside a 2-minute window at peak RSS
  well under half the box's 24GB -- NO memory-wall behavior anywhere in
  this range, in sharp contrast to iter 7's real 23-item pool (killed
  after ~10 min, RSS still climbing past 8GB unbounded). Iter 7's
  accelerating-growth-exponent curve is real but was measured on generic
  prefixes of a MUCH bigger pool (14-23 items) -- it does not license "kf=3
  is infeasible at any pool rich enough to matter" as a blanket statement.

  STEP 3 (wire kf=3 into the REAL, verified search, not just the table):
  added an opt-in `--kf3` CLI flag raising engine C's `fwd_tabs` range
  from the verified default `0..=2` to `0..=3` (default behavior with no
  flag confirmed byte-identical: re-running `--mitm head4u` with no flags
  reproduces iter 4's exact original candidate/node counts). This is
  nearly free to add: `EngineC::probe` already loops over `self.fwd`
  tables per already-visited suffix-DFS node, so an extra kf=3 table adds
  one more cheap lookup per node, not more DFS nodes -- confirmed
  empirically (b2d's and xr3p's `--kf3` engine-C chain-node counts came
  back byte-identical to their original kf<=2 runs).

  RAN THE FULL kf<=3-EXTENDED SEARCH TO COMPLETION (blocking, one target
  at a time to avoid memory cross-contamination) for the three targets
  where it adds genuinely new coverage:
    * b2d: engine A k<=4 (757,804,807,331 candidates, 345.4s, matching
      iter 4's order of magnitude) + engine B (359,719,607 nodes, 9.3s)
      + engine C kf<=3 (2,118,285,916 chain nodes -- identical to the
      original kf<=2 count, confirming zero new DFS nodes -- 374.4s).
      Total 760.9s (~12.7 min). **RESULT: still NO <=5-op program.**
    * xr5: engine A k<=4 (1,024,323,677,115 candidates, 359.2s) + engine
      B (1,802,855,447 nodes, 29.7s) + engine C kf<=3 (2,118,285,916
      nodes, 350.7s). Total 921.7s (~15.4 min). **RESULT: still NO
      <=5-op program.**
    * xr3p: engine A k<=4 (578,337,366,272 candidates, 198.5s) + engine
      B (1,772,521,818 nodes, 17.5s) + engine C kf<=3 (2,104,193,812
      nodes, 289.0s). Total 592.2s (~9.9 min). **RESULT: still NO <=4-op
      program.**
  `head4u` was NOT re-run under `--kf3` (kf=3 is logically inert for it --
  the wanted op-budget bitmask never reaches that depth, so re-running
  would only reconfirm iter 4's already-exhaustive k<=3 negative at zero
  new information). `a2d`/`b2e`/`c2out` were NOT extended: their
  `MTarget.enable_engine_c` is `false` (an iter-4 CPU-budget decision
  predating this measurement), so `--kf3` has no code path to affect them.
  Given step 2 shows their pool=15 kf=3 tables are just as cheap as
  b2d/xr5/xr3p's, the original CPU-budget rationale for skipping engine C
  on these three is worth re-examining, but flipping `enable_engine_c` on
  and running their (untested, materially bigger) full chain-DFS is a
  new, not-yet-taken step -- recorded as a proposal, not executed this
  iteration (see updated P-12).

  VERDICT: iter 7's kf=3 "memory wall" finding was CORRECT for what it
  actually tested (the full 23-item `full_hash` pool) but its closing
  language overgeneralized to every segment target, which this iteration
  disproves directly: b2d, xr5, and xr3p (13-item real pools) all
  completed their FULL kf<=3-extended verified search in under 16 minutes
  each, with no memory-wall behavior. This is a genuine new closing
  result at a real depth boundary (kf<=3, one step past iter 4's kf<=2)
  for the three smallest still-open segment targets -- all three remain
  negative. No <=(current_ops-1)-op program was found for any of them, so
  there is nothing to port.
  Kernel port: NONE. `perf_takehome.py`/`dev.py` untouched throughout
  (only `fusion_search.rs` was modified: the new `--kf-scale-target`
  probe, the opt-in `--kf3` flag, and `run_mitm_target`'s parameterized
  `max_kf`). Build clean; `cargo test --release --bin fusion_search`:
  9/9 passing, unchanged. Default (`--mitm` with no `--kf3`) behavior
  verified byte-identical to before.
- 2026-07-26 iter 11 (H-025, bounded research agent, worktree
  fast-forwarded from stale 5da6061 to main@994e41b via `git merge main`
  first): took iter 10's two flagged next steps.
  STEP 1: enabled engine C for `a2d`/`b2e`/`c2out` and TIMED their
  chain-DFS for the first time ever. Rather than permanently flipping
  each target's `MTarget.enable_engine_c` (an iter-4 CPU-budget guess
  that predated any real timing), added an opt-in `--force-engine-c` CLI
  flag: forces engine C on for a named target even when its own struct
  says `enable_engine_c=false`, with zero effect on any target that
  already has it `true` and zero effect when the flag is absent (default
  `--mitm` reconfirmed byte-identical: `head4u` re-run with no flags
  reproduced iter 4's exact candidate/node counts: 410,492,695
  op_count=3 candidates, 336,272,337 chain nodes, 6.4s). Ran all three
  targets to completion, one at a time, at the verified default kf<=2
  first (parity check), then again at kf<=3 (`--force-engine-c --kf3`):
    * a2d: kf<=2 total 376.7s (engine A op3 897,443,941 cands 0.4s;
      engine B 748,712,546 fwd nodes 25.9s; engine C 2,118,285,916 chain
      nodes 349.9s; peak RSS 375MB). kf<=3: fwd tabs kf=0..3 =
      1/405/149,601/60,055,880 entries; chain nodes IDENTICAL
      (2,118,285,916, confirming zero new DFS nodes, same as iter 10's
      b2d/xr3p cross-check); total 480.5s; peak RSS 12.06GB.
    * b2e: kf<=2 total 386.8s (engine A 905,632,153 cands 0.7s; engine B
      759,217,852 nodes 26.2s; engine C 2,118,285,916 nodes 359.4s; peak
      RSS 361MB). kf<=3: kf=3 table 40,037,130 entries; chain nodes
      identical; total 454.6s; peak RSS 12.64GB.
    * c2out: kf<=2 total 386.8s (engine A 905,629,134 cands 0.5s; engine
      B 759,200,698 nodes 26.9s; engine C 2,118,285,916 nodes 359.0s;
      peak RSS 361MB). kf<=3: kf=3 table 40,201,721 entries; chain nodes
      identical; total 452.9s; peak RSS 13.04GB.
  **ALL THREE STILL NEGATIVE at kf<=3**: no <=6-op program found for any
  of the three 7-op interior spans, at the deepest boundary now tested
  for them. Surprising sub-finding: despite being nominally "one op
  longer" targets than b2d/xr5/xr3p, their FULL runs (377-481s) were
  actually CHEAPER than b2d/xr5/xr3p's (592-922s, iter 10) -- because
  `max_chain_ops = 5.min(kmax_use)` caps engine C's chain-DFS depth at 5
  regardless (kmax_use=6 for these three still hits the same cap as
  kmax_use=5), while these three's `engine_a_kmax=3` (vs 4 for b2d) makes
  their engine A phase cheaper. The original iter-4 CPU-budget rationale
  for `enable_engine_c=false` on these three is now empirically retired:
  their chain-DFS was cheap all along, just never measured.
  STEP 2: kf=4 at the segment scale. Added a kf=4 arm to `build_fwd_tab`
  (one more nesting level than kf=3, same "every temp consumed by the
  very next op" chaining rule) and extended `run_kf_scale_target_probe`'s
  loop from `0..=3` to `0..=4` (with a 45-minute-per-kf self-limit check
  -- a known-incomplete safeguard since it can only fire AFTER a given
  kf's `build_fwd_tab` call returns, not during one very slow build).
  Picked `b2d`: the fastest kf=3 build of all six real segment targets
  per iter 10 (31.6s, 25,108,399 entries at its 13-item pool). Ran
  `--kf-scale-target b2d` to completion (blocking foreground, real
  `timeout` budget). **RESULT: kf=4 did NOT complete.** The process was
  killed by its own outer 2850s (47.5 min) timeout, still mid-build, with
  no output for kf=4 itself. Crucially this is a CPU-time wall, NOT a
  memory wall: an in-process RSS sampler (every 5s) showed memory
  oscillating in a stable 3.9-5.9GB band for the entire run, never
  approaching the box's 24GB limit and never showing the unbounded climb
  iter 7 saw for `full_hash`'s kf=3 memory wall. Since kf=3 took 31.6s at
  this exact same pool, kf=4 costs AT LEAST ~90x kf=3 (2850s and still
  not done) -- a much steeper per-kf-step cost jump than kf=2->kf=3 was
  at this pool size. Given table construction alone didn't finish in
  47.5 minutes for the cheapest of the six segment targets, wiring kf=4
  into a real, verified engine C search was NOT attempted (would cost
  many more hours per target with no evidence it would ever land, and no
  reason to expect a materially cheaper pool elsewhere -- b2d was already
  the best case). CLOSED INFEASIBLE (time-bound) at the tooling/budget
  available this iteration; a reopen needs either a fundamentally
  different forward-table representation (as iter 7 already concluded
  for the memory-wall case) or a much larger wall-clock allowance
  (multi-hour-plus per target, unverified whether it would even
  terminate short of the box's actual resource limits).
  NOTE: the `--kf-scale-target` invocation's stdout was piped through
  `tail -100` for capture; because the RSS sampler alone produced ~570
  lines before the outer timeout fired, the per-kf `kf=N: entries, Xs`
  lines for kf=0..3 on this specific run scrolled out of the captured
  window before they could be logged verbatim here -- the kf=3 reference
  numbers above are iter 10's already-verified figures for `b2d`, not a
  fresh re-print from this run; this does not affect the kf=4 timeout
  conclusion, which was observed directly (process still running past
  2850s with no kf=4 line ever printed).
  Kernel port: NONE (both steps are negative/infeasible findings).
  `perf_takehome.py`/`dev.py` untouched throughout. Only `fusion_search.rs`
  changed: new `--force-engine-c` CLI flag, `run_mitm_target`'s added
  `force_engine_c` parameter, a `build_fwd_tab` kf=4 arm, and
  `run_kf_scale_target_probe`'s loop extended to kf<=4 with a
  best-effort per-kf time guard. Build clean; `cargo test --release
  --bin fusion_search`: 9/9 passing, unchanged. Default (`--mitm` with no
  flags) behavior reconfirmed byte-identical.

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
- P-12 [op-reduction, iter-6b, UPDATED iter-7]: with H-016's per-cut
  kf<=2/j<=5 ceiling now confirmed to also hold GLOBALLY (no waypoint
  assumption, `full_hash` MITM target, now actually landed and
  re-verified on current `main` in iter 7 -- 2,868B engine-A candidates,
  2,118,285,916 engine-C chain nodes, no <=10-op program), the two
  remaining moves for "11 in 10" were: (a) extend engine C's forward-table
  builder to kf=3, or (b) fix CEGIS's scaling wall (case-split op-kind
  instead of one mux'd expression). Iter 7 ACTUALLY ATTEMPTED (a) rather
  than just estimating it: implemented real kf=3 support in
  `build_fwd_tab` and measured it directly (not extrapolated) at
  increasing pool sizes on the real 8-core/24GB box. RESULT: (a) is
  CLOSED INFEASIBLE, and for a different reason than the original ~1000x
  CPU estimate suggested -- it's a MEMORY wall, not a time wall. Entries
  hit 85.6M (284s, 16-item toy pool) with the growth exponent still
  ACCELERATING (~5.2 -> ~10.0 as pool size climbed toward 16-23), and the
  real 23-item pool's kf=3 attempt had to be killed after ~10 min with
  RSS unboundedly climbing past 8GB (freed ~16GB system-wide on kill --
  it was nowhere near converging). A pool small enough to finish in
  minutes (<=12 items) is too impoverished to contain the actual
  multi-stage hash constants needed for ANY meaningful span (even the
  smallest 6-op sub-span target needs ~13 items to be non-trivial). There
  is no pool size simultaneously tractable-in-hours and representative of
  the real function -- "more wall-clock" will not fix this, only a
  different table representation would (external/streaming dedup, or a
  proven 2-3-order-of-magnitude algebraic canonicalization). (b) (the
  CEGIS case-split fix) remains untried and is now the more promising
  remaining lever, since it doesn't share this memory-blowup failure
  mode. Absent (b) being funded, H-025/G-10 stay open only in the
  "unreachable at current tooling scale" sense -- treat as effectively
  closed for practical purposes.
  CORRECTION (iter 10): the above "kf=3 CLOSED INFEASIBLE" verdict was
  measured ONLY against synthetic prefixes of `full_hash`'s own 23-item
  pool -- it was never actually tested against any individual segment
  target's real (much smaller) pool, and the closing sentence ("no pool
  size is both tractable in hours and rich enough... even the smallest
  existing sub-span target already needs a ~13-item pool") turned out to
  be an overgeneralization once actually checked. Iter 10 built kf=3
  forward tables against every real still-open segment target's own pool
  (b2d/xr5/xr3p at 13 items, a2d/b2e/c2out at 15, head4u at 9) and found
  ALL of them cheap: 17-120s, 3.5-11.2GB peak transient RSS, nowhere near
  the memory wall iter 7 hit at pool=23. It then wired kf=3 into the real,
  verified engine C search (opt-in `--kf3` flag, default behavior
  unchanged) and ran it to completion for b2d (760.9s), xr5 (921.7s), and
  xr3p (592.2s) -- ALL THREE STILL NEGATIVE at this deeper boundary. So:
  (a) is CLOSED INFEASIBLE only for the FULL/global `full_hash` target
  specifically (pool=23); for every individual segment target (pool<=15)
  it is CLOSED NEGATIVE (genuinely searched and ruled out at kf<=3, not
  infeasible at all). The two still-untaken next steps for THIS scale are
  (i) enabling engine C (currently `enable_engine_c=false`) for a2d/b2e/
  c2out and running their chain DFS for the first time ever (their pool=15
  kf=3 tables are confirmed cheap; the chain-DFS cost itself is untimed
  for these three specifically), and (ii) kf=4 at the segment scale
  (untested; likely still cheap given the trend, but not measured). Only
  the FULL 23-item `full_hash` pool remains a genuine memory wall
  requiring a different table representation to progress past kf<=2.
  UPDATE (iter 11): both (i) and (ii) are now taken. (i) enabled and
  timed for real via a new opt-in `--force-engine-c` flag (default
  `--mitm` behavior unaffected): a2d/b2e/c2out's chain-DFS turned out
  CHEAPER than b2d/xr5/xr3p's (377-481s vs 592-922s total, because
  `max_chain_ops` caps at 5 for both groups while these three's
  `engine_a_kmax=3` vs 4 makes their engine A phase faster) -- ran to
  completion at kf<=2 and kf<=3 for all three, ALL STILL NEGATIVE. Every
  real segment target (all six) is now closed negative at kf<=3 with
  nothing left in this class untested at that depth. (ii) kf=4 measured
  for real on `b2d` (cheapest kf=3 case, 31.6s/25.1M entries at iter 10):
  did NOT complete a single kf=4 table build within a 47.5-min wall-clock
  budget -- CLOSED INFEASIBLE, but as a genuine CPU-TIME wall this time,
  not memory (RSS held steady at 3.9-5.9GB throughout, no runaway growth
  at all unlike iter 7's kf=3-on-full_hash memory wall). kf=4 was never
  wired into any real search as a result. The trend guess in the
  previous paragraph ("likely still cheap") is now falsified: kf=3->kf=4
  costs at least ~90x at the SAME pool where kf=2->kf=3 cost roughly
  the accelerating-but-still-tractable growth iter 10 measured -- a much
  steeper step. Absent a fundamentally different forward-table
  representation, kf=4 is closed at the segment scale too, for a
  different resource reason than `full_hash`'s kf=3 closure but the same
  practical conclusion: not reachable with this tooling.

## H-036 (2026-07-27): alternative algebraic DECOMPOSITIONS of myhash — CLOSED NEGATIVE (analytic + enumerative)

Scope: re-derivations of the hash in different op bases, explicitly NOT
fusions of the current step sequence (that space is H-003/H-016/H-025's,
closed). Four directions from the backlog statement, each closed below.
No kernel change: no candidate survived to emission. ops/hash unchanged
at 11.39 avg (11 mixing ops + nv-xor − 9/16 C5 elision); fast gate
re-confirmed green at 1038 with zero diff to perf_takehome.py/dev.py.

Structural observation that frames everything: in the current 11-op DAG
every node costs EXACTLY 1 op from already-present values. A shared new
intermediate w serving two nodes u,v costs |w|+2 >= 3 ops against the 2
it would replace, so shared-subexpression REARRANGEMENT can never win;
op removal requires either (a) a globally shorter program — closed
negative at depth<=7 with no waypoint assumption (H-025 iters 6b/7,
2.87T engine-A candidates + 6.9B/2.1B MITM nodes), or (b) deleting a
node because its consumers can re-derive their outputs in 1 op without
it. Family (b) is finite over the trace-node set and is exactly what the
new probe enumerates.

1) Cross-stage/cross-round shared subexpressions with the concrete
   constants (family (b)): NEW TOOL tools/hash_relation_probe.py.
   Enumerated every 1-op derivation of every node of the 2-round trace
   DAG (25 nodes: both rounds' a1,t1,u1,a2,p,q,a3,a4,t5,w5,val plus
   x, nv2, x2) from every other trace node: all 8 bin ops over all node
   pairs both orders, all bin ops vs a solved free constant (add/sub
   both orders/xor/mul-by-odd-inverse/and/or canonical solves, all 32
   shift amounts), madd over all node triples, madd(node,node,C-solved),
   madd(node,K-solved,C-solved), madd(node,K-solved,node). 340,023
   candidates, N=64 structured+random samples (cross-round relations
   forced to hold under per-sample random nv2). RESULT: 67 hits, ALL 67
   classified inside the defining stage windows (chain ops, their local
   inverses, sibling xor rearrangements; positive controls like
   q = madd(p, 0x200, 0xbb372800) found as expected). ZERO long-range
   coincidence relations. Combined with the counting argument above:
   no decomposition over this intermediate set shortens the hash.

2) Multiply distribution / constants co-designed with shifts: the four
   multipliers ARE already the full co-design harvest (4097=1+2^12,
   33=1+2^5, 16896=33*2^9, 9=1+2^3 — the existing 18->11 fusion).
   Deeper distribution is blocked by the two xorshift stages: verified
   numerically that s0 (madd) is NOT GF(2)-affine and s1/s5 (xorshifts)
   are NOT Z-affine for these constants (50-sample falsification each),
   so no single-algebra global form exists, and any mixed shorter form
   is a globally shorter program (closed, (a) above). Constant
   coincidence scan over {C0,C1,C2,C3,C4,C5,ap,aq}: all pairs under
   shifts/cheap-multiplier/near-add/2-bit-xor relations — NONE except
   the definitional aq = C2<<9.

3) madd-canonical 2-op windows: every 2-op window re-derivation is
   inside the probe family (madd with solved K,C from any trace node) —
   0 hits; independently subsumed by the six per-segment closures at
   kf<=3 (iters 10-11).

4) Parity from a prefix/cheaper projection: MOOT for op count — parity
   is already ZERO ops in mainline (H-015 table reversal). Bit trace for
   the record: parity(val) = bit0(a4) ^ bit16(a4) ^ 1 (C5 has bit0=1,
   bit16=0); bit0(a4) collapses linearly (kq even, kp/k4 odd) to
   bit0(x) ^ bit19(a1) ^ const, but bit16(a4) needs the low-17 carry
   chains of all three madd stages, and every machine op is full-width,
   so the producing chain has the same op count as the full hash. Any
   depth-only benefit was closed by G-8 (parity-early is
   valu-throughput-bound). Mid-round val cannot be deferred/projected
   away regardless: it feeds the next round's hash input exactly, and
   final-round vals are graded exactly.

Two NEW analytic closures of transform-domain families the prior
searches did not formally cover:
- xor-conjugation (carry val as val^D, D absorbed free by pre-xoring the
  node-value table, generalizing H-015): xorshift stages transport
  xor-domains at zero cost (f(b^D) = f(b) ^ D ^ (D>>s)), but madd stages
  BLOCK them: K*(x^D)+C == K'*x+C' for all x forces K'=+-K (x=0,1) and
  then (x^D)-x (D even) or (x^D)+x (D odd) constant in x, which holds
  only for D=0 (D odd fails at x=2 already). So every xor-domain is
  confined to the xorshift spans adjacent to the round boundary —
  exactly the space c5_prexor already exploits and xr3/xr3p closed.
- affine conjugation (carry val as K*val+C): composing affine maps with
  the madd stages is pure constant relabeling (same op count, inside the
  solved-constant search space already), does not transport through
  xorshift stages, and cannot cross the ^nv round boundary. No op-count
  degree of freedom exists in this family at all.

Honest caveats: (i) the probe's vocabulary matches fusion_search's
(no compare/select ops; a 1-bit compare output cannot carry 32-bit
full-entropy intermediates, but select-based branchy forms are formally
unsearched); (ii) family (a) remains open beyond depth 7 as before —
this iteration adds no depth there, by design; (iii) cross-block sharing
with the idx-state block is impossible beyond parity (idx values are
small integers; the only shared quantity is the routing bit, already
0-op).

VERDICT: H-036 CLOSED NEGATIVE. The re-derivation directions either
reduce to the already-closed shorter-global-program question or are
proven empty here. Recommend the strain stop reopening hash op-count
below the 892-gap pressure unless someone brings a fundamentally new
program class (select-based forms, or a depth>7 search breakthrough);
the remaining credible route to 892 is outside the hash op count
(H-035 idx-state folding, load/schedule shape).

## H-035 (2026-07-27): fold the idx recurrence into hash multiply_adds — REJECT

- hypothesis (from the 892-leaderboard gap analysis): the affine recurrence
  p <- 2p + b / addr = base + p should ride the hash's existing 2,950 madd
  slots for free with pre-scaled/biased operand tables (the c5_prexor
  transformed-domain trick applied to position), driving Idx 7,448 ->
  ~1,000 lane-ops (~-100 cyc composed).
- verdict: **REJECT — the fold is algebraically impossible on this ISA,
  and the removable-op budget is ~4x smaller than the hypothesis needs.**
  A companion micro-lever (idx_boundary_select, the P-14 follow-up the
  code explicitly left open) was implemented, verified bit-exact, and
  measured **cycle-neutral: 1038 -> 1038** at the mainline config.

### Why the fold cannot exist (closure argument, mod-2^32 madd)
- The steady-gather update is st' = 2*st + ov + par with par = bit0(vl),
  vl the full 32-bit hashed value (load-bearing: intermediate hashes chain
  into the next round and the final stores, so vl cannot carry position in
  any of its bits — its 32 bits are all spoken for).
- One `multiply_add(a,b,c)` has three operand slots. To fold st, vl, and a
  constant into ONE op the only assignments are:
  * st*two + vl = 2st + vl — carries ALL of vl's bits, not just bit0;
    the error 2*(vl>>1) is runtime-dependent, no layout fixes it.
  * vl*k + f(st): the only k for which vl*k mod 2^32 depends solely on
    bit0(vl) is k = 2^31 (vl*2^31 = par<<31). The parity then sits at
    bit31 — unusable as an address addend (mem indices are exact), and
    any odd (invertible) scale A applied to st to relocate the parity
    would need A*par from vl in one op, which only exists for the even
    A = 2^31, which destroys st's bits (st*2^31 keeps only bit0 of st).
    Self-consistent scaled/biased domains w = A*st + B all reduce to
    this same dead end.
  * The bit31 bias DOES self-destruct on doubling (2*(x + par<<31) = 2x
    mod 2^32), but the round that carries it needs the true address for
    its own gather, so nothing is gained.
- Therefore per steady-gather transition the floor is: 1 op parity
  extraction (& 1 / % 2 — no shorter form) + 1 recurrence madd + 1
  combine, where only the combine's ENGINE is negotiable (P-14/H-029's
  vselect moves it to flow because ov+/-par for 0/1 par is a choice
  between two precomputed constants). Tournament transitions are already
  at 1 madd (parity shared with the fold conds under parity_conds).
  Mainline is already AT this floor everywhere except engine placement.
- ov = 0 (which would free the madd's +c slot for par and genuinely drop
  the combine) requires the forest based at mem[1] (1-indexed heap with
  base folded away — the missing piece of P-10's premise). Checked and
  closed: copying the forest needs ~256 vloads + 256 vstores against only
  ~176 spare load slots at 1038 (load engine 91.5% busy) — the copy costs
  more than the ~160-192 valu slots it could save; per-level relocation
  (B_{L+1} = 2*B_L) needs free mem regions that overlap the live forest
  and mem is sized without slack. P-10's "likely rejected" can be marked
  CLOSED with this sharper reason: the 2-term problem is only escapable
  by a memory-layout change the machine budget cannot pay for.

### Budget refutation
- Idx at 1038 = 7,448 lane-ops = ~2 vec-ops per transition (448
  transitions x 8 lanes; tournament 1-2 ops, gather/boundary 3 ops).
- Even the impossible best case (every 3-op transition to 2 ops:
  ~192 steady + ~62 boundary sites) removes ~1,700-2,000 lane-ops, i.e.
  a valu-floor drop of <= ~5 cycles-equivalent per engine-mix — nowhere
  near the hypothesized 6,400. **No Idx-only path reaches 892**; the gap
  must be hash decompositions (H-036) or loads (-116 needed, H-037).

### Implemented + measured: idx_boundary_select (new kwarg, default off)
- dev.py `build_kernel_scheduled(idx_boundary_select=...)`: the epoch-exit
  boundary conversion `madd(st,st,negtwo,rec_vecs[key]); vec(-/+,st,st,par)`
  becomes `vsel(par,par,rec-/+1,rec); madd(st,st,negtwo,par)` — the same
  select-vs-add reshaping P-14 landed for the steady-gather branch,
  covering the branch the P-14 implementation note explicitly left open.
  The rec-/+1 arm vectors ride setup-dead lv[0..15] (same hosting trick as
  omf1_vec at lv[24..31]; zero new scratch, one setup vec each), with a
  loud build-time assert mirroring idx_select's against the b3l_diffs
  round-15 dffold fallback reclaiming lv (stream-order corruption guard).
  62 sites at mainline shape: 12 (r=3 exits, g<12) + 20 (r=4, g>=12) +
  30 (r=14 epoch-2 exits, g<30); keys {(30,"-"), (62,"-")}.
- measurements (tools/run_variant.py, frozen grader, BASE_KWARGS = the
  1038 mainline config):
  * flag off: 1038 correct; flag on: **1038 correct** (also seeds 1/7/42
    and debug_compares=True — all bit-exact).
  * engine census at 1038/1038: alu 11881 -> 11617 (-264), valu 6119 ->
    6100 (-19), flow 797 -> 845 (+48), load/store unchanged. Mechanism
    confirmed (par-combines left alu/valu for flow) — wall-clock is
    simply not bound by those slots.
  * l4_gmin retune sweep (P-3 pattern), 7x5 grid a in 5..12 x b in
    28..32, flag on: best remains (9,30) = 1038; smooth bowl, no new
    optimum. Secondary sweeps (tie_break variants, pool sizes,
    pair_tournament_first_fold_race, idx_recurrence_race off, skew (4,4)/
    (8,2)): all >= 1038.
  * dev.py's own dispatch config (1052): + flag = 1052 (neutral there
    too). dev.py default path byte-identical with flag off (1052; full
    gate `tests/submission_tests.py` 9/9 OK, mainline 1038 untouched).
- disposition: kept flag-gated as a NEGATIVE CONTROL / composition
  candidate (it lowers alu/valu occupancy for free, so a future accept
  that becomes alu- or valu-bound at these cycles may compose with it;
  it is strictly-no-worse and bit-exact). Do NOT flip mainline — zero
  standalone gain.

### Follow-ups
- H-036 (hash re-derivation) is now the ONLY lane-op class big enough for
  the 892 gap — this analysis strengthens its justification note.
- H-037 (load_offset): unaffected; the gather-address FEEDING arithmetic
  it targets is the same 2-op floor shown here, so expect small.
- If any future accept turns the 1030s valu-bound: re-measure
  idx_boundary_select (+ idx_select) composed — they free ~283 alu/valu
  slots between them at zero cycle cost today.
- P-10 can be moved to CLOSED in the backlog with the fp=1/copy-budget
  argument above (stronger than the previous "likely rejected").

## H-038 (2026-07-27): compare/select-extended hash program search — CLOSED NEGATIVE

Scope: the ONE vocabulary gap all three closed tool classes explicitly name
(G-10 fusion/MITM, G-20 re-derivation, H-025 CEGIS/MITM): programs using the
machine's compare ops `<` / `==` (alu/valu, 0/1 result) and the flow engine's
`select(cond, a, b)`. Searched honestly at every previously-closed boundary;
NOTHING survives. No kernel change (no candidate reached emission); mainline
untouched at 1038; full gate green (tests/submission_tests.py exit 0,
CYCLES 1038, worktree byte-clean vs main for perf_takehome.py/dev.py).

### New tooling (all in tools/ or rust_harness/, kernel untouched)
- `fusion_search --cmpsel` (rust_harness/src/bin/fusion_search.rs): interior
  enumeration extended with lt/eq over all operand pairs and select over all
  (cond, a, b) triples (cond non-const, a != b); final level adds pooled
  lt/eq/select, solved select arms (select(c,x,C) / select(c,C,x) /
  select(c,C1,C2)), and solved thresholds lt(x,C)/lt(C,x)/eq(x,C) for
  0/1-valued targets. The MITM engines' FORWARD sides inherit the extension
  through the shared enumerate_level. Flag default off — byte-identical
  legacy behavior, 9/9 pre-existing self-tests green.
- `--selftest-cmpsel` positive controls: 3 planted functions whose shortest
  forms REQUIRE the new vocabulary (carry-add x+(x<2^31); two-constant
  branch; select mix over two inputs) — all rediscovered at planted length
  and verified on 10M+ inputs. The tool even found equal-length alternates
  (madd on a boolean with solved (K,C)), i.e. the new op interactions
  genuinely enumerate.
- `--engine-a-kmax N`: caps MITM engine A forward depth (cmpsel multiplies
  the k=4 general layer ~10-30x into a CPU wall; base-vocabulary k<=4
  closure stands from iters 4/7).
- `tools/hash_cmpsel_probe.py`: 1-op compare/select re-derivation probe over
  the 25-node two-round trace DAG (extends G-20's family (b)).

### Why the MITM suffix/meet sides need no compare/select extension (proved,
stated in the tool header): a compare link collapses the chain value to
{0,1}; a select link with constant arms collapses to <=2 distinct values;
every requirement battery for a full-width target has >2 distinct probe
values, so no suffix containing one can reproduce it; a compare as the meet
op is impossible for the same reason. The only non-collapsing unary select
link, select(x,x,C) = (x==0 ? C : x), differs from the identity link at the
single input 0 — probe-indistinguishable from identity (already covered) and
able to repair a program at only one point of 2^32.

### Coverage (all NEGATIVE; 32-probe batteries; any find verified on 10M+
inputs before reporting)
1. 1-op re-derivations (hash_cmpsel_probe.py): 337,548 candidates over the
   25-node DAG, N=64 structured+random samples — 0 hits. Measured structural
   facts: NO trace node is 0/1-valued (compares can never equal a node);
   only x on the structured x=0 sample is ever zero (select cond==0
   branches degenerate over this node set).
2. Forward suite, depth = current-1 (fusion_search --cmpsel), 12 full-width
   targets, 13.84B candidates total: full 11->\<=3 4.19B; g01 4->3 1.02B;
   a2u 3->2 285K; b2c 3->2 391K; g123mid 4->3 2.15B; f23 3->2 692K; g234
   4->3 2.15B; g45 4->3 1.53B; e2out 3->2 200K; head2 2->1 766; xr3 4->3
   655M; par_c 8->\<=3 2.14B. All negative. par_d/par_e "finds" are the
   KNOWN 2-op parity forms (madd + shr31) plus new equal-length lt-flavored
   sign-test variants (lt(t1, 0x80000000) == shr31 here) — parity already
   costs 0 ops in mainline (H-015), so no gain; compares' only appearance
   anywhere in the campaign is as these equal-length parity alternates.
3. Depth-4 forward closures (the old --long questions, cmpsel): head3 5->4
   453.4B; xr4 5->4 440.8B; u2e 5->4 303.8B; par_c_deep 5->4 289.1B
   (parity target searched WITH solved compare thresholds). Total 1.487T,
   all negative.
4. MITM boundary questions (--mitm --cmpsel --engine-a-kmax 3
   --force-engine-c; engines: A = forward exhaustive k<=3 cmpsel, B =
   fwd-DFS-3 cmpsel probing 1.4M inverted suffix chains, C = chain DFS <=5
   probing kf<=2 cmpsel prefix tables), A/B/C counts per target, all
   negative:
   - b2d 6->5: 1.50B / 1.05B / 2.12B      - xr5 6->5: 1.78B / 3.89B / 2.12B
   - xr3p 5->4: 1.14B / 3.84B / 2.10B     - xr4r 5->4: — / 3.73B / 2.10B
   - head3r 5->4: — / 3.77B / 2.10B       - head4u 4->3: 1.11B / 540K / 336M
   - u2er 5->4: — / 2.16B / 2.10B         - a2d 7->6: 3.05B / 2.16B / 2.12B
   - b2e 7->6: 3.07B / 2.19B / 2.12B      - c2out 7->6: 3.07B / 2.19B / 2.12B
5. full_hash 11->10, NO waypoint/segment assumption (the iter-6b/7 global
   question, cmpsel): engine A k<=3 4.15B; engine B 19.66B forward nodes
   (1,221 j=1 + 1,423,563 j=2 inverted chains); engine C 2.12B chain nodes
   against kf<=2 cmpsel prefix tables of 995,640 entries. NEGATIVE.

Grand total: ~1.586T explicit candidates/nodes with the extended vocabulary.

### Honest boundary (NOT covered)
- Interior compare thresholds / select arms drawn from the per-target
  constant pool only (final-op constants are solved) — the same pool caveat
  every prior fusion_search run states.
- MITM engine A k=4 under cmpsel (CPU wall; base vocabulary k<=4 closed in
  iters 4/7). Compare/select ops sitting in the LAST ~4 ops in non-chain /
  non-meet positions beyond engine B's depth-3 forward reach are the same
  already-stated base-tool caveat class ("binary op of two temps atop a
  depth-4 prefix").
- kf=3 cmpsel prefix tables (base closed kf<=3 in iter 11; cmpsel grows
  tables ~13-25x into the same wall class as base kf=4).
- 32-probe probabilistic identity, as in all prior runs.

### Verdict
CLOSED NEGATIVE. G-20's reopen-if clause ("a compare/select-based branchy
form is shown viable") is answered: not viable at any searched boundary.
Hash op-count is now closed by a FOURTH independent tool class; the only
thing compares buy on this DAG is equal-length sign-test alternates for
parity bits (worthless — parity is 0 ops). Structural moral: a compare
contributes at most 1 bit (carry/borrow material, e.g. distributing shifts
over adds), and for these constants no such redistribution shortens
anything; a select must be paid on flow (1/cyc, ~76% utilized) even if one
existed. Recommend graveyarding as the final hash-op-count entry: the 892
gap is NOT in the hash program; remaining credible mass is loads/schedule
shape (H-039/H-040 territory).
