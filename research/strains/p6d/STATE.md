---
title: P6-D — the differential-count theorem, extended to EVERY K2 parity
date: 2026-08-02
type: research
status: final
task: recover P5-I3's 324 "fail-transfer-on-technicality" shapes (251 cut-test
      failures + 73 even-K parity-split failures), derive the even-K2 statement
      with proof + guards, mass-apply over the p5k queue, and report the new
      kill fraction
links: [[../p5i/STATE.md]] [[../p6c/STATE.md]] [[../../RESEARCH.md]]
---

# Strain P6-D — theorem coverage, not solver engineering

status: DONE. **All 324 shapes recovered** (100%: 251 + 73 -> 354 total
transferring shapes, up from 30). The recovery is real but the *price* is real
too: for the 314 shapes whose K2 parity is genuinely free, the even branches
re-open 177 of the 435 shift pairs, so a recovered shape kills 610/961 rather
than the 787/961 a forced-odd shape kills.

    queue kill fraction   46.85% (P6-C, window only)  ->  49.23%
    residual              1,526,118 instances         ->  1,457,792  (-4.5%)

Tools (all new, read-only w.r.t. the repo): `tools/p6d_census.py` (reason
tally), `tools/p6d_probe.py` (why the 73 fail), `tools/p6d_algebra.py`
(THEOREM P6D-1 + numeric guards), `tools/p6d_extend.py` (extended transfer
test), `tools/p6d_forced.py` (CHAIN-T6b + the even-K2 bijection probe),
`tools/p6d_filter.py` (extended realizability filter + queue mass sweep),
`tools/p6d_planted.py` (SELFTEST-PLANTED for the extended filter).

## 0. What the two buckets actually were

`tools/p6d_census.py` reproduces p5i sec.13's tally exactly
(2242 / 408 / 251 / 73 / 1 / 30). `tools/p6d_probe.py` then shows the 73 are
**not a separate phenomenon**: in all 73, shr-B's input slot is a `xor2`, so
p5i3_transfer's `k2_madd = next(k for k in madds if k+1 == e_slot)` returns
None, the K2 madd is therefore swept into the "other madds" parity split, and
its even branch hits the interpreter's lossy even rule -> TOP. Both buckets ask
one question: **what is the differential count when K2 is EVEN?**

## 1. THEOREM P6D-1 (unified count; sec.9 is its v = 0 slice)

Notation as p5i sec.9: u = w-1-s1 >= 1, t = s1+s2-(w-1) >= 1, s2 = u+t <= w-2,
c the value feeding the single madd (K2,C2) reaching shr B, x -> c bijective
(T6a), e = K2 c + C2.

First, the *differential* never used K2's parity:
  c* - c = 2^(w-1) + sg 2^u exactly (sg = 1-2c_u); e* - e = K2 2^(w-1) +
  sg K2 2^u, and the first term is 2^(w-1) (K2 odd) or 0 (K2 even) — either
  way invisible below bit w-1, hence at bit s2 <= w-2. So for ANY K2,
      D = K2_t ^ [A+q >= 2^t]  (c_u=0),   K2_t ^ [A < q]  (c_u=1),
      A = bits u..u+t-1 of e,  q = K2 mod 2^t,  K2_t = bit t of K2.
Only the COUNT changes. Let v := v2(K2), k := K2>>v (odd), C' := C2>>v,
M := #{c : D ^ K2_t = 1}; N = M or 2^w - M according to K2_t. Then

    v >= t :  q = 0, D = K2_t is CONSTANT, M = 0, N in {0, 2^w};
    v <  t :  M = 2^(w-t+v) (q'-1) + 2^(w+1-s2+v) n_1,
              q' := k mod 2^(t-v)  (ODD),
              n_1 := #{c_lo < 2^u : bit_u(k c_lo + C') = 1}  in [0, 2^u].

**Substituting (t, q, C2) -> (t-v, q', C2>>v) and scaling by 2^v is the whole
even-K2 correction.** v = 0 reproduces sec.9 verbatim.

Proof (full text in `tools/p6d_algebra.py`'s module docstring). Write
C2 = 2^v C' + r, r < 2^v; then e = 2^v s + r with s = (k c + C') mod 2^(w-v).
(1) REDUCTION: with A = A_lo + 2^v A_hi (A_lo = bits u..u+v-1 of e < 2^v) and
q = 2^v q', A+q >= 2^t <=> A_hi + q' >= 2^(t-v), and A < q <=> A_hi < q'. So D
is sec.9's differential at parameter (t-v, q') read from bit u+v.
(2) LOW BIT: bit_{u+v}(e) = g(c_lo) ^ c_u with g(c_lo) = bit_u(k c_lo + C')
— the c_u term 2^(u+v) k c_u contributes exactly c_u at bit u+v (k odd) and
carries nothing below it.
(3) HIGH BITS: bits u+v+1..u+t-1 of e are exactly uniform over c_hi (k odd),
2^(w-s2+v) values of c_hi per residue.
(4) COUNT: sec.9's alpha/beta computation at (t-v, q') gives
M = 2^(w-s2+v)[2^u (q'-1) + 2 n_1] = 2^(w-t+v)(q'-1) + 2^(w+1-s2+v) n_1. QED

> **DEAD END, recorded so nobody re-derives it.** The natural first guess —
> "for even K2 both sg-classes see the same low part of A, so alpha+beta is
> constant and M = 2^(w-t) q" — is FALSE. Bit u+v of A still depends on c_u
> (step 2); only bits u..u+v-1 lose the dependence. The false version predicts
> the wrong 2-adic valuation and would have over-killed. The w=14 FORM guard
> catches it immediately.

### COROLLARY P6D-2 — sec.9's divisibility needs T6a but NOT T6b

v2(M) >= min(w-t+v, w+1-s2+v) = w+1-s2+v >= w+1-s2 (u >= 1), so

        N == 0  (mod 2^(w+1-s2))   for EVERY K2, of either parity.

So the whole s2 <= 14 mass kill (33-s2 > v2(N_myhash) = 18) transfers to every
shape satisfying T1-T5 + **T6a alone**. T6b's only job was to pin K2's parity.

### COROLLARY P6D-3 — the extended filter

At w = 32, N = 2^18 A with A in {8289 (branch N=M), 8095 (branch N=2^32-M)}:
2^(33-s2+v) | N forces **v <= s2-15** (hence s2 >= 16 for any even branch), and

    Ntilde_v = A 2^(s2-15-v) = Ntilde_0 / 2^v,  n_1 = Ntilde_v mod 2^u,
    Q = Ntilde_v >> u,  q' = 2Q+1 < 2^(t-v)   (+ the n_1 = 2^u boundary case)

which is p5i sec.12's arithmetic with t -> t-v. Since n_1 counts
bit_u(k c_lo + C') with k ODD and C' free, **sec.12's realizability theory
(sliding half-circle window, descent lemma, m(k,u)) applies verbatim** with
LB = lower_bound_m(u, t-v, q'). A pair is ALIVE iff some v in 0..t-1 and some
N-branch survives.

### ROW-31 (p5i sec.2) also transfers at every parity

At t = 0 the theorem degenerates to M = 0, i.e. D is CONSTANT: sec.2's
"e_{s2} always flips" (D = 1, N = 2^w) is the K2-odd case; for even K2
K2 2^u = 0 mod 2^(u+1) so D = 0 and N = 0. Either way N in {0, 2^w} =/=
N_myhash. Guarded (below). So the 30-pair row s1+s2 = 31 dies for all 354.

## 2. CHAIN-T6b — 9 shapes are forced-odd after all

If shr-B's input slot E is a DAG cut **and** E is reached from the K2 madd's
output by single-input ops (xorc/madd) only, then F: x -> E is bijective and
F = g o madd_K2 o h with h = (x->c) bijective. An even chain madd would make g
non-injective, so g is bijective and madd_K2 = g^-1 F h^-1 is bijective =>
**K2 ODD**. p5i3_transfer's T6b is the chain-length-0 special case; extending
it to xorc chains moves 9 of the 73 back into the forced-odd class (they keep
sec.12's 113-alive verdict, i.e. 787/961 killed).

**The remaining 63 xor-join shapes are genuinely free-parity** (E = xor2(bypass,
e), cut but not chain-reachable): `tools/p6d_forced.py` searched for constants
with EVEN K2 making x -> E bijective and **found a witness for every one of 4
sampled shapes** (ranks 226, 653, 485, 74; v = 4,8,6,5 at w=10). So there is no
hidden parity-forcing lemma there. Lead closed.

## 3. GUARDS (all 0 violations)

| guard | what it checks | scale | result |
|---|---|---|---|
| GUARD-EVEN w=12 sand9 | N in {M, 2^w-M}, M by P6D-1; N == 0 mod 2^(w+1-s2) | 135 trials, v2 = 1..10 | DIV 0, FORM 0 |
| GUARD-EVEN w=14 sand9 | same | 264 trials, v2 = 1..12 | DIV 0, FORM 0 |
| GUARD-ODD w=14 sand9 (control) | v=0 slice must reproduce sec.9 | 264 trials | DIV 0, FORM 0 |
| GUARD-EVEN w=14, **12 recovered queue shapes** (6 cut-bucket + 6 even-bucket) | same | 198 trials each = 2,376 | DIV 0, FORM 0 |
| GUARD-MIXED w=14, 10 recovered shapes | EVERY madd gets a random valuation: N in {M, 2^w-M} or N in {0,2^w} | 264 each = 2,640 | DIV 0, FORM 0 |
| GUARD-T0 w=14, 7 shapes | row-31: any parity => N in {0, 2^w} | 96 each = 672 | DIV 0, FORM 0 |
| **SELFTEST-PLANTED-EXT** w=14 | plant even-K2 constants, brute-force the true N, filter must say ALIVE | 264 planted instances | **VIOLATIONS 0** |
| TEETH w=14 | fraction of legal N killed | 41,028 (N, s1, s2) | odd-only **13,424 = 32.7%** (exactly p5i3_planted's figure — cross-checks the width-w reimplementation), any-parity 8,690 = 21.2% |
| CONTROL v=0 vs `p5i3_arith.decide_pair` | 435-pair grid | 435 | 0 mismatches (113 alive both ways) |
| CONTROL window sweep | reproduce P6-C sec.3 | 2,988 shapes | **1,345,350 exactly** |

## 4. Revised transfer conditions

T1-T5 unchanged. T6a (x -> c bijective) unchanged and **still not optional**
(p5i sec.13's rank-2953 counterexample stands; `p6d_extend` re-checks it *per
parity assignment* — an even madd inside c's cone destroys bijectivity, so such
an assignment is only accepted when the abstract state is constant).
T6b is **replaced**:

  T6b' (was T6b): if CHAIN-T6b holds, K2 is odd and only v = 0 is admissible
       -> sec.12's verdict (113 alive over the 435-pair grid, 174/961 open).
  T6b'' (new): otherwise both parities are admissible -> the union over
       v = 0..t-1 (290 alive over the 435-pair grid, 351/961 open).

`tools/p6d_extend.py extended_transfer()` implements this; over the 3,005-entry
queue it returns **354 shapes (30 old + 324 recovered), 0 lost**.

## 5. LEDGER

Shift-space per shape (of 961 assignments):

| class | shapes (of the 2,988 open) | window | row-31 | diffcount | killed | open |
|---|---|---|---|---|---|---|
| forced-odd (CHAIN-T6b) | 38 | 435 | 30 | 322 | 787 | 174 |
| free-parity | 314 | 435 | 30 | 145 | 610 | 351 |
| no transfer | 2,636 | (per-shape 435..900) | - | - | - | - |

Instance ledger over P6-C's universe (2,988 open shapes x 961 = 2,871,468):

    window theorem (P6-C baseline)          1,345,350   46.85%
    + P5-I3's 30 shapes, fully applied        +10,208   47.21%
    + P6-D extension (324 recovered)          +58,118   **49.23%**
      (= 9 chain-recovered x 352 + 314 free-parity x 175)
    residual needing a solver     1,526,118 -> 1,457,792   (-4.5%)

Rescaling P6-C sec.4's projection by the residual: decidable harvest ~60
CPU-days (was 63), with-timeouts ~15.3 CPU-years (was 16), still ~28% of the
queue undecidable. **P6-C's strategic conclusion is unchanged: per-pair
decision cannot close the queue.** The extension is a real but sub-linear
multiplier — the binding constraint is that only 354/2,988 = 11.8% of shapes
have a sandwich pattern at all.

QUEUE STATUSES: **deliberately not edited**, same reasoning as P5-I3/P6-C —
174 (resp. 351) shift assignments survive on every transferred shape, so no
shape is CLOSED and flipping a status would silently retire an open shape.

## 6. Sandwich9's 68 open pairs: NOTHING NEW

sandwich9 is CHAIN-T6b forced-odd (E is the K2 madd's own output and is a cut),
so only v = 0 is admissible and the extended filter collapses to sec.12 exactly
(the v=0 control confirms: 0 mismatches). The unified theorem's new content is
entirely in the v >= 1 branches, which sandwich9 cannot use. **The 68 open
pairs are untouched; no new theorem applies to them.** p5i sec.13's standing
recommendation (a statistic keyed on a SECOND output bit, out_1, whose
differential brings in K3's carry structure) remains the open axis.

## 7. Resume protocol

1. **out_1 / second-bit statistic** — still untried, and now it would apply to
   354 shapes rather than 30. Highest EV remaining in this line.
2. The 408 "x->c not syntactically bijective" shapes are the last unrecovered
   bucket. `bijective_cone` is *syntactic*; some of those cones may be
   bijective for semantic reasons (e.g. xor2 of two shifted copies). Worth a
   census before assuming they are unreachable.
3. Do NOT re-derive: the naive even-K2 guess (sec.1 box), the mirror theorem
   (p5i sec.10, vacuous tier-wide), a parity-forcing lemma for the 63 xor-join
   shapes (sec.2, witnesses exist).
