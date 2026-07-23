# Strain: flow-balance

## Charter
Move work off the saturated valu/alu engines (98.2%/94.6%) onto the 30%-idle
flow engine and the load/store slack; exploit placement freedom the current
kernel leaves unused. Owns code regions: tournament select/cond blocks in
emit_group_round, ListScheduler placement policy.

## Frontier
**1130** @ `parity_conds=True` + mainline tunables (tournament_levels=(1,2,3),
alu_offload=True, l4_gmin=(22,28), pool_sizes=(17,4), skew=(4,3)). Correct;
zero scratch delta (1535/1536 unchanged); default path bit-identical to 1140
mainline; all 9 submission tests green. Tunables re-swept under the flag:
mainline values remain optimal (l4_gmin grid, pools, skews all >= 1130).

## Assigned
- H-001 (iter 1): parity-vector conds — kill cond-extraction masks. DONE, accepted at strain level (1130).
Queued: H-007 (schedule-aware fold placement), H-006 (load-side), H-009, H-011.

## Iteration log
(append-only)
- iter 1 (H-001): parity_conds — 1140 -> 1130 (-10), correct, zero scratch.
  The prime variant (per-group parity rings) is infeasible: needs 848+ words,
  1 free. Landed a zero-scratch reformulation instead: newest parity rides
  nv[g] (dead between served rounds), the p := 2p+b accumulator madd LAGS one
  round into the next tournament block (madd(st,st,two,nv) before nv is
  clobbered), older-bit conds extract from the round-START-ready lagged st,
  and at L4 b2 lands at bit0 (raw 0/1 for the U-madds — the >> dies). The L2
  b0-copy moved to flow as vselect(c,st,st,st) (pure copy). Op deltas: alu
  -1144 lane-slots, valu -81 slots, flow +64; alu 94.6->87.0%, valu 98.2->
  97.8%. WHY ONLY -10 (predicted -40..-120): the eliminated ops were mostly
  absorbed by alu slack, and valu THROUGHPUT is now the binding floor —
  6634 valu slots / 6 = 1106 cycle-equivalents vs 1130 actual. Chain
  shortening (madd conds ready at round start, ~2 links off each tournament
  round) bought little because the schedule is throughput- not latency-bound
  at current l4_gmin. Verdict: mainline-candidate (strictly <1140, gated,
  default untouched).

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
- P-1 [-> strengthens H-007, cost S]: madd->vselect flip for tournament
  first-folds, now nearly free under parity_conds: replace D_vecs (odd-even
  diffs) with O_vecs (odd values) at setup — SAME scratch — and emit
  W[t] = vselect(b3, O[t], E[t]) on flow instead of madd(b3, D[t], E[t]) on
  valu; conds are raw parities (nv), ready at round start. l4 alone moves
  8 madds x 14 group-rounds = 112 slots off the binding valu engine (~19
  cycle-equivalents); L1/L2/L3 first-folds add 448 more candidates. Flow is
  at 35.6% (1-slot engine, ~730 free slots). G-4's serialization loss does
  not directly apply (W's are dependency-independent), but per-group flow
  serialization must be schedule-aware — flip a SUBSET, largest-win-first.
- P-2 [-> H-004, cost M]: valu madd diet. valu throughput is the floor now
  (6634/6 = 1106). Biggest remaining Idx/Routing madds: the lagged fold
  madd(st,st,two,nv) per tournament round (~384 slots) and the epoch-exit
  gaddr conversions. Attack: absorb the fold into the exit conversion
  (st kept as parities-in-registers until exit, exit becomes a 2-3 madd
  Horner chain — op-neutral at L3 but frees the per-round fold), or absorb
  2p+b into the gather-address madd on the r->r+1 boundary.
- P-3 [sweep, cost S]: re-run the l4_gmin/skew grid AFTER any madd->flow
  flip lands: serving more l4 groups costs valu madds today, so (22,28) may
  shift once W-folds ride flow; l4_gmin=(32,32) (no l4 service) measured
  1180 and (0,0) measured 1253 under parity_conds — the optimum sits in a
  valu-vs-stall trade that P-1 directly relaxes.
