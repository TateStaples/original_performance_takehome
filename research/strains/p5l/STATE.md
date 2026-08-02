# Strain P5-L — 2-round composite <=19 ops: mechanism accounting by theory

status: FINAL (2026-08-02) — **<=19 composite REFUTED by arithmetic within
the complete named-mechanism space; the 2-round route reduces exactly to
the single-round <=9 question (no independent composite magic exists).**
UPDATE (P5-L2, 2026-08-02): the last OPEN item, the dir1 commutation z3
query, is now CLOSED **UNSAT** analytically (sec 3.6, tools/p5l_dir1.py).
Mechanism (c) drops from "<=1 speculative" to **0 proven**. The refutation
no longer has any quantitative slack to spend.
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

## 1. Mechanism accounting table (FINAL)

| # | mechanism | max ops savable | argument | status |
|---|---|---|---|---|
| a | mask absorption into fold-ins (c5_prexor) | 2 (amortized) | node-table transform free; ALREADY BANKED in census (hash(k)=512k+176 nets 336 elisions) | CLOSED (banked, not new) |
| b | sigma-sigma layer merge | 0 | no adjacent sigma pair exists (every pair madd-separated); even if adjacency were forced: L19*L16 = I^S16^S19 costs exactly 4 ops = 2+2 separate (support lemma + z3 merge3 1509/1 UNSAT/analytic); mask-merge 1 op is the SAME op banked in (a) | CLOSED (sec 3.1, 3.4) |
| c | madd<->sigma commutation (enabler for b,f) | **0** | z3 quadruple-criterion queries over ALL affine B, all odd K'', all consts: dir2 (4097,19) UNSAT 2.6s; dir2 (9,16) UNSAT 4.5s. dir1 (4097,16) and dir1 (33,19) z3-TIMEOUTed and are now closed **UNSAT by the top-bit lemma** (sec 3.6): dir1 needs K == +-1 (mod 2^s); 4097 mod 2^16 = 4097 and 33 mod 2^19 = 33, neither +-1. Even had dir1 been SAT: only enables madd4*madd'' fusion worth 1 op, and the runtime y2 fold-in then blocks it (mech e) plus affine byproduct B must be implemented (cost >= saving) | **CLOSED both directions** |
| d | shorter sigma / mask transport past madds | 0 | sigma_s floor = 2 ops (1-op refuted: madd needs C=0,K=1 => sigma=id false; shr/xorc/xor2 trivially fail); masks cannot cross madds (P3-F XOR<->ADD lemma); no two masks adjacent | CLOSED |
| e | fold-in absorption into madd addend | 0 | runtime lemma: v^y == v + f(y) for all v iff y in {0,2^31}; y uniform [0,2^30) (2^31 unreachable, 0 measure 2^-30) | CLOSED (sec 3.5) |
| f | cross-boundary madd fusion (madd4*madd0') | 0 | separated by sigma16 AND runtime fold-in xor; needs (c)-dir2 (UNSAT) or (c)-dir1 AND xor-past-madd (refuted by e) | CLOSED |

**Sum of savings beyond banked (a): 0 proven, and after P5-L2 the "<=1 if
dir1 were SAT" branch is gone too -- 0 exactly. Needed: 3 (24 - 2 banked -
19) under the generous reading that (a)'s 2 ops are still on the table;
needed 5 (24 - 19) under the strict reading that the 24-op census already
banks (a), which is what the census actually is. 0 < 3 <= 5 => the <=19
composite is REFUTED across the entire mechanism space under EITHER
bookkeeping convention, and with no remaining OPEN query.**

Baseline audit (P5-L2): tools/p5d_cegis.py REAL_11 is exactly 11 ops
(4 madd, 2 shr, 2 xorc, 3 xor2); 2*11 + 2 fold-ins = 24 confirms sec 0.

## 2. Reduction statement (FINAL)

Cross-round interaction savings = 0 (sec 1) and the boundary span is rigid
at 7 ops in the deletion family (span7->5 UNSAT P5-D; span7->6 ALL UNSAT
here). Therefore:

  min composite ops = 2*(min single-round ops) + 2 fold-ins - 2 elisions
  = 2*m + 2 - 2 = 2m.   Composite <= 19  <=>  m <= 9 (integer).

**The 2-round composite question REDUCES EXACTLY to the single-round 9-op
question (P5-I sandwich9 lift-and-prune, P5-J/K).** There is no independent
2-round route to effective k<=9.5. Caveats (the only formal gaps):
(i) ~~dir1 commutation OPEN~~ — **RESOLVED UNSAT by P5-L2, sec 3.6**;
(ii) non-decomposable global 19-op restructurings — the same (S)-hypothesis
gap as P3-F's N>=11; bounded here by the span deletion-family closures and
by every P5-B/D/H search negative. A full-shape z3 sweep of 4-op and 5-op
boundary-span forms (~40k shapes) would upgrade (ii) at the span locus;
est. driver-fleet job, not in-session.

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

### 3.4 z3 merge3: no 3-op merged sigma layer (tools/p5l_z3.py merge3)

Target v ^ (v>>16) ^ (v>>19), ALL 3-op shapes, extended vocab
{madd,shr,xorc,andc,orc} unary + {xor2,add2,sub2,and2,or2,mul2} binary,
all constants free: **1510 pruned shapes: 1509 UNSAT, 1 TIMEOUT, 0 FOUND**
(230s total). The one TIMEOUT [madd, shr, madd] is closed ANALYTICALLY:
(K1*v+C1)>>s has image size <= 2^(32-s) < 2^32 for s>=1 and a following
madd cannot re-inflate it, but the target has GF(2)-rank 32 (bijective).
=> **merged sigma19*sigma16 costs exactly 4 ops — identical to separate
implementation. Sigma merging saves 0 linear ops, closed soundly.**

### 3.4b z3 span7->6: boundary span cannot save even ONE op (deletion family)

All 1-deletion templates of P5-D's SPAN_7 (primed boundary span
stage1(stage0(sigma16(e)^y')) at 6 ops, full constant freedom:
**5 valid templates, ALL UNSAT** (del=[1]b1 164.5s, del=[2]b1 177.2s,
del=[3] 0.0s, del=[4] 0.0s, del=[5] 1.3s; del=[0] degenerates, del=[1]b0 /
del=[2]b0 cascade below 6 ops = SKIP, subsumed by P5-D's span7->5 UNSAT).
Combined with P5-D: **the 7-op boundary span is rigid at 7 in the deletion
family — neither 1-op nor 2-op savings exist.**

### 3.5 Runtime XOR<->ADD lemma (fold-in absorption, runtime form)

(v ^ y) == v + f(y) for all v iff y in {0, 2^31}: v=0 forces f(y)=y;
v=y forces 2y == 0 mod 2^32. Node values are uniform in [0, 2^30), so
y = 2^31 never occurs and y = 0 has measure 2^-30. => the fold-in xor can
NEVER become a madd runtime-addend, and no xor can cross any madd
(P3-F lemma, runtime-value form, verified numerically).

### 3.6 dir1 commutation CLOSED — the top-bit lemma (P5-L2, tools/p5l_dir1.py)

The predecessor's dir1 z3 runs timed out and their output was lost (no log
on disk, no surviving process). Re-running the same encoding was pointless,
so dir1 was closed by theory instead. dir1 asks: E? odd K'', C'', C and
GF(2)-AFFINE B with  K*sigma_s(v) + C == B(K''*v + C'')  for all v.

**TOP-BIT LEMMA.** Flip the top bit of v. Since K'' is odd,
K''*(v^2^31)+C'' = u ^ 2^31 with u = K''v+C''; since B is affine,
B(u^2^31) = B(u) ^ D for a CONSTANT D; since sigma_s is linear and
bijective, substituting w = sigma_s(v) (which then ranges over ALL of
Z_2^32) eliminates K'', C'' and B entirely and leaves

    (L)  K*(w ^ e) + C == (K*w + C) ^ D  for all w,   e := 2^31 ^ 2^(31-s).

Restrict to the 2^31 values of w with bit (31-s) clear: there w^e = w+e, so
with E := K*e mod 2^32 = (K*2^(31-s)) ^ 2^31 and X := K*w+C (which sweeps a
set of size 2^31, as w |-> Kw+C is a bijection), (L) becomes X + E == X ^ D.
Carry analysis: D_i = E_i ^ c_i so the carry word is c = D ^ E with c_0 = 0,
and c_{i+1} = maj(X_i, E_i, c_i) leaves X_i free exactly when D_i = 0. Hence
the solution set of X+E == X^D is empty or a coset of dimension
32 - popcount(D & 0x7fffffff); containing 2^31 values of X forces
popcount(D & 0x7fffffff) <= 1. K odd makes j := 31-s the lowest set bit of
E, so c_j = 0 and D_j = 1: thus D in {2^j, 2^j+2^31}, and the carry chain is
then consistent only if E's bits j+1..30 are all equal.

  **=> dir1 is possible only if K == +1 or K == -1 (mod 2^s).**

  - dir1 (K=4097, s=16): 4097 mod 2^16 = 4097, not +-1 => **UNSAT**.
  - dir1 (K=33,   s=19): 33 mod 2^19 = 33,   not +-1 => **UNSAT**.

Validation (the lemma is necessary, not sufficient, and it is not vacuous):
- **Exhaustive small-width dir1** (`run_exhaust`): for widths n=6 (s=2,3)
  and n=7 (s=3,4), over ALL odd K, ALL odd K'', ALL C'', ALL C, with B
  tested for exact GF(2)-affinity: **0 mismatches** — every solution found
  satisfies the lemma. Solutions exist exactly at K in {1, 2^(n-1)-1,
  2^(n-1)+1, 2^n-1}, i.e. K == +-1 mod 2^(n-1): the same degenerate
  +-1-multiplier family that produced sec 3.3's dir2 K=1 positive control
  at 0x7fffffff. (An earlier draft of the closed form omitted the -1 branch
  and this sweep caught it — the carry-chain test itself was already right.)
- **Width-32 brute force** (`scan32`): (L) at w=0 forces D = C ^ (C+E), so
  all 2^32 values of C can be scanned directly against 20 probe values of w:
  K=4097 s=16 -> **0 surviving C**; K=33 s=19 -> **0 surviving C**;
  controls K=1 s=19 -> 2^19 survivors, K=1/65537 s=16 -> 715849728
  survivors (machinery does find solutions when they exist).

Two independent methods, both with passing positive controls, agree.
**Mechanism (c) = 0 proven, no OPEN queries remain in the table.**
