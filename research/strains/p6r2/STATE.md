# P6 R2 — ROUND-0 DOMAIN-RESTRICTED HASH (30-bit input domain)

Date: 2026-08-02.  Tool: `tools/p6r2_domain_cegis.py` (selftested: myhash ==
frozen HASH_STAGES on 2k probes; numpy ref checked; full-2^30 verifier passed
positive AND negative controls).

## 1. The domain, verified from source

`tests/frozen_problem.py` (== site problem.py per P6-A):
- `:417` tree node values = `randint(0, 2**30 - 1)` -> every nv < 2^30
- `:434` all walkers start at index 0 (root)
- `:435` initial values = `randint(0, 2**30 - 1)` -> val0 < 2^30

=> round-0 hash input x = val0 ^ root_nv < 2^30 (bits 30,31 zero), for all
32 round-0 group-rounds.  **Round 11 does NOT qualify**: walkers wrap back
to the root (uniform depth), nv is 30-bit, but val is a full-width 32-bit
hash output — the xor is full-width.  Only round 0 = 32 of 512 group-rounds.
Outputs stay full 32-bit (they feed round 1): only the INPUT domain shrinks.

Soundness of the search: all z3 samples drawn from [0, 2^30); UNSAT on
in-domain samples refutes the restricted claim (no epsilon anywhere).  SAT
candidates would be verified by exhaustive 2^30 numpy sweep before FOUND.
Conversely NONE of the full-domain negatives transfer here automatically
(their sample sets included out-of-domain points), so every shape below was
genuinely re-opened and re-decided.

## 2. Structural theorems re-derived on the 30-bit domain (`lemmas` battery)

| filter | full-domain status | 30-bit-domain status |
|---|---|---|
| zero-shr forms | dead (triangularity) | **DEAD** — in-domain witness: myhash(0)&1=1, myhash(2)&1=0 |
| one-shr, s<=28 | dead (bit-window) | **DEAD** — in-domain window witnesses found for every s in 1..28 |
| one-shr, s in {29,30,31} | dead via x vs x^2^31 probe (INVALID here) | **DEAD by a NEW counting leg**: in a one-shr DAG every out bit i is a function of (x mod 2^(i+1), w) with w = h(x)>>s taking <= 2^(32-s) values, so low-(33-s)-bit output patterns per residue class are capped at 2^(32-s); measured 9>8 (s=29), 5>4 (s=30), 3>2 (s=31) with in-domain probes |
| **MINIMUM-SHR (>=2 shrs)** | proved | **HOLDS on the domain** (all three legs above) |
| K2 cut-bijectivity (cut shr dead) | any s | **WEAKENS**: myhash is injective on the domain (2^30 outputs), so cut shr s>=3 dead by counting; **s in {1,2} at a cut is no longer killed** |
| differential-count theorem (s2<=14 sandwich9 kills) | proved | **INVALID** (probes x^2^31 out of domain) — those pairs re-open, see sec. 4 |

## 3. Prefix-cut route: CLOSED COMPLETELY

If a 10-op form keeps the real form's cut at c = sigma19C1(stage1(x)), the
saving must come from a <=3-op prefix agreeing with
`prefix_ref(x) = (v ^ C1) ^ (v>>19), v = x*4097 + C0` on [0, 2^30) — the one
sub-function whose input IS the restricted operand.
- prefix2 (10 templates, all-slots-used, dedup): **10/10 UNSAT**, all <1s.
- prefix3 (57 templates): **56/57 UNSAT** (nearly all <1s), 1 timeout
  closed by theory: `madd-shr-madd` is a pure chain, the shr is a cut;
  prefix_ref is injective on the domain (bijective stages) so s>=3 dies by
  counting (2^(32-s) < 2^30), and s in {1,2} dies by window witness
  x=0x1cf3c95b, x'=0x37685253 (agree mod 8, prefix bit0 differs).
=> **no cut-preserving 10-op form exists on the domain.**  Any domain-
restricted <=10-op form must restructure across the sigma19 boundary.

## 4. Whole-shape CEGIS verdicts (free constants unless noted)

DEL1 = one op deleted from the real 11-op form (10-op shapes; xor2
deletions cascade to 9):

| shape | verdict | evidence |
|---|---|---|
| del0 (first madd) | **UNSAT** | 42s, in-domain samples |
| del1 (first shr) | **UNSAT** | 0.0s (one-shr, matches lemma) |
| del2 (xorc u) | OPEN | timeout 60/240/500s free; 90s with s=(19,16) fixed |
| del3 b0 (xor2 c -> t), 9op | OPEN | timeout 63s free, 90s fixed |
| del3 b1 (xor2 c -> u), 9op | **UNSAT** | 1.6s |
| del4 (madd p) | OPEN | timeout 60/240s free, 90s fixed |
| del5 (madd q) | OPEN | timeout 60/240s, 90s fixed |
| del6 b0 (= sandwich9), 9op | OPEN | see pair scan below |
| del7 (madd e) | OPEN | timeout 60/240s, 90s fixed |
| del8 (second shr) | **UNSAT** | 0.0s (one-shr, matches lemma) |
| del9 (final xorc) | OPEN | timeout 60/500s free |

DEL2 (two ops deleted, <=9-op shapes, 25s quick pass over all 45 pairs):
**29 UNSAT, 20 TIMEOUT-open** (per-shape log in the session transcript;
rerun: `python3 tools/p6r2_domain_cegis.py del2 550 25 "<pairs>"`).

SANDWICH9 on the domain (madd/sigmaC/madd/sigmaC/madd, shifts fixed):
- **(19,8) UNSAT 0.5s** — note s2=8 <= 14: on the full domain this pair was
  killed ONLY by the (domain-invalid) differential-count theorem; here it
  dies directly and soundly on in-domain samples.
- **(12,16) UNSAT 0.4s**.
- (19,16), (19,14), (19,12), (16,14): timeout 85s — OPEN.
- free-shift run: timeout (matches the P5 z3 wall; refutation is
  cheap-or-never).

**ZERO SAT / ZERO FOUND anywhere.**

## 5. The prize, re-derived honestly (p3c_design_cost deltas)

Saving k ops on round 0 only = 32 group-rounds x k vec-ops = 32k vec-ops
off HASH_VEC (5808).  Frontier re-enumerated with patched HASH_VEC:

| k saved (round 0) | as-built frontier | best-case frontier | vs shipped design |
|---|---|---|---|
| 0 | 964.8 | 946.0 | — |
| 1 (10-op form) | 962.0 (**-2.8**) | 943.2 (**-2.8**) | -4.3 (compute-bound) |
| 2 (9-op form) | 958.7 (**-6.0**) | 940.9 (**-5.1**) | -8.5 |
| 11 (round-0 free, ceiling) | 934.0 (**-30.8**) | 915.8 (**-30.2**) | -46.9 |

Corrections to P6-A's figures: the ~8.5-cyc "realistic" and 47-cyc ceiling
assumed the compute floor (60 lane-ops/cyc) binds; at the OPTIMAL frontier
designs the binder is flow/load and the frontier re-optimizes (serves more
L4), so the census-level prize is **2.8 cyc for a 10-op form, 5.1-6.0 for a
9-op form, ~30 ceiling**.  The larger 4.3/8.5 numbers apply only against
today's compute-bound shipped schedule.  Round-11 inputs are full-width, so
no doubling.  Note k=2 at best-case coefficients grazes 940.9 — even a 9-op
round-0 form would NOT reach 940 on its own at the census level.

## 6. Verdict

**PARTIAL (no find, substantial sound closures, question narrowed).**
- A <=10-op domain-restricted form is REFUTED for: all zero/one-shr shapes
  (any s), the entire <=3-op-prefix route, 4 of 11 del1 variants, 29 of 49
  del2 variants, sandwich9 pairs (19,8) and (12,16).
- OPEN (z3 wall, TIMEOUT never treated as closed): 7 del1 variants, 20 del2
  variants, sandwich9 s2>=12 pairs tried, free-shift sandwich9.
- The domain restriction is REAL as a re-opener (full-domain kills provably
  do not transfer; (19,8) had to be re-killed) but produced zero SAT in
  every family searched, and the sound prize even on success is smaller
  than charter estimates (2.8-6.0 cyc at the frontier).

Rerun commands: `selftest | lemmas | del1 | del2 | prefix2 | prefix3 |
sw9pairs | sw9free` (see module docstring).
