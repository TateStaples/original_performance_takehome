# P5-E: the k=10 rescue hedge — trim census for D1'/D2'

Status: FINAL
Task: enumerate/cost every legitimate vec-op of support trim for a 10-op-hash
design; deliver full k=10 censuses vs 904 (with-idx) and 889 (no-idx) with a
PASS/FAIL verdict, plus the k=9 stacking margin.
Tool: `tools/p5e_trim.py` (reproduces P5-C's 902/918/859/875 in calibration
section A, then reprices with the ledger below).

## VERDICT

**k=10 FAILS both boards, decisively.** Even granting every trim on the
ledger including the speculative ones and the optimistic ring re-mine, the
best-case floors are **902 (no-idx, target 889) and 919 (with-idx, target
904)** — short by 13/15 at FLOOR level, i.e. before any regret. With the
11-15-cycle regret allowance the realized miss is 24-37 cycles. The honest
EXPECTED floors are **909 / 926** (worse than P5-C's un-trimmed 902/918,
because the costs P5-C's floors omit exceed all trim found). The ~170-vec-op
supplier does not exist in this space.

**k=9 survives honest repricing**: floors 857-868 (no-idx) / 874-885
(with-idx), realized 868-883 / 885-900 → clears 889 by ~6-21 and 904 by
~4-19. The margins are REAL but roughly half of P5-C's quoted 29-30.

## TRIM LEDGER (lane-ops, vs the POOL0=53,286 decomposition of p5c_frames.py)

What POOL0 already contains (so NOT harvestable again — this was the main
double-count audit): T1 free-form folds, T2 ring at **100% coverage**, T3
add_imm→alu, index at the derived optimum 5,960 (44 idx-madds already
valu-spelled), setup at the aggressive ~580, the 382-lane round-15 fold
penalty. Sources: P3-A C1\* definition, P3-D joint census 56,654 @945,
p5c_frames.py header.

| line | lanes (n=14 / n=11 serves) | status / source |
|---|---|---|
| T-omf: each serve-more gr deletes its gather's omf select (F+14n not 15n) | −112 / −88 | DERIVED (P3-B: idx_selects = g exactly). RISK: may double-count against P3-C's coupling cancellation for round-4 serves; dropping it costs +1-2 cycles |
| T-c5: round-4 serves make the group's round-3 trailing ^C5 elidable (prexored L4 broadcast table) | −88 / −64 | DERIVED this session from c5_prexor mechanics (perf_takehome.py:407-409, :1035, :1085) |
| T-idx15: the 3 remaining round-15 L4 serves, −3 madds each | −72 | MEASURED rate (p3d_attrib: −632/26 gr = −24.3/gr) |
| T-dual: w_fold re-tune recovers part of the round-15 fold penalty inside POOL0 | −210..−296 | SPECULATIVE (P3-D: +296 of +488 on dual_fold rows; "recovering ALL still gives 942" = ~−210; never re-tuned) |
| Round-0/round-11 specialization (brief item 1) | **0** | DERIVED, see §Round-0 below |
| C1 idx-madd respell / T1 race_sel sub removal / T3 / setup trim | 0 | already inside POOL0 (audit above) |
| k=10 scratch → ring coverage (brief item 5) | ~0 (≤−40) | DERIVED: k=10 frees ≤1 transient temp vector × ≤32 in-flight groups = ≤32 words = 1.3 rings of the 573-word deficit to 100%; coverage 62.5→≤64.5%, residual −5 vec. Peak hash liveness (p,q pair at the s2s3 fused stage) likely unchanged anyway |
| with-idx writeback: P5-A's 808-lane tail | REJECTED, use 1,568 | P5-A §1 assumed pos4 from the packed accumulator; T2 deletes it. All 32 round-15 groups are served in D1', so pos4 must be packed from raw parities P0..P3: 6 vec/group × 32 = 192 vec + 32 alu + 32 vst — P5-C's row CONFIRMED |
| 3-op packing of 5 loose bits (P3-B soft joint) | −256 IF it exists | OPEN — never searched; would not change any verdict |
| **identified total** | **−482..−568** | vs −1,218 (no-idx) / −1,374 (with-idx) required under P5-C's own optimistic base |

## ADD LEDGER (honest costs the P5-C floors omit)

| line | lanes | status |
|---|---|---|
| A-ring: T2 ring residual at the measured 62.5% ceiling | +776 (97 vec); optimistic st-deletion re-mine 79% → +432 | MEASURED (h059_ringmax, P3-E §1) — POOL0 assumes 0 |
| A-pen15: 2.35 vec/gr penalty on the 3 added round-15 serves | +56 | MEASURED rate (P3-D) |
| A-slider: hash census 46,464 = 12 ops × 512 gr − ~336 C5 elisions; the removable unit per op is 512 vec (4,096), not the charter's 528 (4,224) | +128 per removed op | DERIVED audit of the P5-A/P5-C slider; elision count is inferred (~251 counted vs 336 implied — ±: unresolved, flag ±2-4 cycles at k=9) |
| A-setup: POOL0 ~580 vs h058-measured 616 | +16..+104 | MEASURED census |

## CENSUS TABLES (tools/p5e_trim.py section B/C; law: pool + 8·max(0,F−C) ≤ 60C, load ≤ 2C, store ≤ 2C)

**D2' no-idx, target 889, k=10** (serve-more n=14: r4=11, r15=3; F=1,562; load 1,778 = 2×889 exactly; store 96):

| scenario | pool_h | floor | @889 lane deficit | realized (+11..15) |
|---|---|---|---|---|
| BEST (all trims, ring 79%, charter slider) | 49,111 | **902** | −1,155 (−19.2 cyc) | 913-917 |
| EXPECTED (measured ring, mid setup, slider 512) | 49,713 | **909** | −1,757 (−29.3) | 920-924 |
| WORST (no speculative trims) | 49,967 | **911** | −2,011 (−33.5) | 922-926 |

**D1' with-idx, target 904, k=10** (tail +1,568/+1 ld/+32 st; n=11: r4=8, r15=3; F=1,520; load 1,803; store 128):

| scenario | pool_h | floor | @904 lane deficit | realized |
|---|---|---|---|---|
| BEST | 50,703 | **919** | −1,391 (−23.2) | 930-934 |
| EXPECTED | 51,305 | **926** | −1,993 (−33.2) | 937-941 |
| WORST | 51,559 | **928** | −2,247 (−37.5) | 939-943 |

**K9-STACKING** (same trims/adds; the trims are hash-independent and stack):

| board | P5-C quote | honest floor (BEST/EXP/WORST) | realized | margin vs target |
|---|---|---|---|---|
| no-idx 889 | 859 | 857 / 865 / 868 | 868-883 | +6..+21 |
| with-idx 904 | 875 | 874 / 882 / 885 | 885-900 | +4..+19 |

The trim stack is worth ~3-5 cycles at k=9; the honest adds cost ~6-7 floor
cycles vs P5-C's quote. k=9 still clears both boards, with margins that now
depend on regret staying ≤15 — the theory-first gate still passes, thinner.

## Round-0 / round-11 specialization (brief item 1): total 0

- (a) Restricted range: at round 0 both fold-in operands are < 2^30
  (problem.py:449,467) so a = val0^nv0 < 2^30 — but the first fused stage is
  already a single madd (a·4097 + C0, perf_takehome.py:408) and its output
  is full-width, so nothing downstream simplifies. A shorter 30-bit-input
  composite for stage s1 is a synthesis question (P5-D-shaped), cap 256
  lanes per op removed × round 0 only. Round 11 does NOT qualify: the
  walker val there is a full-width hash output; only nv is restricted.
- (b) Priming VALUES with root_nv: strictly negative. The 32 fold-in xors
  are invariant wherever scheduled (op stream is data-independent, the xor
  must be executed); a mem round-trip adds 32 vstores + 32 vloads for zero
  lane savings, and load is the engine at exactly 2C.
- (c) Round 11: root broadcast already exists (root_nv_vec / primed-root,
  perf_takehome.py:1035); round-10's trailing ^C5 is already elided via the
  primed root; wrap index cost already 0 (P3-B). Nothing left to take.

## Flow re-check at C=889/904 (brief item 6)

Flow is saturated at exactly C in every cell; the overflow law already
treats folds and omf as perfectly fungible flow/valu (T1 + P3-B round 2), so
omf-as-madd respelling frees nothing the model has not already credited.
Placement feasibility only needs ≥C of the F-ops schedulable on flow; the
shipped scheduler places 775-940 flow ops at higher C, and demand shrinks
with C. Store never binds (128 max vs 1,778+). The b3l assert
(perf_takehome.py:729) still needs the frame-6 dead-region spill for
all-32 round-15 serving — allocation work, no census delta.

## What would reopen k=10 (all three needed simultaneously, none identified)

~1,200-2,000 lanes of NEW trim: the only open candidates are the 3-op 5-bit
packing (−256, unsearched) and a round-0 30-bit-input hash shortening
(≤−256/op, unsearched); both granted still leave ≥−650 no-idx. Ring
coverage >79% is word-blocked at K=32 and K≤16 costs +75 realized (P3-E).

## Caveats

- All numbers inherit P5-C's decomposition (POOL0 calibrated to the P3-D
  joint census within ~80 lanes) and P3-C's ±0.1-1.6% engine-model error.
- T-omf may double-count the coupling cancellation (flagged above).
- The A-slider elision count (336 implied vs ~251 hand-counted) is the one
  unreconciled number; it moves k=9 floors ±2-4 cycles, k=10 verdict never.
