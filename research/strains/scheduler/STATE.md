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
