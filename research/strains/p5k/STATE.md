# Strain P5-K — 9-op question COMPLETE at the shape level (Phase-5)

status: DONE (partial on two named axes: capped stratum (3,2,1,3);
36/2992 unowned shapes screened)
tools: `tools/p5k_enum.py` (enumerate/DP/canon/normalize/map; selftest
PASS), `tools/p5k_screen.py` (queue build + z3 screen),
`tools/p5k_queue.json` (THE deliverable queue),
`tools/p5k_shapes_n9.json` (458,161 canonical shapes, 49MB),
`tools/p5k_screen_results.jsonl`

## SCREEN TABLE (2026-08-02, top-36 by rank, 60s z3, full const freedom)

UNSAT 4 (closed): ranks 24, 28, 29, 30 (28-30 share prefix
madd,madd,xor2(1,2) = xor-of-two-affines; all refuted in 1.4-3.5s).
TIMEOUT 32 (open, iter=0): every 3-madd sigma-rich shape hits the same
wall P5-D documented (z3 QF_BV cannot decide >=3 chained free 32-bit
multipliers at 60-120s; sandwich9 identically). SAT-candidates: 0.
=> The perfect tier is z3-RESISTANT as a class. The right solver for
the whole tier is P5-I's per-(s1,s2) window/differential machinery, not
longer z3 budgets. Queue statuses: QUEUED 2,956 / SCREEN-TIMEOUT 32 /
SCREEN-UNSAT 4 / OWNED-P5J 8 / OWNED-P5I 1 (sandwich9, rank 328) /
CLOSED-P5D 4.

## 0. Scope statement (what "complete" means here)

Vocabulary is P5-D's template basis (tools/p5d_cegis.py): madd(i)=v*K+C,
shr(i)=v>>s (s in 1..31), xorc(i)=v^C, xor2(i,j). This spans all unary
32-bit affine maps (incl. shl = madd with K=2^s, add-const = K=1), xor
masks, right shifts, and binary XOR. NOT in the vocabulary (out of scope
by brief; note for completeness): binary runtime add/sub/mul/and/or,
runtime-amount shifts, madd with runtime addend. P5-B/P5-D MITM covered
richer op pools for chain-decomposable shapes; this strain is exhaustive
at the SHAPE level over the 4-type basis.

Model: 9 ops, slot 0 = x, op k -> slot k+1, output = slot 9; validity =
every slot 1..8 read by a later op (=> all ops on the output cone; every
slot lies on an x->out path).

## 1. MINIMUM-SHR THEOREM (proved + numerically validated): #shr >= 2

Claim: any shape with <= 1 shr cannot compute myhash for ANY constants.
(a) All four op types are bit-triangular upward except shr: bit b of
    madd/xorc/xor2 output depends only on bits <= b of inputs; shr(s)
    displaces downward by s. So out bit0 depends on x bit i only if some
    x->out path has total shift >= i.
(b) myhash out_0 depends on x_31: witness x=0x4E005510 vs x^2^31
    (myhash bits 0 differ; verified). Kills 0-shr shapes and 1-shr
    shapes with s <= 30 (out_0 would be a function of x mod 2^31).
(c) s = 31 case: for ALL constants, D_{2^31}out_0 is CONSTANT.
    Upstream of the shr the x^2^31 = x+2^31 perturbation stays exactly
    at bit 31 (odd/even-K madd: +K*2^31 = 2^31 or 0 mod 2^32; xorc/xor2
    exact); the shr turns it into a constant bit-0 flip; downstream,
    bit 0 of every slot flips by a constant (madd bit0 flip = K_0 AND
    argflip; xorc/xor2 = XOR of constant flips); bypass branches carry
    the perturbation only at bit 31, which cannot reach bit 0 without a
    second shr. myhash's D_{2^31}out_0 is NONCONSTANT: witnesses
    0x4E005510 (D=1) and 0x4679814A (D=0). Same proof style as P5-I's
    window/differential theorems (strains/p5i/STATE.md secs 1-2).
Numeric guard (tools/p5k_enum.py --selftest): 492 (shape,const) trials
over all 1-shr 6-op shapes: D constant ALWAYS; negative control (real
11-op shape + sandwich9 canonical, real-like shifts): 19/24 nonconstant
-- the test has teeth. SELFTEST PASS.

## 2. SOUND FILTERS

K1  #shr >= 2 (theorem above).
K2  no shr at a DAG cut vertex (incl. final op): myhash is a bijection;
    a cut slot v factorizes out = G(F(x)) with F,G necessarily bijective
    (every slot reachable from x => no downstream op bypasses the cut);
    shr-final F has range <= 2^31. Corollary used in z3 screens: every
    madd at a cut must have ODD K (P5-H's odd-K lemma generalized).
R1  fanout-1 same-type unary chains (madd-madd, shr-shr, xorc-xorc)
    compose to one op => the instance implies an <= 8-op form. Removed
    from the 9-op question, tracked as the (separate, smaller) n=8
    sub-question.
R2  fanout-1 xorc feeding shr or xor2: (v^C)>>s = (v>>s)^(C>>s),
    (v^C)^b = (v^b)^C -- instance-preserving map into the partner shape
    with xorc AFTER (partner remains enumerated). Canonical form: every
    fanout-1 xorc feeds a madd or is final. (P3-F XOR<->ADD lemma is why
    xorc can NOT be pushed past madd -- those shapes stay distinct.)
R3  xor2(v, xorc(v)) (and both-xorc-of-same-slot) = constant output =>
    <= 8-op family.
R4  xor2 absorbing an arg of its own xor2 argument (x^(x^w)=w) => <= 8-op.
Dedupe: exact lex-min topological canonicalization (ties branched),
validated against brute force at n=5 (3 strata, exact set match).

## 3. ENUMERATION FUNNEL (n=9, exact where stated)

- Raw typed sequences:                      514,896,782,400
- Valid (all ops live, output=slot9):         1,150,842,615  (exact DP)
- + K1 (#shr>=2):                               555,652,601  (exact DP)
- + final-op-not-shr:                           522,151,181  (exact DP)
- Canonical DAGs after K2+R1-R4+dedupe: materialized per stratum (DFS),
  top strata below; full per-stratum sequence-level DP table via
  `p5k_enum.py --strata` (84 strata with s>=2; s<2 killed by K1;
  x2=0 impossible: a 9-op unary-only program is a chain, chains need
  shr ops at cuts -> K2).

Exact cross-check: 522,151,181 = 522,140,619 (sum over the 84 x2>=1
strata) + 10,562 (x2=0 pure unary chains with #shr>=2, final!=shr --
ALL killed by K2: in a chain every shr is a cut). The DP and the strata
decomposition agree to the sequence.

Stratum ranking (closeness to real form: m in {3,4}, s=2, c in {1,2},
x2 in {2,3}): score-0 strata (3,2,1,3) 16.2M seqs, (3,2,2,2) 4.3M,
(4,2,1,2) 2.1M; score-1: (4,2,2,1) 185K, (4,2,0,3) 4.0M, (3,3,1,2)
2.7M, (2,2,2,3) 24.3M. Top-7 = 53,805,870 seqs = 10.30% of the
sequence-level space; unmaterialized tail = 468,334,749 seqs across 77
strata (all score >= 2, i.e. structurally farther from the real form).
Calibration: (4,2,2,1) -> 617 canonical shapes from 185K seqs (~300:1
crush). Top-7 strata enumeration RUNNING.

n=8 sub-question (where R1/R3/R4-killed shapes land; nobody owns it):
raw 8,172,964,800 -> valid 41,412,054 -> K1+final-not-shr 16,884,288
(= 16,881,066 over 56 x2>=1 strata + 3,222 chains killed by K2). Top
strata: (3,2,1,2) 356K, (3,2,2,1) 45K, (4,2,1,1) 22K seqs. An 8-op
find would be strictly stronger than a 9-op one; left open and priced
small (same crush ratio => ~10-30K canonical shapes in its top strata).

## 4. OWNERSHIP MAP (28 deletion templates + sandwich9 -> canonical)

sandwich9 (P5-I) == canonical [madd,shr,xor2(1,2),xorc,madd,shr,
xor2(5,6),xorc,madd] -- stratum (3,2,2,2). The p5i sigmaC form and this
are the same shape class under R2 (mask commutes out of the sigma).

P5-D's 16 UNSAT deletion templates: 10 REDUCE to <= 8 ops (degenerate;
explains their fast UNSATs), 6 map to 4 distinct canonical shapes
([0,2], [1,3], [0,4]==[0,5], [0,9]) -- these 4 canonical shapes are
CLOSED (P5-D's UNSAT is at full constant freedom).
P5-J's 12 OPEN deletion templates: DEL[4,6] branch=[1] REDUCES to 8 ops
(flag to P5-J: that z3 target is an 8-op question in disguise); the
other 11 map to 8 distinct canonical shapes: [2,3], [2,4]==[2,5],
[2,7], [4,7]==[5,7], [0,7], [2,9], [7,9], [4,9]==[5,9]. P5-J's queue is
really 8 shapes, not 12.

## 5. ENUMERATION RESULTS (materialized, 2026-08-02)

| stratum (m,s,c,x2) | seqs (DP) | canonical shapes | capped? |
|---|---|---|---|
| (3,2,1,3) | 16,191,760 | >200,000 | CAPPED at 8.3% of DFS (est. 1-2.5M total) |
| (3,2,2,2) | 4,257,510  | 22,416  | complete |
| (4,2,1,2) | 2,128,755  | 17,045  | complete |
| (4,2,2,1) | 184,905    | 617     | complete |
| (4,2,0,3) | 4,047,940  | 74,187  | complete |
| (3,3,1,2) | 2,707,360  | 16,487  | complete |
| (2,2,2,3) | 24,287,640 | 127,408 | complete |
Total materialized: 458,161 canonical shapes
(tools/p5k_shapes_n9.json, 49MB). Kill tallies across runs: R1 1.59M,
R2 2.13M, K2-cut 205K, dup 418K (sequence-level, cumulative).

PERFECT-TIER (score all-zero: m in {3,4}, s=2, >=2 sigma motifs, a path
through both shrs, maxfan<=2, c<=2, x2<=3): 808 shapes materialized,
of which 678 from the CAPPED stratum => **the perfect tier is NOT yet
complete**; completing (3,2,1,3) (Rust port or one long Python pass,
~40 min, keep only score-0) is the #1 follow-up.

## 6. QUEUE + NEW CLOSURES (tools/p5k_queue.json)

Queue: 3,005 entries = top-3000 ranked QUEUED + 11 owned + 2
forced-in owned (see below); statuses QUEUED / SCREEN-* / CLOSED-P5D /
OWNED-P5I (sandwich9, rank 328) / OWNED-P5J.

NEW STRUCTURAL CLOSURES of previously-open templates (no z3 needed):
- DEL[2,3] branch=[0] (one of P5-J's 12 OPEN): its canonical form has
  shr at a cut (out = G(madd(x)>>19)) => K2 kills it for ALL constants.
  P5-J's z3 TIMEOUT was chasing a shape that provably cannot work.
- DEL[4,6] branch=[1] (P5-J OPEN): REDUCES to 8 ops -- not a 9-op
  question at all.
- DEL[1,3] (P5-D UNSAT): has only ONE shr -- K1 explains the UNSAT.
P5-J's effective queue after P5-K: 7 distinct canonical shapes
(was 12 templates).

## 7. RESUME PROTOCOL (driver / P5-I)

1. **Complete stratum (3,2,1,3)** (the only cap): one long pass of
   `p5k_enum.py` with cap raised (est. 40 min Python; storage-filter to
   score-0 keeps memory sane) or a Rust port. Until then the perfect
   tier (808 known members) is a LOWER bound.
2. **P5-I generalization is the solver for the tier**: every score-0
   shape is madd/sigma-structured with 2 shrs; the window theorem
   (out_0 reads x mod 2^(pathshift+1)) and the row differentials apply
   per shape with the same soundness. Consume `p5k_queue.json` entries
   status=QUEUED in rank order.
3. z3 screening deeper into the queue only pays on madd-light shapes
   (the 4 UNSATs were the madd-degenerate prefixes); do not spend z3 on
   3-4-madd shapes at <600s.
4. n=8 sub-question unowned (counts in sec. 3); any R1/R3/R4-killed
   9-op instance lands there.
5. Vocabulary caveat stands (sec. 0): completeness is over the 4-type
   template basis; runtime binary add/mul/and/or joins are outside it
   (P5-B/P5-D MITM partially cover those for chain-decomposable shapes;
   P5-D Lemma A kills additive-shift links generally).
