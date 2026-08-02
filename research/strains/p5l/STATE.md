# Strain P5-L — 2-round composite <=19 ops: mechanism accounting by theory

status: IN PROGRESS (2026-08-02)
brief: decide by THEORY whether myhash(myhash(x^y1)^y2) has a <=19-op form
(24 naive = 2 fold-ins + 2x11). P5-D closed the LOCAL boundary route
(span7->5 all 10 deletion templates UNSAT); this strain does the GLOBAL
mechanism accounting: enumerate every algebraic elimination mechanism, bound
its max savings, sum. If sum < 5, the composite fusion route is refuted.

## 0. Composite op census (baseline 24)

Per round (REAL_11 decomposition, tools/p5d_cegis.py):
  madd0 (K=4097,C0) | sigma19C1 = shr19+xorcC1+xor2 (3) | maddP,maddQ,xor2 (3)
  | madd4 (K=9,C4) | sigma16C5 = shr16+xorcC5+xor2 (3)  = 11 ops
Composite = fold-in(^y1) + 11 + fold-in(^y2) + 11 = 24.
Op totals: 8 madd, 4 shr, 4 xorc, 6 xor2, 2 fold-in xor.
Target <=19 => must save >=5.

## 1. Mechanism accounting table

(filled in as results land; args below)

| # | mechanism | max ops savable | argument | status |
|---|---|---|---|---|
| a | mask absorption into fold-ins (c5_prexor) | 2 (amortized) | node-table transform free; ALREADY BANKED in census (hash(k)=512k+176 nets 336 elisions) | CLOSED (banked, not new) |
| b | sigma-sigma layer merge | 0 | no adjacent sigma pair exists (every pair madd-separated); even if adjacency forced: L19*L16 = I^S16^S19 costs 4 ops = 2+2 separate (support lemma + z3 merge3); mask-merge 1 op is the SAME op banked in (a) | pending z3 merge3 |
| c | madd<->sigma commutation (enabler for b,f) | 0 | conjugate of mult-by-K through sigma_s is non-GF(2)-affine; z3: no affine B for boundary (K,s,dir) triples | pending z3 commute |
| d | shorter sigma / mask transport past madds | 0 | sigma_s floor = 2 ops (1-op refuted, sec. 3); masks cannot cross madds (P3-F XOR<->ADD lemma) | CLOSED |
| e | fold-in absorption into madd addend | 0 | runtime lemma: v^y == v + f(y) for all v iff y in {0,2^31}; y uniform [0,2^30) | CLOSED (P3-F lemma, runtime form verified) |
| f | cross-boundary madd fusion (madd4*madd0') | 0 | separated by sigma16 AND runtime fold-in xor; needs (c) AND xor-past-madd, both refuted | CLOSED conditional on (c) |

Sum of NEW savings (beyond banked (a)): 0. Banked best composite = 22 ops
(effective k=11 — the mainline). 22 - 19 = 3 short.

## 2. Reduction statement (what would have to be true instead)

Savings must come from loci, not mechanisms:
- boundary span (SPAN_7, 7 ops): ->5 UNSAT (P5-D, deletion family);
  ->6 tested here (sec. 5); ->4 would alone give 19 (open, full-shape
  z3 sweep ~40k shapes = driver-fleet job).
- within-round: = the single-round k<=10 question (P5-B/D/H negatives,
  open only at the (S)-hypothesis level; owned by P5-I/J/K).
The composite question REDUCES to (span<=6?) x (single-round<=10?): no
composite-specific mechanism exists.

## 3. Computations

### 3.1 GF(2) linear-layer answer (tools/p5l_compose.py, ALL PASS)

- Fused 11-op myhash == problem.py HASH_STAGES: 100k randoms + corners.
- **L19 * L16 = I ^ S16 ^ S19** (S^35 = 0 at width 32), rank 32 (bijective);
  functionally verified 10k. The interleaved fold-in xor has identity linear
  part, so L19 * X_y * L16 has the same linear part; y rides as an affine
  input.
- **Minimum op count for the merged layer v ^ (v>>16) ^ (v>>19): 4 ops**
  (shr3, xor2, shr16, xor2: t = v^(v>>3); out = v^(t>>16) — verified).
  Lower bound: support-offset argument — target has shift-support {0,16,19}
  (3 offsets, incl. 0, two distinct nonzero). In the linear vocabulary
  (shr/shl/xor2/xorc), shr maps support A -> A+s, xor2 unions supports;
  from {0} one shr caps all supports at subsets of {0,s} (size 3
  unreachable); reaching size 3 needs >= 2 unions and >= 2 shrs => >= 4
  ops. Nonlinear detours at 3 ops: closed by z3 merge3 (sec. 3.4).
  **Separate implementation also costs 4 (2+2). Merged saving on linear
  parts = 0. Mask saving (1 xorc) is the same op already banked by
  c5_prexor — not double-countable.**

### 3.2 Commutation obstruction, quantified (tools/p5l_compose.py)

- mult-by-K is GF(2)-linear iff K is a power of 2; witnesses printed for
  K in {4097, 33, 9, 16896}.
- Partial commutation for K = 2^s+1 (exact, chain-DP validated by brute
  force): K*v acts GF(2)-linearly (== v ^ (v<<s)) exactly on
  {v : v & (v<<s) in {0, 2^31}} — the SAME 2^31 exception as the P3-F
  XOR<->ADD lemma. Fractions: K=4097: 0.884% of inputs; K=33: 0.308%;
  K=9: 0.225%. No special-K relief: the linear-action set is measure-~0.
- Natural conjugate g(w) = K*sigma_s(inv(K)w): affinity fails on 100.00%
  of 50k sampled triples for all four (K,s) pairs; explicit witnesses in
  script output.

### 3.3 Commutation z3 verdicts (tools/p5l_z3.py commute)

Question (fully general): does ANY GF(2)-affine B (arbitrary 32x32 matrix +
const, eliminated via the quadruple criterion f(x)^f(y)^f(z)^f(x^y^z)==0)
plus ANY odd K'', C'', C satisfy the commutation identity?
- Encoding validated by positive control K=1: dir2 FOUND a genuine affine
  commutation via the degenerate multiplier 0x7fffffff = 2^31-1 (the
  known +/-1 mod 2^31 affine-multiplier family), externally affine-verified
  on 20k triples. Controls prove the machinery can find real solutions.
- **dir2 (K=4097, s=19): UNSAT 2.6s** — madd0' cannot move forward through
  sigma19 leaving any affine layer behind.
- **dir2 (K=9, s=16): UNSAT 4.5s** — madd4 cannot move forward through
  sigma16.
- dir1 (K=4097, s=16), dir1 (K=33, s=19): running (dir1 encoding is
  z3-heavy; SAT-side control also timed out, but UNSAT determinations
  are the sound outputs).
Soundness: UNSAT on sampled triples => no affine B exists (samples are
necessary conditions).

### 3.4 z3 merge3 + span7->6 (running)

(pending)

### 3.5 Runtime XOR<->ADD lemma (fold-in absorption, runtime form)

(v ^ y) == v + f(y) for all v iff y in {0, 2^31}: v=0 forces f(y)=y;
v=y forces 2y == 0 mod 2^32. Node values are uniform in [0, 2^30), so
y = 2^31 never occurs and y = 0 has measure 2^-30. => the fold-in xor can
NEVER become a madd runtime-addend, and no xor can cross any madd
(P3-F lemma, runtime-value form, verified numerically).
