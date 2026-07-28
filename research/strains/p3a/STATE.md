---
title: P3-A — the serving axis: what the tournaments actually cost, and the design that clears 940
date: 2026-07-28
type: research
status: final
task: Attribute the non-hash serving-support arithmetic op-by-op; determine whether it can be eliminated or migrated off alu/valu; cost alternative serving formulations as full censuses against the 940 target.
links: ["[[../p3b/STATE]]", "[[../../graveyard]]", "[[../../RESEARCH]]"]
---

# P3-A: serving axis

Tools written (read-only, new files only):
- `tools/p3a_attrib.py` — monkeypatches `ListScheduler.put` (the single funnel
  all emits pass through) and records, per placed slot, the innermost
  `perf_takehome.py` call-site chain plus the round/level/group of the
  enclosing `_round_stage_generator` frame. Exact, not inferred.
- `tools/p3a_mech.py` — folds those call sites into mechanisms. Reproduces the
  H-058 census total EXACTLY (59,489 alu+valu lane-ops / 1,892 load / 797 flow
  / 46 store @ 1006 cycles).
- `tools/p3a_model.py`, `tools/p3a_opt.py` — parametric census model +
  optimizer over the serving design space, scored by simultaneous floors.

## (a) Measured mechanism census of the shipped 1006 kernel

| mechanism | alu+valu lane-ops | alu sl | valu sl | flow | load | store |
|---|---|---|---|---|---|---|
| hash.core (11-op hash, 352 `^C5` elided) | 42,240 | 9,304 | 4,117 | 0 | 0 | 0 |
| hash.foldin (`val ^= node_val`, 1/group-round) | 4,096 | 1,360 | 342 | 0 | 0 | 0 |
| idx.parity (`val & 1`) | 3,584 | 56 | 441 | 0 | 0 | 0 |
| tourn.L3 | 2,048 | 0 | 256 | 192 | 0 | 0 |
| tourn.L4 (pair machinery) | 1,744 | 40 | 213 | 208 | 0 | 0 |
| idx.addr (steady gather recurrence) | 1,328 | 0 | 166 | 166 | 0 | 0 |
| idx.exit (gaddr rebuilt from position) | 1,144 | 296 | 106 | 0 | 0 | 0 |
| pos.fold (position accumulator `p:=2p+b`) | 1,128 | 432 | 87 | 0 | 0 | 0 |
| setup | 665 | 65 | 75 | 22 | 60 | 46 |
| cond.mask (conditions extracted from `st`) | 624 | 208 | 52 | 0 | 0 | 0 |
| tourn.L2 | 400 | 0 | 50 | 166 | 0 | 0 |
| pos.seed (ringed L2 seed) | 320 | 0 | 40 | 0 | 0 | 0 |
| tourn.L1 | 168 | 0 | 21 | 43 | 0 | 0 |
| gather.load | 0 | 0 | 0 | 0 | 1,832 | 0 |
| **TOTAL** | **59,489** | | | **797** | **1,892** | **46** |

Per-level detail is in the tool output (`p3a_mech.py`, and the per-level table
reproduced by the one-liner in the session log).

**Attribution corrections this makes to the Phase-3 charter:**
1. The charter's "idx-minimum 8,192 lane-ops" is NOT a floor of this design.
   Served group-rounds carry no address at all; the whole measured
   index+position family (idx.parity + idx.addr + idx.exit + pos.fold +
   pos.seed) is 7,504 lane-ops. Subtracting a non-binding 8,192 is what
   produced the charter's "-64%" figure. The honest requirement at 940 is:
   non-hash alu+valu must fall from **13,153 to <= 10,064 lane-ops (-23.5%)**.
2. Routing's 504 `multiply_add` slots (4,032 lane-ops) are tournament SELECTS
   spelled as `cond*diff + base`, not address arithmetic (confirms P3-B).
   They live in tourn.L1..L4 above.
3. `pos.fold` runs even on retained-parity ("ringed") groups, because the
   packed accumulator `st` must still be identical for the epoch-exit gaddr
   conversion. It is upkeep for the *packed* representation, not for serving.

## (b) Three structural theorems (derived, not measured)

**T1 — every tournament node is freely flow-or-valu at 1 op.**
Serving one group-round at level d costs exactly `2^d - 1` two-way ops
(G-23/H-058: no permute, no scratch-indexed read => routing is 1 load or
2^d-1 selects). A node combining constant subtables A (bit=0) and B (bit=1) is
either `vselect(b, B[q], A[q])` — 1 flow slot — or
`madd(b, (B-A)[q], A[q])` — 1 valu slot; in BOTH cases the two children are
again tournaments over CONSTANT tables of size `2^(d-1)` (for the madd form
the child table is the elementwise difference `B-A`, precomputable at setup).
Therefore **no interior node ever needs a runtime subtract.** The shipped
kernel's `race_sel` sub+madd interiors (96 lane-ops at L4) and
`make_newest_parity_last_diffs` (64) are an artifact of the newest-first tree
shape and are removable. Broadcast-vector count is `2^d` per served level
either way (L1..L4 => 2+4+8+16 = 30 vectors, 240 scratch words).

**T2 — the position accumulator is pure overhead for serving.**
Retain the raw parity bits per level (exact 0/1, free — they are the parity
extract's write) and the tournament conditions are read directly:
`cond.mask` (624), `pos.fold` (1,128) and `pos.seed` (320) all go to zero
(-2,072 lane-ops). The position is instead built by Horner **only at a gather
boundary**: `d` madds for `d` bits instead of the steady 1 madd, i.e. +2 valu
ops per exit. Exits are 32 per epoch-0 group plus each round-15 L4
group-round left unserved => 35 at the optimum, so +70 vec-ops. Net **-1,512
lane-ops**. This is the single largest lever on the axis and it is
load-bearing: with the packed accumulator kept, the best floor is 958.

**T3 — nothing else on the axis can leave alu/valu.**
- `store` engine (46/2012 used): stores cannot compute. The one real use is
  building a broadcast vector as 8 scalar `store`s + 1 `vload` instead of a
  `vbroadcast` — this removes REAL COMPUTE (1 valu op per table vector, up to
  48) at +1 load and +8 store slots each. It is load-limited, not store-limited.
- `flow` `select`/`add_imm` are SCALAR (1 word/slot, problem.py:328-333), so
  they cannot do vector work. The only flow vector op is `vselect`, 1/cycle.
  The single useful `add_imm` finding is the reverse direction: the 20 setup
  `add_imm` slots should move TO alu, freeing 20 flow slots for folds
  (-160 alu+valu lane-ops). This is load-bearing at 940.
- `debug` is free but writes nothing the kernel reads.

## (c) CENSUS TABLE — every candidate serving formulation, scored at C=940

Capacity at 940: alu+valu 56,400 lane-ops | load 1,880 | flow 940 | store 1,880.

| # | design | alu+valu lane-ops | load | flow | floors /60 /2 /1 | VERDICT @940 |
|---|---|---|---|---|---|---|
| S0 | shipped (measured @1006) | 59,489 | 1,892 | 797 | 991.5 / 946.0 / 797 | FAIL: alu+valu by 3,089, load by 12 |
| C1 | ring/no-accumulator (T2), s=221, shipped fold spelling & setup | 56,544 | 1,876 | 940 | 942.4 / 938.0 / 940 | FAIL: alu+valu by 144 |
| **C1\*** | **T1+T2+T3: ring, free-form fold placement, `add_imm`->alu, 4 store-broadcasts, s=221** | **56,272** | **1,880** | **940** | **937.9 / 940.0 / 940.0** | **PASS all three** |
| C2 | sum-of-products (multilinear madd, no vselect at all) | 61,960 | 1,880 | 229 | 1,032.7 / 940.0 / 229 | FAIL: alu+valu by 5,560 |
| C3 | store-engine broadcast pushed to all 48 vectors | 56,072 | 1,935 | 940 | 934.5 / 967.5 / 940 | FAIL: load by 55 |
| C4 | serve more to buy load slack (s=250) | 58,888 | 1,692 | 940 | 981.5 / 846.0 / 940 | FAIL: alu+valu by 2,488 |
| C5 | serve L0..L4 fully (s=256) | 59,512 | 1,644 | 940 | 991.9 / 822.0 / 940 | FAIL: alu+valu by 3,112 |
| C6 | serve everything, no gathers (s=448) | 571,000 | 108 | 940 | 9,516.7 / 54.0 / 940 | FAIL: alu+valu by 514,600 |
| C7 | gather everything, no serving (s=0) | 54,088 | 3,644 | 450 | 901.5 / 1,822.0 / 450 | FAIL: load by 1,764 |
| C8 | C1\* but keeping the packed accumulator (T2 off) | 57,472 (@958) | 1,916 | 958 | min floor **958** | FAIL @940 |
| C9 | C1\* + omf constant-select eliminated (cross-axis, P3-B index-bias) | 55,128 (@920) | 1,840 | 920 | min floor **920** | PASS, floor 920 |

**C2 is exactly isomorphic to the select tree, not cheaper.** Evaluating the
multilinear polynomial in the d parity bits by Horner costs `2^d - 1` madds —
the same node count as the tournament — but every node is then valu-only
(the top madd's arms are runtime values, so it is not a select). It strictly
loses: it converts 1,139 flow-eligible ops into 1,139 valu ops.

## BUDGET LINE

Charter's stated budget: "setup + serving overhead + wrap <= 1,744 lane-ops."
That target is an artifact (see (a).1). Restated correctly and answered:

- Pool as the charter defined it (non-hash minus a nominal 8,192 idx floor):
  shipped **4,833** -> best achievable **2,264** lane-ops. Does not reach 1,744.
- Pool as it actually binds (ALL non-hash alu+valu lane-ops, which is what the
  capacity algebra sees): shipped **13,153** -> best achievable **10,032**,
  against a hard ceiling of **10,064** at 940. **Clears, by 32 lane-ops.**

Composition of the best 10,032: parity 3,584 (at floor, P3-B) + index/exit
2,376 + folds spilled to valu 3,424 + setup 528 + add_imm-on-alu 120.

## Minimum floor of the serving axis

`tools/p3a_opt.py` scans C x serving profile. **Minimum simultaneously
feasible floor = 939 cycles**, at s=221 served group-rounds
(L1 64 + L2 64 + L3 64 + L4 29), 227 gathered, 1,139 folds.
At the optimum **load and flow bind exactly and simultaneously**
(flow = C, load = 2C) with alu+valu ~1.5 cycles of slack. The trade at the
margin is: +1 served L4 group-round = -8 load slots but +15 folds, and since
flow is saturated those 15 folds land on valu — an exchange rate of
1 load slot ~ 1.875 valu vec-ops, which is why every "serve more" variant
(C4/C5/C6) loses and every "gather more" variant (C7) loses.

## Honest caveats

1. **939 is a FLOOR, not a realized cycle count.** Measured regret between
   floor and realized on this kernel is ~11-15 cycles (shipped: floor 991.5,
   realized 1006). A design whose floor is 939 with two engines exactly
   saturated would realize ~950-960, not 940. Under the Phase-3 acceptance
   bar as literally written ("simultaneous engine floors all < 940") C1\*
   PASSES; it does not imply a realized 940.
2. **Model error.** The model calibrates against S0 to within 55 lane-ops
   (0.1%) once the flow-allocation difference is accounted for, but the
   margin at 940 is 128 lane-ops (16 vec-ops, 0.23%). Two inputs carry that
   much uncertainty on their own: `SETUP_VEC_MIN = 70` (measured shipped 83;
   48 broadcast vectors + 12 priming vxors + ~10 scalar-equivalent) and the
   exit count (35). **This result is at the edge of the model's resolution.**
3. **Scratch.** Retained parities cost 3 vectors/group (768 words at K=32)
   where the packed `st` cost 256. At K=32 the design overruns
   SCRATCH_SIZE=1536 by ~85 words. It fits at K=16 live groups
   (~1,080 words), and H-058 measured K>=11 suffices for ILP at 940 — but
   K<32 is an untested frame (charter frame #4).
4. `add_imm`->alu (20 flow slots) is load-bearing: without it C1\* FAILS.
   Setup cost 70-vs-83 and the store-engine broadcast are NOT load-bearing.
5. T1 (free-form fold placement) is not load-bearing AT the saturated optimum
   (all interiors fit on flow either way); it matters only when flow has
   slack, and it is what makes the L4 `race_sel` subtracts removable.

## Cross-axis handoff to P3-B

The `omf` two-way constant choice in the gather-address recurrence
(`gaddr' = 2*gaddr + omf +/- par`) consumes 227 flow slots at the optimum.
Because flow is exactly saturated, each of those slots displaces one fold
onto valu. **Eliminating it takes the serving axis's floor from 939 to 920**
(C9 above) — the single largest remaining lever anywhere in reach, and it is
an index-representation question, not a serving question. Note the constraint:
P3-B's `val | 0xFFFFFFFE` = `par - 2` form makes the recurrence constant-free
only if the biased accumulator can be loaded from directly, which it cannot
(`load` reads `mem[scratch[addr]]` exactly). Whether a per-level constant
re-bias exists is P3-B's call.
