# Strain: algo — ALGO-FIRST under the idealized machine

Charter (user directive, iter 13): assume infinite scratch + perfect slot
allocation; find which ALGORITHMIC changes move the ideal floor, and the best
achievable ideal floor under known-open mechanisms. Fitting research
(scratch pressure, packer friction, tie-breaks) is parked.

## H-044 (2026-07-27): ideal-machine cost model + serving-strategy solve — MODEL LANDED, HEADLINE: ideal floor of the CURRENT algorithm is ~932 (< the 940 frontier); the 1038->940 gap needs NO new op-count algebra

Tool: `tools/ideal_floor.py` (scipy LP; runs on plain python3, no repo deps).
All numbers below reproduce from `python3 tools/ideal_floor.py`.

### The model

Fungibility (explicit):
- A vectorizable lane-op runs as 1 lane of a valu slot (6x8 = 48/cyc) or as
  1 alu slot (12/cyc) -> combined 60 lane-ops/cyc for PLAIN ops (+ ^ & | <<
  >> - ...). multiply_add lanes scalarize at 2 alu slots/lane (fused only on
  valu). Scalar-only work is alu-only. Select-shaped work is additionally
  flow-eligible: 1 flow vselect = 8 lane-ops of selection; with a
  PRECOMPUTED diff vector a select also has a 1-valu-slot spelling
  b + cond*(a-b); a select between runtime intermediates costs 2 valu slots
  (v- then madd) or 3 lane-ops of masked &|^ (dominated everywhere; the
  masked column exists in the tool's table and never wins).
- load 2/cyc, store 2/cyc, flow 1/cyc, dep span floor 439.

Layer 1 (validation, as-built 1038 census: alu 11,841 / valu 6,125 / load
1,900 / store 38 / flow 788; cross census in `CENSUS_1038`):
- rigid per-engine floors: valu 1020.8 (binder), alu 986.8, load 950.0,
  flow 788 — matches G-23 exactly.
- fungible ideal floor of the as-built multiset: **1014.0** (target band
  1014-1021 -> VALIDATED). 60,825 fungible lane-ops + 774 flow selects.

Layer 2 (algebraic serving model, infinite scratch): fixed algorithm core
from the census — hash 45,064 lanes in prexor'd form (16,384 madd + 28,680
plain; +8 lanes penalty per unprimed gathered group-round), idx 5,600 lanes
(2,968 madd + 2,632 plain; + 8-lane addr combine per gathered group-round),
setup 16 scalar + 14 flow + 46 base loads + 38 stores. 512 group-rounds;
levels 0-4 have 64 group-rounds (2 epochs), 5-10 have 32.
KEY infinite-scratch simplifications (all load-bearing):
1. tournament CONDITIONS ARE FREE: the d path bits at level d are exactly
   the last d parity vectors, which the idx chain already materializes as
   0/1 vectors — infinite scratch just retains them (as-built spends ~2,000
   lanes re-extracting conds + pool combines; this is deletable OVERHEAD,
   not algorithm).
2. first-layer folds get precomputed diff broadcast tables -> 1 madd each.
3. tables built once (tree static, shared across both epochs), prexor'd
   (^C5 folded into the table build) for free.

### Per-level serving cost table (per group-round; d = tree level)

| d | grp-rnds | gather | flow-tourn | valu-tourn | masked-alu | table once |
|---|---|---|---|---|---|---|
| 0 | 64 | 8 ld + 1 vs | 0 | 0 | 0 | 1 vs + 1 ld |
| 1 | 64 | 8 ld + 1 vs | 1 fl | 1 vs | 16 ln | 3 vs + 1 ld |
| 2 | 64 | 8 ld + 1 vs | 3 fl | 4 vs | 56 ln | 6 vs + 1 ld |
| 3 | 64 | 8 ld + 1 vs | 7 fl | 10 vs | 136 ln | 12 vs + 1 ld |
| 4 | 64 | 8 ld + 1 vs | 15 fl | 22 vs | 296 ln | 24 vs + 2 ld |
| 5 | 32 | 8 ld + 1 vs | 31 fl | 46 vs | 616 ln | 48 vs + 4 ld |
| 6 | 32 | 8 ld + 1 vs | 63 fl | 94 vs | 1,256 ln | 96 vs + 8 ld |
| 7 | 32 | 8 ld + 1 vs | 127 fl | 190 vs | 2,536 ln | 192 vs + 16 ld |
| 8 | 32 | 8 ld + 1 vs | 255 fl | 382 vs | 5,096 ln | 384 vs + 32 ld |
| 9 | 32 | 8 ld + 1 vs | 511 fl | 766 vs | 10,216 ln | 768 vs + 64 ld |
| 10 | 32 | 8 ld + 1 vs | 1,023 fl | 1,534 vs | 20,456 ln | 1,536 vs + 128 ld |

(fl = flow slots, vs = valu slots, ln = alu lane-ops; gather adds +1 vxor
penalty if the level is unprimed; priming a level costs ceil(2^d/8) each of
loads/stores/vxor-slots once.)

### LP solutions (minimize C over serving mix + priming + engine assignment)

| scenario | C | serve mix (grp-rounds) | prime | selects (flow / valu-1st / valu-inner) |
|---|---|---|---|---|
| as-built mix pinned, ideal allocation | **951.4** | L1-3: 64, L4: 25 | L5 | 937 / 142 / 0 |
| FREE mix = ideal floor, current hash+idx | **931.6** | L1-3: 64, L4: 31.1 | L4: 0.51, L5: 1, L6: 1 | 918 / 253 / 0 |
| free mix, flow disabled (control) | 1040.0 | L1-3: 64, L4: 4 | L4-L6 | 0 / 480 / 284 |

At both optima the LP drives valu = alu = load = flow floors EXACTLY equal
(931.6 each: valu 5,589 slots, alu 11,179, load 1,863, flow 932). Per-cycle
mix at the free optimum = valu 6 : load 2 : flow 1 with alu 12 (~1.5
valu-equiv) — **this is corsix's 7.5:2:1 balance, derived independently by
the LP**. Deep serving (L5+) never selected: 31+ select-slots per 8 loads
loses at any census we can reach; the flow-disabled control shows the whole
serving idea is FLOW-FUNDED (without flow: C=1040, only 4 L4 grp-rounds
served — selects on valu are net-negative, re-confirming G-4/G-12/G-14 from
the model side).

### Sensitivity table, at the free-mix optimum (932)

| perturbation | C | dC |
|---|---|---|
| hash plain -1,000 lanes | 921.2 | -10.3 |
| hash madd -1,000 lanes | 921.2 | -10.3 |
| hash -4,096 lanes (-1 op/hash) | 889.2 | -42.4 |
| hash -8,192 lanes (-2 ops/hash) | 846.8 | -84.7 |
| idx -1,000 lanes | 921.2 | -10.3 |
| idx all-plain removed (-2,632) | 904.3 | -27.2 |
| idx maintenance FREE (bound) | 873.6 | -57.9 |
| +1,000 lanes overhead re-added | 941.9 | +10.3 |
| +2,280 lanes (cond-materialization pessimism) | 955.1 | +23.6 |
| loads -100 | 916.7 | -14.8 |
| loads +200 | 961.2 | +29.7 |
| flow x2 (hypothetical) | 892.8 | -38.8 |
| flow x0 | 1040.0 | +108.4 |

Readings:
- The marginal rate is ~**97 lane-ops per cycle**, not the naive 60: at the
  balanced frontier, each cycle cut also shrinks the flow budget (selects
  spill back to valu at 8 lanes/slot) and the load budget (more serving
  needed at 15 selects/8 loads at the L4 margin). Op-removal is worth ~40%
  less than the old "60/cyc" floor arithmetic claimed.
- madd vs plain removal are equivalent (alu slack absorbs plain 1:1 first).
- Loads are live again at the ideal mix: ~0.15 cyc/load (the old "load leg
  closed" G-22 verdict was about the AS-BUILT mix, where load sat 70 cycles
  below the binder; at the balanced optimum load binds).
- Under per-engine rigidity (layer 1), alu-only removals move nothing until
  ~-400 slots (valu binds at 1021 vs alu 987); under ideal fungibility that
  distinction disappears — every fungible lane-op counts at 1/97.

### Reconciliation with the 940 frontier (H-043's numbers to hunt)

- **Free-mix ideal floor 931.6 < 940.** ZERO op-mix delta from the current
  hash+idx algorithm is needed to explain 940. Minimal sufficient delta =
  the ideal-mix reorganization itself:
  1. select placement: ~930 flow selects (flow ~100% busy schedule-wide;
     we run 774 at 76% busy),
  2. routing overhead ~2,000 lanes deleted (conds retained across rounds
     instead of re-extracted; no pool combines),
  3. serve ~31/64 L4 grp-rounds (we serve 25) and prime L4-L6 (we prime L5),
  4. loads at ~1,863 with ~100% load util (we: 1,900 at 91.5%).
- With the as-built serving mix PINNED, 940 is UNREACHABLE by any amount of
  compute removal (load floor 951 binds) — serving-mix change is MANDATORY,
  op removal alone can never get there.
- 892 (no-idx board) under our rules: needs 3,825 further lane-ops removed
  (~0.93 ops/hash) at the free mix — consistent with H-040's finding that
  892 lives on the relaxed board (no-idx relief 9-23 cyc + organization).
- Gap decomposition: 1038 actual -> 1014 (24 cyc scheduling friction +
  engine rigidity) -> 951 (63 cyc overhead: flow-shifted selects ~3,100
  lanes + deleted cond/pool overhead ~2,000 lanes + prexor'd tables) ->
  932 (20 cyc serving-mix optimization).

### Honesty caveats (where the ideal model is optimistic)

1. Flow at 100.0% for the whole schedule: every flow bubble sends a select
   back to valu (+~1/60 cyc each). As-built flow busy is 76%; the frontier
   builds must be running flow essentially bubble-free.
2. Load at 100.0%: as-built is 91.5% with the 176 free slots structurally
   stuck in setup/drain (G-18). Same packing demand.
3. Free conds need the last d parity vectors retained per group: ~1k words
   scratch at L4 across skewed groups — infinite-scratch only; a real build
   must solve the H-041 scratch problem (1,533/1,536 used). Pessimism probe
   (+2,280 lanes if every cond layer is re-materialized): +23.6 cyc -> 955,
   still far below as-built.
4. Global engine budgets ignore windowing: select demand lives in serving
   rounds (levels 0-4, 320/512 grp-rounds incl. both epochs), gathers in
   rounds 5-10. The (4,3) group skew is what interleaves them per-cycle;
   the ideal model assumes perfect interleave (G-23 measured today's real
   interleave is already near-perfect in the steady window, so this is the
   least-worrying caveat).
5. Span grows slightly with deeper select chains; 439 << 932, not binding.

### What the model says to spawn next (priority order)

1. **H-045 (flow-saturation build): the single biggest modeled lever is
   moving ~150 more selects/cycle-budget onto flow and keeping flow
   bubble-free.** Concretely: serve 6 more L4 grp-rounds (25->31), prime L4
   remainder + L6, retain parity vectors to delete cond re-extraction, and
   emit first-folds madd-only where flow is full. Modeled prize: 1014 ->
   ~951 territory under ideal allocation; realistically bounded by caveats
   1-3. This is ALLOCATION-SHAPED but ALGO-SPECIFIED: the op multiset
   itself changes (overhead deletion), so it is in-charter for algo-first.
2. **H-043 (writeup mining) should look for**: flow/select occupancy near
   100%, cond-bit retention across rounds, priming beyond one level,
   serve-count at L4 above ours, load util ~100%, and NOT for hash algebra
   — the model says the frontier needs none.
3. Scratch-liberation research (enables caveat 3): the 892-style routes all
   assume table+cond residency; the model quantifies the prize of each
   freed region (e.g. free conds are worth ~24 cyc vs re-materialization).
4. If any op-removal lever ever reopens: value it at ~1/97 cyc per lane-op
   (not 1/60), and remember loads are back on the exchange at ~0.15
   cyc/load once the mix is balanced.
