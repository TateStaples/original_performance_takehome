# Strain: cross (cross-pollination, iteration 6)

## Mandate
One-off cross-pollination pass (per LOOP.md rule 10): find what the
single-strain agents structurally could not see — combination plays,
violated premises, unexplored axes — and TEST the best. Base 94d5f00
(mainline 1064).

## Frontier
**1053 (flag-gated, MAINLINE CANDIDATE, -11)** @
`mem_prime=(5,)` + `store_pair=True` + `b3_last=(15,)` + `b3l_diffs=True`
+ `l4_gmin=(12,30)` on top of the unchanged 1064 mainline flag set.
Correct on 4+ fresh-data runs (also with debug_compares both ways);
default dispatch + default stream verified BIT-IDENTICAL to 94d5f00
(programmatic instr compare over dispatch, mainline kwargs, mainline
no-debug, b3_last-only, parity_conds=False, no-flags; scratchpad/
bitcheck.py); grader 9/9 green at 1064. At 1053: valu census 6209
(floor 1035), friction 18 cyc.

Decomposition (each at its own l4_gmin optimum, all measured):
| stack | gmin | cycles | delta |
|---|---|---|---|
| mainline | (13,28) | 1064 | — |
| + mem_prime=(5,) | (12,28) | 1061 | -3 |
| + store_pair | (12,30) | 1057 | -4 |
| + b3_last=(15,)+b3l_diffs | (12,30) | **1053** | -4 |

Controls (the three pieces are individually ~0 and only pay composed):
store_pair alone 1064 (tail is compute-bound until b3l frees it);
b3_last+b3l_diffs w/o store_pair 1064 (frees compute, exposes the
1/cyc store serialization); b3_last alone still +14 (G-17 reproduced);
mem_prime flag-only 1067 (needs the gmin slide, P-3 pattern again).

## What landed (all default-off, bit-exact defaults)

### H-026 `mem_prime` — the marginal-cost member of the c5_prexor family
H-015's P-4 killed "pre-xor the deep tree" with all-or-nothing
arithmetic (+254 vloads -> >=1108 floor). Nobody costed ONE level.
Level 5 = 4 vloads + 4 vec xors + 4 vstores staged through the
setup-dead `lv` scratch during the setup load lull, and round 4 (the
round feeding level-5 gathers) joins the elide set for all 32 groups:
-32 mid-window vec ops for ~zero marginal load cost. The elided-round
parity inversion at GATHER-mode exits is closed with the omf1 = 2-fp
vector (gaddr' = 2*gaddr + (omf+1) - par'), homed in lv[24..31] (dead
after setup) — zero allocation; the served-exit inversion was already
generic in rec_off()/the elide sign. Level 6 does NOT pay: (5,6) is
+3..+6 worse than (5,) at every gmin tried — the coarse mem model
serializes the load->xor->store waves (a store per cycle), so level 6's
8 extra waves push mem_write_c into the first gathers; a batched
variant measured WORSE (1064 vs 1061), reverted. Levels 7+ are
strictly dominated (double loads, same 32-xor gain).

### H-028 `store_pair` — same-cycle mem writes in the scheduler model
The coarse one-location mem model forces mem_write >= mem_write_c + 1,
i.e. 1 store/cycle on a 2-wide store engine. Every store in this
kernel targets a distinct mem word (final vals, l4/mem_prime priming),
and bundle semantics commit writes at end of cycle, so same-cycle
write PAIRS are exact. One-line relaxation in ListScheduler.ready()
(instance flag `pair_writes`, default False = bit-identical). The 32
final vstores were serializing 1/cyc with the last ~5 exposed beyond
the final hash — profile showed cycles 1056-1060 pure store-drain
once b3l_diffs freed the compute.

### H-027 `b3l_diffs` — G-17's reopen-if satisfied by DEAD-REGISTER reuse
G-17 closed b3_last because the reversed fold's leaf selects have
broadcast arms: flow-serial (1-slot) or valu sub+madd (doubled). Its
reopen-if asked for >=64 free scratch words for leaf-diff tables.
Those words exist AT THE FINAL ROUND as dead registers: the `st` of
every non-served group (last read = r14's gather issue) and the `nv`
of every earlier block's group (last read = its own r15 fold-in).
b3l_make_diffs() pools them earliest-dead-first (52 vectors at
gmin=(.,30)): 8 leaf-diff vectors (dT[k] = tabs[2k+1]-tabs[2k], with
odd_of[] registered so dual_fold races madd-vs-vselect per leaf) plus
NINE private registers per served group (3 once-computed exact-0/1
masks + 3 E-temps + 3 D-temps). The private registers matter as much
as the diffs: the first b3l_diffs build reused the shared cond/tm
pools and profiled heavy pool WAW at the drain (blocked-on pool/anon
53.8, census +38); private regs + once-computed masks brought the
census BELOW baseline. Graceful degradation: pool-short groups fall
back to the H-023 dffold path (measured correct at gmin=(12,26) and
b3_last=True). Post-b3 chain at r15: ~4 fold levels -> 1 madd.

### `bl_last` — the L2/L3 generalization is a measured NEGATIVE
Same newest-parity-last factorization applied to L2/L3 needs NO new
tables (node = evens[t] + b_new*diffs[t], t = older bits in st at
round start; pre-fold evens/diffs by t on flow, one post-parity madd).
Landed for the last skew block's listed rounds. Measured on the 1057
stack: r13 +2, r14 +13, both +8. The 6 pre-fold vselects/group flood
the 1-wide flow engine exactly as G-12 predicts — even at the drain,
because block 3's r13/r14 window still overlaps blocks 1-2's tail
work. Kept in-tree as a negative control; reopen only if flow gains
slots (never) or the last block's r13/r14 window becomes truly idle.

## Premise audit of the graveyard (angle 2) — all still closed at 1064
- G-8 parity_early: incompatible with c5_prexor (assert); valu 98.1%.
- G-13 spec_fold: "auto" measured 1064 (exact 0 again); valu+alu
  headroom condition not met.
- G-14 sel_race: 1067 (+3) — H-024's ramp changes did NOT flip it;
  flow's local saturation windows moved but valu is still the binder.
- G-17 b3_last: (15,) alone still 1078 (+14) — but the reopen-if IS
  satisfiable via dead-register reuse (H-027 above): with diffs +
  private regs + store_pair it contributes -4 at the (12,30) optimum.
- Dormant emit-order/tie-break flags: stage_tail:1 1064, vec_valu
  1064, fold_flow 1063-1064 — all neutral, as at 1070.
- vsel_auto=(1,3) now OVERFLOWS scratch under l4_race=3 (the 1087-era
  sweep win is dead at the current allocation).

## Domain-transform family + 16-round shape (angles 1, 4) — analysis
- The ^C1 fold (stage 1) cannot commute anywhere: separated from the
  fold-in xor by the stage-0 madd (non-affine boundary) and from
  stage 2/3 likewise; the xr3p/head4u MITM negatives (H-016) already
  pin every such boundary at current depth. No new searchable target.
- Carrying val in a shifted/scaled domain across the round boundary
  removes zero ops: the 4-op boundary (sigma16 ^ n' -> stage0) is a
  sub-segment of xr3p whose 5->4 negative covers it.
- Tournament-round "known-constant" fold-ins do not collapse: for a
  known n, stage0(v^n) is not affine in v, and per-candidate
  speculation is G-13 (re-measured 0 this iteration).
- The q = (a*kp + C2) << 9 factorization of the kq madd is G-15's
  measured +70 (already tried as "hash kq-madd conversion").
- Epoch asymmetry: the only structural per-epoch dials are l4_gmin
  (already per-epoch; the (12,30) slide IS this iteration's epoch-1
  exploitation) and skew shape (swept exhaustively, (4,3) stays).
  Rounds 11-14 are gather-free by construction; nothing else differs.

## Residual friction at 1053 (sched_profile)
18 cycles = 30 empty-slot store-drain tail (~5 cyc: the last block's
r15 hash staircase + paired stores) + 22 ramp (structural per H-024)
+ 35 r15/seam (upstream r14 throughput staircase, NOT fold latency —
b3l_diffs proved the fold link was only worth ~4 composed) + scatter.
valu floor 1035; census 6209. Below ~1035 requires op removal
(H-025 CEGIS is the only open hash lever) plus proportional load/alu
relief; the l4_gmin dial keeps absorbing valu relief into load relief
at ~1 cyc/group (P-3 pattern held twice more this iteration).

## Follow-ups proposed (for the driver)
- P-c1 [mainline flip] [DONE]: verify + flip the 1053 stack (store_pair=True,
  mem_prime=(5,), b3_last=(15,), b3l_diffs=True, l4_gmin=(12,30)) via
  the full gate. All flags default-off today; flip = dispatch kwargs.
  DONE (dev.py/perf_takehome.py split): this stack is now baked in
  unconditionally as perf_takehome.py's flag-free mainline (dev.py keeps
  the flag-configurable form for sweeping). Superseded further by H-029's
  idx_select flip (2026-07-25): l4_gmin retuned (12,30) -> (9,30),
  mainline now 1043 (was 1053). Grader 9/9 green.
- P-c2 [sweep]: add mem_prime {(),(5,)} x store_pair x b3_last
  {(),(15,)} x b3l_diffs x l4_gmin (dense epoch-1 27..32) x pools to
  the standing grid; the epoch-1 optimum moved 28 -> 30 under the
  stack and may move again after any accept.
- P-c3 [op-reduction]: H-025 (CEGIS) unchanged as the only open
  op-removal lever; this iteration's -11 came from setup/drain/model
  slack, which is now largely harvested.
- P-c4 [scheduler, small] [TESTED 2026-07-23, REJECTED]: the store-drain
  tail (~5 cyc) could shrink if the LAST block's stores paired tighter
  with its hash completions (emission-order of the final store loop,
  last-finishing groups first); bounded by ~3-4 cyc, zero risk to try in
  a sweep-class run. RESULT: landed a `store_order` flag
  (perf_takehome.py, default "group" = unchanged natural order) with two
  variants — "rev" (fully reverse emission order) and "tail_first" (only
  move the last 4 groups, matching H-021's known g28-g31 staircase, to
  the front). BOTH measured WORSE, not better: mainline 1053 -> 1064
  (either variant); idx_select+l4_gmin=(9,30) 1043 -> 1054 (either
  variant) — a clean, consistent +11 cyc regression in both engine
  contexts. The natural group emission order is already tuned (likely an
  artifact of b3_last=(15,)'s own fold-order optimization interacting
  with which groups the scheduler favors) — reordering it blind, even
  targeting only the known-late groups, breaks something that already
  worked. Flags kept in-tree as negative controls, default off/unchanged.
  Closing this proposal; the store-drain tail does not respond to
  emission-order tricks the way the premise assumed.
- P-c5 [graveyard hygiene]: G-17's reopen-if is satisfied and
  harvested (b3l_diffs); rewrite the entry to point at H-027's
  mechanism and the bl_last L2/L3 negative (flow flood confirmed a
  second time, drain-side).
