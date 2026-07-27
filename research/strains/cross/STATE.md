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

## H-040 — Web research: what explains the 892 leaderboard score (2026-07-27)

Pure research hypothesis; no kernel changes. Question: our floors say 1,015 lane-op floor for the
current program organization, both known levers to 892 are closed — so what is 892?

### Verified facts (all URLs fetched 2026-07-27)

**1. The leaderboard and its two boards.**
- Site: https://vliw-challenge.fly.dev (community-run, "Based on Anthropic's Original Performance
  Take-Home", Mastodon login). Scoreboard API is public, no auth:
  - Without Indices: `https://vliw-challenge.fly.dev/api/scoreboard`
  - With Indices: `https://vliw-challenge.fly.dev/api/scoreboard?indices=1`
- Grading pipeline (from `https://vliw-challenge.fly.dev/static/pyodide-worker.js`): the browser runs
  the submitted `perf_takehome.py` in Pyodide, calls `KernelBuilder(); kb.build_kernel(10, 2047, 256, 16)`,
  and POSTs `kb.instrs` (the instruction stream JSON) to the server for validation. **Identical
  problem parameters to ours** (forest_height=10, n_nodes=2047, batch=256, rounds=16). The site's
  `problem.py` (`/static/problem.py`) is the upstream VM (same SLOT_LIMITS, valu=6, etc.) — only
  cosmetic/annotation diffs vs our copy. So it is NOT a different problem variant.
- The two boards differ only in the server-side output check: "Without Indices" does not require the
  final `inp.indices` writeback; "With Indices" is the full reference-kernel contract (our rules).

**2. Where 892 sits.**
- 892 = rank 1 on the **Without Indices** board: @wouterkool (https://mastodon.social/@wouterkool),
  5 submissions. Next: 900 (@saifalharthi, 66 subs), 908, 922, 923 (@josusanmartin, 136 subs), 924,
  926, 927, 941 (@jamespayor), 955, ... 971 (@corsix), 993 (@dougall), 1000, ...
- **With Indices** board (our exact grading): top = **940** (@josusanmartin), then 958 (@jamespayor),
  981 (@glentaggart), 994 (@corsix), 995, 996, 1002 (@dougall), 1018, 1033, 1038 (@b2_4814d920 — our
  own mainline score appears here), ...
- So: 892 is on the relaxed board, but that is NOT the main explanation of the gap — under our exact
  rules the frontier is 940, i.e. ~98 cycles below our 1038 and 75 below our claimed 1,015 floor.
- Measured cost of the indices requirement at the frontier: Austin Wallace reports 1,137 (no idx
  storage) vs 1,152 (with) = **15 cycles** for his solution (https://www.austinwallace.ca/kernel);
  board-top deltas: wouterkool 892 (no-idx board only), josusanmartin 923 vs 940 = 17, jamespayor
  941 vs 958 = 17, corsix 971 vs 994 = 23, dougall 993 vs 1002 = 9. Consistent with our G-21 cap:
  idx-writeback relief is worth ~10-25 cycles, not 146.
- wouterkool has no public Mastodon posts (0 statuses via API) and no public takehome repo on GitHub;
  he is a combinatorial-optimization researcher (beam search, VRP, Gumbel-top-k sampling —
  github.com/wouterkool) — search-based scheduling is a plausible but unverified inference.

**3. Disclosed frontier techniques.**
- **corsix (971/994), blog post 2026-02-08** https://www.corsix.org/content/anthropics-compiler-challenge:
  - Frames the kernel as 512 copies (16 rounds x 32 vector lanes) of a small computation graph to be
    placed on a grid of per-cycle cells: 7.5 "valu" (6 valu + 12 alu/8), 2 load, 2 store, 1 flow.
  - Naive gathers alone need 4096 load cells => >=2048 cycles; sub-1000 requires (a) shrinking the
    graph (op-count reduction) and (b) **replacing "+base"+gather with selection trees**: "preload
    the values of every possible idx, and use the output from all earlier &1 boxes to select"; cost
    grows with tree level (level k: 2^(k-1)-ish selects, each 1 flow OR 1-2 valu); "**more than 280
    gathers can be gainfully replaced with selection trees**".
  - Key claim: the real problem is **balancing the instruction mix to 7.5:2:1 valu:load:flow in every
    individual cycle** — "instruction selection and instruction scheduling are intertwined"; winner =
    whoever searches that joint space best.
- **Austin Wallace (1,137/1,152)** https://www.austinwallace.ca/kernel: 16-technique writeup incl.
  depth-specific node selection (preload/vselect vs gather per level), pointer-form indices,
  stage-major hash interleaving, ALU offload of constant work, wavefront scheduling across tiles,
  full list scheduling over dependency graphs, and **beam search over the schedule itself**
  (beam width 2, 3 candidate bundles, first 25 cycles). Was "tied 11th in the world" on 2026-01-24.
- Other public writeups are all >=1,105 cycles (epicvogel 1,105 via Claude Code orchestration
  https://x.com/EpicVogel/status/2029322218505924653; obviy.us 1,524; trirpi.github.io deep-dive;
  fiigii/ai-comp compiler + HN threads https://news.ycombinator.com/item?id=48911420,
  https://news.ycombinator.com/item?id=46700594). No public writeup below 1,100 other than the
  board data itself; nobody has published the 892 recipe.
- Second leaderboard exists (X-login, server-side sandbox, 30s timeout): https://www.kerneloptimization.fun/
  — same repo, single board, "code must pass validation tests".

### Interpretation (inference, clearly flagged)

- 892 = (a) a **~920-cycle-class organization under full rules** plus (b) ~20-30 cycles of relief
  from the no-idx-writeback board. Our two closed hypotheses were closed correctly (hash op-count
  magic and idx-recurrence folding are not the lever; the idx-writeback lever really is small).
- The 1,015 "floor" is an artifact of OUR op mix. The frontier's mix is different in kind: they
  convert hundreds of gathers (load-engine ops) into flow/valu select trees per tree level, then
  re-balance so valu, load, AND flow are all near-saturated every cycle. Our floor computed over
  the current organization cannot see this because it holds the gather count fixed.
- The with-indices frontier (940) proves >=98 cycles of headroom exist for us without any rules
  change. The levers, in order of evidence strength:
  1. **Gather -> selection-tree conversion swept per level with global mix re-balancing** (corsix:
     >280 gathers convertible; check how many we convert today and whether our flow engine is
     saturated).
  2. **Joint instruction-selection + scheduling search** (beam/anneal over bundle choices, not
     greedy list scheduling with fixed selection) — Wallace got 15-30 cycles from a tiny beam;
     wouterkool's profile suggests much heavier search pays.
  3. Depth-specific hybrid per level (preload levels 0-k free/cheap, select-tree mid levels,
     gather only deep levels), with the crossover re-derived from engine-pressure, not op-count.

### Recommended loop redirection

- Retire "hash op-count" and "idx-folding" lines for good (confirmed correct closures).
- New strain: measure per-cycle engine occupancy histogram of the 1038 build; count current
  gathers-by-level vs corsix's ">280 convertible" bound; prototype select-tree conversion at one
  additional level with mix re-balancing.
- New strain: replace greedy scheduling with a small beam over candidate bundles (Wallace's
  parameters as a starting point), measured end-to-end.
- Target restated: 940 is achievable under our exact grading; 892 requires the no-idx board.
# H-043 — Frontier writeup mechanism extraction (2026-07-27)

Status: CLOSED-ANSWERED (research-only; written here because this agent may not
commit to the repo — paste into research/strains/cross/STATE.md).
Brief: deep-read all public frontier material (corsix 971/994, wallace 1137/1152,
plus any dougall/jamespayor/josusanmartin trail), extract every op-level or
algorithmic technique, map onto our ledger, rank the genuinely-new items with
idealized-machine gains against census {alu 11,881 / valu 6,119 / load 1,900 /
flow 797 slots at 1038; 60,841 alu+valu lane-ops; floor 1,015}.

## Sources covered

| source | score | status |
|---|---|---|
| corsix.org/content/anthropics-compiler-challenge | 971/994 | FULL — article text + all 3 SVG diagrams decoded (SVG text extraction; diagrams carry the op-level content WebFetch misses) |
| austinwallace.ca/kernel | 1,137/1,152 | FULL writeup |
| HN 46700594, user amirhirsch (comments 46709173/46719908/46735107, via Algolia API) | 1,137 claimed, argues floor ~1,014-1,024 | FULL comment text |
| github.com/fiigii/ai-comp (+ x.com/fiigii thread, HN 48911420) | 1,137 | general-purpose compiler, no algo tricks; HN thread 429'd |
| josusanmartin (940) | — | NO challenge writeup exists; his blog (josusanmartin.com) covers Highload.fun only; method there = massive vibecoded automated search |
| jamespayor (958), dougall (1002) | — | NOTHING public found (2 searches each; dougallj github/blog have no takehome material) |
| trirpi.github.io, medium (Indosambhav, Adityarawat), obviy.us, x.com/EpicVogel | 1,105-1,524 | below our 1038; skimmed via search snippets, nothing beyond the items below |

## Key decode: corsix diagram 2 (his entire "strategy 1", verbatim from SVG)

Reduced per-copy graph: `+base, gather, ^nv, [*4097 + 0x7ED55D16], [>>19, ^0xC761C23C, ^],
[*33 + 0xE9F8CC1D], [*16896 + 0xACCF6200], [^], [*9 + 0xFD7046C5], [>>16, ^0xB55A4F09, ^], [&1], [*2+]`.
Verified algebra: 0xE9F8CC1D = (C2+C3) mod 2^32, 0xACCF6200 = (C2<<9) mod 2^32,
16896 = 33*512 — i.e. stage2∘3 double-madd fusion, EXACTLY our 11-op hash.
**The 971-frontier hash is 11 ops. G-10/G-20/H-025 are CONFIRMED by the frontier,
not contradicted.** His idx update is &1 + *2+ (the "+1" folded) = our extract+madd;
his +base survives as a separate box (we fold boundary/base handling comparably;
our Idx census 7,448/8/512 ≈ 1.8 vec-ops per copy-round is already ≤ his 3).

Corsix valu-class boxes per steady copy: 15 (12 hash+nv, 2 idx, 1 +base) = 120
lane-ops; ×512 = 61,440 → 1,024 floor on the 60-lane-op budget — ABOVE ours
(60,841 → 1,015). **Corsix's raw graph is not smaller than ours. His 971 comes
from strategy 2: exporting ops out of the 60-budget onto the flow engine and
deleting gathers/+base via select trees, balanced per-cycle at 7.5:2:1
("every single one of the ~1000 cycles wants to hit that ratio … instruction
selection and instruction scheduling are intertwined").**

## Technique-by-technique mapping

| # | technique | source | our status |
|---|---|---|---|
| T1 | s0/s2/s4 madd fusions; s2∘3 double-madd+xor (11-op hash) | corsix d2; wallace; amirhirsch | DONE (G-10; constants verified identical) |
| T2 | ^C5 pre-xor / merge stage-5 xor into next round's ^nv via primed node tables ("first several rounds when every tree value is in use") | amirhirsch 46735107 | DONE for scratch tables (H-015 c5_prexor) + L5 mem (H-026); generalization G-22-rejected — see FLAG-1 |
| T3 | parity from stage-4 bits {0,16} without constant xor | amirhirsch 46709173 | DONE, stronger (parity = 0 ops, H-015 table reversal, G-20) |
| T4 | constant/vec-op offload valu→alu (1 valu = 8 alu lanes); "12 scalar + 6 vector xors per cycle" | wallace; amirhirsch | DONE (H-019 emit_any racing; G-15 equilibrium) |
| T5 | gather → binary select tree over preloaded nodes; each select = 1 flow OR 1-2 valu; >280 gathers gainfully replaced | corsix (cost table L0-L5); wallace depths 0-3 | PARTIAL — our L0-L4 tournaments serve ~281 group-rounds (= his ">280"); G-23: at our census the REMAINING conversions lose. Residual delta = the flow-spelling share, see N-1 |
| T6 | depth-specific idx representation (1-bit root, 2-bit d1, pointer-form p=base+idx from d2; recurrence p'=2p+const) | wallace | EQUIVALENT — G-21 steady floor extract+madd+combine already reached; pointer form same op count, only relocates the +base (G-21's ov==0 analysis covers) |
| T7 | compile-time wrap-check elimination (deterministic depth per round) | wallace; amirhirsch phases r1-5/6-9/10/11-14/15 | DONE (round-specialized kernel, boundary selects) |
| T8 | value scratch residency all 16 rounds; early vstores; DCE; add_imm consts | wallace; amirhirsch | DONE (H-021/H-023/H-024) |
| T9 | wavefront/skew groups staggered ~1 round | wallace | DONE (skew (4,3), G-6) |
| T10 | beam-search bundle packing; scored ready-set repair | wallace | PARKED (H-042, fitting) |
| T11 | per-cycle joint instruction-selection × scheduling at 7.5:2:1 | corsix | PARTIAL — we select spellings before scheduling (races are local); see N-3 |
| T12 | final-round parity skip (r15 needs no next-idx compute beyond the stored index) | amirhirsch | DONE (drain analyses; with-indices still stores idx) |

## Contradiction flags

- **FLAG-1 (scope hole): G-22** rejected C5-priming generalization on PLACEMENT
  grounds (waves displace critical path; front compute-saturated) while
  measuring a real lane-op reduction (-144 at (5,6)). Under the new ALGO-FIRST
  idealized regime (perfect allocation), that rejection's grounds are exactly
  what is idealized away → G-22 is closed-for-mainline but OPEN-for-ideal-model.
  Same class: G-18's vload sibling-pair variant (rejected on alu transpose +
  scratch, both allocation-side).
- **No frontier claim contradicts G-10/G-20/G-21/G-23.** Corsix's diagram
  positively CONFIRMS the 11-op hash closure, and his stated order (shrink
  graph, THEN convert gathers) confirms G-23's joint condition.
- amirhirsch (46719908) independently argues sub-900 impossible and floor
  ~1,014-1,024 from the same arithmetic as our combined-compute floor — the
  40-75 cycles the real frontier found below that are flow-export + joint
  scheduling, not op-count magic.

## Genuinely-new items, ranked (idealized-machine gains)

- **N-1 Flow-maximization of routing/idx selects (T5+T12 residual).** Every
  vector select spelled on flow leaves the 60-lane-op budget entirely. We use
  797/1038 flow slots; idx_boundary_select (G-21 byproduct, flag-ready OFF)
  frees 283 alu/valu slots at zero cost today. Solving c=(60,841−8X)/60 with
  X=c−797 gives **ideal 988** (−27 vs the 1,015 floor, −50 vs actual) if ~190
  more vector-selects admit flow spellings. This is the single largest ideal
  lever and is pure spelling, no new algorithm.
- **N-2 Idealized C5-priming generalization (T2, via FLAG-1).** Lane-op ledger
  −144 per level-pair measured at (5,6); extended across gather levels ≈
  −400..−700 lane-ops → **ideal −7..−12** (priming loads fit the 176 free
  setup/front load slots per G-22's byproduct window).
- **N-3 Joint per-cycle selection×scheduling (T11).** Not an op remover; it is
  what converts N-1's ideal into real cycles (spelling chosen per cycle against
  the live mix, corsix's "intertwined" point) and what plausibly separates
  940/958 (search-heavy, josusanmartin's known vibecoded-search MO, no writeup)
  from corsix's 971. Recovers our 23-cycle floor gap only in conjunction with
  N-1/N-4.
- **N-4 L5+ select-trees under infinite scratch (T5 tail).** Activates exactly
  per G-23 once N-1/N-2 land the budget near ~950-per-engine: at 940 the load
  budget is 1,880 < our 1,900, so ≥1 more level must leave the load engine;
  L5 costs 16 flow + 15×(flow|2valu) per group-round vs 8 loads + 1 valu —
  affordable only with flow slots freed by shorter total schedule (joint
  fixpoint; H-044's solve should iterate N-1→N-4 to convergence, est. landing
  ~950-960; 940 additionally needs N-3-class search).

Composed ideal estimate: N-1+N-2 ≈ 976-981; +N-4 fixpoint ≈ 950-960; the last
~10-20 to 940 is N-3 search quality. No public evidence of any mechanism
outside this set; nothing public from the 940/958/1002 holders at all.

**Bet: the frontier's ~400-valu-slot reduction is not a valu-op deletion — it
is valu→flow export (N-1) plus the select-tree/load rebalance it unlocks (N-4),
found by joint selection-scheduling search (N-3). The op census that must
actually shrink is loads (≥20) and flow-spellable selects, not hash/idx
arithmetic — which the frontier provably (corsix d2) runs identically to ours.**
