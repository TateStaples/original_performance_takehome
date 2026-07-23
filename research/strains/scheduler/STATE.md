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
