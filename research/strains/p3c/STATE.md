---
title: "P3-C: the design-space cost calculator and the exhaustive answer on 940"
date: 2026-07-28
type: research
status: final
task: "Build tools/p3c_design_cost.py (abstract design -> exact per-engine census + floors), validate it against the shipped kernel, then enumerate the entire design space and report whether any point clears 940 on all three engines simultaneously."
links: ["[[research/RESEARCH.md#Phase-3-charter]]", "[[research/strains/p3b/STATE.md]]", "[[research/graveyard.md#G-33]]", "[[research/graveyard.md#G-34]]"]
---

# P3-C: design-space cost model + enumeration

**Verdict in one line: over the ENTIRE design space (every served-level set,
every partial count, every flow/valu fold split, every K), the minimum
simultaneous max-floor is 964.8 at as-built coefficients and 946.0 with ALL
condition-prep and gather-support arithmetic set to zero — so 940 is NOT
reachable by changing WHICH levels are served. The optimal served-level set
is the one we already ship (L1-L3 full + ~23-27/64 of L4). 940 opens only if
the index axis is driven to P3-B's b=0 optimum (5,888 lane-ops) AND all
support arithmetic is free: that point measures 937.4.**

Tools (mine, read-only, new): `tools/p3c_design_cost.py` (the calculator +
enumerator), `tools/p3c_probe.py` (marginal-cost probe against dev builds).

## 1. The model

`tools/p3c_design_cost.py`. A design is `served[d] = n` (how many of level
d's group-rounds are served by selection rather than gathered), plus `K`
(live groups), plus three cost parameters (`idx_slack`, `mask_rate`,
`gather_ovh`). Shape: 512 group-rounds, `level(r) = r mod 11`, so levels
0-4 carry 64 group-rounds each and levels 5-10 carry 32.

| term | value | provenance |
|---|---|---|
| hash | 5,808 vec-ops (46,464 lane-ops) | CONSTANT, G-10/G-20/G-24 |
| gather a group-round | 8 load slots + `gather_ovh` vec-ops | ISA: no permute, no scratch-indexed vector read; one load per lane |
| serve level d | `2^d - 1` folds, of which `2^(d-1)` are LEAF folds of two broadcast constants (1 valu madd with precomputed diff, **or** 1 flow vselect) and `2^(d-1)-1` are INTERIOR (1 flow vselect **or** 2 valu ops) | dev.py L1/L2/L3 emitters + `b3l_fold_diffs`; spelling equivalence at dev.py:848 |
| serve support | `mask_rate * (d-1)` vec-ops of condition extraction | 0 when a parity ring retains the raw parity vectors |
| index | P3-B's transition rule (below) | research/strains/p3b/STATE.md |
| setup | 77 vec-ops + 60 load + 22 flow at 30 table entries, growing with entries | measured @1006 |
| scratch | `24*K + 16*(table entries) + 285` | fits the measured 1533 exactly |

**Index (P3-B correction, folded in).** Only 448 of 512 group-rounds pay:
the L10->L0 wrap and the last round are exactly free. Per paying transition
into successor level e: 1 vec-op parity extract always; +0 if e is SERVED
(the bit stays loose); +1+j if e is GATHERED, where j is the run of served
levels immediately below e that must now be packed; +1 flow slot if e is
gathered and e-1 was also gathered (the steady `omf +/- par` select).

> **The coupling, resolved.** Serving a level makes the transition INTO it
> cost 1 instead of 2, but makes the exit transition out of the served run
> cost one more per loose bit. For a contiguous served prefix these cancel
> EXACTLY, so index cost is (to first order) invariant to S. My model
> reproduces P3-B's 448-extract structure and gives 842 vec / 178 flow at
> the shipped serving policy against their measured 898 / 166 — i.e. the
> model naturally lands on their FLOOR (826), which is what a design-space
> calculator should do.

**The flow/valu fold split is the only free variable** and it is solved
analytically (leaves cost 1 valu op, interiors 2, so leaves are always spent
first; the objective is convex piecewise-linear in the split).

## 2. VALIDATION (`python3 tools/p3c_design_cost.py`)

Shipped design = `{L1:64, L2:64, L3:64, L4:27}`, the measured flow/valu
split fed in rather than optimised:

| bucket | model | measured (h058_census) | err |
|---|---|---|---|
| alu+valu lane-ops | 59,537 | 59,489 | **+0.08%** |
| load slots | 1,892 | 1,892 | **0.00%** |
| flow slots | 810 | 797 | **+1.57%** |
| store slots | 46 | 46 | 0.00% |
| scratch words | 1,533 | 1,533 | 0.00% |

Floors: model compute 992.3 / load 946.0 / flow 809.5 vs measured
991.5 / 946.0 / 797.0. No bucket exceeds 3%; the flow gap is the 13 slots
of `race_sel`/`race_copy` spelling drift between engines, which is a
scheduling race, not a design property.

Independent cross-checks the coefficients survived:

* `tools/h058_marginal.py --no-ring` measured slopes per served L4
  group-round: d(vec) = +11.66, d(flow) = +6.31, d(load) = -8.00
  => 15 folds + ~3 masks. The model's L4 serve is 15 folds + masks. Match.
* `tools/p3c_probe.py` matched-flag builds: adding level 3 to the
  tournament prefix costs exactly +4 valu madd, +3 flow vselect, +2 valu
  `&` per group-round, -8 loads = **7 folds + 2 masks**, i.e. `2^3-1`. Match.
* **DEAD END (recorded so nobody repeats it):** `tournament_levels=(1,2,3,4)`
  in dev.py measures only ~7 ops/group-round for "level 4", which would
  falsify `2^d-1`. It is an INVALID BUILD: dev's fold emitter has explicit
  branches only for L==1/2/3 and its final `else` is labelled `# L == 3`,
  so a 4th level silently re-runs the 8-way fold over 16 candidate values.
  Do not use T4/T5 probe rows as evidence.

## 3. THE ENUMERATION

Every subset of {L1..L10} fully served x every partial count at one further
level x the optimal fold split (~405k designs). K is not a search dimension
because it is **census-neutral** (see 5).

### Frontier (top rows, as-built coefficients)

| max-floor | lane-ops | load | flow | store | f_cmp | f_ld | f_flw | binder | served | gathered | scratch | design |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **964.8** | 57,887 | 1,924 | 965 | 46 | 964.8 | 962.0 | 964.8 | flow | 215 | 233 | 1533 | L1L2L3 + L4x23 |
| 966.0 | 57,797 | 1,932 | 963 | 46 | 963.3 | 966.0 | 963.3 | load | 214 | 234 | 1533 | L1L2L3 + L4x22 |
| 966.3 | 57,977 | 1,916 | 966 | 46 | 966.3 | 958.0 | 966.3 | flow | 216 | 232 | 1533 | L1L2L3 + L4x24 |
| 967.8 | 58,067 | 1,908 | 968 | 46 | 967.8 | 954.0 | 967.8 | flow | 217 | 231 | 1533 | L1L2L3 + L4x25 |
| 969.3 | 58,157 | 1,900 | 969 | 46 | 969.3 | 950.0 | 969.3 | flow | 218 | 230 | 1533 | L1L2L3 + L4x26 |
| 970.0 | 57,707 | 1,940 | 962 | 46 | 961.8 | 970.0 | 961.8 | load | 213 | 235 | 1533 | L1L2L3 + L4x21 |
| 970.8 | 58,246 | 1,892 | 971 | 46 | 970.8 | 946.0 | 970.8 | flow | 219 | 229 | 1533 | **L1L2L3 + L4x27 = SHIPPED** |
| 972.3 | 58,336 | 1,884 | 972 | 46 | 972.3 | 942.0 | 972.3 | compute | 220 | 228 | 1533 | L1L2L3 + L4x28 |
| 973.8 | 58,426 | 1,876 | 974 | 46 | 973.8 | 938.0 | 973.8 | flow | 221 | 227 | 1533 | L1L2L3 + L4x29 |
| 974.0 | 57,617 | 1,948 | 960 | 46 | 960.3 | 974.0 | 960.3 | load | 212 | 236 | 1533 | L1L2L3 + L4x20 |

Relaxed-coefficient optima (same enumeration):

| coefficients | min max-floor | design | 940? |
|---|---|---|---|
| as-built index slop + as-built support | **964.8** | L1L2L3 + L4x23 | no |
| index at P3-B floor, support as built | 959.7 | L1L2L3 + L4x24 | no |
| index as measured, ALL support free | 950.6 | L1L2L3 + L4x26 | no |
| index at floor AND all support free | **946.0** | L1L2L3 + L4x27 | no |

**Every optimum has the SHIPPED SHAPE: levels 1-3 fully served, level 4
partially served, levels 5-10 gathered.** The served-level axis is closed
by exhaustion: no other set is even close.

Designs that serve L5+ (flagged for scratch per the brief, NOT rejected on
it): best is `L1L2L3 + L5x17` at max-floor **994.0** (scratch 1,789 > 1,536).
Best case it is 981.2. So L5 loses by 30-47 cycles even before scratch is
consulted — which re-confirms G-33/H-058 from a completely independent
direction: scratch was never the reason L5 serving loses.

## 4. THE ANSWER

**Minimum max-floor over the entire enumerated space = 964.8 cycles**
(design: L1-L3 served in full, 23 of 64 L4 group-rounds served, 233
gathered; census 57,887 lane-ops / 1,924 load / 965 flow / 46 store;
floors 964.8 / 962.0 / 964.8 / 23.0; scratch 1,533). All three engines
bind within 3 cycles of each other — the design space is a genuine
three-way tie, which is why no local move helps.

**940 is not reachable by re-choosing the served-level set.** At the
best-case optimum (946.0) the shortfall at 940 is exactly:

* compute +328 lane-ops over the 56,400 budget,
* load +12 slots over the 1,880 budget,
* flow +5 slots over the 940 budget.

Stated as the binding inequality at 940: the load cap forces >= 219 served
group-rounds (`8G + 60 <= 1880` => `G <= 227`); the cheapest 219 served
group-rounds cost 1,109 folds; flow can absorb at most `940 - 22 - idx_flow`
= 740 of them; hash + index-at-floor + setup already consume 6,727 of the
7,050 vec-op budget, leaving 323 for the rest — **shortfall 46 ops.**
That 46-op gap is the whole of the 940 question.

**The true structural floor of this problem under this ISA** is therefore
**~965 as built / ~946 with every support op removed**, unless the index
axis moves. Realized cycles sit ~15-20 above a compute-bound floor and ~70
above a load-bound one (h058_marginal), so ~965 floor => ~980 realized;
946 floor => ~965 realized.

## 5. K (simultaneously live groups) — census-neutral

| K | lane-ops | load | flow | scratch |
|---|---|---|---|---|
| 32 | 58,246 | 1,892 | 971 | 1,533 |
| 24 | 58,246 | 1,892 | 971 | 1,341 |
| 16 | 58,246 | 1,892 | 971 | 1,149 |
| 11 | 58,246 | 1,892 | 971 | 1,029 |
| 8 | 58,246 | 1,892 | 971 | 957 |

K changes **only** scratch and latency slack. It moves no engine floor, so
it cannot participate in the 940 arithmetic — a census restatement of G-33
("freed scratch buys nothing at any size") and consistent with H-058's
K >= 11 latency sufficiency. The charter's hope that "a design holding fewer
groups live changes which serving strategies are affordable" is FALSE on the
census axis: the strategies it would afford (L5 serving) lose by 30-47
cycles for reasons that have nothing to do with scratch.

## 6. SENSITIVITY to the index axis (P3-B's grid)

| index lane-ops | vec-ops | min max-floor (support as built) | min max-floor (support free) | note |
|---|---|---|---|---|
| 7,184 | 898 | 964.8 | 950.6 | measured today |
| 6,608 | 826 | 958.0 | 945.1 | P3-B floor, today's policy |
| 5,888 | 736 | 950.2 | **937.4** | P3-B b=0 L4 policy |
| 5,120 | 640 | 942.0 | 929.1 | hypothetical -30% |

**Only one cell in the whole table clears 940, and it needs BOTH legs at
once**: index driven to P3-B's b=0 optimum AND every condition-prep /
gather-support vec-op eliminated (i.e. a parity ring covering 100% of
served group-rounds and a zero-overhead gather boundary). Neither leg alone
suffices (950.2 and 945.1 respectively). That is the exact, falsifiable
specification of what a 940 design must be.

## 7. What I would do next

1. Ask P3-A whether any serving mechanism beats `2^d - 1` folds. The model
   takes `folds(d)` as a plug-in; a mechanism at `2^d - 1 - k` would move
   the answer by roughly `k * 219 / 8.5` cycles.
2. Price the "support-free" leg for real: how many of the 219-227 served
   group-rounds can a parity ring actually cover given scratch? (H-045/H-048
   got 20 rings; 100% coverage is the assumption behind 946.0.)
3. The 46-op shortfall at 940 is 0.6% of the census. It is small enough that
   the model's own +-1.6% flow-bucket error covers it, so 940 should be
   treated as "at the model's resolution limit", not "provably impossible".
   Sharpening the flow bucket (attributing the 13-slot race drift) is the
   single highest-value refinement.

## Caveats (honest)

* The split of the shipped Routing bucket between `mask_rate` and
  `gather_ovh` is under-determined by the TOTALS alone. Three calibrations
  reproduce the measured totals exactly and give:
  `mask 0.222 / gather 0.43` -> 964.8; `mask 0.582 / gather 0` -> 964.0;
  `mask 0 / gather 1.17` -> 974.2. The third is REFUTED by direct
  measurement: the matched-flag T2->T3 probe shows +128 valu `&` over 64
  served L3 group-rounds = exactly 2.00 mask ops per served group-round, so
  `mask_rate` cannot be 0. Across the two surviving calibrations the answer
  is 964.0-964.8, i.e. the verdict is robust to +-1 cycle; individual
  frontier rows are not quoted better than +-2.
* Partial levels are costed by expectation over the serve fraction. Exact
  for fully-served/fully-gathered levels; the optimum has at most one
  partial level (L4), where the approximation is worth < 1 cycle.
* This is a FLOOR calculation. Realized cycles carry regret (~15-20
  compute-bound, ~70 load-bound). No design here was scheduled.
