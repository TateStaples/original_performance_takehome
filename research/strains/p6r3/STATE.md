# P6-R3 — served-level-local conjugation family: DEAD BY REDUCTION

status: FINAL (2026-08-02). Verdict: **DEAD — the family collapses by seam
cancellation to the already-searched boundary-segmentation space; no member
can beat the 11-op round body unless the untransformed 10-op question is
already answerable, and the two nontrivial members put through the machinery
are locally UNSAT everywhere with floors 5 ops short.**

Tools: `tools/p6r3_family.py` (formalization + bit-exact verification + cost
tables; ALL PASS), `tools/p6r3_cegis.py` (z3 CEGIS member verdicts, planted
positive control FOUND+verified 2^20+10M).

## 1. Family definition (formalized)

Carried representation w = phi(v) across a contiguous span of SERVED rounds
(r in {0..4} and {11..15}; 10 of 16 rounds), phi GF(2)-linear invertible,
**round-varying phi_r allowed**. With the proved decomposition
H = X_C5 ∘ S ∘ Q (S = sigma16 layer, 2 ops; Q = 8-op core madd4097 |
shr19,xor2,xorcC1 | madd33,madd512,xor2 | madd9; fold = 1; total 11):

- interior round:  w' = A(Q(X_n(B(w)))),  A = phi_next∘S,  B = phi_r^{-1}
- entry round (gathered/memory predecessor): B = I, cost 9 + c(A)
- exit round (gathered/memory successor):    A = S, cost 11 + c(B)
- node table: n -> phi(n) (+ c5-style constant merges) — linear phi is
  FORCED by the fold-in xor (non-linear phi cannot transform the table;
  mult-by-odd-K phi additionally fails affinity on 100% of samples,
  P5-L 3.2, and pays +2 explicit ops/round)
- parity/position machinery: idx' consumes bit0(v') = row0(B)·w'. Free iff
  row0(phi^{-1}) = e0 (**C_par class**: all left-shift xorshifts qualify;
  all right-shift xorshifts fail) or iff the tap shares the next round's
  B-computation (phi = S). Else +<=2 ops/gr. The index recurrence itself is
  untouched (it consumes one bit).

Bit-exact verification (`p6r3_family.py`): the conjugated construction on
the real 16-round schedule reproduces reference values AND the full parity
stream for phi in {sig16r, sig19r, sig16l, sig3l, sig12l, sig3l∘sig16r},
200 walks x 16 rounds each, PASS.

## 2. Absorption cost table (deliverable a)

| boundary | seam | runtime cost | one-time setup |
|---|---|---|---|
| served->served (interior) | B∘A = I — **cancels** | 0 (optimal impl computes S directly; w never materializes) | served tables: 31 nodes = 4 vec x c(phi) vec-ops, ~<=16 vec-ops ~ 2.7 cyc total |
| gathered->served (entry) | A alone | +(c(A)−2) ops/gr | same table setup |
| served->gathered (exit) | B alone | +c(B) ops/gr | — |
| gathered->gathered | phi = I forced | 0 | transport DEAD: 2,047 nodes = 256 vload + 256·c(phi) valu + 256 vstore; **load/store-slot floor 128 cyc/pass vs total prize <=70 cyc** — loses before valu cost is even counted |
| initial load / final store | entry/exit class | +(c(A)−2) / +c(B) | output must be exact plain v |
| parity tap | row0(B)·w' | 0 if C_par or shared-B; else +<=2 ops/gr | — |

Entry+exit sum per span = (c(A)−2) + c(B) >= 0, equality iff phi in {I, S}.

## 3. Why no member can be shorter (deliverable b) — three results

**(R1) Seam cancellation / segmentation invariance.** At every interior
served->served seam, B∘A = phi^{-1}∘phi = I exactly (numerically verified
per phi). The optimal implementation never materializes w: the concatenated
multi-round op chain is IDENTICAL to baseline for EVERY linear phi,
round-varying included. The only surviving family parameter is the **cut
placement** of the circular 11-op chain — precisely the space already
searched by H-016 (MITM over all 10 boundaries, 2.36T), H-025 (full-hash
MITM 2.9T), G-10 (per-segment exhaustive), P5-B's f2ap/e2xw (the two 4-op
cross-round spans, <=3 full-forward, finds=0), and P5-D/L span7->5/->6 (all
UNSAT). **A phi-conjugated win would BE one of those cuts.** Conjugation is
not a new search space; it is a re-parameterization of the old one.

**(R2) Decomposable floor.** Interior round = 1 + 8 + c(A) + c(B). Any
nontrivial GF(2)-linear map costs >=2 in the machine vocabulary (no 1-op
invertible linear map exists; sigma floor = 2, P5-L2 d), so
c(A)+c(B) >= 2 with equality only on the trivial orbit phi in {I, S}
(floor 11 = baseline). For every other single-xorshift phi, A = phi∘S is a
2-layer product (c=4 exact for sig19r∘S, P5-L2 3.1; for left-phi products
c<=4 by factoring and c>=3 since the mixed-support matrix is no one-sided
I+S_j) => **floor 14-15, i.e. 4-5 fused ops needed to reach 10, where the
two local fusion channels can supply at most 2 combined — and the sweeps
below show they supply 0.**

**(R3) Novelty audit (per mission instruction).** P5-L2's mechanism (b)
assumed "no adjacent sigma pair exists"; conjugation CREATES the adjacency
phi∘S — but (R1) shows the created adjacency is exactly compensated at the
next seam; nothing leaks. P3-F's xor-const conjugation closure (no xor
crosses a madd) is the affine part of this family and stays binding: the
fold-in and ^C1 survive in every member. The one genuinely new object is
the DRESSED span family {A∘(tail), (head)∘B} for chosen phi — new MITM
targets never searched — and those are what the member runs close below.

## 4. Member verdicts via machinery (deliverable c)

Positive control: planted 3-op form under the same shape family — **FOUND
and verified 2^20+10M** (via the known y=2^31 xor/add exception: K=1,
C=2^31). The machinery can find what exists.

| member | phi | floor | local channels tested | result | verdict |
|---|---|---|---|---|---|
| M1 | S = sig16r (and I): trivial orbit | 11 (needs 1) | = the untransformed 10-op question | f2ap/e2xw <=3 finds=0 (P5-B, full forward); span7 rigid at 7 (P5-D/L); H-016/H-025 | **DEAD to prior depth — not a new target** (R1) |
| M2 | sig16l (C_par, involution) | 15 (needs 5) | head madd4097(sig16l(w)^n) 4->3: **ALL 1,281 3-op shapes** in REAL_11 vocab, free constants: 124 live after dead-code pruning = 48 analytic (single-shr image deficit vs bijective target) + **76 z3 UNSAT, 0 timeouts**. tail sig16l(sig16r(9h+C4)) 5->4 deletion family: del0 UNSAT, del2b1 ANALYTIC (all h-paths cross the shr => image <=2^31 < bijective target), rest degenerate | max local supply 0 of 5 | **DEAD** |
| M3 | sig3l (C_par; all three multipliers 4097,33,9 ≡ 1 mod 8, the top-bit-lemma-friendly choice) | 15 (needs 5) | head 4->3: same ALL-shapes sweep, 76 z3 UNSAT + 48 analytic, 0 timeouts. tail 5->4: same deletion closure | max local supply 0 of 5 | **DEAD** |

## 5. Coverage limits (stated, per project discipline)

- Head sweeps are exhaustive over ALL 3-op shapes in the vocabulary
  {madd, shr, xorc, xor2} with all constants free (the vocabulary of every
  known form; `//`,`%`,`cdiv` closed definitional by P3-F). Tail closures
  are deletion-family (P5-L 3.4b precedent), not all-4-op-shapes.
- Non-local >=3-op restructurings of a dressed body remain formally open —
  but that is the standing (S)-gap, and by (R2) the conjugation family needs
  MORE of it (5 ops) than the untransformed question does (1 op): the family
  is strictly dominated. Any non-local miracle would rather be spent on the
  raw form.
- (R1) makes the family's interior EXACTLY baseline, so no depth of member
  search can ever beat prior art there; only entry/exit dressings were new,
  and they only ADD cost.

## 6. Bottom line

The ~2-cycle served-local overhead estimate from the charter was right but
moot: the family cannot produce a saving to spend it on. **Cycles gained:
0. The (S)-gap remains the sole live premise, unchanged by this strain.**
The one reusable positive: the served-table transform trick (4 vec x c(phi)
setup) and the C_par classification are now on record for any future
representation-change idea — any future phi-like proposal should be checked
against (R1) seam cancellation FIRST before funding any search.
