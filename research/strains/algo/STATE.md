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

## H-045 (2026-07-27): flow-saturation build — PARTIAL LANDING, mainline-candidate 1038 -> 1034 (-4) via parity-vector cond retention in dead-register rings + l4_gmin slide

Charter: build the full H-044 prescription (cond retention, flow ~100%,
serve 31 L4, prime L4/L5/L6, load ~100%; modeled endpoint 931.6). What
landed is the retention enabler + the serving-mix slide it unlocks; the
flow-saturation and priming legs were measured and did NOT convert at the
new mix. All flag-gated in dev.py, default OFF; default stream verified
BIT-IDENTICAL to HEAD (programmatic instr compare, dispatch + BASE_KWARGS);
full gate 9/9 green at 1038 with flags off.

### Landed frontier

run_variant, correct: true on seeds 1,2,3,7,42,99 + 2 unseeded runs +
debug_compares=True:

    parity_ring=True l4_gmin=(7,30)            -> **1034**  (BASE otherwise)
    + c5_primed_gather_levels=(5,6) + region_hazards + dead_reg_staging
      at l4_gmin=(8,30)                        -> 1034 (tie, seeds 2/7 too)

### Mechanism 1 — parity_ring (THE new primitive)

The tournament conds at depth d ARE the last d parity vectors (H-044 fact).
`parity_ring` retains them: each round's raw parity is written into a
per-(epoch, group) 3-slot ring (P0/P1/P2; the newest L4 bit keeps riding
nv), the position accumulator is SEEDED at L2 (madd st = 2*P0 + P1 —
replaces the lag fold, so st is identical downstream: epoch-exit gaddrs,
b3l packed folds all unchanged), and every cond re-extraction disappears:
per ringed group-round, the L2 flow copy (1 flow), both L3 mask extractions
(2), all 3 served-L4 mask extractions, and (b3l rewiring, step 2) the 5
b3l mask ops of a served r15 group. ZERO ops added anywhere.

SCRATCH-LIBERATION LEDGER (the gating problem; all zero-net borrows —
permanent allocation stays 1533/1536):
- liveness audit (scratchpad tool over sched_trace, 1038 build): 3 words
  never touched (1533-35); lv[0..23] dead after cycle ~36; root_pr_vec
  free [7,382]; root_nv_vec dead after ~316; block 0/1's st/nv dead from
  ~[655-790] to the b3l pool claims (~1009); block 2/3's st/nv/val unborn
  until ~[260-390].
- ring funding (emission-order-safe: every donor's real accesses sit
  strictly on the other side of the ring's accesses in emission order, so
  the scheduler's per-address hazards can only serialize, never corrupt):
    (0,0) groups 0-7   <- block 2 st/nv (16 vec, born slot 6)  : 5 rings
    (0,1) groups 8-15  <- block 3 st/nv (born slot 9)          : 5 rings
    (1,2) groups 16-23 <- block 0 st/nv (dead after slot 14/15): 5 rings
    (1,3) groups 24-31 <- block 1 st/nv (dead after slot 17/18): 5 rings
  = 480 borrowed words, 20/32 groups per epoch ringed, served-at-L4
  groups funded first (6 ops/ring vs 3). val vectors are NOT usable
  donors on the e1 side (final vstores read them at the drain) and on the
  e0 side only under lazy_val_loads (measured +13 alone — dead end).
- extras (landed, default OFF via parity_ring_extras): lv[0..23] as one
  more ring per epoch + root_nv_vec (e1): e1 extras NEUTRAL (1034), e0
  extras +3 (lv false-deps against the setup table stream delay an early
  tournament). Not worth it.
- b3l interop: the r15 dead-register pool now EXCLUDES served groups'
  ring bases (still read at r15 by the rewired masks); with ring conds a
  served group pops 5 private temps instead of 9 (E/D share the hi temp).

### Measured composed results (seed 1; all correct)

| config | cycles |
|---|---|
| BASE (mainline) | 1038 |
| parity_ring alone | 1035 |
| slices (0,0)/(0,1)/(1,2)/(1,3) alone | 1039 / 1038 / 1038 / 1037 |
| (0,0)+(0,1) / (1,2)+(1,3) | 1036 / 1037 (superadditive to 1035) |
| parity_ring + gmin (7,30) | **1034** ((8,30) 1037, (9,30) 1035, (6,30) 1038, (7,29)/(7,31) 1037) |
| + idx_boundary_select (any gmin tried) | 1037-1040 — REJECT in composition |
| + mem_prime (5,6)+region+dead_reg @ (8,30) | 1034 tie ((7,30) 1037; (5,6,7) 1038) |
| + parity_ring_extras (0,) / (1,) | 1037 / 1034 |
| + pool (16,3) / (17,4) | 1047 / OOM |
| + lazy_val_loads | 1055 (alone 1051) |
| tie_break () / +idx_alu | 1035 / 1040 |

### Occupancy vs the LP targets (occupancy_hist, 1034 build vs 1038)

| engine | 1038 slots (floor) | 1034 slots (floor) | LP target |
|---|---|---|---|
| valu | 6119 (1020) | 6093 (1015.5) | 5589 (932) |
| alu  | 11881 (990) | 11801 (983)   | 11179 |
| load | 1900 (950)  | 1884 (942)    | 1863 @ ~100% |
| flow | 797 (76.8%) | 794 (76.8%)   | 932 @ ~100% |

Friction above the valu floor: 18 -> 18.5 (unchanged). Deletion realized:
~106 alu+valu slots (~570 lanes) of the ~2,000-lane modeled overhead;
L4 served 25 -> 27 group-rounds (LP wants 31); flow util DID NOT MOVE.

### Distance-to-model diagnosis (1038 -> 932 gap: realized 4)

1. Cond retention is REAL but 2/3-blocked by scratch: full coverage needs
   ~512-1,024 ring words; the mid-schedule slices (blocks 2/3 in epoch 0,
   blocks 0/1 in epoch 1) have NO dead registers — every st/nv/val is live
   mid-window, and the only real reserves (lv 24w + root vecs 16w + 3w)
   fund ~1 ring per epoch, measured neutral-to-negative. The LP's +23.6cyc
   pessimism probe (all conds re-materialized) bounds what full retention
   is worth beyond this partial: ~2/3 of ~24 = ~16 ideal cycles still on
   the table, needing a >=384-word liberation nothing visible provides.
2. Flow saturation did not engage: deleting the 20 L2 flow copies freed
   flow slots, but no new selects moved onto flow (76.8% before and
   after); idx_boundary_select (the designated first installment) is +3
   composed — its boundary vselects land in locally-full flow windows
   (G-4/G-12 mechanism, third confirmation). The LP's ~930-selects-on-
   flow endpoint needs bubble-free flow, which no local spelling change
   reaches from here — this is H-042/N-3 (joint selection x scheduling)
   territory, not spelling territory.
3. Serving-mix slide: P-3 pattern held AGAIN ((9,30) -> (7,30), +2 L4
   group-rounds funded by the retention relief, worth -1 of the -4). The
   LP's 31-served endpoint stays gated on ~400 more valu slots of relief.
4. Priming: L6 crossed from +1..+3 to NEUTRAL at the new mix — direction
   as the LP predicted, magnitude still zero; L7 still +4. The (5,6)
   tie is a free option if load ever binds (removes 136 alu lanes for +8
   loads).
5. Honest read of H-044 after this build: the model's coupled-prize story
   is CONFIRMED in direction (gmin slid, L6 crossed to neutral, pieces
   compose superadditively) but the conversion rate is ~150 lanes/cycle,
   not the ideal 97, and the two big legs (full retention, flow ~100%)
   are blocked by scratch supply and flow-window structure respectively —
   neither is a spelling/knob problem.

### Follow-ups (driver)

- F-1 [mainline flip candidate]: parity_ring=True + l4_gmin=(7,30) = 1034
  (-4). Needs porting into perf_takehome.py's flag-free form + full gate.
- F-2: any future accept that frees >=24 contiguous words funds one more
  e1 ring (+~3-6 ops); >=384 words reopens full retention (~16 ideal cyc).
- F-3: standing sweeps should carry parity_ring as a dimension; the gmin
  optimum under it is (7,30) and will slide again after any accept.
- F-4: the b3l ring-mask rewiring + donor-pool filter is load-bearing for
  ANY future e1-ring extension serving r15 groups — do not fund served
  groups' rings from registers the b3l pool claims without the filter.
- F-5: flow-saturation leg: re-scope as a scheduler-side hypothesis
  (H-042 beam / N-3), not further spelling flags; three independent
  negatives now show local flow-window flooding eats every spelling win.

## F-1 (2026-07-27): H-045 parity_ring ported to mainline perf_takehome.py — LANDED, 1038 -> 1034

Flag-free port of the verified frontier (`parity_ring=True, l4_gmin=(7,30)`)
into perf_takehome.py: ring-slice set gated on the graded (4,3)/32-group
16-round shape (any other shape silently keeps the packed-st path), ring map
built after alloc_state from cross-block st/nv donors (5 rings per 8-group
slice, served-at-L4 groups first), L2 seed-madd + L3/L4 ring cond reads, b3l
ring-mask rewiring (5-temp pop) + served-ring donor-pool filter, parity
writes redirected into ring slots. No extras (parity_ring_extras stays dev-
only), no lazy-val donors (mainline loads vals at setup).

Divergence found and closed: the first port measured 1036, not 1034 — the
files had drifted on temp-pool slot keying (perf used `g % pool_size`, dev's
temp_slot() rotates by global emission index). Porting dev's emission-index
rotation recovered 1034 exactly. This keying is now baked into
perf_takehome.py (comment explains the WAW-halving effect).

Gates: `perf_takehome.py Tests.test_kernel_cycles` CYCLES: 1034 (x2);
`tests/submission_tests.py` 9/9 green, all CYCLES lines 1034 (x2).
Debug vcompare hooks unchanged and exercised (test runs with value_trace +
debug compares enabled and passes).
