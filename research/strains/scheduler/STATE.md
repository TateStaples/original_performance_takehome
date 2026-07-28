# Strain: scheduler

## Charter
Close the gap between actual cycles and the valu op-mix floor (1070 vs
6262/6 = ~1044 -> 26 cycles of scheduling friction): ListScheduler
priority/lookahead, emission-order search finer than skew, per-engine
tie-breaks. Owns: ListScheduler, the emission loop in
build_kernel_scheduled, tools/sched_profile.py. Rotated in iter 3 for the
retired critical-path strain; this file starts at iter 4.

## Frontier
**1070 (unchanged).** Iter 4 measured the friction first and then swept
the emission-order/tie-break lever space: every variant >= 1070. The core
finding is that the 26 cycles are NOT harvestable by reordering the same
ops — the friction decomposes into a load-throughput-bound setup ramp, a
chain-latency-bound drain, and ~0 middle slack — so the strain's charter
levers (order/priority/tie-breaks) are measured-exhausted at this op mix.
Default stream verified BIT-IDENTICAL to 283427d (programmatic instr
compare, scheduled + fallback paths); grader 9/9 green at 1070.

## The friction profile (the deliverable)
`tools/sched_profile.py` (new): builds the mainline with a default-off
placement trace in ListScheduler (`kb.sched_trace = []`), replays
emission order to re-derive every op's binding hazard, and explains each
empty valu slot. Because placement is greedy earliest-feasible, an empty
valu slot at cycle c means every later valu op had dep_ready > c — the
ops placed just after a gap, and their producers, are exactly what the
gap waited on. Headline (mainline, 1070):

- 158 empty valu slots over 55 gap cycles = 26 friction cycles;
  1015/1070 cycles run 6/6 full.
- **Drain tail, ~79 slots (~13 cyc)**: r15 (final round; L4-SERVED groups
  28-31 of the last skew block) + r14-15 seam + store-drain. Frontier ops
  are single groups' tournament+hash chains, RAW on `val`/`nv`; alu/load/
  flow all ~idle there. Groups finish in a ~5-cycle staircase (g28@1053
  -> g31@1068): each group's r15 inputs arrive staggered because the
  UPSTREAM is throughput-saturated. Post-parity chain of a served-L4
  round = ~7 select levels + 10 hash levels ~= 17 serial cycles.
- **Setup ramp, ~55 slots (~9 cyc)**: cycles 0-19, vbroadcasts RAW on
  `load:const` / lv vloads; the load engine is 2/2 SATURATED the whole
  ramp (~60 setup load slots: ~19 consts + 36 vloads + header/root).
  Load throughput, not ordering, is the binder.
- **Mid-stream scatter, ~24 slots (~4 cyc)**: L0/L9/L10 seams, mostly
  RAW on `val` (hash chain) with occasional gather-`nv`. Confirms the
  H-006 agent's finding: cycles ~100-950 are triple-saturated
  (valu+alu+load); there is nothing to harvest in the middle.
- Hazard kinds: RAW 141 / WAR 4.5 / WAW 1.5 of 158 — false dependencies
  (pool WAW/WAR) are NOT the friction; pool sizing is fine.

## Iter 4 variant measurements (all flag-gated, default-off, correct)
| variant | cycles | note |
|---|---|---|
| (default) | 1070 | bit-identical to 283427d |
| emit_order=stage | 1092 | per-block stage round-robin; ALSO raises valu slots 6262->6296 (worse race choices) |
| emit_order=stage_all | 1161 | cross-block round-robin; G-5 confirmed at op granularity |
| emit_order=stage_tail:1/2/3 | 1070/1074/1075 | drain-only interleave: neutral at best |
| emit_order=rev_tail:1/2/3/5 | 1077/1091/1089/1086 | critical-group-first at drain: negative |
| flow_consts=True | 1085 | consts on flow: the 1-slot flow queue (17 consts + 32 va + rec/la add_imms) becomes the new setup binder |
| vals_first=True | 1085 | val vloads before tables: delays lv stream +15 |
| vals_first="hash" | 1085 | val vloads after hash consts: same +15 (any lv delay costs the same) |
| tie_break=fold_flow / vec_valu | 1070/1070 | streams DIFFER (ties real), cycles identical |
| tie_break=idx_alu | 1073 | alu keeps idx ties: negative |
| combos (fold_flow,vec_valu[,idx_alu]) | 1070/1071 | |
| l4_gmin=(13,32)/(13,26)/(13,24) | 1086/1075/1083 | (13,28) locally optimal, both directions |

Bug found & fixed en route: stage-interleaving is only hazard-SAFE if no
shared pool temp (t1[s], cond/tm/tmM[j]; j = g % CP, CP=2 -> 4 groups per
block share) is live across a yield — mid-tournament yields corrupted
results (caught by run_variant's correctness check). The committed yield
points are all at pool-dead boundaries; both stage modes verified correct.

## Why the levers are exhausted (mechanism)
The greedy scheduler already places every op at its earliest feasible
cycle regardless of emission position; emission order only breaks
slot-contention ties. At 6/6 saturation ties are plentiful but
value-free: any reordering just relabels which group waits. The residual
friction is structural: (a) ramp = setup load-slot count / 2, (b) drain =
depth of the last block's final tournament+hash chain, (c) middle = 0.
Order/priority/tie-break knobs cannot change (a) or (b).

## Follow-ups proposed (for the driver)
- **b3-last final-round tournament (best lead, predicted -5..-8)**: at
  r15 the served-L4 fold tree folds by the NEWEST parity b3 first (8
  madds) then b2,b1,b0 selects — putting the r14-parity dependency at the
  chain HEAD. Reversing fold order (fold by b0,b1 early — st bits ready
  at round start — b3 LAST) makes the post-parity chain 1 select + hash
  ~= 11 levels instead of ~17, directly attacking the 13-cycle drain.
  Costs 8+4+2+1 = 15 selects vs 8 madds + 7 selects (neutral op count;
  needs both arms as values: all-8 odd tables = l4_race=True scratch).
  Op-level restructure -> flow-balance/op-reduction territory, final
  round only.
- **Setup load-slot removal** (ramp, up to ~9): fewer consts (derive
  hash constants from each other via alu at 12/cycle? e.g. kq = kp<<9,
  aq = (ap-C3)<<9 — each derived const frees a load slot for a vload),
  or vload 8 consts at once from a mem-resident constant table if one
  exists (it does not — would need a store first, store engine is free).
- Cross-check drain vs skew shape after any structural accept: the drain
  cost scales with the LAST block's chain depth, so shapes that end on a
  gather round (short chain) rather than served-L4 could reclaim ~5 —
  but epoch phasing is fixed by rounds=16; only l4_gmin=(.,32) tests it
  and loses +16 on gathers (net +16-13 > 0, consistent).

## H-024 successor work (iter 5): setup load-slot removal — variant frontier 1064

**Result: -6 (1070 -> 1064) from `derive_consts=True, alu_val_addrs=True`**,
flag-gated, default BIT-IDENTICAL to baa91e7 (programmatic instr compare,
scheduled + fallback paths); grader 9/9 green at 1070 (default dispatch
untouched). Variant correct on seeds {unseeded, 1, 2, 7, 42} and with
`debug_compares=True`.

Three new default-off kwargs in `build_kernel_scheduled`:

- `derive_consts` (H-024 lead 1): 9 of the 18 setup constants are cheap
  algebraic combinations of already-loaded ones and now materialize as
  IN-PLACE scalar alu chains (no temp words) instead of one `load:const`
  slot each: 2=1+1, 8=4+4, sh5=16=1<<4, k4=9=8+1, kp=33=16+16+1,
  kq=kp<<k4 (0x4200=0x21<<9 confirmed), k0=(16<<8)+1=4097,
  sh1=19=(2+1)+16, negtwo=(1^1)-2. The arbitrary hash addends (C0, C1,
  ap, aq, C4, C5) have NO 1-op relations (brute-forced over +,-,^,|,&,
  shifts against every loaded scalar; also loading C2+C3 instead of
  ap/aq is load-count-neutral) and stay as loads, as do 1/4/6 (header
  critical path: deriving 6 delays the ivp load +2 on the val0 path).
  14 alu ops (idle ramp) replace 9 of ~21 scalar load slots. Alone: 1068.
- `alu_val_addrs` (found while profiling lead 2): the 32 initial-value
  vload ADDRESSES (ivp + 8g) move off the 1-wide flow engine (32 serial
  add_imms which booked flow solid to ~cycle 40, gating val vloads at
  1/cycle from c16 and crowding the tournament fold vselect races off
  flow) onto the alu as four parallel +32 chains (34 ops, 2 scratch
  words for the 24/32 steppers). Alone: 1070 — the const-load queue is
  still the binder; composed with derive_consts: **1064**, and total
  valu slots drop 6262 -> 6261 (one fold race wins flow back).
- `lazy_val_loads` (H-024 lead 3, NEGATIVE control): emitting each
  group's va/vload at its round-0 first touch instead of up-front is
  +9 alone (1079) — the va flow add_imms then claim slots BEHIND the
  pst/rec setup ops, delaying round-0 starts — and exactly neutral under
  alu_val_addrs (1064: placement backfills, emission position of
  feasible-early ops only moves ties). Confirms H-021's mechanism note.

Ramp profile before/after (tools/sched_profile.py):
| | mainline | derive+alu_val_addrs |
|---|---|---|
| cycles | 1070 | 1064 |
| friction vs valu floor | 26 | 20 |
| empty valu slots (gap cycles) | 158 (55) | 123 (45) |
| setup-ramp empty slots | 49 | 22 |
| first tagged (round-0) cycle | 12 | 7 |
| load engine | 2/2 c0-c15, then 1/cyc (flow-gated vals) | 2/2 c0-c15 solid |
| ramp blockers | load:const 33.3, vload/add_imm | val 73 (r0 hash warmup), load:const 9.5 |

Composition sweep: tie_break=fold_flow 1064 (=), flow_consts 1066,
vals_first=True/'hash' 1070/1070, +lazy 1064 (=). Remaining ramp (~22
slots over c0-c6) is round-0 hash-chain warmup + the irreducible
fp->root->bvec->fold depth — near-structural; the drain (r15 L4, 66
slots) is untouched and stays H-023's territory. Follow-up for the sweep
strain: re-tune l4_gmin/skew/pools under derive_consts+alu_val_addrs
(the ramp shift may move the sharp 1070 optimum).

## Iteration log
(append-only)
- iter 4 (H-021): friction profiled to the slot (tools/sched_profile.py,
  trace hook in ListScheduler — default-off, bit-identical). 26 cycles =
  13 drain (chain latency) + 9 ramp (load throughput) + 4 scatter
  (saturated). 16 emission-order/setup/tie-break variants measured, ALL
  >= 1070; levers measured-exhausted; flags kept in-tree as negative
  controls + sweep dimensions (emit_order, flow_consts, vals_first,
  tie_break). Honest zero; b3-last drain restructure promoted as the
  strain's successor lead. Grader 9/9 @ 1070.
- iter 5 (H-024): setup load-slot removal ACCEPTED at the variant
  frontier: derive_consts (9 consts alu-derived, kq=kp<<9 et al.) +
  alu_val_addrs (32 va addresses off flow onto 4 parallel alu chains)
  = 1070 -> 1064; ramp empty slots 49 -> 22, round 0 starts c12 -> c7.
  lazy_val_loads negative alone (+9), neutral composed — kept as a
  negative control. Default bit-identical; grader 9/9 @ 1070.
- iter 7 (H-031, post-H-030 mainline 1041): store-drain re-investigation
  per the driver's 3-region brief (setup ramp / final-round drain /
  store-drain tail). Findings + accept below.

## H-031: store-drain tail was a scheduler mem-model artifact, not a
structural bound. Mainline **1041 -> 1038** (flipped into perf_takehome.py)

**Region 3 (store-drain) -- REAL FIND, ACCEPTED and FLIPPED.** The class
docstring says memory is tracked coarsely (one pseudo-location for all of
mem) because "reads are plentiful (gathers) and the only writes are the
final vstores, so per-address tracking would buy nothing" -- true for
WAW (H-028 already fixed that side with `store_pair`), but nobody had
checked the WAR/mem_write-vs-mem_read side: `ready()`'s `mem_write`
branch makes EVERY store wait until `last_mem_read_cycle`, the cycle of
the LAST gather anywhere in the entire kernel, address-oblivious. Direct
measurement (script: dump `kb.sched_trace`, tag = (round, group), find
each group's last write to its own `val{g}` address): group 0's hash
chain is fully done at cycle **696**, yet its store is placed at cycle
**1025** -- a 329-cycle wait purely from this coarse gate, NOT from any
real hazard. Every group's finish time (696 for g0 up to 1036 for g31)
sits far below the actual store cycle (1025-1040): the store engine sits
completely idle (except 5 small mem_prime writes at c23-36) for ~989
cycles despite results being ready.

This is provably safe to relax for the FINAL store loop specifically:
`build_mem_image` (problem.py) lays out `forest_values_p` (gather source)
and `inp_values_p` (store target) as consecutive, disjoint, STATIC
ranges; gather addresses never leave `[forest_values_p, forest_values_p +
n_nodes)`. The only reads that ever touch `inp_values_p` are each group's
one-time initial vload, which complete at setup (~c40), always before any
store's earliest possible ready cycle (>=696, since a store needs its
group's full round-15 hash chain). mem_prime's tree-priming writes DO
alias their own reads (read tree, xor, write back) and are left untouched.

Implementation: `ListScheduler.ready`/`.emit` take a new
`ignore_mem_read_hazard` param (default False in `dev.py`; wired
unconditionally into `perf_takehome.py`'s single final-store call site).
A companion `store_order` mode `"finish_asc"` (dev.py only) sorts the
store loop by each group's ALREADY-KNOWN `scheduler.last_write[hash_chain_vecs[g]]`
instead of natural group index; measured IDENTICAL to natural "group"
order (1038) -- the default group layout (skew blocks ascending) already
tracks finish order closely enough that sorting buys nothing extra.

MEASURED (mainline 1041 baseline, verified both via `tools/run_variant.py`
and directly against `perf_takehome.py`):
  store_disjoint_region=True                    1038  (-3, FLIPPED)
  + store_order="finish_asc"                    1038  (=, redundant)
  + store_order="rev"                           1053  (+12: reversing
    emission order violates the WAW gate's monotonicity -- g31's store
    (ready ~1037) gets processed FIRST, bumping `last_mem_write_cycle` to
    1037, which then floors every earlier group's store back up to 1037)
  + store_order="tail_first"                    1053  (same mechanism)
  l4_gmin retune under the flag: (9,30) [default] 1038, (10,30) 1040,
    (9,29) 1042, (8,30) 1041 -- default l4_gmin stays optimal, no retune.
Verified correct on 8 draws (seeds 1-7, 42, unseeded) + `debug_compares=True`,
grader 9/9 green @ 1038. Profile after the fix (`tools/sched_profile.py
--detail`): the store-drain region drops from 4 fully-idle-except-store
cycles to 1 (cycle 1037 only); stores now interleave with the r15 L4
drain's compute instead of trailing it.

**Regions 1 and 2 -- re-confirmed structural, no new lever found.**

- Setup ramp: re-profiled at the 1041 mainline (post-H-030). Load engine
  runs 2/2 solid every cycle from c0 through the whole ramp with zero
  idle load slots -- confirmed throughput-bound, not latency-bound.
  Counted the necessary load-engine ops still in the ramp: 6 arbitrary
  hash constants (C0, C1, ap, aq, C4, C5 -- H-024 already brute-forced
  these against every 1-op alu combination of loaded scalars, found none)
  + 2 header loads + 1 root load + 32 val vloads (one per group, real
  input data, not derivable) + ~2 level-table vloads = ~43 load ops,
  ceil(43/2) = 22 cycles -- matches the profiler's 22 measured empty-slot
  count exactly. This is a tight floor: shrinking it further needs either
  a new algebraic relation among the 6 remaining constants (already
  proven absent) or a way to fetch more than 2 load-engine words/cycle
  (an ISA change, out of scope). No new idea found; H-024's `derive_consts`
  + `alu_val_addrs` already harvest everything derivable.
- Final-round drain (r15 L4 + r14-15 seam): re-profiled; alu/load/flow
  sit mostly idle there (e.g. cycle 1033: alu=0, load=0, flow=0, only
  valu busy at 2-3/6) while valu chases a genuine serial RAW chain on
  `val` (multiply_add -> ^ -> >> -> ^, level by level, the hash's own
  stages). This is the identical mechanism H-002/H-010/H-023 already
  measured exhaustively: the chain is the hash itself, already shortened
  once (H-027's `b3l_diffs`, in mainline) and its shortening bought
  nothing further to try beyond what's landed -- there is no unconsumed
  slack on any OTHER engine at those specific cycles to move work onto
  (unlike the store-drain, where the store engine had ~989 cycles of pure
  idle capacity, the alu/load/flow idleness here is only a few slots per
  cycle, already smaller than one op's worth of useful relocatable work).
  No new speculative-fold or reordering variant was tried beyond H-023/
  H-027/H-030's existing sweep since no new mechanism (unlike H-031's
  mem-hazard finding) was found to justify one; this region is treated as
  re-confirmed rather than newly closed.

## H-031b: applied H-031's lens to the other 3 hazard-coarseness angles --
one real (but negative) find, three confirmed no-ops. Mainline unchanged (1038).

Instrumented `ListScheduler.ready()` directly (temporary stderr prints on
every branch-fire, reverted before finishing) and ran the full mainline
build (seed 1, and re-checked seeds 2-5/42/100 plus several non-mainline
flag combos to vary the schedule shape) to get real fire counts instead of
guessing.

**Angle 1 (mem_read-vs-mem_write RAW gate, `ready()` line
`if mem_read and self.last_mem_write_cycle + 1 > cycle`) -- fires ONCE in
the entire build, and never during any real (round-loop) gather.** The one
fire is `dev.py`'s mem_prime loop (H-026): its first vload (tree level
d=5) waits on the just-emitted pair-tournament priming stores (tree level
L4=4) -- cycle forced 11 -> 25. This is provably a false hazard the same
way H-031 was: `build_kernel_scheduled` already asserts
`all(L4 < d < forest_height + 1 for d in primed_gather_levels)` (line
~994), and per-level tree-node ranges are disjoint by construction, so
mem_prime's reads can never actually alias the pair-tournament's writes.

Implemented as a new default-off flag to test it properly rather than
leaving it as a hunch: `ListScheduler.ready`/`.emit` gained a symmetric
`ignore_mem_write_hazard` param (mirrors H-031's `ignore_mem_read_hazard`
but for the read side), wired at the mem_prime vload call site via new
`build_kernel_scheduled` kwarg `mem_prime_ignore_l4_hazard` (default
False). **Measured: 1038 -> 1039 (a 1-cycle REGRESSION), reproduced
identically across seeds {1,2,3,4,5,42,100} and with `debug_compares=True`
-- correct on all, but worse.** Relaxing the gate lets the vload land
earlier, which perturbs the greedy schedule's downstream tie-breaks enough
to cost 1 cycle elsewhere net. Verified-safe, verified-not-a-win: flag
kept in tree, default off, as a negative control (matches H-024's
`lazy_val_loads` precedent for documenting a correct-but-negative lever).

**Angle 2 (mem_prime's own priming writes serializing against each
other) -- confirmed NO-OP.** Instrumented the `mem_write` WAW branch
(`t = last_mem_write_cycle + (0 if pair_writes else 1)`) the same way:
zero fires anywhere inside the mem_prime loop. The only WAW fire in the
whole build is in the unrelated final-store loop (two disjoint result
stores co-locating into the same cycle under `store_pair` -- expected
H-028 territory, not a new gap). mem_prime's 3-buffer round-robin
(`stage = level_table + (k%3)*VLEN`) already spaces iterations far enough
apart (via real per-address scratch RAW/WAW and engine throughput) that
the coarse mem WAW gate never has to intervene. No lever found here.

**Angle 3 (per-address `last_write`/`last_read` dicts falling back to a
range coarser than necessary) -- confirmed NOT APPLICABLE.** Read every
helper that builds `reads`/`writes` lists (`vec`, `vsel`, `madd`,
`dual_fold`, `race_sel`, `race_copy`, `race_idx_madd`, `race_leaf`,
`depth_first_fold`, the scalar per-lane gather loop, the tournament
level-table load loop). Every one passes exactly the touched address
range (either the precise `self._v(addr)` VLEN block for vector ops, or
the single `addr+i` for per-lane scalar ops) -- no case of a whole-vector
hazard computed when only a sub-range is touched, and no `min_cycle`/hint
mechanism more conservative than the actual per-address maxima (the one
`min_cycle` use, the final `pause`, is a legitimate ordering requirement,
not a hazard proxy). This code has already been hardened through H-001..
H-031; the per-address tracking is precise.

**Angle 4 (`first_free_cycle_hint` staleness risk) -- confirmed SAFE, no
bug.** Read `put()`'s hint-advance logic: the hint for an engine only
advances past a cycle after re-scanning and confirming `engine_slot_counts
>= SLOT_LIMITS` at every cycle in the newly-claimed range, and slot counts
are monotone non-decreasing (ops are only ever added), so "cycles below
the hint are full" is an invariant that, once established, cannot be
invalidated later. Every code path that places an op (`emit`, `emit_any`'s
committing loop, the `_sched_vec` alu/valu split) routes through
`find_free`, which always clamps to the hint first -- there is no
direct-`put()` path that could plant an op below a stale hint. Verified
empirically too: instrumented a post-build assertion (every cycle below
each engine's final hint must be at its slot limit) across the mainline
config plus 7 shape-varying overrides (`alu_offload=False`,
`store_pair=False`, `l4_gmin=(6,30)`, `vals_first="hash"`,
`emit_order="stage_all"`, `skew=(6,2)`) -- zero violations in any of them.
The docstring's claim ("optimization for scan speed, not correctness") is
verified true; this is not a missed-earlier-placement bug.

All temporary instrumentation reverted; `dev.py` diff after this session
is exactly: the `ignore_mem_write_hazard` param + docstring note, the
`mem_prime_ignore_l4_hazard` kwarg (default False), and its one call site
-- all inert unless explicitly turned on via `tools/run_variant.py --set`.
Mainline (`perf_takehome.py`, `tools/run_variant.py` default) unchanged at
1038; `tests/submission_tests.py` re-run clean (9/9, 1038, speedup
142.3x).

- iter 8 (H-032): bounded generalization of H-031's single-flag fix into
  a small per-region mem-hazard model, per the driver's brief. Investigated
  and NOT adopted -- mainline stays 1038, unchanged.

## H-032: generalized H-031's flag into a per-region mem hazard model;
provably sound, but REGRESSES the real schedule by 1 cycle. Not adopted.

**What was built.** `build_mem_image` (problem.py) lays out a handful of
statically disjoint ranges: a 7-word header, `forest_values_p` (tree node
values -- read by every gather and the tournament broadcast-table vloads;
written IN PLACE only at two specific tree levels by the C5-priming setup:
level L4 via `pair_tournament_level_mem_primed`'s `primed_store`, and each
level d in `c5_primed_gather_levels` via `mem_prime`'s vload/^C5/vstore
wave), and `inp_values_p` (read once per group at setup, written once per
group by the final vstores). Replaced `ListScheduler`'s single
`last_mem_read_cycle`/`last_mem_write_cycle` scalars with per-region dicts
and tagged every one of the 9 `mem_read=True`/`mem_write=True` call sites
with which range(s) it provably touches (tree levels are disjoint index
ranges by construction, so a level-4 write and a level-5 read/write never
alias). This exactly subsumes H-031 (the final store's region,
`input_values`, never overlaps any forest region, so its write skips every
gather's read hazard with no flag needed) AND additionally lets
`mem_prime`'s own priming read for level d skip waiting on `primed_store`'s
unrelated level-L4 write (previously coarsely serialized: measured via a
stack-tracing probe on the coarse model, one such read's ready cycle was
bumped from 11 to 25 purely by the address-oblivious gate -- independently
reproducing H-031b's angle-1 finding via a completely different
implementation).

**Measured effect: correct, but WORSE, not better.** Swapping in the full
region model (all 9 sites tagged, `store_disjoint_region`'s exemption now
implicit) measured **1039** on every seed tried (1-4), one cycle ABOVE the
1038 mainline the narrow H-031 flag already achieves -- correct
(`debug_compares=True` green) but strictly worse wall-clock. Bisecting by
re-adding the scalar-coarse mechanism and relaxing ONE hazard at a time
isolated the cause precisely: separating the initial per-group val-vloads
(`input_values` region) from the forest reads removes a hazard that
`primed_store`'s write was incidentally depending on for ITS OWN placement
(the val-vloads happen to be the last read recorded in the shared bucket
right before `primed_store` emits, even though the two are genuinely
address-disjoint). Relaxing it lets `primed_store` schedule one cycle
earlier, which ripples into a different engine-slot conflict later in the
tightly packed setup ramp and costs a cycle back, net negative. This is a
real property of greedy list scheduling, not a bug: a strictly looser
hazard constraint is not guaranteed to yield a monotonically better (or
even equal) placement once engine-slot contention is involved.

To separate this ripple from the OTHER, genuinely new relaxation
(`mem_prime`'s read vs the unrelated level-4 write), that piece was
isolated in total independence -- added as `last_mem_write_cycle_by_region`
tracked ALONGSIDE the untouched original scalars/flags (everything else,
including `input_values`, stays on the exact 1038 mechanism) and gated
behind a new `mem_prime_narrow_hazard` flag. Result: **1039** on seeds
1-4 with the flag on, **1038** with it off (default) -- so even fully
isolated from the val-vload ripple, this specific "beyond H-031" find is
ALSO a 1-cycle regression on its own, matching H-031b's independent
finding of the same result via a differently-shaped flag
(`mem_prime_ignore_l4_hazard`). Two independent implementations agree.

**Verdict: not adopted.** Region tagging is architecturally sound and
DOES remove every false hazard the coarse model has in this kernel
(nothing further was found beyond the two cases above), but empirically
it is a net loss here, not a free generalization -- the coarse model's
one surviving "false" hazard (mem_prime vs level-4) turns out to be
load-bearing for the SCHEDULE (not for correctness) via a greedy-
scheduler side effect: relaxing a hazard is not guaranteed to yield a
monotonically better placement once slot contention is involved. Mainline
stays on the exact H-031 mechanism; no flag added to `perf_takehome.py`
or `tools/run_variant.py`'s `BASE_KWARGS` (both investigation flags kept
`dev.py`-only, default off, for reproducibility).

## H-033 (iter 6): collect-then-schedule PriorityScheduler prototype

**Result: implemented, verified CORRECT, measured WORSE.** This was built
in a worktree checked out from an old base commit (predating this
session's idx_select/fold_flow/H-031 wins), so all measurements below are
against that worktree's own "mainline" of **1053 cycles**, not the 1038
this session's true current mainline achieves. The DESIGN and MECHANISM
findings are architecture-level (about global-DAG scheduling vs streaming
placement on this workload's reuse pattern) and hold regardless of the
absolute baseline number; only the raw cycle counts below are relative to
the older 1053 checkpoint, not today's 1038.

### Design (see the agent's worktree `dev.py` `ListScheduler.collect_tasks`/
`_collect_task` and the new `PriorityScheduler` class, right after
`ListScheduler` -- NOT applied to this repo's `dev.py`, see Porting below)

A genuine collect-then-schedule architecture, per the external repo's
description: flat task DAG, backward pass (priority = longest path to a
sink, downstream = fanout with multiplicity), forward pass (global
ready-set re-evaluation per cycle, greedy pick by `(priority, downstream,
-task_index)` per engine, same SLOT_LIMITS/RAW(1)/WAW(1)/WAR(0) gap
semantics as `ListScheduler.ready()`).

Key engineering decision (avoiding a rewrite of the ~2000-line hash/
tournament/idx builder body against a second placement-deferred
interface): the existing `ListScheduler` run IS the collection phase.
It gained an additive, default-off `collect_tasks` flag: when on, every
`put()` (including the ones `emit_any`'s local race resolution and
`dual_fold`/`_sched_vec` already call) ALSO appends a Task and derives
hazard edges from task-id analogs of `last_write`/`last_read`, with ZERO
change to any cycle ListScheduler itself returns or any race it resolves
-- the build produces the exact same op stream as `scheduler_mode="list"`,
byte for byte (confirmed: total ops per engine identical in every
measurement). `PriorityScheduler` then consumes ONLY the collected
tasks/edges -- never ListScheduler's own cycle numbers -- and re-derives
placement completely from scratch, a real (not simulated) global pass
that can and does place tasks in a different cycle order than emission
order.

One real bug found and fixed en route: tracking only the SINGLE latest
reader of an address (mirroring `ListScheduler.last_read`'s single-max-
cycle dict) is UNSOUND for a DAG meant to support arbitrary rescheduling
-- two independent readers with no edge between them can land in either
order under a from-scratch forward pass. Fixed by tracking the full
reader list since the last write and adding a WAR edge to every one of
them. Caught by the correctness harness at forest_height>=4 (small shapes
never exercised the failure mode) -- a silent wrong-answer bug before the
fix.

### Correctness
60/60 passing (6 shapes x 5 seeds x {list, priority}, `debug_compares=True`
full per-value trace assertions) after the WAR fix, plus 6 seeds at the
full graded shape (forest_height=10, batch=256, rounds=16) with the
complete accepted flag combination -- correct every time. `list` mode
(mainline) confirmed bit-identical throughout.

### Measured cycles (full graded shape, seed 1, identical across 6 seeds)
| scheduler | cycles | delta vs list |
|---|---|---|
| list (that worktree's mainline) | 1053 | -- |
| priority (priority+downstream tie-break) | 1097 | **+44** |
| priority, downstream forced to 0 (priority+index only) | 1081 | +28 |
| priority, priority forced to 0 (downstream+index only) | 1066 | +13 |
| priority, both forced to 0 (pure task-index / program order) | 1072 | +19 |

Total ops per engine identical across every row -- every regression is
100% placement, not op count.

### Where the extra cycles go
`list`: 37 gap cycles, concentrated in the ramp (7) and the drain (28) --
the parallel middle has 0, confirming this strain's prior findings.
`priority`: 139 gap cycles -- 123 of the 139 are in the DRAIN alone
(modest +11 in the ramp); almost the entire regression is the priority
scheduler's drain being much worse than list's.

### Why (best-supported mechanism, not fully root-caused)
The ablation table is the key evidence: removing the priority (longest-
path-to-sink) signal HELPS (1066, downstream+index-only is least bad),
and the full priority+downstream combo is WORST (1097) -- critical-path
prioritization is actively counterproductive here, not merely unhelpful.
But even "no reprioritization at all" (both forced to 0, strict emission
order over a globally-reevaluated ready set) is still +19 over
`ListScheduler`'s incremental greedy placement. That isolates the real
cost: a from-scratch forward pass over a fully-expanded task DAG cannot
losslessly reproduce `ListScheduler`'s tighter packing on this workload's
dense small-pool (temp/cond pool sizes 16/4) WAR/WAW reuse pattern --
correctness requires an edge to EVERY reader since the last write (not
just the latest), a strictly larger constraint set than the single
per-address cycle floor `ListScheduler.ready()` uses, and this denser
edge set binds harder in the resource-starved drain (few groups left, few
ready tasks, narrow slack) than in the wide parallel middle (always >=6
ready valu tasks regardless of extra edges). `ListScheduler`'s cycle-
based, incrementally-updated, monotonic `first_free_cycle_hint` placement
appears to be a better fit for THIS workload's specific reuse pattern
than a generic priority-DAG re-derivation, at least with the priority/
downstream metrics implemented here. Untried follow-ups: a distinct-
descendant (bitmask) downstream count, a regionally-normalized priority,
or a hybrid (list-schedule the drain, priority-schedule the middle).

### Porting to `perf_takehome.py`
NOT PORTED -- the measured result is a regression. The code lives only in
the now-cleaned-up agent worktree (not this repo's `dev.py`); a future
session that wants to pick this up would need to re-implement it (design
fully specified above: additive `collect_tasks` bookkeeping on
`ListScheduler` + a new `PriorityScheduler` class + a `scheduler_mode`
kwarg on `build_kernel_scheduled`) rather than restore a patch, since it
was built against a stale pre-refactor base commit.

## Iteration log addendum
- iter 6 (H-033): built a genuine collect-then-schedule alternative
  (`PriorityScheduler`), NOT a local tweak -- the thing this strain
  repeatedly flagged as the one unattempted lever that could close the
  gap to the external repo's 1026. Verified correct (60/60 small-shape
  runs + 6 full-graded-shape seeds, one real WAR-edge soundness bug found
  and fixed). Measured WORSE at every priority/downstream configuration
  tried, worst case +44 (that worktree's 1053 -> 1097), concentrated 84%+
  in the drain. This is a substantive, well-executed NEGATIVE result: the
  external repo's architectural pattern, correctly replicated, does not
  help THIS kernel's specific op-mix/pool-size regime -- the streaming
  scheduler's single-per-address-cycle-floor approximation turns out to
  be a genuine asset (not just a limitation) for a workload with small,
  densely-reused temp/cond pools, not a strict downgrade from a "real"
  global scheduler. Not ported; documented for any future reopen attempt
  (distinct-descendant downstream, regional priority, or a hybrid
  drain/middle policy are the concrete unexplored variants).
- iter 7 (H-034, ported from the external repo's now-1020-cycle commit):
  ported the `add_imm`-off-a-zero-register scalar-constant mechanism,
  scoped narrowly to `derive_consts`'s documented residual set (C0, C1,
  ap, aq, C4, C5 -- the six with no 1-op algebraic relation, per H-024).
  Measured WORSE, 1038 -> 1041 (+3), reproduced identically on seeds
  {1,2,3,7,42,unseeded} and correct under `debug_compares=True`. Not
  adopted; see H-034 below.

## H-034: flow_residual_consts (six residual hash addends via flow add_imm
off an alu-derived zero) -- correct, reproducible +3 regression. Not adopted.

**What was built.** New `derive_consts`-dependent flag `flow_residual_consts`
in `dev.py`. When on: a scratch zero word is materialized with one alu `^`
(`residual_zero_c = one_c ^ one_c`, costing an idle-ramp alu slot, NOT a
load -- unlike H-021's `flow_consts`, which spends one real `load:const 0`
for its zero base), then each of `derive_consts`'s six un-derivable
arbitrary addends (C0, C1, ap, aq, C4, C5) is emitted as
`flow: add_imm(dest, residual_zero_c, value)` instead of `load: const`,
inside the existing `const()` closure (checked before the plain load
fallback, gated on `val in residual_flow_const_values`). Confirmed valid
against `problem.py`'s `Machine`: `add_imm(dest, a, imm) = (scratch[a] +
imm) % 2**32`, so `add_imm(dest, zero, C) == C` exactly. This is a
narrower, more targeted mechanism than H-021's `flow_consts` (which routes
ALL scalar constants through flow and was already measured negative, both
alone at the old mainline -- 1085 vs 1070 -- and composed with
`derive_consts` -- 1066 vs 1064): here only 6 of the ~20+ setup consts
move, and the zero base itself doesn't cost a load slot either.

**Measured: 1038 -> 1041 (+3), reproduced on 6 seeds, correct on all
(`debug_compares=True` green).** `tools/sched_profile.py` shows why: the
setup-ramp empty-valu-slot count DOES drop slightly (22 -> 19, confirming
the 6 freed load slots help the ramp itself), but total valu slots
INCREASE (6125 -> 6131, +6) and total gap cycles rise (44 -> 52, +8),
with a brand-new 8-slot gap appearing at `r0-0 L0` (round-0 startup) that
didn't exist before, plus `flow:vselect` newly appearing as a gap-blocker
producer (10.8 weighted slots) where it wasn't one previously. Mechanism:
this kernel's `emit_any` fold races dual-encode some ops as EITHER a flow
`vselect`/`add_imm` OR a valu op, resolved by whichever engine is free
first at emission time (H-021's `tie_break=fold_flow` territory). Adding
6 extra flow ops early in the ramp shifts those race outcomes -- some fold
races that used to win flow now lose it and fall onto valu instead,
which is the already-saturated 6-wide engine everywhere except the ramp/
drain. The net (+6 valu slots, delayed round-0 start) costs more than the
6 freed load slots save. This is the same qualitative mechanism H-024
noted in passing for `alu_val_addrs` ("one fold race wins flow back") and
the same failure mode documented for `flow_consts` -- moving scalar setup
work onto flow is not free here because flow is a shared resource with
the fold-race encoder, not an idle sink.

**Verdict: not adopted.** Flag kept in `dev.py`, default off, as a
negative control (same precedent as `flow_consts`, `lazy_val_loads`,
`mem_prime_ignore_l4_hazard`). Mainline (`perf_takehome.py`,
`tools/run_variant.py` `BASE_KWARGS`) untouched at 1038; the six residual
constants stay as `load:const` -- H-024's floor analysis (43 load ops,
ceil(43/2)=22 ramp cycles, zero idle load slots) is reaffirmed as tight
in the sense that even successfully removing load-engine pressure doesn't
help once the freed engine (flow) has second-order coupling to the fold
races elsewhere in the schedule.

## H-042 (2026-07-27, UNPARKED re-scoped): joint instruction-selection x
## scheduling via offline-searched spelling plans — STRAIN FRONTIER 1032 -> 1031,
## mechanism landed, per-site selection space measured-EXHAUSTED at 1031

Charter (unpark): the flow leg of the frontier organization — three
independent measurements (G-4/G-12, H-045 3rd confirmation, H-044 LP)
say ~60 modeled cycles route through a bubble-free flow engine and that
no spelling/flag change reaches it, because select readiness is
anti-correlated with flow bubbles. Build a scheduler-side mechanism that
co-decides WHAT spelling to emit and WHERE/WHEN.

### Mechanism landed (dev.py, flag `flow_spelling_plan`, default () = bit-identical)

`ListScheduler` numbers every multi-encoding `emit_any` race site in
emission order on two counters: flow-containing races (dual_fold /
race_sel / race_leaf / race_copy — unconditional calls, emission-stable
subsequence) keyed >= 0, schedule-dependent non-flow races (_sched_vec
alu/valu splits, race_idx_madd) keyed -(i+1). The kwarg maps site key ->
encoding index, placed UNCONDITIONALLY (race skipped). KEY SOUNDNESS
PROPERTY: every encoding of a site is a semantically equivalent spelling
of the same computation, so ANY plan is correct by construction — only
cycles move; the H-048 emit_any-liveness unsoundness does NOT apply
(we never borrow storage, we only pick spellings). Verified programmatic
bit-identity vs HEAD flags-off (mainline + 1032 frontier); full gate 9/9
green flags-off. `sched_snap`/`sched_install` carry both counters (spec_fold
rollback safety). Offline driver: scratchpad h042_search.py (greedy sweep
over per-site flips + sideways plateau walk, objective = bundle count,
~0.1 s/build => thousands of exact evaluations per run).

### Selection-slack instrumentation (1032 frontier build)

- 2,087 emit_any sites, 1,063 with >= 2 legal spellings; 388 carry a
  pure-flow spelling (the joint-search currency). Greedy already puts
  233 on flow; 155 lose to valu/alu.
- Flow busy 783/1032 = 75.9% => 249 bubble slots. Of the 155 flow-lost
  sites, ZERO have a final free flow slot within retire-delta <= 3 of
  their chosen cycle — the G-4/G-12 anti-correlation confirmed at site
  granularity (bubbles live in windows where no select is losing).
- Consumer-slack oracle (place the vselect anywhere in
  [hazard-ready, first-consumer-read - 1] into a FINAL-schedule bubble):
  only 46/155 are feasibly movable at all; 80/155 have slack <= 0
  (consumer reads next cycle).

### Measured results (all correct:true where run through the grader)

| config | greedy | + searched plan | plan | flips |
|---|---|---|---|---|
| BASE mainline (dev) | 1038 | 1037 | ((22,0),) | 1 fwd: (2,7) ramp fold valu->flow |
| parity_ring (8,30), no ring plan | 1037 | 1032 | ((1,1),(148,2),(354,1)) | 2 rev + 1 alu-arm |
| parity_ring (7,30), no ring plan (= F-1 mainline form) | 1034 | **1032** | ((185,0),(361,1)) | 1 fwd (slack 0) + 1 rev — matches the ring-plan frontier WITHOUT rings |
| frontier: ring plan 4 rings (8,30) | 1032 | **1031** | ((354,1),) | 1 rev: (13,29) drain fold flow->valu |
| ring plan @ (7,30) | 1034 | 1032 | ((2,1),(361,1)) | 2 rev |
| ring plan @ (9,30) | 1036 | 1032 | ((0,1),(5,1),(347,1)) | 3 rev |
| ring plan @ (8,29) / (8,31) | 1035 / 1035 | 1033 / 1035 (no flip found) | ((340,1),(394,1)) / () | 2 rev / 0 |

**New strain frontier: 1031** = 1032 config + `flow_spelling_plan=((354,1),)`.
Verified: seeds 1,2,3,7,42,99 all 1031 correct; debug_compares=True 1031
correct; full gate flags-off 9/9 green (mainline 1034 untouched).
Equivalent verified 1031: FULL-16-ring parity_ring_plan (all 384 audited
words, complete cond retention) + flow_spelling_plan=((1,1),(352,1)) —
seeds 1,2,3,7,42,99 all 1031 correct. The F-1-form
(parity_ring, (7,30), no ring plan) + ((185,0),(361,1)) = 1032, seeds
1,2,3,7,42,99 all correct — matches the ring-plan frontier with zero
borrowed words, the natural mainline port candidate.

### The mechanism that actually pays (surprise, inverted)

The modeled direction (push MORE selects onto flow into bubbles) NEVER
pays here: batch-forcing all 115 slack-feasible valu->flow flips = 1077
(+45); every single forward flip on the ring-relieved configs is
neutral-to-negative. What pays is the REVERSE: forcing a flow-WON race
OFF flow (to its valu/alu spelling) in the ramp/drain windows. Greedy
emit_any is myopic — it minimizes own retire time and takes a flow slot
that a later, tighter op needed; the searched flip returns the slot and
re-routes several downstream races (the 1031 build differs from 1032 by
-5 valu, -8 alu, +3 flow slots: one forced flip cascades through
subsequent race decisions). All paying flips sit exactly in H-041's soft
windows: sites 0-22 (rounds 1-2, ramp) and 347-361 (rounds 13,
drain-adjacent). The steady window contributed nothing, as H-041's
99.3-99.8% packing predicted. The one paying forward flip (mainline site
22) exists only because BASE's ramp flow is less congested — after
parity_ring frees L2 flow copies, forward flips die entirely.

### Exhaustion evidence (this leg is now CLOSED at the current emission order)

- Greedy sweep to fixpoint + ~2,000-evaluation sideways plateau walk over
  the 388-site flow-race space: no descent below 1031.
- Aux-extended search (all 1,063 race sites incl. alu/valu splits): full
  sweep found zero improving single flips; walk stayed 1031.
- Fresh searches at neighboring l4_gmin points (7,30)/(9,30)/(8,29)/
  (8,31) with re-derived plans: none beats 1031 — the P-3 gmin slide did
  NOT fire on this relief (the freed slots are in ramp/drain, not in the
  steady window where L4 serving lives).
- Independent-basin convergence: a randomized plateau walk from the
  EMPTY plan (different RNG seed) wandered through 100+-entry random
  plans and landed at exactly 1031; a second seeded walk never left
  1031. Multiple distinct plans achieve 1031 (e.g. the 1-flip ((354,1),)
  and a 102-entry random plan), none reach 1030 — 1031 is the plan-space
  optimum for this config, not a greedy artifact.

### Ring conversion under re-searched plans (F-8)

Each remaining audited-safe ring added to the 4-ring frontier plan, flow
plan re-searched per config (site indices shift across ring configs, so
each point gets its own ~2-min search):

| added ring | composed (greedy, H-048) | + re-searched plan |
|---|---|---|
| (0,7)  | +1..+2 | 1031 tie (plan claws the ring cost back) |
| (0,13) | +1..+2 | 1031 tie |
| (0,14) | +1..+2 | 1031 tie |
| (1,0)  | ~0     | 1031 tie |
| (1,8)  | ~0     | 1031 tie (base plan alone suffices) |
| (1,9)  | ~0     | 1031 tie |
| (1,21)-(1,29) e1 leftovers | ~0 each (H-048) | not individually re-run; class-identical to (1,8)/(1,9) |
| ALL 16 rings (384 words = FULL retention) | +5 (H-048, no plan); 1034 greedy | **1031 tie** (2 rev flips) |

**Zero of the 12 spare rings turned net-profitable, but the plan makes
retention FREE.** The searched plan NEUTRALIZES the borrow-hazard cost
everywhere: singles tie 1031, and even the FULL 16-ring plan — 384
borrowed words, the F-2 full-retention threshold, +5 without a plan —
ties 1031 with 2 re-searched flips (rev sites 1, 352; ramp + drain).
F-2 should be restated once more: full cond retention is now
COST-NEUTRAL and flag-reachable, deleting ~48 ops (16 rings x ~3) with
zero cycle change; the retention relief itself no longer converts
below 1031 (its freed slots sit in the saturated steady window). The
remaining conversion blocker is emission ORDER, not spelling choice and
not scratch supply. (6 of the 12 spares individually re-measured; the
6 unmeasured are e1-leftover class, identical to the measured e1
neutrals, and all 12 are included in the full-16 tie.)

### Verdict vs the ~60-cycle modeled flow prize

Realized: 1 cycle on the frontier (5 on the unringed config). The
per-site selection dimension of the joint search is now measured-
exhausted; the residual flow prize is NOT reachable by choosing
spellings at fixed emission order, because the anti-correlation is
structural: the round cadence that creates flow bubbles (gather-heavy
phases) is the same cadence that starves select readiness. Moving the
~150-select mass onto flow requires changing WHEN selects become ready,
i.e. reordering EMISSION (beam over the interleave/round_robin order,
H-033-style collect-then-schedule) or the H-047 restructure — not
per-site selection. That is the honest next scope for the remaining
~12-cycle ramp+drain cap (H-041) and the LP's flow leg.

### Follow-ups (driver)

- F-9 [strain frontier]: 1032 config + flow_spelling_plan=((354,1),) =
  1031 (-1). Port note: plans are config-specific measurement artifacts
  (same class as parity_ring_plan); re-derive via scratchpad
  h042_search.py (~3 min) after ANY emission-order/flag change. The
  mainline flag-free form should re-search on its exact config.
- F-10: plan re-search is cheap (0.1 s/build); standing sweeps can carry
  a short plan search per point (budget ~60 s) the way they carry gmin.
- F-11: the beam/emission-order leg (true H-042/N-3 remainder) is
  unstarted: move set = round_robin interleave order + generator
  boundaries in the ramp/drain windows only; per-site selection should
  ride ON TOP of it (compose the plan search after each reorder).

## F-9 (2026-07-27): H-042 win ported to flag-free mainline — perf_takehome.py 1032 -> 1031

Ported `flow_spelling_plan=((354,1),)` to perf_takehome.py. Site 354
identified semantically (stack-instrumented dev build, frontier config):
the FIRST of the two level-2 first-fold `dual_fold` races of
(round 13, group 29), unringed L==2 branch. Perf's race-site stream
re-numbered with dev's keying rule: zero drift — perf's flow-site 354
is the same semantic site, and forcing it to encoding 1 (valu madd)
reproduced 1031 before any edit. Landed flag-free house-style: at the
unringed L==2 branch, `(multiply_add if (round, g) == (13, 29) else
first_fold)` on the first fold — `multiply_add` is placement-identical
to dual_fold's valu encoding (same op/reads/writes via scheduler.emit).
Gates (each run twice): test_kernel_cycles CYCLES 1031; submission
tests Ran 9 OK, all CYCLES 1031. Port note stands: the pin is a
config-specific measurement artifact — re-derive (tools/
spelling_plan_search.py) after any emission-order change to perf.

## H-051 (2026-07-27): bounded-backtrack scheduler with LB pruning — MEASURED FIRST, THEN SEARCHED: the packing/placement axis is EXHAUSTED at 1031. Greedy is (empirically) optimal for its own op stream; the 18-cycle friction band is dependency structure, not packing loss.

Tool: `tools/backtrack_sched.py` (new; dev.py untouched — no flag needed
because the answer is a proven negative, and H-049 is concurrently editing
dev.py's emission-order machinery). Config under study: the 1031 mainline
equivalent (`parity_ring=True, l4_gmin=(8,30), parity_ring_plan=(4 rings),
flow_spelling_plan=((354,1),)`).

### Method: exact offline constraint model of the online scheduler

`capture` monkeypatches dev.ListScheduler with a subclass recording, per
placed op, the full hazard context (engine, slot, reads, writes, mem
flags, H-031 ignore flags, min_cycle, tag) — 20,562 ops. Processing them
in emission order with the scheduler's own running-maxima rules yields an
explicit precedence DAG (RAW/WAW lag 1, WAR lag 0, coarse-mem edges
honoring store_pair + ignore flags; the final pause's
min_cycle=last_store_cycle is greedy-DERIVED and remodeled as lag-0
edges from all stores). Soundness: offline greedy over the DAG
reproduces ALL 20,562 captured placements bit-exactly (1031). Any DAG- +
slot-limit-feasible placement is a correct program; `verify` rebuilds
bundles from placements and runs the frozen grader — identity placement:
1031, correct:true on seeds 1/2/3/7/42/99.

### Regret profile (the deliverable): where the 18 cycles are lost

Bounds for THIS op stream (fixed spellings/addresses/emission order):
valu slot count 6077 -> floor 1013; dependency-only CP 426 (pure RAW —
425 lag-1 edges: 130 pool/anon + 285 val/nv/st hash-chain, i.e. the
439-span figure re-derived on the concrete stream); load 946, alu 981,
flow 786. Two-sided energetic interval bound (release est_i x deadline
C-1-h_i, per engine): **1015** = provable floor for ANY packing of this
stream. Actual 1031 -> open window <= 16.

F(c) = (c+1) + max(remaining-slot floors, conditional-CP of the
remaining DAG given the prefix fixed). regret(c) = F(c) - 1013; the 18
unit jumps localize every lost cycle:

| region | cycles lost | jump cycles | binder |
|---|---|---|---|
| setup ramp | 4 | 0, 1, 2, 5 | vbroadcasts RAW on load:const/vload (load 2/2 solid) |
| L9/L10 seam | 1 | 538 (r3/r9-10) | hash-chain RAW (val) |
| L7/L8 seam | 1 | 831 (r7-8/r12) | hash-chain RAW (val) |
| r9-11 epoch seam | 5 | 913, 915, 921, 926, 932 | **mid-schedule cluster (new): groups 24-31 r9/r10 hash+fold chains staircase; RAW on val/nv/pool, valu 2/6 with alu 8-12/12 busy** |
| drain | 7 | 1001, 1002, 1007, 1012, 1014, 1020, 1022 | r14-15 chain latency; cpLB overtakes engine LB from c=1001 |

(profile cross-checked against tools/sched_profile.py at the same
config: 109 empty valu slots over 47 gap cycles, hazard attribution
96.6/109 RAW — the frontier is genuinely not ready, not slot-starved.)

### Search coverage: all zero improvement

Incumbent 1031 throughout; every trial = full DAG re-schedule (19 ms).
- Priority list scheduling (parallel SGS, offline, knows the future):
  tail-height 1062, est+tail (CP) 1195, reverse-emission 1045. Emission
  order is a strong spine; global reorderings are sharply negative.
- Discrepancy-1 (delay one op d cycles, greedy completes): windows
  (+-8 around every jump, all engines) x d in {1,2}: 3,798 trials; same
  windows x d in {3,5,8}: 5,697 trials; **entire stream** (all 20,562
  ops) x d in {1,2}: 41,124 trials. Best 1031.
- Discrepancy-2 (delay two ops jointly, radius 3 of each jump,
  valu/load/flow, d in {1,2}^2): 84,540 trials. Best 1031.
- Discrepancy-3 (random triples, radius 4 of jumps, valu/load/flow/alu,
  d random in {1,2}): 34,928 trials. Best 1031.
Total ~170k full re-schedules, zero improvements. The searches directly
test the H-051 mechanism (backtrack = un-place an op that greedy placed
earliest and try later slots; a delayed-op floor + greedy completion IS
a bounded-backtrack leaf, and disc-1 over the entire stream is the
complete first backtrack level); with 96.6/109 of gap weight RAW-bound,
delaying competitors cannot fill gaps, and no 1-3 deviation compresses
the seams.

### Verdict + hand-offs

- Bounded-backtrack/B&B over packing choices at the current op stream:
  **no prize** (0/170k deviations improve; provable floor 1015 means the
  axis's theoretical max is 16, and the RAW-bound gap structure says the
  practical max is ~0). Composes with H-042 (per-site spelling exhausted
  at 1031) and iter-4 (order/tie-break exhausted): the scheduler strain's
  three axes are all measured-closed at this op mix.
- The 5-cycle r9-11 epoch-seam cluster (c=913-932) is the one NEW
  actionable target: it is the same chain-staircase mechanism as the
  drain but mid-stream, where rounds 9-10 (L9/L10 gather rounds, long
  post-parity chains) overlap the epoch-2 tournament rounds. Emission-
  structure levers (H-049's axis) or chain-shortening algebra (b3-last
  style) are the right tools; packing is not.
- Reusable machinery in tools/backtrack_sched.py: exact capture of the
  op stream + validated offline re-scheduler + frozen-grader verify of
  arbitrary placements (`verify`), energetic interval bound (`bound`),
  per-cycle regret profiler (`regret`). Any future emission-order or
  spelling change can re-run the whole analysis in ~2 min to re-measure
  its own residual packing slack.

## H-049 (2026-07-27): emission-order search (H-042's F-11 successor) —
## STRAIN FRONTIER 1031 -> 1023 (-8), order space mapped, structured
## families all closed, windowed local search is the payer

Charter: H-042 proved per-site spelling under the FIXED emission order is
exhausted at 1031 and the residual modeled flow prize is emission-order-
shaped. Attack the order itself: the interleave of group-round emissions
presented to the greedy scheduler.

### Mechanism landed (dev.py, kwarg `emission_plan`, default () = bit-identical)

`build_kernel_scheduled` gained `emission_plan`: when non-empty it
REPLACES the diagonal step loop with an explicit sequence of entries,
each `(r, g)` (emit that group-round contiguously) or
`("rr", ((r1,g1),(r2,g2),...))` (round-robin those group-rounds' stage
generators at the H-021 pool-dead yield points). Validated to cover every
(round, group) exactly once with per-group rounds ascending — any such
order is DATAFLOW-correct by construction (the scheduler re-derives all
hazards from the stream), but parity_ring borrow windows are
liveness-TIMED, so every candidate is simulation-verified
(run_variant.measure, ~0.17 s/eval: build + frozen grader + correctness).
Default off verified programmatically bit-identical vs HEAD on both the
mainline (1038 dev BASE) and the 1031 frontier config; an explicit
default-order plan also reproduces the default stream bit-for-bit.
Driver: tools/emission_order_search.py (phase1 structured families +
windowed local search, multiprocessing, JSONL checkpoints + per-best
plan dumps). All searches on the frontier config MINUS
flow_spelling_plan (site numbering is order-specific), greedy = 1032.

### Order-space map: every structured family closed at or above 1032

phase1 (57 evals, one axis at a time + pairwise composition of ties):
| family | best | note |
|---|---|---|
| baseline (4,3)-skew default order | 1032 | |
| wave_order rev / rot:1 / rot:2 | 1070-1075 | 2 of 3 INCORRECT (ring windows) |
| group_order rev / rot:1..4 | 1043-1060 | correct, all worse |
| zip (group-granular cross-wave interleave) | 1043-1053 | INCORRECT both forms |
| stage_rr tail 1/2/3 (stage round-robin drain) | 1032/1036/1037 | tie at 1 step |
| stage_rr ramp 1/2/3 | 1033-1037 | |
| stage_rr all steps (per-step / per-wave) | 1159 / 1058 | G-5 re-confirmed |
| tail_df 1/2/3/4/5 (depth-first drain) | 1032/1032/1067/1063/1108 | |
| lag perturbations (11 shapes) | 1038 best | most worse or incorrect |
| 8 blocks stagger 1/2 | 1100 (incorrect) / 1040 | |
| 13 uneven blocks stagger 2 (external-repo shape) | 1096 | correct, -56 worse |
| 2 blocks | incorrect | |
| pairwise compositions of ties | >= 1032 | |

The (4,3) diagonal is locally optimal at every structured granularity;
aggressive reorders (wave rev, zip, 2-block) BREAK ring-borrow
correctness — the sim check is load-bearing, not paranoia.

### The payer: windowed single-entry local search (+ sideways plateau walk)

Move set: pop one entry, reinsert +-{1,2,4,8} positions (validity-checked),
windows by position (ramp = first 120 entries, drain = last 120, all) or
by round (`r:LO-HI`); accept strictly-better, walk sideways at p=0.7.
| round | window | budget | evals | result |
|---|---|---|---|---|
| 1 | ramp+drain | 1500 s | 60.5k | 1032 -> 1026 (6 paying moves: 3 drain-side r12-14 block-3 reorders, 3 ramp moves) |
| 2 | all | 1500 s | ~58k | 1026 -> 1024 (2 moves, both ramp region) |
| 3 | ramp+drain | 1800 s | ~70k | 1024 -> 1023 (1 ramp move) |
| 4 | r:8-12 (H-051 epoch-seam intel) | 1200 s | 55k | ZERO improvement |
| rr micro | stage-granular merges (pairs/triples), ramp+drain | 467 cands | | ZERO winners |

The paying moves are small, discrete, and confined to H-041's soft
windows (ramp c0-100, drain/steady seam r12-15); the walk between
descents accumulates hundreds of sideways displacements (434/512 entries
differ positionally from default) but the cycle-relevant content is the
~9 descents. Round 4 is the important negative: the r9-11 epoch seam
(H-051's 5-cycle regret cluster, c=913-932) did NOT yield to 55k
whole-entry order moves targeted exactly at rounds 8-12 — that seam's
staircase is chain-bound at this order granularity, same class as the
drain CP.

### Composition results (the surprise: order absorbs the spelling prize)

- flow_spelling_plan re-search (greedy sweep, flow + aux moves — aux =
  forcing _sched_vec valu/alu splits, i.e. the offline form of the
  external repo's SCHED_FLEX_ALU deferred binding) on the 1026, 1024 AND
  1023 orders: fixpoint at ZERO flips, plan (). H-042's 1-flip win is
  subsumed; per-site selection (including dynamic valu->alu class) has
  no residual on searched orders. Conversely the old ((354,1),) pin is
  order-specific and was dropped.
- l4_gmin re-sweep (7..9 x 29..31) at 1026, 1024, 1023: (8,30) optimal
  every time, margins 3-9 cycles — the P-3 slide did NOT fire (relief
  lands in ramp/drain, not the steady L4-serving window).

### Frontier + verification

**New strain frontier: 1023** = parity_ring=True, l4_gmin=(8,30),
4-ring parity_ring_plan (unchanged), flow_spelling_plan=(),
emission_plan = tools/h049_best_plan.json (512-entry committed artifact).
Verified: seeds {unseeded,1,2,3,7,42,99} all 1023 correct;
debug_compares=True 1023 correct; flags-off full gate 9/9 green at 1031
(perf_takehome.py untouched). Occupancy (100-cyc windows) vs default
order: ramp load slots pulled forward (108 -> 118 in c0-99), mid-stream
alu packing up (~1144 -> 1192 in c800-899), drain 32 -> 24 rows past
c1000 — the 8 cycles come 3 from drain-side seams, ~5 from ramp/seam
compaction, ~0 from the steady window.

### Verdict vs the ~55-cyc modeled prize

Realized: 8 cycles (1031 -> 1023), roughly the full H-041/G-23
"ramp+drain measured-recoverable ~12" minus the order-resistant epoch
seam (5) and residual ramp CP (H-051 profile: ramp 4, seams 2, epoch
seam 5, drain 7 at 1031). The steady-state ~40-cycle remainder of the
modeled flow prize did not move under ANY order family — with H-042
(spelling exhausted) and H-051 (packing exhausted, LB 1015) this
triangulates: below ~1023 needs op-count/chain changes (algo strain),
not placement, selection, or order.

### Follow-ups (driver)

- F-12: mainline port decision — perf_takehome.py has no emission_plan
  machinery; porting means either the kwarg (flag-free constant plan
  baked as a module literal) or re-expressing the ~9 load-bearing moves
  as local reorder rules in the step loop. The committed artifact +
  emission_order_search.py reproduce 1023 on dev for whoever ports.
- F-13: restart-portfolio walks (new RNG seeds) still pay slowly
  (~1-2 cyc / 25 min round, not yet flat); cheap background continuation.
- F-14: re-run tools/backtrack_sched.py (H-051, on main) against the
  1023 build to re-localize the residual ~8 friction cycles before
  anyone re-opens an order/packing axis.
- Plans are config-specific measurement artifacts (same class as
  parity_ring_plan): re-derive via emission_order_search.py after ANY
  flag/algo change; spelling re-search after any order change (both
  cheap, ~25 min / ~7 min).

## F-12 (2026-07-27): H-049 emission order ported to mainline —
## perf_takehome.py 1031 -> 1023

Port shape: the 512-entry plan from tools/h049_best_plan.json baked as a
module-level literal `_EMISSION_ORDER` (all plain (r, g) entries, no rr
merges), consumed in build_kernel_scheduled behind the same graded-shape
guard as the parity rings (n_groups==32, rounds==16, skew==(4,3));
other shapes keep the diagonal step loop. Coverage + per-group round
monotonicity asserted at use, exactly like dev's emission_plan
validation. F-9's (13, 29) multiply_add spelling pin REVERTED to the
plain first_fold race — the searched order's spelling re-search
fixpoints at zero flips, so the old pin was a stale order-specific
forcing (comment left at the site).

Gates (each run twice): Tests.test_kernel_cycles CYCLES 1023 / 1023;
tests/submission_tests.py 9/9 green, all nine CYCLES lines 1023, both
runs. Literal programmatically verified equal to the committed JSON
artifact. dev.py and tests/ untouched. Mainline == dev frontier again;
F-14 (backtrack re-localization at 1023) can now run against main.

## H-054 (2026-07-27): select-readiness x flow-bubble anti-correlation —
## REJECTED, and the 33-cycle prize is proven NOT TO EXIST. Two independent
## relaxations (infinite-width flow engine; free-slot oracle on the select
## class) both say the entire select class is worth <= 2 cycles. The
## floor-990 board (F-17) is a single-engine-metric artifact.

Charter (F-17): break the anti-correlation on the floor-990 stream — the
loop's single largest identified prize (~33 cycles) with every other axis
measured-closed. Target board = H-047's mp56+gmin(7,30) mix at flow-heavy
spellings (any-packing floor 990/992, actual greedy 1104).

Region: dev.py scheduler (one new default-off kwarg family) +
tools/h054_*.py wrappers. emission_order_search.py / backtrack_sched.py /
free_slot_oracle.py / mem_prime code untouched.

### Mechanism landed (dev.py, `flow_race_bias`, default 0 = bit-identical)

The brief's direction 4 in its general form: an online spelling POLICY
instead of a per-site plan. `emit_any` accepts a pure-flow encoding whose
retire time is up to B cycles LATER than the race winner's — "wait up to B
cycles for the 1-wide flow engine rather than burn a valu slot". Companion
knobs `flow_race_bias_window=(lo,hi)` (restrict to a cycle band) and
`flow_race_bias_budget=K` (cap total biased placements; the literal
"flow gets one per cycle, valu takes the overflow" policy). B=0 is the
untouched code path; `sched_snap`/`sched_install` carry the counter.
Verified bit-identical vs bd27795 on BOTH the mainline (1038) and the
H-047 frontier (1022) by object comparison of the bundle lists
(tools/h054_identity.py); full gate flags-off 9/9 green, all nine CYCLES
lines 1022.

### Burst characterization (the deliverable), measured ON the target board

tools/h054_diag.py instruments `emit_any` to record, per race site,
`arrival = ready(reads,writes)` (when the select COULD take a flow slot)
and `placed = find_free('flow', arrival)`.

| | greedy 1022 stream | flowmax stream (395 sites forced) |
|---|---|---|
| cycles / max engine floor | 1022 / 1009 (valu) | 1104 / 992 (valu) |
| engine slots valu/flow/alu | 6052 / 796 / 11761 | 5949 / 955 / 10945 |
| flow-capable sites on flow | 236 / 395 | 395 / 395 |
| flow busy | 796/1022 = 77.9%, 226 bubbles | 955/1104 = 86.5%, 149 bubbles |
| selects ready per cycle | 1:187, 2:20, 3:3 (210 arrival cycles, 23 bursts) | 1:292, 2:43, 3:1, 4:1, 5:2 (339 arrival cycles, 47 bursts) |
| burst inter-arrival | median ~20, tail to 39+ | mode 3-7, median 5 |
| wait = placed-arrival | 0:145 1:36 2:17 3:6 ... max 42, mean 1.82 | 0:158 1:31 2:26 3:23 4:18 ... max 106, mean **10.38** |
| required 1-server FIFO queue depth (arrivals only) | peak backlog **3** | peak backlog **5** |
| bubble -> nearest arrival cycle | 55 at d=1, 80 at d>=10 | 30 at d=1, 33 at d>=10 |

The queue-depth answer is the first surprise: a 5-deep buffer in front of
flow would absorb every burst. The bursts are NOT the problem — the mean
wait of 10.4 comes from flow's *baseline* load (the ~560 non-race flow
ops), not from select clustering.

Joint slack oracle (tools/h054_slack.py) — H-042 measured the two sides
separately at the old order/mix (46/155 slack>0; 0/155 with a bubble
within retire-delta 3); re-measured jointly on THIS stream, per flow-lost
site: `wait` = retire(flow enc) - retire(chosen), `slack` = (first
consumer cycle - 1) - retire(chosen).

- 159 flow-lost sites. wait histogram 1:34 2:33 3:20 4:13 5:11 ... 40:1.
- slack histogram -1:24 0:37 1:37 2:12 3:10 ... 20+:9.
- **JOINT feasible (wait <= slack): 23 / 159**, in rounds {1,2,4,13,15}.
- Independent cross-check (tools/h054_windows.py): the window-local
  pairing bound min(bubbles, lost) per window is **23 at W=10** (exact
  agreement with the slack oracle) and 77 at W=50 — but W=50 pairing
  needs ~50 cycles of slack, which no site has.

Occupancy context (tools/h054_windows.py, 100-cycle windows): from c100
to c800 the frontier runs **valu 100%, alu 100% AND load 100%
simultaneously**. The steady state is jointly saturated on three engines,
which is why the single-engine valu floor is not causal.

### Every mechanism tried, and what it recovered

| mechanism | evals | best | note |
|---|---|---|---|
| `flow_race_bias` B = 1/2/3/4/6/8/12/16/24/40/100 | 11 | **1026** at B=1 | monotone; floor falls 1009->993, realized rises ~2.5-3 cycles per floor cycle |
| bias restricted to a cycle window (8 windows x 3 B) | 24 | 1022 (=) | in the bubble-rich windows c640-720 / c740-820 the policy finds **zero** candidates — the anti-correlation is exact, not statistical |
| bias x budget cap K (direction 4 literal) | 42 | 1024 | "one per cycle, valu takes overflow" is what greedy already does |
| batch-force the 23 jointly-feasible sites (direction 2) | 12 | 1024 | census barely moves: valu 6052->6050, flow 796->797 |
| force by round window (r1/r2/r4/r13/r15 feasible subsets) | 5 | 1022 (=) | |
| **cadence de-synchronization (direction 3)**: 19 emission-order families (lags (0,2,4,6)..(0,8,16,24), 8/16/32 blocks x stagger 1-4, zip, group_rev, stage_rr per-step and per-wave) x 6 biases, correctness-checked | 114 | **1022** (the incumbent) | bias is monotone-negative on EVERY family; no desync family within +4 at any bias |
| emission-order local re-search ON the migrated stream (tools/h054_local.py, seeded from the 1022 plan) | 12.0k @ B=2; 11k @ B=4 | 1023 (from 1027); 1025 (from 1031) | "order absorbs spelling" still holds — it recovers 4-6 — but never back to 1022 |

Self-equilibration confirmed at site granularity (H-053 point 4): forcing
20 slack-feasible sites onto flow moved the census by valu -2 and flow
+1, because the forcing displaces ~19 sites greedy would otherwise have
put on flow, and the `_sched_vec` alu/valu split races re-balance behind
it (alu 11761 -> 11481 at B=2). Any per-site migration is silently undone.

### The closure: two independent relaxations, both zero

**(A) Infinite-width flow engine** (tools/h054_width.py; mutates
`problem.SLOT_LIMITS['flow']`, illegal programs, cycles only). Widening
flow is a strict relaxation that dominates every legal flow-side
mechanism — spelling plan, emission order, placement policy, burst
buffering, any of them:

| flow width | 1 | 2 | 4 | 8 |
|---|---|---|---|---|
| greedy cycles | **1022** | 1023 | 1023 | 1023 |
| valu slots (single-engine floor) | 6052 (1009) | 5948 (992) | 5906 (985) | 5903 (984) |

With flow bandwidth FREE, greedy migrates 149 valu slots away by itself
and the schedule does not move. Re-running all 19 emission-order families
under flow width 8: best 1023. There is no flow-side schedule at 990.

**(B) Free-slot oracle on the select class** (tools/h054_oracle.py —
G-26's method, new classes for the ops H-054 is about; routes them to the
64-wide `debug` engine, dependency edges and 1-cycle latency preserved):

| class freed | ops | on the 1022 stream | on the flowmax (1104) stream |
|---|---|---|---|
| `sel` (all 395 flow-capable race sites) | 395 | 1026 (**+4**) | 1026 (-78) |
| `sel_lost` (the 159 migration targets) | 159 | 1026 (**+4**) | 1025 (-79) |
| `vselect` (every vselect however spelled) | 1560 | 1021 (**-1**) | 1021 (-83) |
| `race` (all 1033 multi-encoding sites) | 1033 | 1020 (**-2**) | 1020 (-84) |

**The entire select class is worth <= 2 cycles.** Freeing the selects on
the flowmax stream removes exactly the flowmax penalty and lands back at
the baseline, never below it. The anti-correlation is not slot-shaped:
there is nothing on the other side of it.

### Derived intel: per-engine shadow prices (tools/h054_shadow.py)

Counterfactual engine widenings at the 1022 frontier (illegal, cycles
only). This is the map the loop should steer by now that G-26 has retired
`ceil(slots/width)`:

| relaxation | cycles | delta |
|---|---|---|
| baseline | 1022 | — |
| flow 1 -> 2 / 4 / 8 | 1023 / 1023 / 1023 | **0** |
| store 2 -> 4 | 1022 | 0 |
| alu 12 -> 14 / 16 / 24 | 1022 / 1020 / 1015 | -0 / -2 / -7 |
| valu 6 -> 7 / 8 / 12 | 1021 / 1016 / 1014 | -1 / -6 / -8 |
| load 2 -> 3 / 4 | 1015 / 1016 | **-7** / -6 |
| valu 8 + alu 16 | 1008 | -14 |
| alu 16 + load 4 | 974 | -48 |
| **valu 8 + load 4** | **841** | **-181** |
| valu 8 + alu 16 + load 4 | 800 | -222 |
| all widths x2 | 612 | -410 |

Free-slot oracle by class at the same config (G-26's tool, frontier
overrides): gather -5, madd -6, vec -18, all-compute -34 (988), bcast +1.

Two things fall out. (i) Every single-resource relief is worth 5-8
cycles and no more — the kernel sits in a near-balanced multi-resource
regime (corsix's ratio, third sighting). (ii) valu and load relief are
wildly SUPERADDITIVE (-6 and -6 alone, -181 together): there is a chain
that alternates vector compute and gathers, and relieving either engine
alone just moves the stall to the other. That is the largest unexplained
signal on the board.

### Verdict

**0 of the 33 cycles materialized, and the 33 was never there.** The
floor-990 stream is reachable, its any-packing floor is real, and it is
irrelevant: the single-engine `ceil(valu_slots/6)` metric that produced
990 does not bound this schedule, and two independent relaxations that
strictly dominate every possible flow-side mechanism both return 0. F-17
retargeted the loop onto a board that does not exist; this closes it.

The correct restatement of G-4/G-12/H-042/H-045 is stronger than
"selects cannot reach the flow bubbles": **reaching them is worth
nothing.** The flow engine's shadow price is exactly zero at every width.

### Follow-ups (driver)

- F-19: retire "flow bubbles" / "select-readiness anti-correlation" /
  "the ~40-60 cycle modeled flow prize" as open levers, in the same
  motion G-26 retired engine-floor scoring. Four hypotheses (G-4, G-12,
  H-042, H-054) and one LP have now spent budget on this; the answer is
  0 and it is now proven by relaxation, not by exhaustion.
- F-20 [the successor]: the valu+load superadditivity (-6, -6, -181) is
  the biggest live signal. Probe: which dependency chains alternate
  `_sched_vec`/`_sched_madd` output with `load` gather addresses, and
  does any algebraic restructure (address precompute, gather batching,
  deeper mem priming) break the alternation? This is an algo-strain
  question with a scheduler-strain measurement (h054_shadow.py gives the
  ceiling for any candidate in one 20 s run).
- F-21: `flow_race_bias` stays in dev.py as a default-off,
  measured-negative lever (same status as `flow_spelling_plan`). It is
  the cheapest re-test of this axis after any mix change: one 11-point
  sweep, ~5 s, via tools/h054_curve.py.
- F-22: cadence de-synchronization is now closed THREE independent ways
  — at greedy spellings (H-049 phase1), at flow-heavy spellings (this
  section, 114 evals), and under a free flow engine (19 families, best
  1023). Finer-than-(round,group) emission granularity was deliberately
  NOT built: with the select class worth <= 2 cycles there is nothing
  for it to win.
- F-23: tools/h054_shadow.py (per-engine and joint shadow prices) and
  tools/h054_oracle.py (select-class free-slot oracle) join
  free_slot_oracle.py as standing pre-screens. Any hypothesis that
  claims cycles by moving work OFF an engine should show that engine's
  shadow price first; it costs one run.

## F-13 (2026-07-27): H-049 restart-portfolio continuation —
## 1023 -> 1020 on the H-049 mix AND 1022 -> 1020 on the H-047 mix;
## the jump-radius knob, not the restart seed, is what re-opened descent

Charter: continue H-049's emission-order local search from the 1023
frontier (the walks were still descending ~1-2 cycles/round when H-049's
budget ran out), with a restart portfolio over seeds and window
emphases, re-targeted on F-14's fresh regret sites (ramp 4, epoch seam
5 at c=881-927, drain 4; provable stream floor 1011).

### Driver additions (tools/emission_order_search.py, all default-off)

- `--window p:LO-HI`: local search restricted to a PLAN-INDEX range.
  F-14 localizes regret in CYCLES, so the sites were first mapped
  index<->cycle by capturing the 1023 build with backtrack_sched and
  taking each entry's median op cycle: seam c=881-927 -> entries
  432-471, wide seam c=850-940 -> 404-483, drain c>=960 -> 479-511.
- `EOS_JUMPS`: the reinsertion offset set (default `1,2,4,8`, H-049's).
- `EOS_OVERRIDES`: JSON merged onto FRONTIER_OVERRIDES so a walk can be
  pointed at a different serving mix without editing the driver (needed
  the moment H-047 changed the mix mid-run).
Defaults unchanged: greedy with no emission_plan on the H-049 mix still
measures 1032, as in H-049.

### Restart portfolio (6 walks x 2700 s, ~213k sim-verified evals)

| rd | walk | mix | seed | window | jumps | result |
|---|---|---|---|---|---|---|
| 1 | A | H-049 | 1111 | p:404-483 (F-14 seam) | 1,2,4,8 | 1023, ZERO (31.4k) |
| 1 | B | H-049 | 2222 | ramp+drain | 1,2,4,8 | 1023, ZERO (30.8k) |
| 2 | C | H-049 | 3333 | all | +16,32 | **1020** (-3; 38.0k) |
| 2 | D | H-049 | 4444 | p:432-511 | 1,2,4,8 | 1021 (-2; 38.4k) |
| 3 | E | H-047 | 5555 | all | +16,32 | **1020** (-2; 42.3k) |
| 3 | F | H-049 (from 1020) | 6666 | all | +16,32 | 1020, ZERO (31.9k) |

The discriminating variable is the JUMP RADIUS, not the restart seed:
round 1 re-ran H-049's exact move set (max +-8) under two fresh seeds
and two window emphases and found nothing in 62k evals, while both
walks that added +-16/+-32 descended. H-049's plateau is escapable only
by displacements longer than its own move set — the 1023 point was a
+-8-local optimum, not an order-space optimum. Windowing at the F-14
regret sites (A, D) was WORSE than the unrestricted window (C, E): the
paying moves reshape chains that cross the site boundaries, so
position-restricted walks cannot express them.

### Frontier(s)

- **H-047 mix (live board): 1020** (-2 vs 1022) — parity_ring=True,
  l4_gmin=(7,30), 4-ring parity_ring_plan, c5_primed_gather_levels=(5,6),
  mem_prime_region_hazards=True, mem_prime_dead_reg_staging=True,
  flow_spelling_plan=(), emission_plan = tools/f13_best_plan_1020.json.
- **H-049 mix: 1020** (-3 vs 1023) — same but l4_gmin=(8,30), no
  mem_prime/c5(5,6); emission_plan = tools/f13_best_plan_1020_h049mix.json.
Both verified: seeds {unseeded,1,2,3,7,42,99} 1020 correct, plus
debug_compares=True 1020 correct. l4_gmin re-sweep (7..9 x 29..31) at
each: the mix's own gmin stays optimal (H-047 mix (7,30), margin 3-12;
H-049 mix (8,30) tied with (7,30), margin 4-8) — no P-3 slide, as in
H-049. Spelling re-search SKIPPED by driver instruction: H-047 already
fixpointed at zero wins over 1,157 flips on its 1022 order (third
independent confirmation that order absorbs the spelling prize).

### Orders are mix-specific (cross-application measured)

| order | on H-049 mix | on H-047 mix |
|---|---|---|
| F-13 1020 (H-049-mix walk C) | 1020 | 1022 |
| H-047 1022 | 1027 | 1022 |

The two -2/-3 wins are NOT the same reordering rediscovered; neither
order transfers. Any mix change invalidates the order artifact (and
vice versa) — the plan-search toolchain must be re-run per candidate
mix, exactly as H-047's re-scope assumed.

### New regret decomposition (backtrack_sched capture+regret, both at 1020)

H-047 mix (ops 20473, offline model reproduces the greedy placement
exactly): LB 1006 (valu-engine bound; staircase 1007), CP 541, final
regret 14 = ramp 4 (c=0,1,3,7) + mid/seam 6 (c=744, 813, 848, 911, 913,
922 — rounds 5-15, the r9-11 epoch cluster persists and has SPREAD
earlier) + drain 4 (c=993, 994, 999, 1011, cpLB>=engLB throughout).
H-049 mix (ops 20554): LB 1007, CP 554, regret 13 = ramp 4 + mid/seam 5
(c=311, 792, 880, 911, 923) + drain 4 (identical drain signature).
Reading: the -2/-3 came out of the MID/SEAM band (F-14's 5-cycle
c=881-927 cluster is now spread over c=744-922 at lower total cost);
ramp 4 and drain 4 are byte-for-byte the same sites as F-14 and did not
move under 213k order evals across three rounds. The H-047 mix buys a
cheaper op stream (LB 1006 vs 1007) but currently spends one more cycle
of regret, so both mixes land on 1020.

### Stop rule and follow-ups

Stopped per the diminishing-returns rule: round 3's continuation walk F
re-ran the winning move set (jumps to +-32, unrestricted window, fresh
seed) from the 1020 point for 31.9k evals with ZERO descent, and the
H-047-mix walk E's own descent had flattened by t~1300 s of 2700 s.
- F-18 (cheap, queued): one more radius escalation (EOS_JUMPS with
  +-64/+-128, or a 2-entry compound move) from either 1020 — the round-1
  vs round-2 contrast says radius is the live axis and the current stop
  is only evidence about radius <= 32.
- Mainline port: tools/f13_best_plan_1020.json is a drop-in replacement
  for the `_EMISSION_ORDER` literal that F-15 baked from
  h047_best_plan_1022.json (same 512 plain (r,g) entries, same shape
  guard) — -2 on the live board with no other change.
- Unchanged conclusion from H-049/F-14: ramp 4 + drain 4 are
  chain-bound and order-resistant; H-052's chain shortening remains the
  only lever aimed at them.

## F-18 (2026-07-27): radius escalation past F-13 — NEGATIVE, and the
## single-entry radius axis is now CLOSED BY EXHAUSTION, not by sampling

Charter: F-13 showed the productive axis was the jump RADIUS, not the
restart seed (+-8 walks found zero over 62k evals; +-16/+-32 walks
descended 1023 -> 1020 and 1022 -> 1020), and queued the untested
escalation: +-64, +-128, and 2-entry COMPOUND moves. This is that
escalation, run from the live-board 1020 (tools/f13_best_plan_1020.json
on the H-047 mix, re-verified here at 1020 correct).

### Result: no improvement. Frontier unchanged at 1020.

~130k sim-verified evals, zero below 1020 in every tier.

### New tooling (region tools/f18_*, emission_order_search.py untouched)

- `tools/f18_radius_walk.py` — imports `_eval`/`FRONTIER_OVERRIDES` from
  emission_order_search read-only, adds move kinds beyond its single
  fixed-offset move: `jump` (F-13's, radius from --jumps), `free`
  (re-insert an entry UNIFORMLY inside its maximal feasible interval =
  unbounded radius, and always feasible so it does not burn evals on
  invalid candidates), `comp2` (two independent single moves in one
  candidate), `pairg` (two CONSECUTIVE same-group entries displaced
  together), `block` (contiguous run of 2-4 entries as a unit).
  Also checkpoints the CURRENT plan (`.cur.json`), not just the best, so
  chained rounds continue the sideways drift instead of restarting.
- `tools/f18_exhaust1.py` — enumerates and measures EVERY valid
  single-entry reinsertion of a plan (26,415 of them for the 1020 plan),
  chunked by --start/--stop.

### Why `pairg` is the move that actually raises the radius

A single entry cannot travel past its own group's next round-entry, so
long fixed jumps are mostly rejected: at radius 128 the walk rejected
6,972 of 17,372 proposals, and the >128 displacements that survive are
uniformly harmful (see the histogram below). The barrier is the group's
own successor, so the compound move that lifts the cap is moving two
consecutive same-group entries together — hence `pairg`.

### Sampled portfolio (6 walks, 63.8k evals, all from the 1020 point)

| rd | walk | moves | radius | evals | result |
|---|---|---|---|---|---|
| 1 | A | jump | <=64 | 10,400 | 1020, ZERO |
| 1 | B | jump | <=128 | 10,400 | 1020, ZERO |
| 2 | C | free | unbounded | 10,784 | 1020, ZERO |
| 2 | D | pairg/comp2/block | <=128 | 10,784 | 1020, ZERO |
| 3 | C2 | free+jump (chained from C drift) | <=64 | 10,752 | 1020, ZERO |
| 3 | D2 | pairg/comp2/block (chained from D drift) | <=128 | 10,688 | 1020, ZERO |

Compound-move evals specifically: pairg 9,533 + comp2 8,126 + block
3,813 = 21,472. The drift is real, not a stuck walk: C2/D2 ended
286/276 of 512 positions away from the F-13 seed and still measured
exactly 1020.

### Positive control (the zeros are not a broken driver)

Seeded with the H-047 1022 order on the H-047 mix, the same walker
descended 1022 -> 1021 -> 1020 in 12.5k evals / 300 s, reproducing
F-13's walk E. So the machinery finds order wins when they exist —
and it lands on the SAME 1020, from a different start.

### Exhaustive proof (52.9k evals) — this is the part that closes it

`f18_exhaust1` measured ALL 26,415 valid single-entry displacements of
the 1020 plan (every entry to every position in its feasible interval,
i.e. radius unbounded by construction). Zero below 1020. The 1020 plan
is therefore a STRICT 1-move local optimum at ANY radius — not a
+-8-local optimum as 1023 turned out to be. Repeating the full scan at
a far-drifted plateau point (D2's checkpoint, 276/512 positions moved,
26,449 moves) also returned zero.

Neighborhood histogram of the 26,415 scanned moves:

| cycles | count |
|---|---|
| incorrect (ring-borrow window broken) | 2,026 |
| 1020 (neutral) | 13,464 |
| 1021 | 1,093 |
| 1022 | 618 |
| 1023 | 5,777 |
| >=1024 | 3,437 (worst 1047) |

Two readings worth keeping:
- **The plateau is enormous**: 55% of all correct single-move neighbors
  measure exactly 1020. Order search here is mostly neutral drift, which
  is why sampled walks look "still alive" long after they are done.
- **Radius has a ceiling, and we are past it**: fraction of neutral-or-
  better neighbors by displacement — <=8: 4,293/7,583 (57%); 9-32:
  7,107/13,101 (54%); 33-128: 2,064/3,667 (56%); >128: 0/38 (0%).
  Displacements longer than 128 are uniformly harmful. F-13's radius
  effect was real but saturates: it bought the step from +-8 to +-32 and
  there is nothing further out to buy.

### Verdict

The single-entry radius axis is EXHAUSTED — closed by enumeration, not
by a budget running out. Compound moves are only closed by sampling
(21.5k evals, zero); the 2-move space is ~7e8 and cannot be enumerated,
but with the 1-move neighborhood provably flat-or-worse in every
direction, a 2-move win would have to be a strictly-paired escape, and
9.5k pairg proposals did not find one. Recommendation: retire the
emission-order local search on this mix. Consistent with F-13/H-049/
F-14, the residual regret 14 (ramp 4 + mid/seam 6 + drain 4) is not
order-shaped; only a mix change (which invalidates the order artifact
per F-13's cross-application table) or chain shortening (H-052/H-055)
can move it.
No artifact written: tools/f18_best_plan_*.json would have been a
duplicate of f13_best_plan_1020.json. No verification sweep, l4_gmin
re-sweep or regret re-profile was run — all three were conditioned on an
improvement that did not occur; the F-13 numbers stand.

## F-39 (2026-07-28): PACKING AXIS RE-TESTED AT THE 1006 STREAM — G-25's
## closure HOLDS. 386,090 full re-schedules, zero below 1006; open window
## vs the any-packing floor is 10, and every one of the 11 regret cycles
## is chain-shaped, not packing-shaped.

Charter: G-25 (H-051) closed packing/placement, but it measured the
**1031** stream. Since then the stream changed completely (F-24's
non-uniform lag diagonal, a re-mined 20-ring parity plan, l4_gmin (6,31),
a fully re-walked emission order). This loop has been burned three times
by stale closures flipping sign under a regime change (G-22 -> H-047,
"convergence" -> H-056, F-24's phantom prize), and packing was the one
axis never re-measured. Re-run, not re-derived.

### Method (shared tools called, not modified)

`tools/f39_pack.py` + `tools/f39_par.py` (new; nothing under tools/ was
edited). f39_pack imports `backtrack_sched` and patches its module
globals in-process: `H51_OVERRIDES` <- the 1006 mix loaded straight from
`tools/h057_best_plan_1006.json` (`params.mix` = parity_ring,
l4_gmin (6,31), the 20-ring parity_ring_plan, c5_primed_gather_levels
(5,6), mem_prime_region_hazards, mem_prime_dead_reg_staging,
flow_spelling_plan ()) plus `emission_plan` = the 512-entry `plan`;
`CAPTURE_PATH` <- a separate f39 pickle so the H-051 capture is not
clobbered. f39_par forks 8 workers over the same captured DAG; every
trial is a full offline greedy re-schedule with forced min_cycle floors
(the H-051 deviation model), ~11 ms serial / ~430 trials/s at 8-way.

Config sanity: `run_variant.measure(OVERRIDES)` -> **1006, correct=true**.

### Model soundness on the NEW stream: still bit-exact

- `capture`: **20,462 ops** (was 20,562 at 1031), span 1006, n_cycles
  1006, pair_writes=True.
- `validate`: offline greedy in emission order reproduces **all 20,462
  captured placements exactly** — `exact_match: true, n_mismatch: 0`,
  offline_cycles 1006 == captured_cycles 1006. The constraint model did
  NOT drift with the organization/order change; no mismatch finding.
- `verify` (frozen-grader reconstruction of the identity placement):
  feasible=True, 1006 / correct=true on seeds 1, 2, 3, 7, 42, 99. The
  whole capture -> DAG -> re-place -> rebuild-bundles -> grade path is
  live at this config, so any future win found here is landable-checkable.

### Bounds at 1006 (independently recomputed, matches F-37's stack)

| bound | value |
|---|---|
| realized | 1006 |
| engine LB (valu 995, alu 981, load 946, flow 797, store 23) | **995** |
| dependency CP | 512 |
| staircase [release(est)] | 996 (valu, t=4, 5947 ops beyond) |
| staircase [tail(h)] | 995 (valu, t=1, 5959 ops beyond) |
| **energetic interval LB (ANY packing of this stream)** | **996** |
| fungible (H-044 alu/valu re-assignment) LB | 992 |

**Open window = 1006 - 996 = 10.** (At 1031 it was 16.) The theoretical
maximum any repacking of this op stream can pay is 10 cycles, and the
regret profile says where they are.

### Regret profile at 1006: 11 = ramp 4 + mid 3 + drain 4

| c | +d | F | engLB | cpLB | rounds at c |
|---|---|---|---|---|---|
| 0 | +1 | 996 | 995 | 512 | (setup) |
| 1 | +1 | 997 | 995 | 512 | (setup) |
| 3 | +1 | 998 | 994 | 510 | (setup) |
| 7 | +1 | 999 | 991 | 508 | r0 |
| 805 | +1 | 1000 | 194 | 112 | r7,8,11,12,15 |
| 864 | +1 | 1001 | 136 | 99 | r7,8,9,12,13,14 |
| 915 | +1 | 1002 | 86 | 70 | r9,10,11,12,13 |
| 978 | +1 | 1003 | 23 | **24** | r14,15 |
| 984 | +1 | 1004 | 17 | **19** | r14,15 |
| 993 | +1 | 1005 | 8 | **11** | r14,15 |
| 997 | +1 | 1006 | 8 | 8 | r15 |

Shape vs 1031/1023: the r9-11 epoch-seam CLUSTER (5 cycles at 1031, 5 at
1023) is down to 3 isolated unit jumps spread over c=805/864/915, and the
drain is 4 (was 7 at 1031). The drain is CP-bound — cpLB strictly exceeds
engLB from c=978 on — i.e. the last 3-4 cycles are provably latency, and
no packing decision can touch them. That alone caps the packing-shaped
share of the 11 at <= 7-8, and the energetic bound independently caps it
at 10.

### Search battery on THIS stream — 386,090 trials, zero improvement

Incumbent 1006 throughout. Every trial = a full DAG re-schedule.

| tier | scope | trials | best |
|---|---|---|---|
| priority-list (parallel SGS) | tail_height | 1 | 1046 |
| priority-list | est+tail (CP) | 1 | 1229 |
| priority-list | reverse emission | 1 | 1024 |
| priority-list | forward emission | 1 | 1329 |
| **discrepancy-1, ENTIRE stream** | all 20,462 ops x d in {1,2} | **40,924** | **1006** |
| **discrepancy-1, ENTIRE stream** | all 20,462 ops x d in {3,5,8} | **61,386** | **1006** |
| **discrepancy-2 pairs** | radius 3 around all 11 regret jumps (incl. c=0), all engines, d in {1,2}^2 | **283,780** | **1006** |
| total | | **386,090** | **1006** |

Notes on coverage: disc-1 over the ENTIRE stream at five delay values is
the COMPLETE first level of the bounded backtrack (delay one op that
greedy placed earliest, let greedy complete) — not a sampled window. The
pair tier's per-jump candidate sets were 24-148 ops each (24 @ c=0, 119 @
c=7, 136 @ 805, 130 @ 864, 133 @ 915, 146 @ 978, 148 @ 984, 124 @ 993,
101 @ 997). Priority-list scheduling with global lookahead is again
sharply NEGATIVE (best alternative 1024, +18): the emission order remains
a much stronger spine than any height-based priority.

k=3 sampling was deliberately NOT run: per the loop's diminishing-returns
rule, an empty exhaustive discrepancy-1 over the whole stream plus an
empty exhaustive pair sweep at every regret jump is where this stops.

### Verdict

**G-25's packing closure survives the regime change.** The one axis that
had never been re-measured on the current stream re-measures the same
way, and it is now a tighter negative than it was at 1031: the open
window shrank 16 -> 10, the search was denser relative to the stream
(386k trials over 20,462 ops), and the drain — 4 of the 11 residual
cycles — is provably CP-bound rather than slot-bound. Nothing beat 1006,
so there is no artifact to land and no port to schedule.

Composition with the rest of the strain map: order is closed by
enumeration (G-30/G-31, 26,415 exhaustive single-entry displacements at
1020 + re-walk at this mix), spelling is closed (H-042/F-25, empty
flow_spelling_plan at 1006), packing is closed here. All three scheduler
axes are measured-closed at the 1006 mix, for the second regime running.
The residual 11 is dependency-chain structure: ramp 4 (setup vbroadcast
RAW), mid 3 (three isolated r7-r13 seam jumps, no longer a cluster),
drain 4 (CP-bound r14/r15 chains). Only chain shortening (H-052/H-055) or
a mix change can move it — re-confirmed, not re-argued.

Reusable: `tools/f39_pack.py` (capture/validate/regret/bound/probe/
verify at the 1006 config, config read live from the plan JSON so it
follows the frontier) and `tools/f39_par.py` (8-way parallel disc-1 /
pairs / triples). Re-running the full battery at a future stream is
~15 min of wall clock; re-running measure+validate+bound+regret is ~10 s.
