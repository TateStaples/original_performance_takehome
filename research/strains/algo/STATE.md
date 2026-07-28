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

## H-048 (2026-07-27): scratch liberation via word-level window mining — STRAIN FRONTIER 1034 -> 1032 (-2), 384 audited-safe ring words found, conversion (not supply) is now the binder

Charter: mine ALL scratch classes for ring-fundable words (window-disjoint
availability, not free-forever liveness), reshape where near-miss, dedup
constants, measure each increment on the 1034 config. Tools:
`scratchpad/audit_h048.py` (trace-based availability matrix + global
greedy planner; scratchpad of this session), new dev.py kwarg
`parity_ring_plan` (offline-audited donor triples injected into
parity_ring_map; default `()` = bit-identical, verified programmatically
against HEAD on both the mainline and the 1034 config).

### Landed frontier (dev.py, flag-gated)

    parity_ring=True l4_gmin=(8,30)
      parity_ring_plan=(((0,5),(193,201,601)), ((0,6),(609,617,625)),
                        ((0,15),(185,1225,1233)), ((0,16),(193,201,1297)))
                                             -> **1032** (-2)

4 extra rings (96 borrowed words: lv+0/8/16, st8-12, nv22/23/31), correct
on seeds 1,2,3,7,42,99 + 2 unseeded + debug_compares=True (all 1032).
Equivalent 1032 configs: e0-minus-(0,7) [6 rings], e0-(0,7)+e1_early [12
rings] — same cycles, all-seed-validated; the 4-ring form is minimal.
Closed-loop re-audit of the WINNER stream: all 24 rings (20 structural +
4 plan) pass the donor-safety recheck. Full gate 9/9 green flags-off;
mainline stays 1034 (untouched).

### Availability matrix (audited 1034 build, conservative windows = rounds 0-4 / 11-15 of the group; free words per unfunded window)

| window cluster | free words | dominant classes |
|---|---|---|
| (0,4)-(0,6)   e0 block0 leftovers | 266 | nv 120, st 80, lv 24 |
| (0,13)-(0,15) e0 block1 leftovers | 138 | nv 72, lv 24 |
| (0,16)-(0,23) e0 block2 (mid)     | 74  | lv 24, anon 23, nv 8 |
| (0,24)-(0,31) e0 block3 (mid)     | 67  | lv 24, anon 24, scalars |
| (1,0)-(1,7)   e1 block0 (mid)     | 83  | anon 32, lv 24, root_nv_vec 8 |
| (1,8)-(1,15)  e1 block1           | 171 | anon 56, st 40, lv 24 |
| (1,21)-(1,23) e1 block2 leftovers | 179 | anon 56, st 40, lv 24 |
| (1,27)-(1,29) e1 block3 leftovers | 355 | st 128, nv 72, anon 64 |

Key structural facts: (a) adjacent blocks' ring windows are emission-
disjoint (wave order within a diagonal step), so lv/root_nv_vec-class
donors REUSE across blocks — the same 3 lv vectors legally fund one ring
in nearly every block; (b) the H-045 e1 ledger missed the (1,1)<-block0
and per-window st/nv availabilities that exist because RINGED donors'
births move to their L2 seed (audit is self-consistent on the parity_ring
build); (c) the true zero is only the (0,24)-(0,31)+(1,0)-(1,7) overlap
chain (~5-6 shared safe vectors for 16 windows).

### Soundness finding (cost us one miscompare, now excluded by design)

Trace-based liveness is UNSOUND for emit_any-raced operands: alternatives
read DIFFERENT addresses (dual_fold: diff-table madd vs odd-table
vselect; race_idx_madd: rec VECTOR madd vs rec SCALAR alu lanes; also
one_c/two_vec/omf_vec asymmetries), and only the winning encoding's reads
land in the trace. A plan-induced schedule shift flips races and
materializes reads inside a window that the audit never saw: borrowing
addr 227 (an L1/L2 odd table) for ring (1,1) produced correct=False.
Donor candidacy is therefore restricted to STRUCTURAL classes whose reads
are schedule-independent: st/nv registers, lv words, root_nv_vec. Any
future scratch-borrowing work MUST apply the same exclusion.

### Words found / measured conversion

- Audited-safe plan capacity at (7,30) and (8,30): **16 rings = 384
  words** (exactly the F-2 full-retention threshold) from structural
  donors; 28 (epoch,group) pairs remain unfundable (mid-chain).
- Constant-table dedup (job item 3): ZERO — 59 vbroadcasts, no scalar
  source broadcast twice; tables already shared across epochs.
- Measured at (7,30): every increment is neutral-to-NEGATIVE (e0 rings
  +1..+4 each — WAR serialization against adjacent-block donor births on
  the saturated ramp; e1 rings 0). Composed full-16: +5.
- Measured with per-gmin re-sweep (P-3 slide, third confirmation): the
  optimum moved (7,30)->(8,30) under the plan; (8,30)+e0-subset = 1033,
  minus-one-ring variants = **1032**. The win is retention relief
  FUNDING a serving-mix slide, not op deletion per se: (8,30) alone is
  1037.
- Non-monotone: singles are 1034-1037, leave-one-out sets 1032-1035 —
  ring composition interacts through the scheduler, sweep composed only.

### Distance to the H-044 model prize

Word SUPPLY is no longer the binder: 384 audited-safe words exist and are
flag-reachable today. The binder is CONVERSION — beyond ~4-6 rings the
borrow hazards cost more than the 3-6 deleted ops/ring recover (~150
lanes/cyc marginal rate territory). Full cond retention (~16 ideal cyc)
still requires rings whose hazards sit OFF the critical path, i.e. joint
selection x scheduling (H-042/N-3), exactly where the flow-saturation leg
already points. F-2 should be restated: words are available; cycles per
word is the research question.

### Follow-ups (driver)

- F-6 [mainline flip candidate]: parity_ring + l4_gmin=(8,30) + the
  4-ring plan = 1032 (-2). Port note: the plan addresses are LAYOUT
  CONSTANTS of the current alloc order — a flag-free port should derive
  them from the named vectors (lv, st8-12, nv22/23/31), not hard-code.
- F-7: re-run audit_h048.py + per-gmin planner after ANY accept that
  changes emission order or allocation (plans are build-specific; the
  tool re-derives in ~15s and the dev.py assert catches stale keys).
- F-8: H-042/N-3 should treat the 12 unmeasured-positive audited rings
  as the retention budget the scheduler must make free (hazard-aware
  placement of ring accesses), rather than hunting more words.

## F-6 (2026-07-27): H-048 mainline port — perf_takehome.py 1034 -> 1032

Ported the verified H-048 frontier into the flag-free submission:
l4_gmin (7,30) -> (8,30) plus the 4-ring plan appended in
`build_parity_ring_map`. Per the F-6 note the addresses are NOT baked:
each donor is derived from its named vector (verified equal to the
audited raw addresses 185/193/201, 601-625, 1225/1233/1297 by
instrumenting alloc_scratch):

    (0, 5):  lv+8,  lv+16,  st8      (0, 6):  st9, st10, st11
    (0, 15): lv+0,  nv22,   nv23     (0, 16): lv+8, lv+16, nv31

lv+24 (two_minus_fp_vec) deliberately untouched; donors are structural
classes only (st/nv/lv) — the emit_any trace-liveness exclusion from
H-048 carries over in the code comment. No temp-pool or emission-order
drift this time: cycles matched dev's 1032 on the first build.

Gates: `perf_takehome.py Tests.test_kernel_cycles` CYCLES: 1032 (x2);
`tests/submission_tests.py` 9/9 green, all CYCLES lines 1032 (x3).

## H-047 (2026-07-27): serving-mix change under joint plan re-search — STRAIN FRONTIER 1023 -> 1022 (-1), G-22's mem_prime(5,6) CONVERTS under order re-search; serve-more-L4 closed at the FLOOR level (greedy spellings); the LP's residual mix prize localized to a floor-990 stream that only flow-saturation can realize

Charter (re-scope per F-14 triangulation): re-evaluate the H-044 LP's mix
moves (serve more L4, prime L4/L5/L6, gmin composition) WITH the full plan
toolchain re-run per candidate — emission-plan local search seeded from the
1023 plan (tools/h049_best_plan.json), spelling fixpoint, stream-floor
measurement (H-051 bounds) per candidate. Tools (all new, wrappers only —
emission_order_search.py / backtrack_sched.py untouched):
tools/h047_search.py (sweep/local/one; patches eos.FRONTIER_OVERRIDES),
tools/h047_floor.py (per-candidate H-051 any-packing floor),
tools/h047_flowmax.py (all-flow spelling floor probe),
tools/h047_verify.py, tools/h047_spellcheck.py.

### Landed frontier (dev.py flags, all default OFF)

    parity_ring=True l4_gmin=(7,30) 4-ring parity_ring_plan (unchanged)
    c5_primed_gather_levels=(5,6) mem_prime_region_hazards=True
    mem_prime_dead_reg_staging=True flow_spelling_plan=()
    emission_plan=tools/h047_best_plan_1022.json      -> **1022** (-1)

Verified: seeds 1,2,3,7,42,99 + unseeded all 1022 correct;
debug_compares=True 1022 correct; full gate flags-off 9/9 green at 1023
(perf_takehome.py untouched). Spelling fixpoint on the 1022 order: 1,157
single flips (flow rev + aux + fwd), ZERO wins — order absorbs spelling,
third independent confirmation of the H-049 pattern.

### Per-candidate table (mix change x cycles x floor)

All searches seeded from the 1023 plan; "greedy" = candidate at the FIXED
1023 emission plan; floor = H-051 two-sided any-packing bound of the
candidate's op stream (greedy spellings).

| candidate (serve counts e0+e1) | greedy | after order re-search | floor | verdict |
|---|---|---|---|---|
| baseline (8,30) = 26 served, prime L5 | 1023 | (= frontier) | 1011 | reference |
| mem_prime(5,6)+rdr + (7,30) = 27 served, prime L5+L6 | 1025 | **1022** (2 descents, ~29k evals; ext. +25k evals window=all plateau) | **1010** | WINNER -1 |
| gmin(7,30) = 27 served | 1027 | 1023 (tie, 3 descents) | 1012 | serve+1 alone: tie |
| mem_prime(5,6)+rdr @ (8,30) = prime alone | 1028 | 1024 (600s budget; floor allows 1023) | 1011 | prime alone: no win |
| e1={29,30} (26 served, drain recomposition) | 1024 | 1023 (tie, 18.5k evals) | 1011 | plateau member |
| e1={27,30} / {26,30} | 1024 / 1028 | not searched | 1011 / 1011 | plateau members |
| e1 pairs without g30 ({28,29},{27,28}) | 1031-1033 | — | — | plan-incompat, reject |
| gmin(7,27) = 30 served | 1037 | — | **1018** | floor RISES — reject |
| set e0={5,6}u{8..31} = 28 served (ring-funded adds) | 1028 | — | 1015 | floor rises — reject |
| mem_prime(6,) only | 1026 | — | 1013 | dominated |
| gmin(6,30)/(5,30)/(4,30) (plan-adjusted or unplanned) | 1029-1031 | — | — | reject |
| any e1 < 27 | CRASH | — | — | omf1_vec/b3l private-register wall (hard assert) |
| e0 <= 6 with 4-ring plan | CRASH | — | — | plan collision (entries become structurally funded; fixable by dropping entries) |

Attribution (2x2 clean): the -1 needs BOTH legs. Priming L5+L6 deletes
~184 alu slots (+8 loads, +4 stores) but alone floors at 1011; the relief
FUNDS the P-3 gmin slide (8,30)->(7,30), and only the composition drops
valu 6056 -> 6049 slots = floor 1010. Order re-search then recovers the
same residual regret as baseline (12): 1010 + 12 = 1022. This is G-22's
"+1 at fixed greedy order" candidate converting to -1 exactly as the
re-scoped hypothesis predicted — the first order-conditional mix accept.

### Serve-more-L4 leg: CLOSED at the floor level (greedy spellings)

Every reachable added L4 serve RAISES the any-packing floor: +7.2 valu
slots per served group-round (26->27: 6056->6063; ->30: 6099; floors
1011->1012->1018). The tournament's selects land on saturated valu/alu
under greedy races while the freed loads land 60+ cycles below the
binder. No order search can rescue a raised floor — this closes
serve-more WITHOUT needing per-candidate walks (the floor measurement is
the cheap kill-switch the sweep lacked). Reachability is bounded anyway:
e1 >= 27 (omf1_vec hard wall), e0 >= 7 de-facto (below that, ring-plan
surgery loses 6-8 cycles at every form tried).

### The LP's residual mix prize, localized (flowmax probe)

Forcing ALL flow-capable race sites to their flow spelling (legal by
construction, H-042 soundness) and re-counting engine floors:

| config | valu floor | flow floor | max engine floor | actual cycles |
|---|---|---|---|---|
| baseline greedy spellings | 1010 | 786 | 1010 | 1023 |
| baseline all-flow | 995 | 938 | 995 | 1097 (+74) |
| gmin(7,27) all-flow (serve 30) | 995 | 989 | 995 | 1139 |
| mp56+(7,30) all-flow | **990** | 955 | **990** | 1104 |
| mp56+(7,27) all-flow | 991 | 997 | 997 (flow binds) | 1145 |

The LP's mechanism is REAL at the stream level: at flow-heavy spellings,
serve-more is floor-NEUTRAL (the added selects ride flow, 989 vs valu
995 = the balanced frontier, corsix's ratio again) and priming lowers
the binder to 990. A floor-990 op stream (33 below the 1023 realization)
is flag-reachable TODAY — but its actual schedule is 1104: the entire
prize is locked behind the select-readiness x flow-bubble
anti-correlation (G-4/G-12/H-042), now quantified from the floor side.
Serve-past-27 only makes sense AFTER flow saturation exists (at greedy
spellings it burns valu; at flow spellings it is free). Realized LP
mix prize this iteration: 1 cycle of the modeled ~20.

### Follow-ups (driver)

- F-15 [DONE — see the F-15 section below, mainline is 1022]: the 1022
  config (needed porting
  mem_prime(5,6) + region-hazards + dead-reg staging + gmin (7,30) +
  the new 512-entry emission plan into perf_takehome.py's flag-free
  form; same shape guard as F-12).
- F-16: the omf1_vec e1>=27 wall is the only hard blocker on the e1
  serving axis; funding r15 served groups' private temps (H-048-class
  audited words) would unlock it — but only worth doing after F-17.
- F-17 [the strategic one]: any future flow-cadence mechanism (emission
  machinery that de-synchronizes round cadence from flow windows, N-3
  class) must be evaluated at mp56+(7,30..27)+flow-heavy spellings, not
  at the baseline mix — the floor-990 stream is the right target board;
  baseline-mix evaluation understates the prize by ~15 floor cycles.
- F-18: e1 composition {29,30}/{27,30} tie 1023 after re-search — free
  plateau for drain restructures (H-052 site 3).
- Plans remain config-specific artifacts: h047_best_plan_1022.json is
  measured at its exact config; re-derive after any change (~15 min).

## F-15 (2026-07-27): H-047 mainline port — perf_takehome.py 1023 -> 1022

Ported the verified 1022 config into the flag-free submission, all four
deltas together (the H-047 2x2 says they don't decompose):

1. `l4_gmin` (8,30) -> (7,30).
2. `primed_gather_levels` {5} -> {5,6}.
3. `mem_prime_region_hazards` + `mem_prime_dead_reg_staging` inlined
   unconditionally: priming waves stage through wave-private dead
   registers (`nv[n-1-(k % 8)]` blocks, `st[n-1]` lanes as addresses)
   instead of shared lv[0..23] + the single lv address scalar; their
   vstores drop `mem_write` and each primed level's gathers gate on the
   exact recorded `mem_prime_store_done_cycle[d] + 1` instead.
4. `_EMISSION_ORDER` replaced from tools/h047_best_plan_1022.json (26 of
   512 entries differ from the F-12 plan).

Non-obvious adaptations (only two):

- Delta 3 needed a scheduler change: perf's `ListScheduler` had
  `ignore_mem_read_hazard` but not dev's symmetric
  `ignore_mem_write_hazard`, so that parameter was added to
  `ready`/`emit` (+ docstring) before the priming waves and the primed
  levels' gathers could skip the coarse whole-mem write clock. Dev's
  `mem_prime_min_cycles` is empty at this config, so no per-wave floors
  were ported.
- Delta 2 would have newly broken height-5 builds (the existing
  `L4 < d < forest_height + 1` assert fires on d=6), so the constant is
  written shape-clamped, `{d for d in (5, 6) if d <= forest_height}` —
  identical {5,6} at the graded shape.

No adaptation needed for the parity ring plan: H-047's raw
`parity_ring_plan` addresses (185/193/201, 601-625, 1225/1233/1297) are
exactly what F-6's named-vector derivation already produces, and
`flow_spelling_plan` was empty. No temp-pool or emission-order drift:
1022 on the first build, like F-6/F-12 and unlike F-1.

Gates (each run twice): `perf_takehome.py Tests.test_kernel_cycles`
CYCLES: 1022; `tests/submission_tests.py` 9/9 green, all nine CYCLES
lines 1022. Extra: seeds 1/2/3/7/42/99/123/2026 all correct at 1022,
`test_kernel_trace` (debug vcompares) green. Off-shape sweep at
batch 256 / 16 rounds moved with it, no regressions: h5 1043->1042,
h6 1020->1014, h7 1125 (=), h8 1079->1077, h9 1062->1060.

---

## H-055 (2026-07-27): "shorten the alternating valu<->load chain" — CLOSED NEGATIVE. The premise is false: the chain is worth <= 6 cycles and the -181 joint shadow price is max-of-floors arithmetic, not superadditive chain structure.

Baseline for everything below: mainline/frontier **1022**, `correct: true`
(`tools/h054_common.frontier_kwargs()`); `tests/submission_tests.py` 9/9
green, all nine CYCLES lines 1022. **No dev.py / perf_takehome.py change was
made** — H-055 is entirely measurement. New tools: `tools/h055_chain.py`,
`tools/h055_balance.py`, `tools/h055_preload_oracle.py`.

### 1. The bound stack at 1022 (all reproduced this session)

| bound | cycles | what it relaxes |
|---|---|---|
| realized | **1022** | — |
| greedy with **every RAW/WAW lag set to 0** | **1016** | ALL dependency latency, everywhere |
| valu-slot floor (any packing, G-25 two-sided) | **1009** | packing + order |
| fungible bound (perfect valu/alu respelling) | **1003** | + per-op engine choice |
| all vector ops free (G-26 `free_slot_oracle`) | **993** | the entire compute census |
| load floor (1892 loads / 2) | 946 | — |
| pure critical path (infinite slots) | **516** | all resources |

Census: valu 6052 (floor **1009, the binder**), alu 11761 (981), load 1892
(946), flow 796 (796), store 46 (23).

**Headline: zeroing every dependency lag in the whole kernel buys 6 cycles
(1022 -> 1016).** The rigorous ceiling on chain shortening is 13 (to the
1009 slot floor, which no dependency change can beat without changing the
op multiset); under the current emission order + greedy policy only 6 of
those 13 are latency at all — the other 7 are packing/order friction, which
G-25 (packing) and H-049 (order) already closed.

### 2. The valu<->load "alternation", named and counted (`h055_chain.py cp`)

Critical path = 516 ops over 516 cycles; **708 ops lie on it**. Engine
census ON the CP: valu 498, flow 113, alu 84, **load 10**, store 3.
Transitions on the CP: valu<->flow 149, valu<->alu 87, **valu<->load 15**.

So the alternation exists but is 10 loads in 516 levels. The per-round
steady-state chain (13 dependency levels, e.g. tag (4,4) est 79->91) is:

    ^ fold-in | madd stage0 | >>,^ stage1 | ^ | madd,madd stage2+3 | ^ |
    madd stage4 | >>,^ stage5 | ^ | & parity | vselect (flow, idx_select)
    | madd (2*gaddr + omf) | 8x scalar gather load

i.e. exactly ONE valu->load->valu hand-off per round, 3 levels wide
(parity -> address -> gather). 9 of the 13 levels are the hash.
G-27's reading ("the critical structure ALTERNATES vector compute with
gathers, which is why relieving either engine alone does nothing") is
**not what binds**: the CP is 516 against a 1022 realization — 506 cycles
of slack.

### 3. Why the -181 is not superadditivity (reconciliation of G-27)

Re-ran `tools/h054_shadow.py`. Reading the printed slot counts against each
relaxed machine's OWN floors dissolves the "wild superadditivity":

| machine | valu/alu/load slots | own floors v/a/l/f | max floor | actual |
|---|---|---|---|---|
| baseline | 6052 / 11761 / 1892 | 1009 / 981 / 946 / 796 | **1009** | 1022 (+13) |
| valu 6->8 | 6434 / 9033 / 1892 | 805 / 753 / **946** / 721 | **946** | 1016 (+70) |
| load 2->4 | 6045 / 11865 / 1892 | **1008** / 989 / 473 / 787 | **1008** | 1016 (+8) |
| valu8 + load4 | 6422 / 9449 / 1892 | **803** / 788 / 473 / 699 | **803** | 841 (+38) |

Relieving valu alone re-binds on the load floor (946); relieving load alone
re-binds on the valu floor (1008); the two floors are only 63 apart, so
relieving both drops the *max* by 206. That is a `max()`, not a chain.
**Reachable-by-chain-shortening share of the -181: zero.** Reaching 841
means deleting ~1230 valu slots AND ~950 loads at the current widths — the
valu census is 80% hash (closed G-20/G-24) and the loads are 1 scalar
gather/lane at 0.00% contiguity (closed G-16).

The one knob that runs the valu<->load trade directly is `l4_gmin`
(`h055_balance.py gmin`): each L4 group-round dropped from pair-tournament
service sheds ~3.6 valu + ~59 alu slots and pays +8 loads. Joint floor does
dip (1009 -> 1003 at gmin (20,30)) but realized cycles rise monotonically
(1022 / 1025 / 1033 / 1057 / **1073** / 1089 / 1105 for e0 = 7/8/10/16/20/
24/28), regret 13 -> 75. The floor-equalisation prize is 6 and it is not
realizable. (gmin e0 in {4,5,6,12} asserts on `parity_ring_plan` funding;
e0=32 is `correct:false`.)

### 4. Pair-preload (the user's primary mechanism) — REJECTED, this time with the load cost REMOVED

`tools/h055_preload_oracle.py` rewrites backtrack_sched's exact captured op
stream (whose offline greedy reproduces the real 1022 schedule
cycle-for-cycle) at any subset of the **229 gather sites**, replacing

    par(&) -> A: st = base -/+ par -> 8x load -> fold-in ^        (3 levels)

with the deinterleaved form

    M: base -> 8x load(nv)        [hoisted, parity-free]
       base2 = base-/+1 -> 8x load(nv2)
    par(&) -> vselect(nv, par, nv2, nv) -> fold-in ^              (2 levels)

Note `base` is ALREADY parity-free and already hoisted a full round in the
1022 build (`race_idx_madd` emits it before the parity), so no memory
re-layout is needed at all — the children of a heap node are contiguous, so
the "deinterleaved left/right array" is just `base` and `base+1`. The rewrite
is valu-neutral (the dropped `-` pays for `base2`), costs +1 flow and +8
loads per site, and 16 scratch words per site.

Measured (`sweep`), sites taken from the drain backwards:

| sites | real load engine | **loads made FREE (64-wide oracle engine)** |
|---|---|---|
| 1 | 1027 (+5) | **1023 (+1)** |
| 2 | 1031 (+9) | 1025 (+3) |
| 8 | 1030 (+8) | 1031 (+9) |
| 16 | 1062 (+40) | 1030 (+8) |
| 48 | 1190 (+168) | 1027 (+5) |
| 128 | 1510 (+488) | 1041 (+19) |
| 229 (all) | 1899 (+877) | 1095 (+73) |

**Negative at every subset size even with load throughput removed.** G-18
rejected the general form on load count (+3,472 loads); the sharper
statement now is that the mechanism's *latency* payoff is worth <= 0 because
the CP has 506 cycles of slack. Two supporting facts:
- free load slots schedule-wide = **152** (2*1022 - 1892), and **zero across
  cycles 85-960** (876 consecutive fully-load-saturated cycles;
  `h055_balance.py loadbudget`). The full mechanism needs +1832.
- free scratch = **3 words** (`scratch_next_addr` 1533/1536) and buying 16
  more by shrinking `temp_and_cond_pool_sizes` costs +17 cycles:
  (16,4) 1022 / (15,4) 1039 / (14,4) 1039 / (13,4) 1053 / (12,4) 1051 /
  (16,3) 1049.

### 5. The drain is not latency-bound either (refutes the H-052 premise)

The F-14/H-052 reading was "drain 4 cyc, CP-bound (cpLB >= engLB from
c=996), so latency relief pays most there". Regret profile re-measured at
1022: ramp 4 (c=0,1,2,5), epoch seam 5 (c=812/847/904/918/926), drain 4
(c=995/996/1001/1013) — 13 total, matching F-14's shape. But **zeroing every
dependency lag among the ops placed in cycles 950-1022 (or 980-1022) leaves
the schedule at exactly 1022**. The drain tail is the last group's r14->r15
serial hash (c=988..1019, ~1 op/cycle, machine near-empty); it cannot start
earlier because the valu engine is saturated up to that point in emission
order, not because its chain is long. (Windowed lag-zeroing is not monotone
under greedy — `ramp 0-100` -> 1032, `steady 100-800` -> 1029, both WORSE —
so only the global 1016 and the +0 drain result are load-bearing.)

The ramp's 4 cycles are a **load-bandwidth** ramp, not a chain: cycles 0-5
run load 2/2 (12 const/load slots) while valu takes 0/1/1/3/6/4, because
every valu op needs a scratch word that only the 2-wide load engine can
create. Theoretical minimum deficit (valu usable <= 2c slots by cycle c) is
12 slots = 2 cycles vs today's 24 slots = 4, so the ramp's reachable share
is ~2.

### 6. Re-verified on the NEW mainline (F-13's 1020 order plan) — conclusions unchanged, and stronger

F-13 landed 1022 -> 1020 mid-run. Every H-055 tool takes the plan from
`$H055_PLAN`, so all of the above re-runs on the new stream with one env var
(`H055_PLAN=tools/f13_best_plan_1020.json`). Gate after merge: 9/9 green,
all nine CYCLES lines 1020.

Bound stack at 1020: realized **1020** / **all-lags-zero 1017** / valu-slot
floor **1006** / fungible **1000** / load floor 946 / pure CP **541**.
Census valu 6033 (1006), alu 11695 (975), load 1892 (946), flow 814 (814).
**Chain shortening is now worth 3 cycles globally, not 6** — F-13's order
walk consumed part of the latency slack. Regret 14.

CP at 1020: 541 levels, 719 ops on it, engine census valu 499 / flow 115 /
alu 91 / **load 11** / store 3; **17 valu<->load alternations**. Same shape.

Pair-preload re-run at 1020, real load engine / free-load oracle:
1 site +5 / **+3**; 2 sites +9 / **+2**; 8 +14 / +9; 16 +45 / +9;
48 +173 / +8; 128 +493 / +17; all 229 +883 / +78. **Still positive
everywhere in both columns** — no subset of the 229 gather sites wins even
with load throughput free.

One difference worth recording: zeroing all lags among the drain ops
(c >= 950) now gives **1018 (-2)** where at 1022 it gave +0. So the 1020
drain does have ~2 cycles of genuine latency, but the mechanism that could
buy it (pair-preload) measures +3 at its single best site even with free
loads, i.e. the +1 flow op and the emission-order disturbance already
exceed the prize.

### Verdict / follow-ups

H-055 is **closed negative**, and with it the F-20 axis. The op multiset —
not any dependency structure — is the only remaining lever, and it must move
valu AND load together:
- **F-21**: the reachable envelope at this op stream is 1022 -> 1009 (slot
  floor) / 1003 (fungible). Everything from here is worth <= 19 and is
  order/packing shaped, i.e. F-13's walks.
- **F-22**: to go below 993 the LOAD count must fall (contiguity is 0.00%,
  G-16), and to go below 1009 the VALU count must fall (hash closed G-20/
  G-24, idx closed G-21). Both legs are closed inside this organization —
  consistent with G-23's joint condition. Any future 892-gap work should
  target a different program organization, not this one's schedule.
- **F-23** (tool): `h055_preload_oracle.py`'s rewrite+greedy harness costs a
  structural mechanism in ~2 s without implementing it. Generalize it (edge
  surgery on the captured stream) as the standing pre-screen for any future
  chain/structure hypothesis, alongside `free_slot_oracle` (op-migration)
  and `h054_shadow` (resource).

## H-056 (2026-07-28): re-open the PROGRAM ORGANIZATION — ACCEPTED, strain frontier 1020 -> 1015 (-5), and the first sub-1006 op streams ever measured (LB 996 / 992)

Baseline: mainline **1020** (`tools/f13_best_plan_1020.json` on the H-047
mix); `tests/submission_tests.py` 9/9 green, all nine CYCLES lines 1020 —
re-verified green and unchanged at the end of this session.

**No dev.py and no perf_takehome.py change was made.** The organization is
already fully expressible through the existing `emission_plan` kwarg, so
H-056 is a pure search + measurement result: two new tools and one plan
artifact. Flags-off bit-identity is therefore trivially satisfied.

New tools: `tools/h056_screen.py`, `tools/h056_org.py`.
New artifact: `tools/h056_best_plan.json` (**1015**, `correct: true` at seeds
1/2/3/7/42/99, LB 1003, fungible 998, cp 572, valu 6013 / alu 11761 /
load 1892 / flow 817).

### 0. Why the reopen was justified (and what it found)

G-25..G-29 closed every axis *within* the mainline organization. But every
prior organization experiment (uneven blocks, the external repo's 13-block
shape, the skew sweeps, H-049 phase1's `blocks8`/`blocks13`/`blocks2`) was
measured under a greedy emission order and the pre-H-042 spelling regime.
H-047's precedent (mem_prime(5,6) flipping +1 -> -1 under per-candidate
order re-search) said those verdicts were measured wrong.

They were. **The mainline organization is one of the WORST points in the
organization space by lower bound** (even-4-blocks / stagger-3 /
block-interleave, LB 1013); F-13's 213k-eval order walk spent itself
recovering 1013 -> 1006. Organizations exist whose *unwalked* streams
already sit at LB 996-1005.

### 1. The pre-screen (`tools/h056_screen.py`) — 0.3 s per config

Patches `backtrack_sched.H51_OVERRIDES` in process (and restores it),
captures the exact op stream, and prints the whole bound stack per CONFIG
rather than only for the mainline: realized, per-engine census + floors, CP,
the any-packing `LB`, both energetic staircase bounds, the fungible bound,
the offline-greedy reproduction check, and optionally all-lags-zero and the
full regret profile. Verified against the known mainline numbers on its
first run:

    realized 1020 | LB 1006 | fungible 1000 | all-lags-zero 1017 | cp 541
    valu 6032 alu 11689 load 1892 flow 814 store 46 | model_exact true

At 0.3 s it is cheap enough to screen the LB of *every* candidate, which is
what made the hypothesis tractable: 26k organizations screened in ~20 min.

### 2. The organization sweep (`tools/h056_org.py`) — 28,316 candidates

Axes: block PARTITION (even k | integer-division cut points, i.e. the
external repo's uneven shape | strided/non-contiguous | ramped sizes) x lag
DIAGONAL (uniform stagger and non-uniform) x INTERLEAVE (`block` =
wave-major vs `zip` = group-granular across waves) x wave order x group
order x drain shape (`tail_df`, `stage_rr`). Every candidate reports LB and
grader-verified cycles.

**Best LB per (partition, stagger, interleave) cell**, frontier mix,
`correct: true` only. `cyc` is greedy-realized BEFORE any order search:

| partition | stagger | interleave | best LB | cyc |
|---|---|---|---|---|
| even16 (2 groups/blk) | 1 | zip | **996** | 1029 |
| even16 | 2 | zip | 999 | 1087 |
| **even8 (4 groups/blk)** | **2** | **zip** | **1001** | **1028** |
| cut11 | 2 | zip | 1002 | 1051 |
| cut13 (external shape) | 2 | zip | 1002 | 1071 |
| cut9 | 2 | zip | 1003 | 1036 |
| even4 | 4 | zip | 1005 | 1035 |
| even32 | 1 | zip / block | 1005 | 1087 |
| ramp4 (uneven sizes) | 4 | zip | 1006 | 1026 |
| even16 | 1 | block | 1008 | 1033 |
| even8 | 2 | block | 1010 | 1039 |
| **even4 = MAINLINE SHAPE** | **3** | **block** | **1013** | **1034** |
| cut13 | 3 | block | 1019 | 1150 |

Three clean, monotone findings:

1. **`zip` beats `block` at every partition and every stagger.** Interleaving
   the active waves at GROUP granularity instead of emitting each wave's
   whole block contiguously is worth 2-9 LB cycles everywhere. This is the
   largest single organization lever and it had never been measured at the
   current mix.
2. **Finer partitions on a tighter stagger lower the LB**: 4 blocks of 8 at
   stagger 3 (mainline) -> 8 blocks of 4 at stagger 2 -> 16 blocks of 2 at
   stagger 1 walks LB 1013 -> 1001 -> 996.
3. The LB moves because the **valu census** moves: 6076 (mainline shape,
   default order) -> 6032 (F-13 walked) -> 6003 (even8/zip) -> 5971
   (even16/stag1/zip). Emission order decides the alu-vs-valu race outcomes
   inside `_sched_vec`, so the organization is choosing the op MIX, not just
   the placement. F-13's "orders are mix-specific" has an exact converse:
   **mixes are order-specific, and the organization is the coarse handle.**

Ring-plan confound ruled out by controls: the pinned `parity_ring_plan` is
liveness-timed to the mainline order and silently killed 63% of candidates
(`correct: false`, or an out-of-range gather address). The full sweep was
repeated at `parity_ring_plan=()` (61% correct) and `parity_ring=False`
(96% correct). **The ranking is the same in all three regimes** (noring:
lags(0,4,8,12)/zip LB 1014, f13 1016, even16/stag1 1018, mainline shape
1023) — the finding is not a ring artifact.

### 3. Order walks per candidate (the H-047 discipline) — 1028 -> **1015**

Only candidates with LB <= 1006 earned a walk
(`emission_order_search.py local`, seeded fresh, `EOS_OVERRIDES` = the
frontier mix, `EOS_JUMPS` per F-13/G-29's radius finding).

| seed organization | seed cyc | seed LB | walked | walked LB | regret |
|---|---|---|---|---|---|
| even8/stag2/zip/**rev**/asc | 1028 | 1001 | **1015** | 1003 | 12 |
| even8/stag2/zip/**default**/asc | 1027 | 1003 | **1016** | 1005 | 11 |
| even8/stag2/zip/default/asc (2nd chain, jumps to 32) | 1018 | — | **1016** | 1002 | 14 |
| even8/stag2/zip/**rot:1**/asc | 1025 | 1002 | 1022 | 1001 | 21 |
| even16/stag1/zip/rev/asc | 1029 | **996** | 1023 | 1001 | 22 |
| (control) f13 mainline | 1020 | 1006 | 1020 (G-29: strict 1-move optimum) | 1006 | 14 |

- **1016 is reached by three independent walk chains on two organizations**
  (wave order `rev` and `default` on the even8/stag2/zip partition), each
  `correct: true` at seeds 1/2/3/7/42/99; a fourth chain off the 1016 plan
  reached **1015**. Winning artifact: `tools/h056_best_plan.json` — 1015,
  LB 1003, fungible 998, cp 572, valu 6013 / alu 11761 / load 1892 /
  flow 817.
- The descent is FAST where F-13's was slow: 1028 -> 1020 in ~3 min
  (~2.5k evals), 1020 -> 1017 in ~15 more, 1017 -> 1016 by ~30 min,
  1016 -> 1015 in one more chain. F-13 needed 213k evals for 1034 -> 1020
  on the mainline organization.
  A lower-LB stream is not merely a better floor — it is a
  **better-conditioned order landscape**.
- **RE-SEEDING A FRESH CHAIN AT THE PLATEAU IS THE PRODUCTIVE MOVE.** Every
  single-cycle step (1018 -> 1017 -> 1016 -> 1015) came from restarting a
  new walk chain, with a different RNG seed and a different `EOS_JUMPS` set,
  from the previous chain's best; each chain then plateaued for ~10k evals.
  Wider jump sets kept paying past F-13's `1,2,4,8,16,32`
  (`1,2,3,4,6,8,12,16,24,32` and `1,2,3,5,8,13,21,34` both produced steps).
  The chain stops at 1015: two further fresh chains off the 1015 plan
  (different seeds, `1,2,3,4,6,8,12,16,24,32` and `1,2,3,5,8,13,21,34,55`,
  ~24k evals combined) found nothing below it, so 1015 is where this
  session's budget ran out, not a proven optimum. Total walk spend across
  H-056: ~9 chains, ~75k sim-verified evals.
- Bound stack at the 1015 artifact: realized **1015** / all-lags-zero 1007 /
  valu-slot floor **1003** / energetic 1004 / fungible 998 / cp 572.
  Regret 12 = ramp 4 + mid 2 + drain 6 (the mainline's was 14 = 4/6/4):
  the organization change ate the mid/seam band that F-13 fought for, and
  the residue is now ramp+drain, which G-28 characterised as load-bandwidth
  and valu-saturation respectively.
- LB drift to watch: the even16/stag1 stream enters at LB 996 but the walk
  pulls it back to LB ~1001 — order walks optimise realized cycles and will
  spend floor to get them.

### 4. The deeper-organization config axes — closed on cycles, two record LBs

Screened on both the mainline and the walked even8/zip plan (184 configs):
tournament depth, L4 serving sets, priming levels, scratch pool sizes, store
order, reverse-newest-parity-fold rounds, ring extras, idx_boundary_select,
lazy_val_loads.

- **Nothing beats the incumbent on realized cycles on either plan.**
  `tournament_levels` (1,2) and (1,2,3,4) both assert out under mem_prime
  ("mem_prime stages through the full-width lv scratch"); (1,2,3) is the
  incumbent. `prime(5,6)`, `pool(16,4)`, `store_group`, `revfold(15,)` are
  each the local optimum on BOTH plans — H-047/H-055 confirmed under the new
  organization, i.e. those closures survive the reopen.
- **But the LB axis is alive here too, and it COMPOSES with the
  organization**: on the even8/zip organization `l4_gmin(16,32)` gives
  **LB 992** (realized 1062) and `revfold()` gives LB 999 (realized 1029).
  992 is the lowest bound ever measured on this kernel's real op stream —
  10 below the walked stream and 14 below the mainline. As in H-055's gmin
  table, realized cycles rise monotonically with gmin, so this is a *bound*,
  not a schedule; it is the correct input to the next round.
- pool sizes: `(15,4)`, `(17,3)`, `(18,3)` all reach LB 1001-1003 on the
  even8/zip plan at 1027-1028 realized; `(16,4)` stays the cycle optimum.

### 5. Answer to the gating question, and the new envelope

**Yes — streams below LB 1006 exist, in quantity.** Lowest bounds found:

| stream | LB | realized | note |
|---|---|---|---|
| even8/zip + l4_gmin(16,32) | **992** | 1062 | lowest bound ever measured here |
| even8/zip + l4_gmin(16,31) | 994 | 1059 | |
| even16/stag1/zip/rev/asc | **996** | 1029 | unwalked, `correct: true` |
| even8/zip + l4_gmin(16,30) | 996 | 1056 | |
| even8/zip + revfold() | 999 | 1029 | |
| **even8/zip walked (the artifact)** | **1003** | **1015** | the accept |
| f13 mainline | 1006 | 1020 | previous incumbent |

Envelope at the new frontier: realized **1015** / valu-slot floor **1003** /
fungible **998**. G-28's "1020 -> 1006, everything left is <= 20 cycles and
order/packing shaped" is superseded: the organization axis moved the FLOOR
itself, which nothing in G-25..G-29 could do, and the reachable band is now
1015 -> 1003 with a demonstrated 992-floor stream in hand.

### 6. Follow-ups (ranked)

- **F-24 (mainline port, do this first)**: 1015 needs NO code change — bake
  `tools/h056_best_plan.json`'s order into `perf_takehome.py` exactly as
  F-13 baked the 1020 plan. -5 for a literal swap.
- **F-25**: walk the LB-996 (even16/stag1/zip) and LB-992
  (even8/zip + gmin(16,32)) streams properly. They got 45 min and 0 min
  respectively; 1015 came out of ~75 min on a stream 5-7 LB cycles worse.
- **F-26**: the ring plan is re-derivable per organization. The pinned
  `parity_ring_plan` is worth 6 cycles ON THE MAINLINE ORDER and was carried
  unchanged onto every new organization (where it also broke 63% of
  candidates). Re-mining it for even8/stag2/zip is untried, worth up to ~6.
- **F-27**: order walks with a lexicographic (LB, cycles) objective — the
  current walk spends floor for cycles (996 -> 1001 above). `h056_screen`
  makes LB as cheap as a measurement, so this is a one-line objective change.
- **F-28**: the organization x config CROSS is barely touched. Only gmin,
  priming and pool sizes were crossed with the winning organization;
  `parity_ring_plan`, `flow_spelling_plan` (site numbering is
  order-specific and was left EMPTY throughout H-056 — the H-042 spelling
  prize has never been re-derived on this organization) and the
  tie-break/race knobs were not.
- **G-29 must be re-read as scoped**: it closed 1-move order search *at the
  mainline mix* and explicitly said "reopen-if the MIX changes". The
  organization changes the mix, so a fresh exhaustive 1-move scan
  (`tools/f18_exhaust1.py`) at the 1015 plan is cheap and unrun.

## F-25 (2026-07-28): re-mine the ring plan and the spelling plan for the H-056 organization — ACCEPTED, strain frontier 1015 -> **1011** (-4). The ring plan was stale; the spelling plan is (still) empty; the order was already 1-move optimal at BOTH ends.

Baseline: `tools/h056_best_plan.json` = 1015 (reproduced, `correct: true`),
mainline 1015, gate 9/9 green (re-verified green and 1015 at the end —
**no dev.py and no perf_takehome.py change was made**; the whole result is
config artifacts, so flags-off bit-identity is trivially satisfied).

New artifacts: `tools/f25_best_plan.json` (**1011**, order + full mix incl.
the re-mined 23-ring `parity_ring_plan` and `l4_gmin=(6,30)`),
`tools/f25_spell_plan_1011.json` (the re-derived spelling plan: **empty**).

### 1. `f18_exhaust1` verdict at 1015 — STRICT 1-move optimum (G-29 re-closed at the new mix)

Every valid single-entry displacement of the 1015 plan, radius unbounded by
construction: **25,637 moves, ZERO below 1015**. 17,336 (68%) measure exactly
1015 (the plateau is even bigger than G-29's 55%), 2,102 break correctness
(ring-borrow windows). So H-056's "1015 is where budget ran out" is answered:
1015 is a genuine 1-move local optimum, and the remaining prize was NOT in
the order at that mix.

### 2. The ring plan WAS stale — but its value at 1015 was ZERO, not 6

Re-audit at the H-056 organization (`tools/audit_ring_windows.py` driven at
`emission_plan` = the 1015 order, `parity_ring_plan=()`): **22 fundable
windows / 528 words** under the H-048 structural-donor rule (vs 16 rings /
384 words at the old organization), and iterating audit -> add -> re-audit
reaches a fixpoint at **23 plan rings = 552 borrowed words** (43 rings total
with the 20 structural slices), all passing the closed-loop donor-safety
recheck.

70-candidate composed sweep at the 1015 order (singles, leave-one-out,
e0/e1/prize-6 subsets, incumbent+1, full):

| ring plan | cycles | ops | valu | flow | LB | fungible |
|---|---|---|---|---|---|---|
| `parity_ring=False` | 1024 | 20763 | 6074 | 822 | 1013 | 1009 |
| `parity_ring_plan=()` (20 structural rings) | **1015** | 20554 | 6016 | 823 | 1003 | 999 |
| the pinned H-048 4-ring plan (incumbent) | **1015** | 20529 | 6013 | 817 | 1003 | 998 |
| re-mined 22 rings | **1015** | 20438 | 5987 | 792 | **998** | 994 |
| re-mined 23 rings (fixpoint) | **1015** | 20442 | 5983 | 784 | **998** | 994 |

Every one of the 70 candidates measured 1015. **The carried-over 4-ring plan
was worth exactly 0 cycles at the walked 1015 order** (its 6-cycle valuation
belongs to the mainline order it was mined on), and deleting 116 more ops
with a 23-ring plan also bought 0 realized cycles — it bought **5 cycles of
FLOOR** (LB 1003 -> 998, fungible 999 -> 994). At a strict 1-move optimum
with a 68% plateau, op deletion alone converts at zero.

### 3. What converted the floor: the P-3 serving slide, then a re-walk

Ring plans are gmin-specific (gmin decides which groups are *structurally*
ringed, so a plan mined at another gmin collides on keys), so the plan was
re-derived per gmin (`f25_gmin_audit`, audit-to-fixpoint per point) and each
point measured at the 1015 order:

| l4_gmin | rings | cycles | note |
|---|---|---|---|
| (6,30) | 23 | **1014** | new optimum, LB 998, fungible 994 |
| (7,30) | 23 | 1015 | H-056's mix |
| (5,30) | 22 | 1017 | LB 1001 |
| (6,29) / (6,31) | 23 | 1018 / 1019 | |
| (7,29) / (7,31) | 23 | 1019 / 1020 | (7,31) is **LB 995 / fungible 992** |
| (6,28) / (4,30) / (5,29) | 23/22/22 | 1021 | |
| (>=8, any) | 22 | — | audit-derived plans FAIL the closed-loop recheck; rejected unmeasured |

P-3 pattern, **fourth confirmation**: retention relief slides the serving
mix, here (7,30) -> (6,30). Then the order walk on the (6,30)+23-ring stream
descended 1014 -> 1013 -> 1012 -> **1011** in ~17k evals (~11 min) — on a
stream whose predecessor had just been proven 1-move optimal. Two further
fresh chains (different seeds, `1,2,3,5,8,13,21,34,55`, ~40k evals) found
nothing below 1011.

### 4. Ring plans are ORDER-specific too (a new soundness fact)

Re-running the closed-loop audit at the *walked* 1011 order with the plan
mined at the 1015 order: **40 LIVE-ACROSS violations over 43 rings**
(donors `st10` for ring (0,5), `nv4` for ring (1,13)) — the walk moved
entries so that donor live ranges came to span two ring windows. The config
still measured `correct: true` on 8 seeds, i.e. **the grader did not catch
it** — exactly the H-048 unsound-borrow failure mode, but silent this time.
Re-mining the plan at the 1011 order gives a different 23-ring assignment
(different donors for (0,4)/(0,5)/(0,18)/(0,23), (0,20)+(1,0) added,
(0,21)+(1,13) dropped) that passes the recheck **OK over 43 rings** and
measures the same 1011. Rule to carry forward: **after every order walk,
re-mine the ring plan and re-run the audit; seed-correctness is NOT a
substitute for the window audit.**

**The same check FAILS on the incumbent 1015 artifact** (`h056_best_plan.json`,
i.e. what mainline now runs): audited at its own order, the carried H-048
4-ring plan shows **16 violations over 24 rings** — ring (0,6) borrows
(609,617,625) and donors `st9`/`st11` are live across its window. Caveat on
severity: the audit's window is the span of ALL ops tagged with rounds 0-4
of the group, a strict SUPERSET of the ring's real accesses, so a violation
can be a false positive (and here the frozen grader is green on every seed
and the full gate is 9/9). But H-048 paid for this rule with a real
miscompare, and **at that order the 4-ring plan is worth zero cycles**
(section 2), so the cheap de-risking move is to drop it: `parity_ring_plan=()`
at the 1015 order measures 1015 and audits **OK over 20 rings**.

### 5. Spelling plan: re-derived at this organization, still EMPTY

`tools/spelling_plan_search.py` at the 23-ring/(6,30)/1011 point:
- flow-race sites only: zero-flip fixpoint (sweep 1 exhausted, 1011 -> 1011);
- `H042_AUX=1` (all valu<->alu negative-key race sites too): zero-flip
  fixpoint (283 s sweep, 1011 -> 1011);
- same at the 1015 point (flow: 140 s, aux: 324 s), also empty.

So H-047's zero-flip fixpoint and H-054's shadow-price-0 **do transfer**
across the organization change, even though H-056 showed the organization
moves the race OUTCOMES. Four independent derivations now: the per-site
spelling prize on this kernel is zero.

### 6. The accepted point (all measured, `correct: true`)

    parity_ring=True  l4_gmin=(6,30)
    c5_primed_gather_levels=(5,6) mem_prime_region_hazards=True
    mem_prime_dead_reg_staging=True  flow_spelling_plan=()
    parity_ring_plan = 23 rings (tools/f25_best_plan.json)
    emission_plan    = tools/f25_best_plan.json         -> **1011**

Verified: seeds unseeded x2, 1, 2, 3, 7, 42, 99 all 1011 `correct: true`,
and again with `debug_compares=True` (all 1011). Bound stack at the winner
(`h056_screen --lags-zero --regret`):

    realized 1011 | all-lags-zero 1002 | valu-slot floor 997 |
    energetic 999 | fungible 993 | cp 558
    ops 20400: valu 5982 alu 11681 load 1884 flow 807 store 46
    regret 14 = ramp 4 + mid 4 + drain 6   (H-056's 1015: 12 = 4/2/6)

Second exhaustive 1-move scan, now at the 1011 plan: **25,641 moves, ZERO
below 1011**; 14,513 (57%) plateau, 3,941 break correctness (571 of them
fail to build at all — ring asserts). 1011 is again a strict 1-move optimum.

Leave-one-out at the winner (the ring plan's marginal value AT the walked
point): `()` = 1015, full 23 = 1011, i.e. **-4**; the load-bearing rings are
(1,22) (-2), (0,3) and (0,5) (-1 each), the other 20 are individually free.
Note `loo:(0,25)` measures `correct: false` — dropping ONE ring shifts the
stream enough to invalidate another ring's borrow, so a plan is an
all-or-nothing artifact, not a menu.

### 7. Was the "~6 cycles" there?

Partly, and not where H-056 predicted. The re-mined ring plan is worth
**-4** (1015 -> 1011) but ONLY as a three-step composition: (a) 23 rings buy
floor, not cycles (LB 1003 -> 998); (b) the floor funds a serving-mix slide
to gmin (6,30), worth -1; (c) the changed stream re-opens the order
landscape, worth -3 more from a point that was provably 1-move optimal. The
spelling leg is worth **0** and is now closed at this organization too.

### 8. Follow-ups

- **F-29 [mainline port]**: 1011 needs NO code change beyond what F-6
  already ported — bake `tools/f25_best_plan.json`'s order + the 23-ring
  plan + gmin (6,30) into `perf_takehome.py` (port note from F-6 still
  applies: derive donor addresses from the named vectors, not hard-coded
  layout constants). -4 for a literal swap.
- **F-30**: the (7,31)+23-ring stream sits at **LB 995 / fungible 992** and
  was never walked (it measures 1020 greedy). Same shape as the LB-996/992
  streams H-056 left unwalked; the F-25 loop (audit -> gmin slide -> walk ->
  re-audit) is the recipe.
- **F-31**: 21 windows remain unfundable at every gmin tried — their free
  words are `anon:23` only, and `anon` is excluded by the H-048 structural
  rule. Deciding whether any anon class is schedule-independent (i.e. is
  provably not an emit_any race operand) would unlock the remaining ~1/3 of
  full retention.
- **F-32 [de-risk, free]**: mainline's 1015 stream contains an unaudited
  borrow (section 4). Dropping `parity_ring_plan` there is cycle-neutral and
  makes the stream audit-clean; if F-29 lands 1011 first this is moot, since
  the 1011 artifact's plan is re-mined and clean.
- The **audit-after-walk** rule in section 4 should be applied to every
  existing artifact that pairs a walked order with a plan mined elsewhere.

## F-29 (2026-07-28): F-25 mainline port — perf_takehome.py 1015 -> 1011, and the ring-borrow defect is gone

Ported the verified F-25 frontier into the flag-free submission, three
coupled edits (the plan is only worth 1011 as a unit):

1. `_EMISSION_ORDER` <- F-25's 512 entries (bit-for-bit equal to
   `tools/f25_best_plan.json`'s `plan`; all plain `(r, g)`).
2. `l4_gmin` (7,30) -> (6,30).
3. `build_parity_ring_map`'s appended plan: H-048's 4 rings -> F-25's
   **23** rings. Per F-6 house style no raw addresses are baked; each
   donor is derived from its named vector, verified equal to the audited
   raw addresses in `params.mix.parity_ring_plan` by instrumenting
   `alloc_scratch` (all 23 triples matched exactly). Mapping:

       (0, 3)  st6, st7, st14        (1, 0)  st4, st25, nv31
       (0, 4)  st9, st10, st11       (1, 4)  st0, st3, nv10
       (0, 5)  lv+16, st8, st12      (1,11)  st4, nv2, nv3
       (0,13)  st23, nv17, nv18      (1,12)  root_nv_vec, lv, st19
       (0,14)  nv20, nv22, nv23      (1,14)  st8, st18, st22
       (0,15)  lv, lv+8, nv31        (1,15)  st11, st20, nv5
       (0,18)  st27, nv24, nv27      (1,21)  st9, st10, st26
       (0,20)  st29, st30, st31      (1,22)  st12, st13, nv14
       (0,23)  lv+16, nv29, nv30     (1,23)  root_nv_vec, lv, lv+8
       (0,25)  lv, lv+8, nv31        (1,27)  lv+16, st16, st17
       (0,30)  st1, st2, nv0         (1,28)  st0, st1, st2
                                     (1,29)  st18, st19, st20

   New named donor class vs F-6: `root_nv_vec` (the primed root's
   broadcast vector), epoch-1 only. `lv+24` (two_minus_fp_vec) still
   untouched; donors remain structural classes only (st/nv/lv/root_nv).
   The code comment records that the plan is ORDER-SPECIFIC and
   ALL-OR-NOTHING (F-25: leave-one-out of (0,25) alone miscompiles).

`flow_spelling_plan` stays empty (F-25 re-derived it as empty at this
order; F-9's pin was already reverted by F-12). No other edit.

**Defect fixed.** `tools/audit_ring_windows.py`, run at each config's
exact dev flags:

- pre-port mainline (H-056 order + H-048's 4-ring plan, gmin (7,30)):
  **16 LIVE-ACROSS violations over 24 rings** — donors st9/st11 of ring
  (0,6), which H-056's reorganization invalidated while carrying H-048's
  plan forward unchanged. That plan was worth ZERO cycles at that order.
- ported mainline (F-25 order + 23-ring plan, gmin (6,30)):
  **OK over 43 rings**, zero LIVE-ACROSS lines.

**Equivalence proof.** The ported mainline's emitted bundle stream is
BIT-IDENTICAL to `dev.py`'s under the F-25 config (1011 bundles each,
`main.instrs == dev.instrs`), so the named-vector derivation and the
mix are exactly the measured artifact — no re-derivation drift.

Gates (each run twice): `perf_takehome.py Tests.test_kernel_cycles`
CYCLES: 1011, 1011; `tests/submission_tests.py` 9/9 green with all nine
CYCLES lines 1011, both runs. Ten-seed sweep (0/1/2/3/7/42/99/123/2026/
31337) via `do_kernel_test`: 1011 and correct on every seed, with the
debug/vcompare path LIVE (`perf_takehome`'s own harness leaves
`enable_debug=True`, so every node_val/hashed_val vcompare slot is
checked against the reference trace). No divergence.

F-32 is now moot, as anticipated: the 1015 stream's unaudited borrow is
gone with the stream itself.

## F-24 (2026-07-28): walk the low-LB organization streams — 1015 -> **1011**, but F-25/F-29 reached 1011 independently in parallel (section 6), so this is a TIE ON CYCLES and an ACCEPT ON METHOD; H-056's "LB 992" is an ARTEFACT of reading the wrong bound, and the real lever is a NON-UNIFORM lag diagonal

Baseline: mainline **1015** (`tools/h056_best_plan.json` baked into
`perf_takehome.py`'s `_EMISSION_ORDER`); `tests/submission_tests.py` re-run
green at the end of this session, all nine CYCLES lines 1015.

**No dev.py, no perf_takehome.py and no shared-tool change.** Like H-056 the
whole result is expressible through `emission_plan`, so the port is again a
512-tuple literal swap. New artifacts: `tools/f24_best_plan_1011.json`
(the accept), `tools/f24_best_plan_1012.json` (an independent second
organization below 1015), `tools/f24_seed_even16_stag1.json`,
`tools/f24_seed_even8_rev.json` (H-056 stream seeds, reproduced exactly:
1029 / 1028).

### 1. The headline correction: read LB_energetic, not LB

H-056 ranked its streams on `lb_total` (the any-packing slot/CP bound) and
handed F-24 an "LB 992" stream as the top prize. `h056_screen` already
computes the two ENERGETIC STAIRCASE bounds, which are equally valid for any
packing, and on exactly those streams they are far higher:

| stream | LB | **LB_energetic** | fungible | realized |
|---|---|---|---|---|
| even8/zip + l4_gmin(16,32) | 992 | **1011** | 990 | 1070 |
| even16/stag1 + l4_gmin(16,32) | **991** | **1011** | 990 | 1069 |
| 1015 plan + l4_gmin(16,32) | 995 | **1011** | 990 | 1058 |
| 1015 plan + l4_gmin(16,31) | 997 | 1007 | 986 | 1055 |
| even16/stag1/zip/rev/asc | 996 | **997** | 991 | 1029 |
| even16/stag1 + revfold() | 994 | **996** | 989 | 1037 |
| even8/stag2/zip/rev/asc | 1001 | 1002 | 994 | 1028 |
| 1015 mainline plan | 1003 | 1004 | 998 | 1015 |

**Every l4_gmin>=16 stream has an energetic bound of 1007-1015.** gmin 16
trades 66-88 extra loads for ~50 fewer valu slots: it lowers the *slot* floor
and raises the *release-staircase* floor, so the low `lb_total` is real but
unreachable. The LB-992 stream can therefore never beat 1011 — which is what
this session reached WITHOUT it. Re-confirmed on the new winning
organization (`l4_gmin` re-sweep, section 4): gmin(16,32) there is
LB 993 / **energetic 1011** / realized 1054.

Practical consequence: **rank organization candidates on
`max(LB, stair_release, stair_tail)`, never on `lb_total` alone.** H-056's
section-5 table is invalid as a priority list.

### 2. Walking the H-056 streams (the assigned job) — 1019 / 1026, and a 94% plateau

`emission_order_search.py local` under chained re-seeding (fresh RNG seed +
fresh `EOS_JUMPS` + fresh window per chain, per H-056's tactic).

| stream | LB / LB_e | seed cyc | evals | best | walked LB / LB_e | regret (ramp/mid/drain) |
|---|---|---|---|---|---|---|
| even16/stag1/zip/rev/asc | 996 / 997 | 1029 | 22,519 | **1019** | 994 / 995 | 25 = 4/12/9 |
| even16/stag1 + revfold() | 994 / 996 | 1037 | 18,078 | 1026 | 995 / 996 | 31 = 4/19/8 |
| l4_gmin(16,32) ("LB 992") | 993 / 1011 | 1054 | 5,193 | 1054 (**zero moves**) | — | 55 |

- The LB-996 stream descends 1029 -> 1022 in 2 min / 1.5k evals and 1029 ->
  1019 in ~20 min, versus H-056's 45 min to 1023 — the "lower LB = better
  conditioned" finding holds. But it then STOPS at 1019.
- **`tools/f18_exhaust1.py` at the 1019 plan: 12,000 of the 25,575 valid
  single-entry displacements measured, ZERO below 1019, and 10,418/11,077
  correct neighbours (94%) measure exactly 1019.** G-29's plateau was 55% at
  the mainline mix; on this stream the 1-move neighbourhood is nearly flat.
  Order search on a fixed organization saturates almost immediately here.
- The gmin(16,32) stream is *rigid*: 5.2k evals over three re-seeded chains
  moved it not one cycle off 1054. Its regret is 55 and 35 of it is in the
  RAMP (the extra 88 loads have to drain before anything else starts), which
  no reordering of the 512 group-emissions can touch.
- **Contrary to H-056's "walks spend floor for cycles"**: these walks LOWERED
  the LB (996 -> 994). That warning does not generalize.

### 3. What actually paid: cheap greedy-cycle organization search

The organization, not the order, is the live axis — but H-056 swept it at
~4 s/candidate because it LB-screened every one. A plain grader `measure` is
**0.20 s**, so ranking on greedy cycles first and LB-screening only the
survivors sweeps the space 20x wider (scratch driver, elitist perturbation of
the lag diagonal at a k-block even partition x wave/group order x
interleave):

**29,296 organizations screened in ~28 min** (H-056: 28,316 in ~20 min *with*
LB, but only over structured/uniform diagonals).

The finding: **the lag diagonal should be NON-UNIFORM.** Every organization
H-056 measured used a uniform stagger (`lags = s*b`); the whole low-greedy
frontier here is irregular.

| k | lag diagonal | wave/group | greedy | LB / LB_e | walked |
|---|---|---|---|---|---|
| 8 | (0,3,6,6,10,10,13,14) | default/asc | **1021** | 1002 / 1003 | **1011** |
| 8 | (1,3,6,6,10,11,13,15) | rev/asc | 1020 | 1002 / 1003 | **1012** |
| 8 | (0,3,6,6,10,11,13,15) | rev/asc | 1019 | — | 1014 |
| 8 | (1,3,7,5,9,10,13,14) | rot:1/asc | 1022 | 1000 / 1001 | 1015 |
| 16 | (0,0,1,3,4,7,5,6,8,10,10,10,12,13,14,15) | rev/rot:4 | 1022 | 997 / 998 | 1018 |
| 16 | (0,1,0,3,4,5,6,7,9,9,10,11,12,13,14,15) | rev/asc | 1026 | 998 / 999 | 1018 |
| 8 | (0,2,4,6,8,10,12,14) = H-056 uniform stag2 | rev/asc | 1028 | 1001 / 1002 | 1015 (H-056) |
| 16 | (0,1,..,15) = H-056 uniform stag1 | rev/asc | 1029 | 996 / 997 | 1019 |
| 32 | any | any | >=1087 | — | — |

Three facts:

1. **Greedy cycles predict the walk outcome far better than LB does.** The
   two best-LB streams (996/997) walk to 1018-1019; the best-GREEDY streams
   (1019-1022, LB 1000-1002) walk to 1011-1015. Regret is not a constant to
   be subtracted from a floor — a stream whose greedy schedule is already
   tight is a stream whose order landscape has somewhere to go.
2. **k=8 beats k=16 beats k=32** once the diagonal is free. H-056's
   "finer partition + tighter stagger lowers LB" is true and misleading: the
   16-block streams have the lower floors and the worse realized schedules.
3. The winning diagonals all share the shape (0,3,6,6,10,10,13,14): a
   *repeated* lag (two blocks entering the pipeline on the same step) around
   positions 3-6, then a wider gap. Uniform stagger-2 (0,2,4,...,14) is 7
   greedy cycles worse.

### 4. The accept — 1011

`tools/f24_best_plan_1011.json`: 8 blocks of 4 groups, lags
(0,3,6,6,10,10,13,14), `zip` interleave, `default` wave order, `asc` group
order; seed greedy 1021, then ~57k chained walk evals.

- **`correct: true` at seeds {unseeded,1,2,3,7,42,99}** and additionally with
  `debug_compares=True` at {unseeded,1,42}; 1011 at every seed.
- Bound stack: realized **1011** / LB 1000 / energetic **1002** /
  fungible 997 / cp 490. Census valu 6000 / alu 11793 / load 1892 / flow 823
  / store 46.
- **Regret 11 = ramp 4 + mid 4 + drain 3** (mainline 1015 was 12 = 4/2/6;
  H-056's even8 seed was 27 = 4/14/9). Regret jumps: cycles 0,1,2,3 then
  805, 825, 903, 916, 985, 990, 1002 — the ramp-4 is the same irreducible
  fill G-28 characterised, and the rest is now a thin scatter over the last
  200 cycles rather than a band.
- **Port dry-run passed**: a scratch copy of `perf_takehome.py` with only the
  `_EMISSION_ORDER` literal replaced grades **1011, correct** at seeds
  {unseeded,1,42}. The mainline port is a pure literal swap, no code change.
- **`l4_gmin` re-sweep at the new organization** (6..9 x 29..31 and the
  14..17 x 30..33 region): **(7,30) is still the optimum** — (7,31) 1014,
  (8,30) 1015, (7,29) 1018, (8,31) 1018, (9,30) 1019, (16,30) 1047,
  (16,32) 1054. The H-047/H-055 gmin closure survives the organization
  change; only the *bound* moves with gmin, never the schedule.
- Second, independent organization below the mainline:
  `tools/f24_best_plan_1012.json`, lags (1,3,6,6,10,11,13,15) rev/asc, 1012,
  `correct: true` on the same seed set, LB 1001 / energetic 1002, regret
  11 = 4/2/5. Two different diagonals beating 1015 is the reproducibility
  check that 1011 is not a lucky chain.
- 1011 is where the budget ran out, not an optimum: it survived ~35k further
  evals across 12 re-seeded chains (all jump sets 1..55, all windows).

Total spend: 176,167 sim-verified walk evals across 9 streams + 12,000
exhaustive 1-move evals + 29,296 organization screens.

### 5. Envelope and follow-ups

Envelope at the new frontier: realized **1011** / energetic floor **1002** /
fungible 997. The reachable band is 1011 -> 1002, and the 992-floor story is
withdrawn (section 1).

- **PORT STATUS**: mainline reached 1011 independently via F-25/F-29 while
  this ran (section 6), so the F-24 plan is a TIE on cycles, not a -4, and
  should NOT be ported on its own. Its value is the organization + the
  method, which are the input to F-30.
- **F-30**: the non-uniform-diagonal search is 30k evals old and still
  producing new bests (1022 -> 1021 -> 1020 -> 1019 greedy across four runs).
  Sweep it properly, including uneven block SIZES crossed with the
  irregular diagonal (never combined), and walk the top 5 rather than the
  top 1-2. This is where the next -3..-5 is.
- **F-31**: `parity_ring_plan` and `flow_spelling_plan` are still H-056's
  (and F-25 is re-mining them at the 1015 organization). Both are
  order-specific; they must be re-derived at the 1011 diagonal.
  `flow_spelling_plan` has been EMPTY since H-042 — worth up to ~6.
- **G-29 restated for this organization**: the 1-move neighbourhood is 94%
  neutral at 1019 on the even16 stream, so "the walk plateaued" carries no
  information about the organization's potential. Judge organizations by
  greedy cycles, walk them, and move on.
- **Do NOT spend more on l4_gmin>=14 streams.** Energetic bound 1007-1015,
  ramp-dominated regret, and provably zero order sensitivity (5.2k evals,
  zero moves). Closed.

### 6. Collision with F-25/F-29: 1011 reached TWICE, by two independent routes

While F-24 searched, F-25/F-29 landed mainline **1011** from the H-056
even8/stagger-2 organization by re-mining the parity ring plan (23 rings),
sliding `l4_gmin` to (6,30) on the resulting relief, and re-walking. F-24
reaches the same 1011 from a different direction: the H-045 4-ring plan and
`l4_gmin(7,30)` unchanged, on a new non-uniform 8-block diagonal. Measured
cross:

| f24 organization + | cycles | note |
|---|---|---|
| carried 4-ring plan, gmin(7,30) | **1011** | the F-24 accept |
| no ring plan at all, gmin(7,30) | 1012 | the carried plan is worth 1 here |
| gmin(6,30), no ring plan | 1015 | F-25's serving slide does NOT transfer |
| F-25's 23-ring plan (carried) | asserts | "(0,3) already ring-funded" |
| ring plan RE-MINED at this order (20 rings), gmin(7,30) | 1016 | before re-walk |
| ...same, after 37k re-walk evals | 1011 | ties, no gain |

- **F-25's soundness defect does NOT reproduce here.** `audit_ring_windows`
  at the F-24 order with the carried 4-ring plan: **OK, 0 violations over 24
  rings** (F-25 found 16 live-across violations over 24 at the 1015 order).
  The carried plan happens to be legal on this diagonal — but the standing
  rule stands, and this was checked rather than assumed.
- The ring plan is **order- AND gmin-specific**: every re-mined plan asserts
  out at a different `l4_gmin` ("already ring-funded"), because the set of
  auto-funded rings moves with the serving mix. Re-mine and re-slide
  together or not at all.
- More rings is NOT better: 20 re-mined rings cost +5 against 4 carried ones
  at this order before re-walking, and only recover to a tie after.
- **The two 1011s are not additive as tested.** The open question — and the
  right next hypothesis — is the JOINT chain from the F-24 diagonal:
  re-mine rings, re-slide gmin under the resulting relief, re-walk the order,
  iterate. F-25 got -4 out of exactly that chain at a worse organization.

## H-057 (2026-07-28): the F-25 joint chain run on F-24's non-uniform diagonal — ACCEPTED, strain frontier 1011 -> **1006** (-5), and a second independent diagonal at 1007

Baseline: `tools/f24_best_plan_1011.json` = **1011** (reproduced exactly,
`correct: true`); mainline `perf_takehome.py` = 1011 (F-25/F-29's different
organization). **No `dev.py`, no `perf_takehome.py` and no shared-tool
change** — the whole result is config artifacts again.

New artifacts: `tools/h057_best_plan_1006.json` (the accept: order + full
`params.mix` incl. the re-mined 20-ring `parity_ring_plan`, `l4_gmin=(6,31)`
and the empty `flow_spelling_plan`) and `tools/h057_best_plan_1007.json`
(a second, independent diagonal that also beats 1011).

### 1. The chain, stage by stage (workstream A)

Every stage measured on the frozen grader; bounds from `h056_screen`.

| stage | config | cycles | LB | energetic | fungible | cp |
|---|---|---|---|---|---|---|
| base (F-24 accept) | 4 carried rings, gmin (7,30) | **1011** | 1000 | 1002 | 997 | 490 |
| + rings re-mined at that order | 20 rings (fixpoint), gmin (7,30) | 1016 | 995 | 997 | 992 | 491 |
| + gmin re-slid on the relief | 20 rings, gmin **(6,31)** | 1014 | 997 | 998 | 993 | 492 |
| + order re-walked (chained) | same mix, walked order | **1010** | 994 | 995 | 991 | 486 |
| + walk -> re-mine -> walk (x2) | 20 rings, gmin (6,31) | **1006** | 995 | 996 | 992 | 512 |
| + spelling plan re-derived | `flow_spelling_plan=()` | 1006 | 995 | 996 | 992 | 512 |

**P-3 confirmed a fifth time, and F-25's causal chain reproduces exactly on a
different organization**: 20 re-mined rings buy 5 cycles of FLOOR
(LB 1000 -> 995) and ZERO realized cycles (they cost +5 up front,
1011 -> 1016); the floor then funds a serving slide (7,30) -> **(6,31)**;
and the changed stream re-opens an order landscape that F-24 had walked to
exhaustion. Net **-5**.

- gmin sweep at the base order with the ring plan RE-MINED to fixpoint per
  point (plans are gmin-specific — a plan mined at another gmin collides on
  keys and asserts "already ring-funded"): (6,31) 1014, (7,31)/(6,30) 1015,
  (7,30)/(5,31) 1016, (5,30) 1017, (7,29) 1018, (4,31) 1019.
  **gmin >= 8 audit-derived plans FAIL the closed-loop recheck** (40-80
  live-across violations) at every order tried — the same wall F-25 hit.
- Re-swept gmin twice more (at the walked 1010 order and at the final 1006
  order, 5..8 x 29..32, re-mining per point): **(6,31) stays the optimum**,
  and at the 1006 order every other gmin makes the incumbent plan ASSERT.
  The gmin leg is at a fixpoint.
- `l4_gmin` moved (7,30) -> (6,31) here versus (7,30) -> (6,30) in F-25:
  the slide DIRECTION is organization-dependent, the EXISTENCE of a slide
  is not.

### 2. What actually paid in the walk: ROUND-window moves, not ramp/drain

`emission_order_search.py local` under chained re-seeding. The default
`both` window (first/last 120 plan entries) got 1014 -> 1010 and then
plateaued for 62k evals across 10 re-seeded chains, every jump set 1..64.
The three further cycles came from windows nobody had used on this kernel:

| window | seed | result | note |
|---|---|---|---|
| `both`/`all`/`ramp`/`mid`/`drain` (10 chains, 62k evals) | 1014 | **1010** | then flat |
| **`r:11-15`** (epoch-1 ROUND window) | 1010 | **1008** | first move in 62k evals |
| `drain` | 1008 | **1007** | |
| **`r:11-15`** (again, after a re-mine) | 1008 | **1006** | |
| `r:0-5`, `r:5-10`, `p:0-130`, `p:130-260`, `p:260-390`, `all` | 1006 | 1006 | flat |

`--window r:LO-HI` selects entries by ROUND rather than by plan position, so
it moves the same group-round across the whole stream instead of within a
positional band. **Every single-cycle step below 1010 came from `r:11-15`
or `drain`** — i.e. from the epoch-1 tail, which is exactly where the regret
profile puts its mass (drain 4-7). G-29's "the walk plateaued" verdict is
window-relative: a 62k-eval plateau in position windows was one 200-second
round-window chain away from -2.

### 3. Ring plans break under the walk, and the re-mine is not just a tax (F-25 sec. 4, sharpened)

Audit state after every walk this session (`tools/audit_ring_windows.py`
driven at the exact walked order with the exact carried plan):

| walked order | carried plan audit | re-mined-at-that-order plan | kept |
|---|---|---|---|
| F-24 1011 | OK, 0/24 (4 rings) | 20 rings, OK 0/40, measures 1016 | re-mined (buys floor) |
| 1010 | **OK, 0/40** | 20 rings, OK 0/40, measures 1012 | **carried** |
| 1008 | **80 violations / 40** | 20 rings, OK 0/40, measures 1011 | re-mined (soundness) |
| 1007 | **40 violations / 40** | 20 rings, OK 0/40, measures **1008** | re-mined (soundness) |
| 1006 | **OK, 0/40** | 20 rings, OK 0/40, measures 1007 | **carried** |

Three facts to carry forward:

1. **The unsound point is usually the faster one.** The 1008 and 1007 orders
   measure `correct: true` on all seven seeds AND are 1-3 cycles faster than
   their sound re-mines. Shipping on seed-correctness would have banked 1007
   with 40 live-across violations. **The frontier is the best AUDIT-CLEAN
   point, not the best measured point.**
2. **The re-mine is a chain STEP, not only a tax.** Re-mining at the unsound
   1007 order produced a clean 1008 stream whose order landscape was
   different again — walking THAT is what produced 1006. Full sequence:
   1010 (clean) -> 1008 (dirty) -> re-mine 1011 -> walk 1007 (dirty) ->
   re-mine **1008 (clean)** -> walk **1006 (clean)**.
3. Mining from `()` and mining from the carried plan give DIFFERENT 20-ring
   assignments of the same size, and **the carried-seeded one was unsound**
   (40 violations) where the from-empty one was clean. Always re-mine from
   `parity_ring_plan=()`.

### 4. The accept — 1006 (all measured, `correct: true`)

    parity_ring=True   l4_gmin=(6, 31)
    c5_primed_gather_levels=(5,6)  mem_prime_region_hazards=True
    mem_prime_dead_reg_staging=True   flow_spelling_plan=()
    parity_ring_plan = 20 rings (tools/h057_best_plan_1006.json)
    emission_plan    = tools/h057_best_plan_1006.json   -> **1006**

- **`correct: true` at seeds {unseeded x2, 1, 2, 3, 7, 42, 99}**, and again
  with `debug_compares=True` at {unseeded, 1, 42}; 1006 at every seed.
  Re-verified by round-tripping the saved artifact.
- **Ring audit at the shipped order with the shipped plan: OK, 0 violations
  over 40 rings.**
- Bound stack (`h056_screen --lags-zero --regret`):

      realized 1006 | LB 995 | energetic 996 (release 996 / tail 995) |
      fungible 992 | cp 512 | all-lags-zero 1004
      ops 20462: valu 5966 alu 11761 load 1892 flow 797 store 46
      regret 11 = ramp 4 + mid 3 + drain 4
      jumps: 0,1,3,7 (the G-28 fill) then 805, 864, 915, 978, 984, 993, 997

- **Port dry-run PASSED.** A scratch copy of `perf_takehome.py` with exactly
  three literals swapped — `_EMISSION_ORDER`, `l4_gmin = (6, 30)` -> `(6, 31)`,
  and the `f25_ring_plan` tuple -> the 20 rings below — grades **1006,
  correct** at seeds {unseeded, 1, 42}. Donors symbolized against the named
  vectors (F-6's port rule: never hard-code layout constants):

```python
            h057_ring_plan: tuple[tuple[tuple[int, int], tuple[int, int, int]], ...] = (
                ((0, 3), (st[6], st[7], st[13])),
                ((0, 4), (st[25], nv[8], nv[12])),
                ((0, 5), (lv, lv + VLEN, lv + 2 * VLEN)),
                ((0, 13), (nv[20], nv[21], nv[22])),
                ((0, 14), (st[22], st[23], nv[16])),
                ((0, 15), (nv[17], nv[18], nv[19])),
                ((0, 16), (nv[28], nv[29], nv[30])),
                ((0, 17), (lv, lv + VLEN, nv[31])),
                ((0, 18), (lv + 2 * VLEN, st[30], st[31])),
                ((0, 19), (st[28], st[29], nv[27])),
                ((0, 28), (st[0], st[1], st[3])),
                ((0, 29), (lv, lv + VLEN, st[2])),
                ((1, 8), (nv[0], nv[1], nv[2])),
                ((1, 9), (root_node_val_vec, st[4], st[5])),
                ((1, 21), (st[8], st[9], st[10])),
                ((1, 22), (st[13], nv[8], nv[10])),
                ((1, 23), (root_node_val_vec, lv, lv + VLEN)),
                ((1, 28), (st[0], st[1], st[2])),
                ((1, 29), (lv + 2 * VLEN, st[16], st[17])),
                ((1, 30), (st[18], st[19], st[20])),
            )
```

### 5. Second, independent diagonal: 1007 (reproducibility check)

`tools/h057_best_plan_1007.json`: 8 blocks of 4, lags
**(0,3,6,6,10,11,13,15)**, `zip`/`rev`/`asc` — the diagonal F-24 screened at
greedy 1019 and walked to only **1014 without the chain**. Same chain
applied (rings re-mined to fixpoint at the seed order = 19 rings; gmin
chosen by re-mined sweep = **(6,30)**; order walked): 1023 -> 1011 -> 1009
-> **1007**, plateau over 12 chains / 46k evals. `correct: true` on
{unseeded,1,2,3,7,42,99}; **ring audit OK, 0 violations over 39 rings**;
LB 996 / energetic 997 / fungible 993; regret 11 = ramp 4 + mid 2 + drain 5.

So the chain is worth **-7 on this diagonal** (1014 -> 1007) and **-5 on
F-24's** (1011 -> 1006), from two different organizations. The chain, not
the diagonal, is the lever.

### 6. Workstream B: the non-uniform diagonal search is SATURATED at greedy 1019

F-24 left the organization search "still producing new bests"
(greedy 1022 -> 1021 -> 1020 -> 1019). Re-run with elitist perturbation over
lag diagonals x **uneven block sizes** (F-24's F-30 ask) x wave/group order
x interleave, k in {6,8,10,16}, two independent RNG seeds:

**52,361 organizations screened (~24/s on 4 workers), ZERO below greedy
1019.** Both runs re-found F-24's three known diagonals in their first 44
evaluations and never improved on them in 52k more. Uneven block sizes were
sampled throughout and never entered the elite set; k=6/10/16 never beat
k=8.

With F-24's 29,296 screens that is **~82k organizations, all at greedy
>= 1019**. **The cheap greedy-screen organization axis is closed at this
move set.** F-24's "still descending" reading was the first 44 SEEDS
descending, not the search descending.

Correction worth recording: F-24's "greedy cycles predict the walk better
than LB" held again but is weaker than advertised — the greedy-1019 diagonal
walks to 1007 and the greedy-1021 one to 1006, i.e. a 2-cycle greedy gap
INVERTED under the chain. Screen on greedy, but **walk more than the top 1**.

### 7. Spelling plan: re-derived here too, still EMPTY (fifth derivation)

`tools/spelling_plan_search.py` at the 1006 point: flow-race sites only ->
zero-flip fixpoint (sweep 1 exhausted, 42 s, 1006 -> 1006); `H042_AUX=1`
(all valu<->alu negative-key race sites) -> zero-flip fixpoint (98 s,
1006 -> 1006). H-047's and H-054's verdicts transfer across this
organization too. Byproduct `tools/h042_plan.json` deleted (the tool writes
it next to itself).

### 8. Spend and envelope

280,528 sim-verified walk evals across 9 streams / 48 re-seeded chains,
52,361 organization screens, ~150 ring-mine + audit fixpoints, 2 spelling
fixpoints.

Envelope at the new frontier: realized **1006** / energetic floor **996** /
fungible 992. The reachable band is 1006 -> 996.

### 9. Follow-ups

- **F-33 [port]**: bake `tools/h057_best_plan_1006.json` into
  `perf_takehome.py` — three literals, dry-run already green at 1006
  (section 4). -5 for a literal swap. Update the ring-audit line in the
  `_EMISSION_ORDER` comment (43 rings -> 40) when porting.
- **F-34 [the live axis]**: the ROUND-window walk (`--window r:LO-HI`) is
  under-explored — it produced every step below 1010 and was only ever run
  at r:0-5 / r:5-10 / r:8-15 / r:11-15 / r:13-15. Sweep finer round windows
  (single rounds, r:14-15, r:12-13, ...) crossed with the re-mine loop of
  section 3. This is where the next -2..-4 is.
- **F-35 [soundness x search]**: the walk should be audit-aware. Roughly
  half of walked orders invalidate their own ring plan (section 3) and the
  re-mine costs 1-3 cycles. Adding the borrow-window check to the walk's
  acceptance test would let the search KEEP the fast points that are
  currently discarded (1007 and 1008 were both correct on 7 seeds).
- **F-36**: the 21-24 windows unfundable at every gmin still have only
  `anon:23`-class free words (F-25's F-31, verbatim and unchanged).
- **CLOSED**: the cheap-greedy organization search (section 6). Do not spend
  more budget on lag-diagonal screening at this move set.


## F-33 (2026-07-28): H-057 mainline port — perf_takehome.py 1011 -> **1006**, ring audit clean over 40 rings, bundle stream bit-identical to dev.py

Ported the verified H-057 frontier into the flag-free submission. Three
coupled literals, no structural change — F-24's non-uniform-lag organization
(8 blocks of 4, lags (0,3,6,6,10,10,13,14), zip/default/asc) is expressed
entirely through the emission order, so there is nothing else to port.

1. `_EMISSION_ORDER` <- H-057's 512 entries (asserted bit-for-bit equal to
   `tools/h057_best_plan_1006.json`'s `plan`; coverage, uniqueness and
   per-group-ascending all re-checked).
2. `l4_gmin` (6,30) -> **(6,31)**.
3. `build_parity_ring_map`'s appended plan: F-25's 23 rings -> H-057's
   **20** rings, renamed `f25_ring_plan` -> `h057_ring_plan`.

Per F-6 house style no raw addresses are baked. H-057's symbolized
named-vector literal was used verbatim and then VERIFIED against the
artifact's raw addresses by instrumenting `alloc_scratch`: **all 20 triples
matched exactly**, both before and after the gmin change (layout is stable
at `lv=185`, `root_nv_vec=40`). Donor classes are structural only —
`st`/`nv`/`lv(+VLEN,+2*VLEN)`/`root_nv_vec`; no `anon`. Mapping:

    (0,  3)  st6, st7, st13          (0, 28)  st0, st1, st3
    (0,  4)  st25, nv8, nv12         (0, 29)  lv, lv+VLEN, st2
    (0,  5)  lv, lv+VLEN, lv+2*VLEN  (1,  8)  nv0, nv1, nv2
    (0, 13)  nv20, nv21, nv22        (1,  9)  root_nv_vec, st4, st5
    (0, 14)  st22, st23, nv16        (1, 21)  st8, st9, st10
    (0, 15)  nv17, nv18, nv19        (1, 22)  st13, nv8, nv10
    (0, 16)  nv28, nv29, nv30        (1, 23)  root_nv_vec, lv, lv+VLEN
    (0, 17)  lv, lv+VLEN, nv31       (1, 28)  st0, st1, st2
    (0, 18)  lv+2*VLEN, st30, st31   (1, 29)  lv+2*VLEN, st16, st17
    (0, 19)  st28, st29, nv27        (1, 30)  st18, st19, st20

Note `(0, 5)` now borrows all three level-table words `lv`/`lv+VLEN`/
`lv+2*VLEN` in one ring; `lv+3*VLEN` (two_minus_fp_vec) is still deliberately
unused, and `root_nv_vec` is still epoch-1-only.

### Verification

- `perf_takehome.py Tests.test_kernel_cycles`: **CYCLES 1006**, twice.
- `tests/submission_tests.py`: **9/9 OK**, all nine **CYCLES 1006**, twice.
- Multi-seed via the harness's own `do_kernel_test` (value-trace compares
  enabled): **1006 and correct at all 10 seeds**
  {0,1,2,3,7,42,99,123,2026,31337}.
- **Ring audit on the PORTED config: `OK over 40 rings`, zero LIVE-ACROSS.**
  Run by reading the three literals back out of the shipped file (order,
  gmin, and the symbolic ring plan re-resolved against the live scratch
  map), asserting they equal the artifact, then feeding them to
  `tools/audit_ring_windows.py`. This audits what shipped, not what was
  searched — F-29 caught a stale carried borrow exactly this way.
- **Bit-identity: `dev.instrs == perf_takehome.instrs`, 1006 bundles,
  exactly equal**, at BASE_KWARGS + the H-057 mix + `emission_plan`.
  (First comparison differed only in the `debug` slot, because dev's
  BASE_KWARGS sets `debug_compares=False` while the mainline always emits
  vcompares; with that matched the streams are identical. The grader
  ignores debug slots either way.) The port is airtight: every remaining
  dev/mainline op-mix drift is outside this config.
- No divergence of any kind observed.

### Comment maintenance (the rules that keep costing cycles when dropped)

The `_EMISSION_ORDER` header, the `l4_gmin` line and the ring-plan preamble
were all updated to the new numbers (20 rings / 40 audited rings / (6,31)),
and the preamble now states the two rules explicitly:

- Ring plans are **ORDER-specific AND GMIN-specific** — gmin decides which
  groups are pair-tournament served and therefore what each ring's access
  window is. Never carry a plan across a change to either; **re-mine from
  EMPTY** (H-057 measured that seeding the mine from a carried plan gives a
  same-size but UNSOUND assignment).
- Plans are **ALL-OR-NOTHING**; the leave-one-out counterexample is kept but
  re-labelled as historical (it was `(0, 25)` in F-25's 1011 plan, which is
  not an entry in this one).

Strain frontier and mainline are now both at **1006**; envelope 1006 ->
energetic 996. Next live axis is H-057's F-34 (finer round windows).


## F-34/F-35 (2026-07-28): finer ROUND windows x the audit-aware re-mine loop — NEGATIVE at the frontier; the 1006 order is a STRICT 1-move local optimum by ENUMERATION, and the round-window map is measured

No improvement on 1006. Frontier unchanged, `perf_takehome.py` untouched,
`dev.py` untouched, no shared tool modified. New drivers only:
`tools/f34_lib.py` (programmatic mine/audit), `tools/f34_map.py` (parallel
window map), `tools/f35_loop.py` + `tools/f35_fleet.py` (audit-aware walk
with in-loop re-mining). Total spend this session: **~206k sim-verified
evals** (78k window-map + 25.6k exhaustive + ~102k fleet/loop) plus ~1,100
mine/audit fixpoints.

### 1. The headline: 1006 is a strict 1-move local optimum at UNBOUNDED radius

`tools/f18_exhaust1.py` (G-29's enumerator, called unmodified with
`EOS_OVERRIDES` = the H-057 mix) at `tools/h057_best_plan_1006.json`:

    total single-entry moves: 25,550   (every entry x every position in
    its group's feasible interval -- radius unbounded by construction)
    ZERO below 1006.

Neighbour histogram (25,550 moves): **1006 x 7,487** (29% plateau),
1007 x 1,129, 1008 x 445, 1009 x 299, 1010 x 5,019, 1011 x 3,600,
1012 x 755, 1013 x 772, 1014 x 380, 1015 x 477, 1016 x 123, 1017 x 117,
... ; **3,673 moves (14%) build an INCORRECT kernel**.

This is the F-34 answer in one line: **no round window, however fine, can
pay at 1006**, because the entire single-move neighbourhood has been
enumerated and is empty. Any further order search at this point must be
multi-move. G-29's verdict at 1020 now reproduces exactly at 1006.

### 2. The round-window productivity map (F-34)

Two regimes, and they disagree completely — which is the real finding.

**(a) At either H-057 accept point: every window is dead.** 63 re-seeded
`emission_order_search local` chains, ~78k evals, all flat:

| seed point | windows run | evals | result |
|---|---|---|---|
| 1006 (h057_best_plan_1006) | 16 singletons `r:0-0..r:15-15`; 15 pairs; spans `r:0-4/0-7/5-10/8-15/9-15/10-15/11-13/11-15/12-13/12-15/13-15/14-15`; `drain` — 47 chains, 2 jump sets (1,2,4,8,16 and 1,3,6,12,24,48) | 59,148 | **1006 flat, all 47** |
| 1006 re-mined (19-ring and 20-ring, both 1007) | `r:11-15`, `drain`, `both`, `all` | 14,467 | **1007 flat, all 8** |
| 1007 (h057_best_plan_1007, 2nd diagonal) | `r:0-0/5-5/11-11/14-14/15-15/0-4/5-10/11-15/12-13/13-15/14-15`, `drain/both/all/mid/ramp` — 16 chains | 19,132 | **1007 flat, all 16** |

**(b) From a common PERTURBED start the windows separate sharply.**
Common seed = the 1006 order + 18 random moves = **1015, audit-clean**;
one chain per window, ~1,200 evals each, same RNG family:

| window | best from 1015 | delta |
|---|---|---|
| `drain` | 1009 | **-6** |
| `all` | 1009 | **-6** |
| `r:12-13` | 1010 | **-5** |
| `r:13-15` | 1010 | **-5** |
| `r:14-15` | 1010 | **-5** |
| `r:15-15` | 1010 | **-5** |
| `both` | 1011 | -4 |
| `r:11-15` | 1011 | -4 |
| `r:8-15` | 1011 | -4 |
| `r:0-7` | 1012 | -3 |
| `r:5-10` | 1012 | -3 |
| `r:11-11` | 1012 | -3 |
| `r:0-4` | 1015 | **0** |
| `r:0-0` | 1015 | **0** |
| `mid` | 1015 | **0** |
| `ramp` | 1015 | **0** |

**Which rounds pay: 12-15, and essentially only those.** The single round
`r:15-15` alone matches the whole `r:13-15`/`r:14-15` band (-5) and beats
H-057's coarser `r:11-15` (-4); `r:11-11` alone is worth only -3. Epoch 0
(`r:0-4`, `r:0-0`) and the positional `ramp`/`mid` bands are worth exactly
zero. This refines H-057's "`r:11-15` or `drain`" to **"round 15 first,
then 12-14; everything below round 11 is dead"** — and it matches the
regret profile, which puts 4 of its 11 cycles in the drain band.

So finer round windows ARE a real axis (the fine `r:12-13`/`r:15-15`
windows beat the coarse `r:11-15` H-057 used, from a common start); they
are simply worth nothing at 1006, because of section 1.

### 3. F-35: the audit-aware loop, and what it recovers

`tools/f35_loop.py` folds the borrow audit into the walk: every accepted
descent is audited against the carried plan; a **DIRTY descent is kept**,
its plan re-mined from EMPTY at that order, and the walk continues from the
re-mined stream. Structure is branch-and-return basin hopping around the
best CLEAN point (`home`) so the chain cannot drift upward — the first,
drift-free version of the loop wandered 1006 -> 1007 -> 1008 -> 1015 in
120 s, which is exactly why H-057 had to re-mine only at checkpoints.

**Two mechanism corrections that H-057's checkpoint method never had to
face, and that the in-loop version cannot work without:**

1. **The mine fixpoint is GROW-then-PRUNE, not grow-only.** Iterating
   audit -> append the tool's proposed rings until it proposes none gives a
   20-ring plan that is *not* automatically sound at a perturbed order —
   each added ring shifts the emission windows the next audit sees. Measured
   at four dirty orders off the 1007 diagonal, the grow-only fixpoint came
   back **32 violations / 40 rings every time**. The loop now drops every
   plan ring the closed-loop recheck flags and re-audits (monotone, so it
   terminates). With grow-only, in-loop recovery had a **0/24 success rate**;
   with grow-prune it recovers.
2. **Only PLAN rings are prunable.** `parity_ring_map` holds ~20 natively
   derived rings alongside the ~20 planned ones, and a live-across on a
   NATIVE ring is a property of the ORDER that no plan can repair. Those
   points are genuinely unrecoverable and must be dropped.

Recovery rate, fleet G3 (8 lanes x 470 s, seeded at 1006/1007 and at
perturbed 1015/1016/1018 starts): **92 descents, 34 DIRTY (37%), 19
recovered in-loop into clean continuations, 15 unrecoverable** (native-ring
violations or an incorrect re-mine). So the audit-aware loop converts
**~56% of the points H-057's method would have discarded** into live walk
state — H-057's 37%-dirty rate reproduces ("roughly half" was the right
order of magnitude), and the re-mine-as-re-conditioning step works
mechanically. It bought **zero cycles**: no lane ever put a clean point
below its seed's frontier.

Also measured: dirtiness is *selection*, not noise. Over 247/505 random
single moves off the 1006/1007 orders only **2.0% / 0.4%** audit dirty
(2 of 5 and 1 of 2 of those on native rings) — it is the *descending* moves
that are disproportionately dirty, which is what makes the audit
search-shaping rather than a filter.

Fleet totals: G1 26k evals / G2 21k / G3 28k / G4 24k, plus 13k in the
single-process loop = **~112k evals over 132 branches**, best clean point
found anywhere = **1006** (never improved), best clean point from a
perturbed restart = 1008.

### 4. Deliberate re-conditioning from a CLEAN point (the F-35 corollary)

H-057 kept the carried plan whenever it audited clean. The re-mine at the
1006 order is nevertheless a *different* 20-ring assignment that measures
1007 — a second, legitimate, audit-clean stream at the same order. Both it
and the 19-ring truncation of the same fixpoint were walked (`r:11-15`,
`drain`, `both`, `all`; 14.5k evals): **both flat at 1007.** Re-conditioning
from a clean point is available and sound, but at this frontier it only
costs the +1 and buys nothing back.

Reproduced exactly, as a machinery control: the mine fixpoint at the 1006
order converges in 3 audit rounds (19 rings -> +1 -> 20 rings), audits
`OK over 40 rings`, and measures 1007 — H-057 sec. 3, row 5, to the cycle.

### 5. Frontier re-verification (unchanged)

    tools/h057_best_plan_1006.json -> 1006
    correct: true at seeds {unseeded x2, 1, 2, 3, 7, 42, 99}
    correct: true with debug_compares=True at {unseeded, 1, 42}
    ring audit at the shipped order with the shipped plan:
        "OK over 40 rings"   (0 violations)
    realized 1006 | LB 995 | energetic 996 (release 996 / tail 995) |
    fungible 992 | cp 512 | all-lags-zero 1004
    ops 20462: valu 5966 alu 11761 load 1892 flow 797 store 46
    regret 11 = ramp 4 + mid 3 + drain 4
    jumps: 0,1,3,7 then 805, 864, 915, 978, 984, 993, 997

No `tools/f34_best_plan_*.json` was written: there is no winner below 1006,
and the 1006 point is already shipped as `tools/h057_best_plan_1006.json`
and baked into `perf_takehome.py` by F-33.

### 6. Follow-ups

- **CLOSE the single-move order axis at 1006** (this section 1, by
  enumeration — the same status G-29 gave the 1020 plan). Do not spend more
  budget on any 1-move walk at this point, in any window, at any radius.
- **F-37 [the only live order axis left]: MULTI-move.** G-29 already found
  compound moves (pairg/comp2/block, 21,472 evals) negative at 1020, but
  never at 1006 and never restricted to the productive band. The one
  targeted version worth trying: **simultaneous k-entry displacements
  confined to rounds 12-15** (section 2 says that band owns all the
  descent), k in 2..4, seeded at 1006. The 29% exact-1006 plateau in the
  1-move histogram is the raw material — 7,487 neutral moves is a large
  connected plateau to compose across.
- **F-38**: the perturb-and-redescend statistic is a cheap basin probe —
  18 random moves off 1006 lands at 1015-1018 and re-descends only to
  1008-1010 in ~1,200 evals per window. If a cheap descent from a random
  restart ever reaches 1006 again, the basin is wide and multi-start is
  worthless; so far it never has (0 of 12 restarts), which is weak evidence
  that 1006 is a narrow basin and that a *different* basin may exist.
- **DEAD (measured this session, do not re-run)**: fine round windows at
  1006 or at either 1007 stream; `r:0-*`/`ramp`/`mid` windows at any point;
  re-conditioning by re-mine from an already-clean frontier point;
  audit-aware acceptance as a *cycle* lever (it is a soundness/search-shaping lever
  only — 19 recoveries, 0 cycles).


## F-37 (2026-07-28): multi-move (k-entry simultaneous displacement) in rounds 12-15 — NEGATIVE; the k=2 INTERACTING space at 1006 is EXHAUSTED, and the order axis is now closed at every k it can be closed at

No improvement on 1006. Frontier unchanged, `perf_takehome.py` untouched,
`dev.py` untouched, no shared tool modified. New drivers only:
`tools/f37_lib.py` (composable `(src, anchor)` move algebra),
`tools/f37_single.py` (banded single-move map), `tools/f37_multi.py`
(k-entry search + build-only screen), `tools/f37_bounds.py` (bound stack at
an arbitrary artifact's own mix). Spend: **445,553 cycle-exact evals**
(7,306 phase-A singles + 438,247 multi-move) in ~105 min of wall clock.

### 1. Why this shape, and the move algebra that makes it possible

G-30 closed single moves by enumeration (25,550 moves, zero below 1006), so
any surviving order win must be a **strictly paired escape**, and G-30's
window-productivity map says it must live in **rounds 12-15**. f18's `(i, j)`
reinsertion coordinates do not compose (the second `j` is measured in a list
the first move already shifted), so `tools/f37_lib.py` re-coordinatises a
move as `(src, anchor)` in BASE-index space: displace base entry `src` to sit
immediately before base entry `anchor` (`anchor = -1` = append at end). k
moves are then applied by deleting all k entries at once and re-inserting
each before its still-present anchor. For k=1 this reproduces
`q.insert(j, q.pop(i))` **exactly** — verified on all 25,550 f18 moves,
0 mismatches, and `enumerate_moves(rounds=None)` returns exactly f18's 25,550.

### 2. The screen: build-only, and it is exact

`machine.cycle == len(kernel_builder.instrs)` identically (VLIW, one bundle
per cycle), so the cycle count needs the BUILD only: 0.074 s vs 0.103 s for
build+simulate+reference, and the problem image is built once per worker
instead of once per eval. Validated against the shared
`run_variant.measure` on 60 random composed pairs: **0 mismatches**. Every
candidate strictly below base would have been re-measured with the full
build + frozen grader before being reported (`f37_multi.py` does this
inline); **0 candidates ever reached that path.** Realised throughput
~70 evals/s on 8 workers vs 49/s for full measure.

### 3. The plateau inside rounds 12-15 (phase A)

`tools/f37_single.py` at `tools/h057_best_plan_1006.json`, source round in
{12,13,14,15}, destination interval unbounded by construction:

    7,306 single displacements, ZERO below 1006

| cycles | n | | cycles | n |
|---|---|---|---|---|
| **1006 (plateau)** | **1,641** | | 1010 | 1,110 |
| 1007 | 196 | | 1011 | 836 |
| 1008 | 170 | | 1012-1032 | 1,699 |
| 1009 | 175 | | INCORRECT | 1,479 |

**Plateau size within rounds 12-15 = 1,641** (22.5% of the band; the
whole-plan figure is 7,487/25,550 = 29%). By round: r15 541, r12 402,
r14 359, r13 339. The 1007-1009 "slightly worse" set is **541** moves —
that is the raw material for the +1/-2 pairing that single-move search
structurally cannot see.

### 4. k=2: exhaustive over the interacting space, ZERO

A pair can only do something a single move cannot if the two displacements
**interact**, so pairs are split by whether their base-index spans overlap.
The overlapping half is enumerated exhaustively; the disjoint half is
sampled as a control (section 5).

| mode | pairing | candidates | evaluated | min | landed exactly 1006 | **below 1006** |
|---|---|---|---|---|---|---|
| `nn` | neutral x neutral, spans overlap | 219,184 | 209,311 | 1006 | 126,947 | **0** |
| `nn_res` | ...anchor-clash subset, anchor resolved | 6,488 | 6,488 | 1006 | 4,135 | **0** |
| `wn` | worse(1007-9) x neutral, spans overlap | 97,591 | 92,175 | 1006 | 20,848 | **0** |
| `wn_res` | ...anchor-clash subset, resolved | 4,479 | 4,479 | 1006 | 915 | **0** |
| `ww` | worse x worse, spans overlap | 27,568 | 25,570 | 1006 | 1,027 | **0** |
| `ww_res` | ...anchor-clash subset, resolved | 1,822 | 1,822 | 1006 | 167 | **0** |
| | **k=2 interacting, total** | | **339,845** | **1006** | 154,039 | **0** |

The only pairs not evaluated are the **4,498 whose composite violates the
per-group round order** (both members in the same group, crossing) — those
are not valid emission plans at all, not a coverage hole. The 12,789 pairs
whose anchor is swept away by the partner ARE a coverage hole in the naive
composition, so they were re-run with the anchor slid forward to the
surviving entry (`--only-resolved`): all 12,789 resolve to valid plans, and
all measure >= 1006.

Two facts worth carrying: the interaction is real and strong — **20,848
worse-x-neutral pairs and 1,027 worse-x-worse pairs come back to exactly
1006**, i.e. a +1..+3 penalty fully cancelled by a partner — and yet not one
of 339,845 interacting pairs ever crosses below. The plateau composes, it
just never descends.

### 5. The disjoint-span control (and an honest caveat)

Disjoint-span neutral pairs are **not** additive: only 71% of a 69,811-pair
random sample (of 1,095,747, = 6.4%) returns 1006; 29% go UP (1010 x 12,838,
1011 x 4,398, 1007 x 2,112, ...). **Zero go below 1006.** So the split is a
prioritisation, not a proof: k=2 is exhaustive over the interacting subset
and a 6.4% random sample of the non-interacting subset. Full enumeration of
the disjoint half is ~4.3 h of compute and, given that the mechanism for a
paired escape is interaction and the interacting half is provably empty, is
not worth it.

### 6. k=3, and where k=4 was stopped

`ktuples` samples k-cliques in the span-interaction graph (mutually
overlapping triples of plateau moves — a triple with a non-interacting
member only re-tests the additive case section 5 already covers).

    k=3: 35,000 sampled, 28,591 valid composites, min 1006, ZERO below

**k=4 not run, deliberately.** The loop's diminishing-returns rule applies:
k=2 over the rounds-12-15 plateau is exhausted with zero and k=3 sampling
is flat, so k=4 sampling is budget with no prior behind it.

### 7. Frontier re-verification (unchanged, this session)

    tools/h057_best_plan_1006.json -> 1006
    correct: true at seeds {unseeded x2, 1, 2, 3, 7, 42, 99}
    correct: true with debug_compares=True at {unseeded, 1, 42}
    ring audit at the shipped order with the shipped 20-ring plan:
        "OK over 40 rings"   (0 violations)

Bound stack re-derived at this artifact's own mix (`tools/f37_bounds.py`,
which captures through `backtrack_sched` at the artifact's mix instead of
the H-047/1022 config the shared tools are pinned to):

    realized 1006 | LB 995 (engine: valu 995 alu 981 load 946 flow 797
    store 23) | energetic 996 | fungible 992 | cp 512 | all-lags-zero 1004
    ops 20462: alu 11761 valu 5966 load 1892 flow 797 store 46
    slot floor 995, regret 11   (recorded decomposition: ramp 4 + mid 3 + drain 4)

No `tools/f37_best_plan_*.json` was written: nothing descended, and the
1006 point is already shipped as `tools/h057_best_plan_1006.json` and baked
into `perf_takehome.py`. No l4_gmin re-slide and no audit-aware re-walk were
run either — both are conditioned on a descent, and there was none.

### 8. Verdict: the order axis is closed

Combining G-29 (1020), G-30 (1006, k=1 exhaustive, round-window map) and
this section (1006, k=2 exhaustive over the interacting space + k=3
sampled), at the shipped mix and organization:

- k=1: **enumerated, empty** (25,550).
- k=2 in the only productive band, interacting: **enumerated, empty**
  (339,845). Non-interacting: 6.4% sampled, empty.
- k=3 in that band, mutually interacting: 28,591 sampled, empty.
- every other band (`r:0-*`, `ramp`, `mid`) was already worth exactly zero
  from a perturbed start, so a pair confined there cannot pay either.

There is no cheaper structure left to try on the emission order at this
mix. Anything further requires a different mix or a different program
organization, both of which are closed by their own artifacts (G-24/G-28,
~82k organization screens).

### 9. Follow-ups

- **F-38 (basin-width probe) is now the only order-flavoured item left**,
  and its value is diagnostic, not productive: it asks whether a DIFFERENT
  basin exists, which is the one question sections 1-8 cannot answer by
  local enumeration.
- **DEAD (measured here, do not re-run)**: k=2 multi-move at 1006 in rounds
  12-15, in any pairing (neutral/neutral, worse/neutral, worse/worse),
  overlapping or not; k=3 in that band; k=4 (never worth starting given the
  above); any composition built on the 1006 plateau. The plateau composes
  fine and never descends — 154,039 interacting pairs return to exactly
  1006 and not one goes below.

---

## H-058 (2026-07-28): solve BACKWARDS for a 940 census — ANSWERED, and the answer is a QUANTIFIED IMPOSSIBILITY for this algorithm: the joint slot floor is **960.8**, and 940 needs **-270 vec-ops** at the floor / **-429 vec-ops** to realize, out of a census that is 78% irreducible hash

New tools (all read-only over shared tools; nothing in dev.py /
perf_takehome.py / tests/ touched):

| tool | what it produces |
|---|---|
| `tools/h058_census.py` | exact purpose x engine x opcode cross-census at 1006 + fungibility decomposition + scratch ledger + a def-use pass that separates gather-address combines from tournament folds and idx-selects from folds |
| `tools/h058_envelope.py` | the constraint solve: structural cost model, the 1-D design scan, the mechanism ledger, shadow prices, the measured-slope envelope, the scratch/groups-live curve |
| `tools/h058_marginal.py` | the MEASURED serving-vs-gathering slopes (l4_gmin swept 1..33 served L4 group-rounds) + regret-by-binding-engine |
| `tools/h058_oracle.py` | multi-class free-slot oracle at a `params.mix` artifact (free_slot_oracle only frees one class and only reads the old schema) |

### 1. The measured 1006 census (the anchor everything else is a delta from)

`python3 tools/h058_census.py`:

```
alu 11,761 / valu 5,966 / load 1,892 / store 46 / flow 797   (1006 cycles)
alu+valu lane-ops 59,489 = 7,436.1 VEC-OPS
  Hash    46,464 lane-ops = 5,808.0 vec-ops  (2,048 madd + 3,760 plain)
  Idx      7,600           =   950.0
  Routing  4,809           =   601.1  + 775 flow vselect + 1,832 loads
  Setup      616           =    77.0  (59 vbroadcast + 16 madd + 16 alu)
serving: L0 64 free, L1 64, L2 64, L3 64, L4 27/64 served -> 229 gathered
scratch 1,533/1,536 = 768 state (st/val/nv x 32 groups) + 360 tables + 405 pools
```

**Unit of account: the VEC-OP.** The machine retires 6 valu + 12 alu slots
per cycle = **7.5 vec-ops/cycle** for plain ops (a madd is 1 valu slot but
16 alu slots, so madds go to valu first). 940 cycles = **7,050 vec-ops =
56,400 lane-ops**. Flow is OUTSIDE that budget: 1 vselect = 8 lane-ops of
selection for 1 flow slot.

Hash alone is **5,632 vec-ops** (11 fused ops x 512 group-rounds; the 2,048
madds are exactly 4 x 512, confirming corsix's decoded graph) = **79.9% of
the entire 940 compute budget.** Everything else must fit in 1,418.

**Def-use finding (new):** of the 775 flow vselects, only 546 are tournament
folds — **229 are idx/boundary selects** (H-029), exactly one per gathered
group-round. And gather addresses are produced by a madd (166 group-rounds)
or a `v-` (60), i.e. the `+forest_values_p` combine is ALREADY fused into
the position recurrence for most gathers; the free-standing combine is
~60-90 vec-ops, not 229.

### 2. CORRECTION to H-044 / `tools/ideal_floor.py`: its 931.6 is wrong by ~80 cycles

H-044 re-derived its buckets from the 1038 purpose report and wrote
`idx 7,448 - 1,848 = 5,600` "minus gather-address combines". The combines
are classified into **Routing**, not Idx (a slot writing `st{g}` is Idx; a
slot reading `st{g}` is Routing) — so it subtracted 1,848 lane-ops that were
never in the bucket, then added the combines back separately. Net ~1,850
lane-ops of double-subtraction plus a dropped 616-lane-op Setup bucket
≈ 4,800 lane-ops ≈ 80 cycles of optimism. **`ideal_floor.py`'s layer-2
numbers must not be used as a target.** H-058's tools work in deltas off a
census that reproduces exactly (validation prints +6.0 vec-ops on 7,436),
so the error class cannot recur.

### 3. The design space is ONE INTEGER

Per group-round, from the ISA (validated by the measured slopes in section 4):

| level d | serve on flow | serve on valu | gather |
|---|---|---|---|
| 1 | 1 flow slot | 1 vec-op | 8 loads + ~1 vec-op |
| 2 | 3 | 4 | 8 + 1 |
| 3 | 7 | 10 | 8 + 1 |
| 4 | **15** | **22** | 8 + 1 |
| 5 | 31 | 46 | 8 + 1 |
| d | 2^d - 1 | 3*2^(d-1) - 2 | 8 + 1 |

(valu spelling: first layer = 1 madd `b + cond*(a-b)` with a STATIC diff;
inner folds have runtime arms so they cost `v-` + madd = 2 vec-ops.)

Converted to engine-cycles at the machine's rates (flow 1/cyc, compute
7.5 vec-ops/cyc, load 2/cyc):

| level | flow-serve | valu-serve | gather |
|---|---|---|---|
| 1 | 1.00 | **0.13** | 4.13 |
| 2 | 3.00 | **0.53** | 4.13 |
| 3 | 7.00 | **1.33** | 4.13 |
| 4 | 15.00 | **2.93** | 4.13 |
| 5 | 31.00 | 6.13 | **4.13** |
| 6 | 63.00 | 12.53 | **4.13** |

**The crossover sits exactly between L4 and L5**, which is where the
shipped kernel already sits. Levels 1-3 must be served, levels 5-10 must be
gathered, and the ONLY free variable is `s4` = how many of the 64 level-4
group-rounds are served. Everything Phase 1 called "the organization" is
scheduling, not census. Serving deeper is Omega(2^d) and no scratch budget
changes that; the ISA has **no scratch-indexed read and no permute**, so
per-lane data-dependent routing is exactly "1 load" or "2^d - 1 selects".

### 4. MEASURED marginal rates (`tools/h058_marginal.py --no-ring`, s4 = 1..33)

```
d(vec-ops)/d(s4) = +11.66     d(load)/d(s4) = -8.00     d(flow)/d(s4) = +6.31
d(madd)/d(s4)    =  +7.50     d(scratch)/d(s4) = +0.28  d(cycles)/d(s4) = -2.41
```

Serving one more level-4 group-round costs 11.66 vec-ops **and** 6.31 flow
slots and saves exactly 8 loads. The `-8.00` confirms the load model to the
digit; `+0.28` says the level-4 tables are already resident (the scratch
axis does not gate L4 serving at all).

### 5. THE ENVELOPE AT 940 (deliverable 1)

Two independent models agree:

| model | joint floor | at |
|---|---|---|
| structural (ISA cost table, `h058_envelope.py` [1]) | **962.7** | s4 = 23 |
| measured-slope (regression on section 4, `h058_envelope.py` [5]) | **960.8** | s4 = 23.3, 187 selects exported valu -> flow |

At that optimum **all three engines bind simultaneously**: compute 960.8 /
load 960.8 / flow 960.8, i.e. 7,206 vec-ops (57,647 lane-ops), 1,922 loads,
961 flow slots. This is corsix's 7.5 : 2 : 1 ratio, derived from our census.

**The 940 constraint system, solved:**

```
load   1,880 slots  ->  gathered <= 227 group-rounds  (levels 5-10 alone force 192 = 1,536 loads = 82%)
                        => served >= 221 => s4 >= 29
flow     940 slots  ->  selects on flow <= 938 (L1-L3 alone need 704 = 75% of the budget)
alu+valu 7,050 vec-ops, of which hash needs >= 5,632 (79.9%)
                        => non-hash budget 1,418 vec-ops
                        measured non-hash at s4=29: 1,637 vec-ops
scratch  <= 1,536 words
latency  K >= 32*314/940 = 10.7 live groups
```

**Removal required (measured-slope solve, marginal rate 104 lane-ops/cycle):**

| target floor | vec-ops to remove | lane-ops |
|---|---|---|
| 960 | 10 | 82 |
| 950 | 140 | 1,121 |
| **940** | **270** | **2,161** |
| 930 | 400 | 3,200 |

Shadow prices at the optimum: **-0.091 cycles per vec-op removed**
(= 1 cycle per 104 lane-ops; H-044 guessed 97, close) and **-0.159 cycles
per load slot removed for the first ~50 slots, then 0** (load stops
binding). Flow's price is 0 until the compute floor descends to meet it,
then it becomes co-binding — the joint condition, again.

### 6. Per-mechanism accounting against that envelope (deliverable 2)

`h058_envelope.py` [2], each evaluated at its own best s4:

| mechanism | C | dC | why |
|---|---|---|---|
| baseline (prime L4/L5) | 962.7 | 0 | |
| move the 20 setup `add_imm` off flow to alu | 962.0 | **-0.7** | +20 flow slots for select export |
| prime L6 in mem as well | 960.8 | **-1.9** | saves 32 `^nv` vec-ops for 8 vec-ops + 8 loads |
| prime L6 **and** L7 | 962.0 | +0.7 | L7 costs 16 loads for the same 32 saved -> break-even crosses |
| delete HALF the cond overhead | 956.8 | **-5.9** | 49 of the 97 measured cond vec-ops |
| delete ALL cond overhead | 952.7 | **-10.0** | all 97 |
| delete ALL cond AND setup | 946.0 | **-16.7** | physically impossible (the 59 broadcasts ARE the tables) |
| **relocate forest to fp = 1** (kills every combine) | 990.0 | **+27.3** | -229 vec-ops (-21 cyc) but +252 loads (+126 load-cycles) |
| relocate + zero overhead | 976.1 | +13.4 | still a loss |
| serve 8 L5 group-rounds | 972.1 | **+9.4** | 46 vec-ops (6.13 cyc) vs 8 loads (4.00 cyc) -> -2.1 cyc each |

**Index maintenance is at its floor and no STRUCTURE changes the count.**
G-21 proved the per-step floor is extract + madd. Across the kernel that is
1 `v&` + 1 madd per group-round for the 512 group-rounds minus round 10
(level 10 wraps to index 0 for every walker, so its parity is never read):
2 x (512 - 32) = **960 vec-ops floor vs 950 measured** — we are already
below the naive floor. Restructuring does not help: building the level-4
index from its 4 path bits by Horner is 4 madds, exactly the 4 per-round
madds it would replace, and selecting the index from a 16-entry table would
cost 15 selects instead of 4 madds.

**The address recurrence.** `a' = 2a + 1 + b` is self-similar with no level
constant only if the tracked quantity is `idx + 1`, i.e. only if
`forest_values_p == 1`. Solving `a = alpha*idx + beta` for "addend is
exactly the parity bit b" gives the unique solution `alpha = beta = 1`.
Any other base needs `b + (1 - fp)` in the madd's addend slot, and there is
no single ISA op producing `(val & 1) + K` (the only parity-isolating
multiplier mod 2^32 is 2^31, G-21). Per-level re-basing does not escape it
either: `beta_{d+1} = 2*beta_d - 1` forces `beta_d = 2^d*t + 1`, and no `t`
leaves any gathered level in place. So the combine costs **either** ~1 op
per gathered group-round **or** a 2,047-word relocation at 256 vload +
256 vstore — and that is a measured +27.3 cycles.

### 7. Latency-feasibility (deliverable 3) — NOT the wall

`tools/h058_oracle.py tools/h057_best_plan_1006.json ...`, all measured this
session on the 1006 artifact (edges + the 1-cycle write latency preserved,
only the slot cost removed):

| slots made free | cycles | delta |
|---|---|---|
| — (baseline) | 1006 | |
| all vec + madd compute | **977** | -29 |
| gathers only | 1004 | -2 |
| flow vselects only | 1007 | +1 |
| compute + gathers | **650** | -356 |
| compute + selects | 963 | -43 |
| compute + gathers + selects | **331** | -675 |
| every slot free (the dependency skeleton) | **314** | -692 |

Plus `tools/f37_bounds.py`: cp 512, all-lags-zero 1004, energetic 996,
fungible 992, engine LB 995, realized 1006 (regret 11).

**Verdict: a 940 census is latency-feasible with ~600 cycles of margin.**
The dependency skeleton is 314 cycles. Because a group's 16 rounds are
strictly serial, with K of the 32 groups live the schedule runs 32/K
generations of length C*K/32, and each must cover one group's 314-cycle
span: **K >= 32*314/940 = 10.7, so K >= 11 live groups.** The current
design's K = 32 has 626 cycles of slack. G-26's "993 with all compute free"
is now **977** at 1006, and that residual is LOAD bandwidth (load floor
946), not chain.

**The real schedulability finding is different and it is bad news for 940**
(`h058_marginal.py`, regret column): regret over the point's own floor is
**~20 cycles while COMPUTE binds and ~70 cycles once LOAD binds**
(s4 <= 13: 1072/1088/1104/1120 realized against load floors
1002/1018/1034/1050). The 960.8 joint optimum sits exactly on that
boundary. A 940 design must run load at 100%, so it must budget the larger
number: **realizing 940 needs a census floor near 920, i.e. -429 vec-ops
(-3,432 lane-ops, 5.8% of the whole census).** With hash fixed at 5,632,
non-hash would have to fall from 1,637 to 1,208 vec-ops while idx alone is
950 and the minimum unexportable valu-folds are ~220.

### 8. The scratch / groups-live trade (deliverable 4)

`h058_envelope.py` [6]. Scratch = 24*K (st/val/nv) + 360 (L1-L4 tables and
static diffs) + 405 (pools/consts) — reproduces the shipped 1,533 exactly.

| K live | state | free words | generation length @940 | latency slack | funds |
|---|---|---|---|---|---|
| 32 | 768 | 3 | 940 | +626 | nothing (today) |
| 24 | 576 | 195 | 705 | +391 | — |
| 20 | 480 | 291 | 588 | +274 | pair-preload (256w, closed G-18/G-28) |
| **16** | **384** | **387** | **470** | **+156** | most of full cond retention (512w needed; 387 + ring borrow covers it) |
| 12 | 288 | 483 | 352 | +38 | FULL cond retention from real scratch (384w) |
| 11 | 264 | 507 | 323 | +9 | ditto, at the latency limit |
| 8 | 192 | 579 | 235 | **-79** | INFEASIBLE (generation shorter than one group's chain) |

Per-mechanism scratch demand: an L5 select tree needs 32 broadcast vectors
+ 16 static diffs = **384 words** (affordable from K <= 16) but is
**arithmetically negative by 2.1 cycles per group-round** regardless — the
scratch was never the binding reason (G-23 listed it first; it is actually
third). An L6 tree needs 768 words and is negative by 8.4 cyc/group-round.
Cond retention needs 4 parity vectors x 8 words per live group at level 4 =
**32K words**; today `parity_ring` borrows 480 dead-register words and funds
20 of 32 groups, which is why 97 vec-ops of cond re-extraction survive.

**So the untested axis is real but small: halving groups-live buys the
remaining cond retention, worth ~97 vec-ops = ~7 cycles, at the cost of a
second generation seam.** It does not open select-tree serving at any depth.

### 9. Ranked shortlist (deliverable 5)

**D1 — Compute-bound flow-saturation build: s4 ~ 29, K = 16 sliding window,
full parity/cond retention out of freed scratch, every exportable fold
spelled on flow.** Modeled floor **~945**, realistic realization ~965-975.
Feasible because: loads 1,876 <= 1,880; flow 940 with the 20 `add_imm`
moved to alu; scratch 1,149 + 512 retention <= 1,536 with ring borrow;
latency slack 156 cycles. **Fails if** flow cannot be kept bubble-free —
G-27 measured flow's shadow price at exactly 0 on the current stream
(infinite-width flow = 1022/1023 at 1022; freeing all vselects here = 1007,
+1), so the export only pays after the compute floor has come down to meet
it. That is G-23's joint condition restated, and it is why D1 must land the
cond deletion and the export TOGETHER or not at all.

**D2 — Prime level 6 in mem (`c5_primed_gather_levels` (5,) -> (5,6)).**
-1.9 cycles at the floor, +8 loads, +8 vec-ops, no new scratch. Smallest,
safest, already flag-shaped. **Fails if** the point is load-bound (the 8
extra loads then cost 4 cycles); requires s4 >= 25.

**D3 — Move the 20 setup `add_imm` slots from flow to alu.** +20 flow slots
of export capacity, -0.7 cycles. Trivial; only useful composed with D1.

**D4 — REJECTED with numbers: forest relocation to fp = 1.** +27.3 cycles.
The 229 combines are worth 21 cycles; the 256 vload + 256 vstore pass costs
126 load-cycles. Same verdict if fused with a full C5-priming pass.

**D5 — REJECTED with numbers: L5+ select trees under freed scratch.**
-2.1 cyc per group-round at L5, -8.4 at L6, at ANY scratch budget. This
closes G-23's "reopen-if 256+ scratch words free up" clause: the scratch
was never the binding reason.

**D6 — REJECTED with numbers: full-forest C5-priming.** +248 loads to save
160 vec-ops; break-even is at level 8 (2^d/8 loads vs 32 saved vec-ops), so
only L6 (and marginally L7) ever pay.

**Build D1 first**, but build it as a MEASUREMENT of the joint condition,
not as a 940 attempt: the compass says the honest target of this algorithm
is **~960 floor / ~975 realized**, and 1006 -> ~975 is the whole remaining
prize. **940 is 270 vec-ops below the floor and 429 below realization, and
this analysis cannot locate them** — every candidate source is either
measured at its floor (idx, hash) or measured negative (relocation, deeper
serving, full priming).

### 10. What would have to be true for 940 to exist under our rules

Exactly one of:

1. a hash under 11 fused ops (four tool classes say no: G-10 MITM, H-025
   CEGIS, G-20 re-derivation, G-24 cmpsel; and H-043 decoded the frontier
   running our exact 11 ops);
2. index maintenance under 2 vec-ops per group-round (G-21, re-derived here
   from the recurrence algebra);
3. per-lane data-dependent routing cheaper than "1 load" or "2^d - 1
   selects" — which needs a scratch-indexed read or a permute, and the ISA
   (`docs/isa.md` section 6) has neither;
4. a scheduler that realizes a load-100% stream at regret ~0 when ours
   measures regret 70 in that regime.

(4) is the only one not closed by our own artifacts, and it is exactly the
"joint per-cycle selection x scheduling" item H-043 flagged as N-3 and
attributed to josusanmartin's search-heavy method. **If the loop wants to
chase 940, the target is not the census — it is the 50-cycle regret gap in
the load-bound regime.** That is a scheduling hypothesis, not an algorithm
one, and it should be posed against `tools/backtrack_sched.py` on a
deliberately load-bound stream (s4 <= 13), where the regret is largest and
therefore easiest to attribute.

### 11. Do not re-run (measured here)

- `ideal_floor.py`'s 931.6 free-mix optimum — arithmetic error, see section 2.
- Serving any level >= 5 by select tree, at any scratch budget (sections 6, 8).
- Relocating the forest / re-basing the address recurrence (section 6).
- Priming levels >= 8 (section 6).
- Looking for latency relief: the dependency skeleton is 314 cycles against
  a 940 target (section 7).

## H-064 (2026-07-28): the setup ramp as a dependency CHAIN — **NEGATIVE, and it invalidates its own premise**. The "-13" that motivated the hypothesis is a CONTAMINATED measurement; a clean relaxation prices the entire setup phase at **-2**, every restructuring measured 0 or worse, and H-062 (folded in) is negative by ~80 cycles. This closes the last identified non-zero lever.

Tools: `tools/h064_chain.py` (chain extraction: est / lst / slack / binding
predecessor for every op, plus the setup-only subgraph), `tools/h064_oracle.py`
(windowed-capacity + op-level free/pin/lag oracle over `backtrack_sched`'s
offline greedy, asserted bit-exact against dev's real placement on every run).
New dev.py flags, all default-OFF and verified BIT-IDENTICAL off (bundle
stream + `scratch_next_addr` compared against the pre-patch build):
`va_chain_width`, `setup_lv_addr_alu`, `derive_consts_exclude`.

### 0. THE PREMISE WAS AN ARTIFACT (the most important finding here)

H-063's headline — "freeing every setup engine separately = 0 but freeing
the whole 252-op setup TOGETHER = -13, therefore the ramp is a serial
chain" — does not survive checking. `tools/h063_oracle.py` frees ops by
**rerouting them to the `debug` engine inside a live dev build**, and dev's
adaptive engine races (`alu_offload`, the idx/flow races) read scheduler
occupancy to pick an engine. Freeing setup therefore changes the OP STREAM,
not just its placement:

| census | baseline | setup rerouted to debug | a pure relaxation would give |
|---|---|---|---|
| alu | 11,761 | **11,600** | 11,696 |
| valu | 5,966 | 5,904 | 5,907 |
| flow | 797 | **782** | 775 |
| load | 1,892 | 1,832 | 1,832 |
| store | 46 | 0 | 0 |

That build emits **96 fewer alu ops** and 7 more flow ops than the same
program with the slots merely removed. And of its 13 cycles, 5 are bundles
that became *empty* (cycles 0,1,2,3 and 997 hold only debug slots, which do
not count) and ~8 are floor relief (valu 995 -> 982, alu 981 -> 975) —
which G-36 has now rejected three times as a proxy for cycles.

**Clean measurement.** `h064_oracle` runs the offline greedy (validated
`place == real place`, 1006 cycles, 20,462 ops, every invocation) with the
program held fixed and only slot cost / placement relaxed:

| relaxation of the SETUP phase (program unchanged) | cycles | delta |
|---|---|---|
| all 268 setup ops slot-free | 1004 | **-2** |
| all 268 setup ops slot-free AND pinned to cycle 0 | 1004 | **-2** |
| ... AND every setup->consumer edge given lag 0 (values resident at c0) | 1004 | **-2** |
| head setup only (placed < 40) free + pinned + zero-latency | 1005 | -1 |
| head setup only (placed < 16) free + pinned + zero-latency | 1010 | +4 |
| head setup only (placed < 12) free + pinned + zero-latency | 1011 | +5 |

**The ceiling for H-064 is 2 cycles**, and that ceiling is physically
unreachable: the shortest path from program start to any input datum is
`const`(c0) -> `load` pointer(c1) -> `vload`(c2) -> readable(c3), so setup
can never be instantaneous. The partial-window rows are *positive* because
greedy is non-monotone here (section 3).

### 1. THE CHAIN, NAMED (deliverable 1)

268 ops carry `scheduler.tag is None`; 235 are placed in cycles 0..31, the
rest are mem-prime / result vstores strung along the whole stream. **Every
setup op has slack >= 494** (cp = 512 against a 1006-cycle schedule), so no
part of the setup is critical-path binding. Three chains matter:

**(a) the est-critical prefix** — the head of the cp=512 path, 5 ops deep:

```
#0     load  const        est 0  pl 0  slack 494   -> lit 4
#9     alu   +            est 1  pl 1  slack 494   dc_eight = 4+4
#15    alu   <<           est 2  pl 4  slack 494   dc_k0 = dc_sh5 << dc_eight   (16<<8)
#16    alu   +            est 3  pl 5  slack 494   dc_k0 += 1                   (4097)
#25    valu  vbroadcast   est 4  pl 6  slack 494   k0[0..7]
#269   valu  multiply_add est 5  pl 14 slack 494   FIRST hash op (val1*k0 + C0)
```

`derive_consts` bought a head load slot at the price of 3 cycles of depth
on exactly this chain. Reverting it for `k0` alone (`derive_consts_exclude=
("k0",)`, depth 5 -> 2) measures **1026 -> 1028**; every other single
constant is also +2; the best pair (`k0`,`kq`) is +1. The head load slot is
worth strictly more than the chain depth.

**(b) the `va` value-address chain — the DEEPEST setup-only chain (48 ops)**:
`const(6)` -> `load ivp`(est 1) -> `va_c24 = 8+16`(est 2) -> `va3`(est 3) ->
`va7`(4) -> `va11`(5) -> `va15`(6) -> `va19`(7) -> `va23`(8) -> `va27`(9) ->
`va31`(est 10) -> `vload val31`(est 11, placed 23). Four parallel `+32`
chains, depth 8, slack 532 throughout.

**(c) the `lv` table chain**: `const(4)` -> `load fp`(1) -> `add_imm
lv_addr`(est 2, pl 4) -> `vload lv[0..7]`(pl 6) -> `add_imm`(pl 6) ->
`vload lv[8..15]`(pl 7) -> ... -> `vload lv[24..31]`(pl 9) -> `^C5`(pl 10)
-> the 15 scalar diffs + 36 splats (pl 8..14). Doubly serialised: ONE
`lv_addr` register (WAR edge vload -> next add_imm) on the 1-wide flow
engine. Slack 502-536.

### 2. WHY THE RAMP IS 4 CYCLES, AND WHY IT IS NOT THE CHAIN

Head occupancy, cycles 0..7 (`h064_chain.py head`):

```
cyc   0    1    2    3    4    5    6    7
valu  0/6  1/6  1/6  3/6  6/6  4/6  5/6  4/6     free 24
alu   0/12 1/12 2/12 5/12 8/12 7/12 6/12 4/12    free 63
load  2/2  2/2  2/2  2/2  2/2  2/2  2/2  2/2     free  0
flow  1/1  0/1  1/1  1/1  1/1  1/1  1/1  1/1     free  1
```

valu is 6/6 from cycle 8 to cycle 957 without exception. The whole ramp
regret is the **24 free valu slots in cycles 0..7 = 4 cycles**, which is
exactly the `ramp 4` term of `regret 11 = ramp 4 + mid 3 + drain 4`.

Those slots are a **data-arrival** constraint, not a chain-depth one. No
steady op can execute before cycle 3 (const -> load -> vload -> read), and
before cycle 2 there are at most 2 non-zero scalars in scratch to broadcast,
so >= 10 of the 24 slots are unfillable by ANY program on this ISA. The load
engine is 2/2 saturated for cycles 0..30 carrying **all 60 setup loads and
nothing else** (9 `const`, 3 pointer `load`, 4 `lv` vloads, 44 `val`
vloads); the bubble at [31,65) opens only because the first gather's
release date is t=51.

### 3. GREEDY IS NON-MONOTONE HERE — capacity relaxations make it WORSE

`h064_oracle.py caps` / `headload`, program fixed, only per-cycle width
raised inside a head window:

| widened engine | [0,8) | [0,16) | [0,31) | [0,65) |
|---|---|---|---|---|
| load -> unbounded | **-2** | +10 | +10 | +12 |
| valu -> unbounded | 0 | +12 | +10 | +10 |
| alu -> unbounded | 0 | 0 | +12 | +10 |
| flow -> unbounded | 0 | 0 | 0 | +10 |
| store -> unbounded | 0 | 0 | 0 | 0 |

Giving a head engine MORE capacity costs up to 12 cycles. Same phenomenon
G-32 found by exhaustive re-scheduling (386,090 full re-schedules, best =
greedy's own 1006): **1006 is a razor-thin greedy optimum and any
perturbation of the head falls off it.** It also means the section-0
"ceiling" numbers are not two-sided bounds — but they are the right order
of magnitude, and no measured restructuring beat them.

### 4. RESTRUCTURINGS ATTEMPTED — all zero or worse (REALIZED cycles)

All screened ring-free (ring plans are address- AND order-specific; any
scratch change invalidates the shipped `parity_ring_plan` literals — three
candidate flags crashed with out-of-range gathers before being moved to the
ring-free baseline). Ring-free baseline at the frontier mix = **1026** (the
ring plan is worth 20 cycles).

| change | mechanism | realized |
|---|---|---|
| `va_chain_width=8` / `16` | va chain depth 8 -> 4 / 2, extra offsets derived on the idle alu | **exactly 0** (on the pool baselines with scratch for it) |
| model check: va->va edges lag 0 | chain collapsed to depth 1, program fixed | **+0** |
| `setup_lv_addr_alu` | 4 independent lv address regs on alu; kills the flow serialization AND the WAR chain | **+4** |
| `derive_consts_exclude=("k0",)` | est-critical chain 5 -> 2 deep, costs 1 head load slot | +2 |
| ... each of the other 8 derived constants | " | +2 each |
| ... best pair (`k0`,`kq`) / (`k0`,`sh1`) | " | +1 |
| `flow_residual_consts` (H-034) | the 6 arbitrary hash addends off load onto flow `add_imm` | +3 |
| `flow_consts` (H-021) | every constant onto flow | +5 |
| `derive_consts=False` | every derivable constant back onto load | +6 |
| `alu_val_addrs=False` | va addresses back onto flow | +19 |
| `vals_first=True` / `"hash"` | value vloads hoisted ahead of the tables | +5 (1029 -> 1034 on its own baseline) |
| `emit_order` in {group,round,wave,zip,diag} | setup/steady emission order | 0 (all identical) |

Nothing reached the ring-free baseline, so nothing qualified to be taken
through the standing chain (re-mine rings from empty -> re-slide `l4_gmin`
-> re-walk the order). **Mainline is unchanged at 1006.**

Two structural notes for the record:
- constants can only enter scratch through `load:const` (2/cyc) or
  `flow:add_imm` (1/cyc); `store` cannot produce scratch values and the alu
  has no immediate form, so the head's constant bandwidth is hard-capped at
  3/cycle and the store engine's 116 free head slots are unusable for it.
  The six residual addends (C0 `0x7ed55d16`, C1 `0xc761c23c`,
  ap `0xe9f8cc1d`, aq `0xaccf6200`, C4 `0xfd7046c5`, C5 `0xb55a4f09`) are
  arbitrary 32-bit words with no short derivation from the small pool.
- **scratch is full**: 1533/1536 words. `va_chain_width=8` needs 4 more
  words, `setup_lv_addr_alu` needed 3 (met by reusing `lv_addr` for block
  0). Any further setup restructuring must buy its words from a pool, and
  G-33 has already shown that is cycle-negative.

### 5. H-062 SETTLED — DEAD (folded in)

H-062: gather instead of serve at levels 1-3 for the group-rounds that
execute in the head bubble [31,65), converting compute into loads where
compute is the constraint and loads are idle.

Eligibility (`h064_chain.py`, min-est per (round, group) tag): only **66 of
512 group-rounds have min-est < 65**, and by tree level that is
`{L0: 32, L1: 13, L2: 8, L3: 8, L4: 5}` — so at most **29** L1-L3
group-rounds could ever place a gather inside the bubble.

- **Cost**: 29 conversions x 8 loads = **232 loads** against **68** free
  load slots in [31,65). The 164 that do not fit land in cycles 65..957,
  where the load engine is 2/2 saturated for 893 consecutive cycles (G-34)
  — +82 cycles at 2 loads/cycle.
- **Benefit, upper-bounded by measurement**: `h063_oracle window=31,65`
  frees every op the scheduler places in that window — freeing all 107
  valu ops there is **0**, and freeing all 142 ops on ALL engines is
  **-3**. The conversion removes strictly less compute than "all of it".

Upside <= 3 cycles, load cost ~82. H-063's evidence applies exactly as
suspected. **H-062 is closed negative; no per-level serving predicate needs
to be plumbed.**

### 6. VERDICT — this returns ZERO, and it closes the loop at 1006

- the motivating -13 is a measurement artifact (section 0);
- the clean ceiling on the entire setup phase is -2, and is physically
  unreachable (section 0);
- the ramp's 4 cycles are a data-arrival property of the machine, not a
  chain that can be re-associated (section 2);
- every chain-shortening restructuring measured 0 or positive, including
  the two that provably DO shorten their chains (va depth 8 -> 2 = 0, lv
  serialization removed = +4) (section 4);
- H-062, the only other survivor, is negative by ~80 cycles (section 5).

Frontier verification (config unchanged: `tools/h057_best_plan_1006.json`
`params.mix` + `emission_plan`, `c5_primed_gather_levels=(5,6)`,
`mem_prime_region_hazards=True`, `mem_prime_dead_reg_staging=True`,
`flow_spelling_plan=()`):

- correct on seeds {unseeded,1,2,3,7,42,99} and with `debug_compares=True`,
  1006 cycles on every one;
- `python3 tests/submission_tests.py` — 9/9 OK, `CYCLES: 1006`, speedup
  146.85;
- ring audit `OK over 40 rings`, 0 violations, plan at its grow-then-prune
  fixpoint (0 new rings addable);
- bound stack: cp 512 / load 946 (energetic 977, G-34) / alu 981 / **valu
  995 binds** / realized 1006, regret 11 = ramp 4 + mid 3 + drain 4;
- dev.py flags-off stream **bit-identical** to the pre-patch build (bundle
  list + `scratch_next_addr` = 1533).

### 7. Do not re-run

- `h063_oracle.py`'s phase classes as a *chain* diagnostic: the debug-engine
  reroute changes dev's adaptive race outcomes, so its deltas mix slot
  relief, floor relief, empty-bundle discounts and a genuinely different op
  multiset. For chain questions use `h064_oracle.py` (program fixed, greedy
  validated bit-exact per run).
- Widening any head engine, or any head-window capacity argument: all
  measured positive (section 3).
- Re-associating the va / lv / constant-derivation chains: measured
  0 / +4 / +2 (section 4).
- Serving-inversion in the head bubble at any level (section 5).
