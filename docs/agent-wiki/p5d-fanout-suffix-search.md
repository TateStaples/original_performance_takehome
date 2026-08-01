---
title: P5-D — fan-out suffix MITM, shape census, and CEGIS closures
date: 2026-08-01
type: research
status: partial
task: Search the fan-out-suffix hash-equivalence region P5-B named (9/10-op forms whose suffix reuses an intermediate), census the shape space, and CEGIS what enumeration cannot reach; k=9 is the whole game (k=10 dead per P5-E).
links: ["[[INDEX]]", "[[p5b-kf3-global-mitm]]", "[[p3f-hash-10op-question]]"]
---

# Verdict

**No 9- or 10-op form found; three new closures (one census, two proof-
grade); validated infrastructure + calibrated fleet protocol handed to the
driver.** The fan-out gap P5-B named is now (a) exactly quantified by an
exact shape census, (b) partially closed by a new validated searcher
(joined-kf3 family; slices running), and (c) closed at full constant
freedom for the 2-round boundary's own shape neighborhood (CEGIS UNSAT).

# 1. SHAPE CENSUS (exact DP, brute-force-validated n<=6)

`tools/p5d_census.py`. Model: op p reads a set of 1..3 runtime slots from
{x, t_1..t_{p-1}} (3 = madd), rest constants; output = last; everything
referenced. "Violation" = op not expressible as a chain link (unary-const
or sigma-pair); lv = last violation position. MITM-decomposable iff the
suffix after the forward-table reach is violation-free.

| n | total wiring shapes | P5-B (lv<=3) | P5-D join@4 (new) | kf4chained adds | unreachable by enumeration |
|---|---|---|---|---|---|
| 9 | 10,325,475,541 | 146 | 304 | 192 | 99.99999% |
| 10 | 1,145,484,095,402 | 236 | 494 | 312 | 99.99999% |
| 11 | 165,934,062,171,430 | 382 | 798 | 504 | ~all |

**Enumeration feasibility answer: NO.** The join-at-4 single-r family
(this strain's searcher) is the ENTIRE enumerable increment and it triples
P5-B's shape coverage; everything with a violation at position >=5 (of
which 13.8% are deep single-r joins, 86.2% multi-fanout/madd-fanout at
n=10) is beyond any table-based MITM. Caveat: classification is syntactic;
algebraic rewrites (xor commutes with shr, so sigma-triples fold into XsR
links with adjusted constants — exactly how the real 11-op form becomes
MITM-decomposable) make covered counts lower bounds.

# 2. fanout_mitm (new binary, VALIDATED)

`rust_harness/src/bin/fanout_mitm.rs` — global_mitm.rs machinery + the
join extension:

  [<=3-op FULL-shape DAG prefix; m = final; r = any runtime slot, and
   temps the DAG leaves dangling MUST become r] -> j = g(m,r) ->
  [solved xor/affine meet] -> [invertible pooled chain <= 6]

g vocab: basic {xor,add,sub,rsub}, ext {and,or,mul,4 runtime-shift forms},
maddk {m*K+r, r*K+m, 14 non-pool odd Ks x2}. g is forward-computed so it
need NOT be invertible. Joined tabs are keyed like P5-B fwd tabs; engine C
unchanged. Reach: 3+1+1+6 = 11 (wanted mask <=10; k=9 included).

**Selftest ALL PASS**: xor-join-at-4 plant found by joined-kf3 AND proven
invisible to the P5-B family (no-join control, 0 finds); r=x plant found;
dangling-temp-as-r plant found; 4-shard union preserves coverage.

## Two lemmas out of validation (both load-bearing)

* **Additive-shift lemma**: v+(v>>s), v-(v>>s), (v>>s)-v are NEVER
  bijective mod 2^w (exhaustive w=12; w=32 witnesses). Every unary link of
  a chain suffix of a bijection must be bijective => additive xorshift
  analogues are PROVABLY absent from all chain suffixes. (Their absence
  from all prior link pools was never a gap — now it's a theorem.)
* **Join-absorption lemma (Lemma B)**: an ADD-join adjacent to a madd
  folds into the madd's runtime addend slot and is already inside P5-B's
  kf3full closure (the selftest's negative control DISCOVERED this by
  finding the add-join plant through the no-join family). XOR-joins never
  absorb (P3-F XOR<->ADD lemma). Hence g=xor is the top-priority join
  tier, and g=add's new region is only its non-madd-adjacent placements.

## Calibration + slices (ledger in research/strains/p5d/STATE.md)

**Slice 0/16 (g=xor, r=all) COMPLETE: NEGATIVE** — 24,209,166 joined
prefixes x 2,118,524,244 chain nodes, 0 finds, 2207.5s (engine C 1459.5s
under kf4-grind contention). Slice 1/16 launched (pid 52883, log
research/strains/p5d/slice1.log) and HANDED TO THE DRIVER with the rest
of the fleet: 16 slices/g-tier, priority xor > add > sub/rsub > round12
r=y (calibrated: 4.15M entries per 1/48 shard, 92s build) > ext/maddk.
Recommendation: preempt the kf4chained grind (32 box-hours for xor+add
tiers vs 64 box-days, larger census class). A PROVEN-EMPTY registry for
cross-checking P5-H's STOKE finds is in STATE.md section 4b — any
stochastic find inside a closed family means a bug in one of the two
searchers.

# 3. CEGIS (z3 5.0, QF_BV) — `tools/p5d_cegis.py`

Soundness: UNSAT on sample constraints => template impossible globally
(samples are necessary conditions). SAT => constants verified OUTSIDE z3
(2^20 sweep + 10M random). TIMEOUT = OPEN, never closed. Width-reduction
laddering rejected as UNSOUND (right shifts break truncation mod 2^w).

Controls: full 7-op boundary-span template FOUND+VERIFIED (z3 discovered
an alternate constant family with multiplier -4097 = sign symmetry —
machinery proven end-to-end). Full 11-op hash template with 4 free
multipliers TIMEOUTs at 150s even with concrete shifts: z3 cannot decide
>=3 chained free 32-bit multipliers at this budget — madd-heavy 9-op
templates report TIMEOUT (=OPEN).

## Results

* **span7->5 CLOSED (UNSAT x10, priority-1 for the <=19 composite)**: all
  valid 2-deletions of the primed boundary span M(e,y') =
  stage1(stage0(sigma16(e)^y')) at 5 ops are UNSAT at FULL constant
  freedom. A 2-op/round boundary saving is the minimum useful step toward
  the 24->19 two-round composite; within the span's own shape
  neighborhood it does not exist. Combined with P5-B round12<=10 +
  span-depth-3 closures: the <=19 composite has NO known local entry
  point; only >=5-op nonlocal restructuring across >=3 stage groups
  remains, outside every available tool.
* **hash11->9 2-deletion family COMPLETE: 16 UNSAT, 12 TIMEOUT(=OPEN),
  0 FOUND** (32 variants cascade to !=9 ops, out of question). Pattern:
  every deletion touching a sigma's shift op (shr19/shr16) refutes fast
  (the tail goes affine); all 12 OPEN templates are exactly those keeping
  4 free multipliers. Per-template list in STATE.md section 4.
* **sandwich9 OPEN (the headline open question)**: the natural 3-madd 9-op
  shape madd/sigmaC/madd/sigmaC/madd (not a deletion of the real form,
  all 10 constants + 2 shifts free) TIMEOUTs at 424s — undecided. This is
  the most plausible 9-op candidate shape and the top target for a longer
  z3 run and for P5-H's STOKE search.

# COVERAGE MAP (fan-out region, before -> after P5-D)

| region | before | after |
|---|---|---|
| shape-space quantification | "a gap exists" (P5-B prose) | exact census, enumerable increment identified |
| join-at-4 single-r shapes | 0 searched | searcher validated; g=xor slices running (ledger) |
| additive-shift chain links | unexamined | provably impossible (lemma) |
| 2-round boundary at -2 ops, free constants | unsearched | UNSAT-closed |
| deep joins (lv>=5), multi-fanout | unsearched | still open — provably beyond enumeration; CEGIS only touches templates near the known form |

# Honest not-covered list

(i) joined-kf3 slices beyond those in the ledger (fleet protocol
published); (ii) g=ext/maddk tiers; (iii) round12 r=y (nv-fanout) beyond
calibration; (iv) joins at position >=5 with DAG prefix >=4 (needs
kf4full tables — memory wall) or double-joins (quadratic engines);
(v) madd-heavy 9-op CEGIS templates (z3 TIMEOUT = OPEN); (vi) 9-op shapes
unrelated to the real form's neighborhood — the census says 1.03e10
wiring shapes exist at n=9 and nothing reaches them exhaustively.

# FLOOR IMPACT

None realized (no find). If the fleet's g-tiers finish negative and the
madd-necessity proof (P3-F next-step 3) lands, the k=9 route dies inside
all searched families and 889/904 would require the nonlocal-composite
region nothing can search — at that point the honest statement is
"frontier methods are outside op-identity space entirely" (consistent
with P5-B's R2). A 9-op find would floor 857-868 no-idx / 874-885
with-idx (coordinator's corrected 68 cyc/op arithmetic).
