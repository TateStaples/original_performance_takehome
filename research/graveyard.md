# Graveyard — rejected hypotheses (nothing here is retested without its reopen-if)

All entries carry measured evidence from this repo's actual grader/kernel.
Seeded 2026-07-23 from the 2148->1140 campaign's measured rejections.

### G-1 Full-epoch L4 tournament serving
- statement: serve level-4 rounds for ALL groups from scratch (no gathers).
- evidence: measured 1478 / 1557 / 1561 vs 1431 accepted group-split variant.
  Root cause: tournament depends on previous round's parity, so unlike a
  gather it cannot be prefetched a round ahead — it stalls the r4->r5 load
  stream at the front groups.
- reopen-if: parity-early (H-002) lands, removing the parity->tournament
  serialization. Then this becomes H-008.

### G-2 O(d) butterfly/rotation vselect network (Design B)
- statement: route level-d values in d conditional stride-2^k vselect stages
  instead of 2^d-1 tournament folds.
- evidence: low-3-bit stages are unsound for per-lane offsets (window
  positions would need the CONSUMER lane's condition bits, forcing 2^d-1
  selects anyway); only bits >= 3 shift consistently. Working-array storage
  ~48-64 words/group-slot also loses to broadcast tables on scratch.
- reopen-if: a formulation is found where per-lane windows align with
  producer bits (e.g. walkers sorted into position order between rounds), or
  scratch frees >512 words.

### G-3 Pair-gather (fetch both children one round early)
- statement: gather tree[2i+1] and tree[2i+2] during round r-1, select by
  parity in round r — removes gather from the critical path.
- evidence: doubles load traffic where load is already the binding engine —
  provably negative at r3->r4; ~neutral at r14->r15 but needed 256+ scratch
  words that did not exist (scratch 1535/1536).
- reopen-if: load engine drops well below binding on the target rounds AND
  >=256 scratch words freed.

### G-4 Whole-level L4 folds on flow (vselect U-folds)
- statement: run the L4 fold tree on the 30%-idle flow engine.
- evidence: 1143 vs 1140 — flow is 1 slot/cycle, so 7 serialized vselects
  lengthen the per-group chain even though slots are free.
- reopen-if: per-fold (schedule-aware) placement instead of whole-level
  (that refinement is H-007), or flow gains parallel slots (never).

### G-5 Phase-split emission (all selects before all hashes)
- statement: reorder emission so tournament selects cluster before hash ops.
- evidence: 1544 vs 1458 — emission order is the ListScheduler's slot-contention
  tie-breaker; hoisting selects starves critical hash chains.
- reopen-if: scheduler gains true priority/lookahead (not emission-order ties).

### G-6 Asymmetric skew lags; 8/16-block skews
- statement: non-uniform per-block round lags or more blocks beat (4,3).
- evidence: all swept variants >= 1140; symmetric (4,3) best.
- reopen-if: kernel op-mix changes materially (any structural accept) — the
  sweep strain re-tests this automatically, so no manual reopen needed.

### G-7 Hard walker-window cap in the model scheduler (harness-side)
- statement: hard-capping concurrent walkers reduces register pressure cheaply.
- evidence: rust harness measured 1356 -> 1795 (cycles) when window became a
  hard gate; pressure relief never paid for the ILP loss. Soft priority kept.
- reopen-if: n/a (kept for the record; harness-side only).

### G-8 Parity-early (H-002)
- statement: cheap early bit0-of-hash chain unblocks next round's gather.
- evidence: chain exists and is optimal (+1 madd, depth 8 vs 10; proof in
  critical-path STATE.md / parity_math), but measured 1145-1198 vs 1140 on
  every subset of rounds: the kernel is valu-throughput-bound (98.2%), so 2
  levels of latency buy nothing while +1 madd/group-round costs ~extra/6 cyc.
  Flag `parity_early` kept in-tree (default off, bit-exact).
- reopen-if: valu busy drops well below ~95% (any H-001/H-003/H-007-class
  accept) — retest is `run_variant --set parity_early=...` (see H-013).

### G-9 Full-round L4 tournament under parity-early (H-008)
- statement: parity-early removes the stall that forced l4_gmin group-split.
- evidence: l4_gmin=(0,0) = 1270; + parity_early(3,) = 1284; + (True) = 1339.
  Root cause is the ~7-dependent-level select chain on saturated valu/flow,
  not parity arrival. Supersedes G-1's reopen-if (tested and still negative).
- reopen-if: valu AND flow both gain >=10% headroom, or the L4 fold chain
  shortens structurally (e.g. H-003 finds a shorter select form).

### G-10 Shorter hash forms via segment fusion search (H-003)
- statement: a <11-op hash (or <12 w/ fold-in, <13 w/ parity) exists.
- evidence: exhaustive per-segment search, ~400B candidates: every adjacent
  cut of the chain at depth current-1, fold-in head 5->4 (130.6B),
  cross-round tail 5->4 (126.3B), parity-from-c <=4 (66.2B) — all negative.
  Searcher self-test rediscovers the known stage2∘3 fusion. NOT a global
  minimality proof (global space ~10^28).
- reopen-if: (UPDATED iter 4: H-016 MITM ran and was negative on all 10
  boundaries — 2.36T+16B nodes, solved meets.) (UPDATED iter 6b: H-025's
  enumerative sub-attempt ran the same MITM machinery against the whole
  hash end-to-end with no waypoint assumption — also negative at
  depth<=7/10, 2.9T+1.03B+2.12B candidates/nodes; CEGIS sub-attempt
  inconclusive, scaling wall at k=4.) Now reopens only via: a working
  CEGIS run (fix the multiply_add bit-blast per P-12), a kf>=3 forward
  prefix run on a much bigger machine (P-7's ~1000x cost, unattempted),
  or HASH_STAGES changing.

### G-11 nv double-buffering (H-014)
- statement: removing the gather->nv WAR edge lets the load engine run ahead.
- evidence: instrumented ListScheduler.ready() decomposition over all 1,936
  gathers: nv hazard binds ZERO loads; counterfactual (nv terms deleted)
  moves zero. Structural: nv's last read is the round's first hash op while
  the gather address st is written ~12 dependency levels later — RAW-on-st
  strictly dominates. Loads are slot-contention-bound (64,440 queue-cycles).
  Robust across pools/skews/l4_gmin/parity_early/no-tournament configs.
- reopen-if: an accepted change makes gaddr available BEFORE round r's nv
  reads complete (impossible under the current address recurrence; the
  H-002 earliness family is itself G-8-closed).

### G-12 Hard madd->vselect first-fold flip (H-017 hard variant)
- statement: unconditionally moving tournament first-folds to flow wins.
- evidence: all 15 level subsets lose (1136-1196 vs 1130). Windowed profile:
  flow idle is ANTI-correlated with fold readiness (66-92% busy in fold
  windows, ~0% in gather stretches); a skew block's 8 groups' folds ready in
  ~2 cycles and serialize on the 1-slot engine. Confirms and sharpens G-4.
- reopen-if: n/a — superseded by the accepted schedule-aware vsel_auto,
  which subsumes every case where the flip helps.

### G-13 Parity speculation via xor-select distribution (H-010)
- statement: select-after-speculated-xors shortens the parity chain at zero
  net valu cost.
- evidence: auto race (trial emission both forms, external state rollback):
  0 cycle delta — speculation wins only where the status quo already used
  zero valu; hard L1/L2/L1+2: +20/+64/+115; valu census UP 17-24 under
  forced variants (alu displacement at 88% busy). Third consecutive
  critical-path rejection (G-8, G-11, G-13) -> strain retired.
- reopen-if: valu AND alu both gain >=8% headroom. Retest hooks kept:
  parity_early, spec_fold flags (one command each, see H-013).

### G-14 sel_race: flow->valu reverse race for 0/1-cond selects (H-019 part)
- statement: letting existing flow vselects fall back to valu when flow is
  locally constrained wins cycles.
- evidence: +1..+3 in every combination at the 1088 base; valu is the
  binding engine so giving it MORE work never pays, even raced. Kept
  in-tree as a negative control flag.
- reopen-if: valu drops below ~90% busy while flow locally saturates
  (e.g. after a large op-removal accept).

### G-15 The madd-diet / engine-rebalancing ceiling (H-004+H-018)
- statement: converting state madds to alu-splittable forms scales to <1000.
- evidence: exchange rate is 1 valu slot : 16 alu lanes (worst in kernel);
  equilibrium caps ~68 conversions = floor ~1050, greedy realizes -2..-5
  (idx_race). Hash kq-madd conversion: +70. Both iter-3 agents converge:
  alu 93.9%, valu 97.5% -- NO remaining rebalancing wins. Route to <1000 is
  lane-op REMOVAL (H-016 MITM fusion, load-side gather elimination) plus
  scheduling-slack harvest (H-021), not engine moves.
- reopen-if: any accept frees >=8% of alu or valu (re-run idx_race/madd_x2
  sweeps then; archived patch has the madd_x2 flag ready).

### G-16 Load-side demand reduction: vload/dedup/L5-tables/pair-gather (H-006)
- statement: gather slot demand can be cut by batching, dedup, or table service.
- evidence: lane-contiguity 0.00% at every gather round (50 seeds);
  within-group duplication = uniform-draw expectation (0.86 dup slots/group
  at L5 down to 0.03 at L10); no scratch-indexed scratch read exists (only
  mem addressing is data-dependent) so scratch tables reach walkers only via
  fold tournaments; L4-full costs +75 TODAY (was +130 pre-racing — wall
  moving but far); L5 exchange rate 2x L4's. Mid-kernel is triple-saturated
  (load/valu/alu ~100% for cycles ~100-950): relieving load by adding valu
  ops inside that window always loses.
- reopen-if: valu frees >=10% mid-kernel (then l4_gmin slides via standing
  sweep, zero new code), or target drops below ~960 (re-cost L5 at
  then-current exchange rates).

### G-17 b3-last final-round fold reversal (H-023)
- statement: reversing the served-L4 fold order shrinks the r15 drain.
- evidence: post-parity chain 17->11 achieved, but r15 empty-valu slots
  66 -> 250 (pure flow) / 113 (raced, +47 valu slots): broadcast-arm
  selects have no 1-op valu spelling and flow is 1-wide. 1084 best vs
  1070. Non-final rounds strictly worse (1112-1134). The drain is
  unreachable by fold restructuring; only a global op-removal accept
  (lower valu floor) shifts the tail left (P-13).
- reopen-if: >=64 scratch words free for leaf-diff tables (then re-cost:
  likely still valu-heavier), or mid-kernel valu <90% with r15 the strict
  binder.

### G-18 Pair-preload of both children + single vselect per level (H-035-pre)
- statement: speculatively load tree[2i+1] and tree[2i+2] a round early so
  the parity resolves each level with ONE vselect instead of a 2^d-1 fold
  tree; stagger the speculative loads across levels to spread load demand.
- evidence (measured at mainline 1038, 9/9 green; agent, 2026-07-27):
  * lane-aligned vselect arms force 2 scalar gathers/walker: 217 served
    group-rounds x 16 = +3,472 load slots vs 176 free schedule-wide and
    ZERO free across cycles 100-950 (load 2/2 for 850 consecutive cycles).
    Load floor 950 -> 2,686 (+1,648) to shed 886 vec-ops (valu floor
    1021 -> ~886). Cheapest slice (25 L4-served group-rounds) is still
    +400 loads -> floor 1,150, and is strictly dominated by lowering
    l4_gmin (plain gather = 8 loads, not 16, for the same 20.8 ops).
  * vload variant IS possible (siblings 2i+1/2i+2 are contiguous -- a gap
    in G-16's walker-to-walker contiguity measurement) at 8 load slots/
    group-round, but lands transposed: +16 alu moves/group-round (=3,472
    vs 575 free alu slots, alu floor -> 1,276) and >=64 CONTIGUOUS free
    scratch words when 3 exist (1533/1536).
  * pipelining half: placement-trace replay shows 1,851 gathers accrue
    47,268 queue-cycles (mean 25.5) and only 13 (0.7%) are placed at their
    dependency-ready cycle -- loads wait for SLOTS, not addresses, so
    earlier address availability moves nothing (confirms G-11 at 1038;
    independently reproduced to the digit by tools/export_dashboard.py).
  * the latency payoff (1 op post-parity) is already realized at zero load
    cost by H-023/H-027's newest-parity-last folds.
- reopen-if: G-3's conditions, sharpened -- load util drops below ~75%
  with free slots INSIDE cycles 100-950, AND >=64 contiguous scratch words
  free (vload variant) or >=256 (scalar variant), AND alu gains >=8%
  headroom for the vload transpose.

### G-19 load_offset gather respelling (H-037)
- claim: ("load_offset", dest, addr, offset) could delete per-lane
  gather-address arithmetic by making the +offset lane indexing free.
- evidence: premise false. In problem.py the load slot's dest/addr operands
  are instruction immediates (literal scratch indices baked in at assembly),
  so load_offset executes bit-for-bit as ("load", dest+offset, addr+offset)
  -- a compile-time alias, not a hardware capability. dev.py's gather loop
  already folds that add in Python at emission. The only runtime ops feeding
  gather addresses are the idx recurrence itself (H-035's region). Measured:
  dev.py flag ON/OFF both 1052, delta exactly 0; full gate green at 1038.
  Flag-gated respelling (gather_load_offset, default OFF) kept in dev.py as
  documentation of the equivalence.
- moral: audit "unused opcode" census hits against the simulator's operand
  semantics before hypothesizing -- immediates vs scratch-indirection decides
  whether an opcode is a capability or an alias.
- reopen-if: never (equivalence is exact, not empirical).

### G-20 Hash re-decomposition / re-derivation space (H-036)
- claim: alternative algebraic DECOMPOSITIONS of myhash (not fusions of the
  current step sequence) could shave ~1.5 ops/hash and close the 892 gap.
- evidence: closed negative at three levels (tools/hash_relation_probe.py,
  340,023 candidates over the 25-node two-round trace DAG; N=64 structured+
  random 32-bit samples as screen).
  * structural: every node of the 11-op DAG costs exactly 1 op, so any shared
    new intermediate serving two nodes costs >=3 ops vs the 2 it replaces --
    subexpression sharing can never win. Op removal requires a globally
    shorter program (H-025 space, closed depth<=7) or a deletable node whose
    consumers re-derive in 1 op -- enumerated completely: 67 hits, all chain
    ops/local inverses/sibling rearrangements, zero long-range coincidences.
  * analytic: xor-conjugation domains transport free through xorshifts but
    are blocked by madd stages for any D!=0 (confines the family to the
    already-closed c5_prexor/xr3p space); affine conjugation is constant
    relabeling already inside solved-constant searches, can't cross ^nv.
  * parity-from-prefix is MOOT: parity already costs 0 ops (H-015 table
    reversal); mid-round val is non-deferrable (feeds next hash exactly).
  * constant-coincidence scan over {C0..C5,ap,aq}: nothing but definitional
    aq=C2<<9; s0 not GF(2)-affine, s1/s5 not Z-affine.
- moral: three independent tool classes (fusion/MITM G-10, CEGIS H-025,
  re-derivation/conjugation here) bottom out at the same boundaries. Stop
  reopening hash op-count; the credible 892 route is idx folding (H-035)
  and load/schedule shape.
- reopen-if: someone exhibits a <11-op two-round-consistent program (e.g.
  leaderboard disclosure), or a compare/select-based branchy form (the one
  stated vocabulary gap) is shown viable, or depth>7 global search becomes
  computationally feasible.

### G-21 Idx-recurrence-into-hash-madd fold (H-035)
- claim: pre-scale/bias the position recurrence p <- 2p+b so existing hash
  multiply_adds carry it for free; Idx 7,448 -> ~1,000 lane-ops, the single
  largest 892-gap lever.
- evidence: REJECTED on algebraic impossibility + budget shortfall.
  * one madd's three operand slots admit only st*2+vl (carries ALL of vl's
    runtime bits, not just parity) or vl*k+f(st) where the only parity-
    isolating multiplier mod 2^32 is k=2^31 -- parks parity at bit31,
    unusable as a mem-address addend; relocating it needs an odd multiple
    of parity from vl in one op, which doesn't exist. Steady-gather floor
    is extract(1)+madd(1)+combine(1) per round; mainline is already there
    (only the combine's engine is negotiable, = P-14).
  * ov==0 escape (forest based at mem[1] frees the +c slot): copying costs
    ~256 vloads+vstores vs ~176 spare load slots; per-level relocation
    overlaps the live forest. Also closes P-10 with a sharper reason.
  * budget: impossible-best-case removes ~1,700-2,000 lane-ops, 4x short
    of the 6,400 the 892 gap needs. NO Idx-only path reaches 892.
- landed anyway (flag-gated OFF, cycle-neutral): idx_boundary_select --
  moves 62 boundary par-combines off alu/valu to flow (-283 alu/valu slots,
  1038->1038, bit-exact). Re-measure composed with idx_select_before_madd
  if a future accept turns the 1030s alu/valu-bound.
- moral: with H-036/G-20 this closes BOTH named 892 levers. Within the
  current program organization (11-op hash x 4,096 + per-round gather), the
  lane-op arithmetic cannot reach 892. The gap explanation must be outside:
  different board/variant, branchy program forms (G-20's vocabulary gap),
  or a structurally different kernel organization.
- reopen-if: a sub-11-op hash appears (G-20 reopen), or an addressing mode
  lands that reads mem[a+b] without materializing a+b.

### G-22 mem_prime generalization beyond L5 + the -116-loads supply side (H-039)
- claim: generalize H-026's primed gather tables to more levels to cut
  Routing lane-ops and load count (the "-116 loads for 892" leg).
- evidence: REJECTED at every configuration. (5,6): best 1039 (+1) even
  with region-exact hazards + dead-reg staging + placement floors;
  (5,6,7): 1044; (5,6,7,8): 1065. Lane-ops DO drop ((5,6): -144) but come
  off slack engines while wave costs displace the critical path. Reverse
  control: dropping (5,) = 1057, so L5 stays load-bearing. MECHANISM
  CORRECTION for H-026's L6 note: the "coarse mem model serializes
  priming into first gathers" explanation is FALSE (priming retires ~59,
  first affected gathers 135/167); the real ledger is (a) compute-
  saturated front (valu 6/6, alu 12/12 from cycle ~9) makes each wave's
  ^C5 displace round compute ~1:1, (b) free load slots exist only in the
  dependency-dead 0-60 front (~90) and the useless drain, (c) elided
  lane-xors sit in the load-bound 135-950 window where compute relief
  shortens nothing. Cost doubles per level, gain constant — crossover is
  already behind L5. Supply side of -116 loads: priming ADDS loads; with
  G-16 (demand), G-18 (speculation), G-21 (relocation) the load-count leg
  is closed inside the current organization (consistent with H-040: 892
  is the no-indices board; select-tree conversion, not fewer loads, is
  the frontier lever).
- landed (default OFF, negative controls): mem_prime_region_hazards,
  mem_prime_dead_reg_staging, mem_prime_min_cycles. The region-hazard
  machinery is reusable if mid-window load slack ever opens.
- byproduct worth keeping: the front 0-60 dependency-dead load window
  (~90 slots) is REACHABLE via dead-reg staging — useful to any future
  hypothesis needing setup-time mem traffic (e.g. H-041 select-tree prep).
- reopen-if: an accept opens load slack inside cycles 100-950, or the
  organization changes so the front is no longer compute-saturated.

### G-23 Gather->select-tree conversion at the current op census (H-041)
- claim: corsix's frontier organization (>280 gathers replaced by select
  trees, valu:load:flow 7.5:2:1 per cycle) could convert here directly.
- evidence: REJECTED at the current census, three independent ways
  (tools/occupancy_hist.py landed; full tables in flow-balance/STATE.md).
  * we ALREADY run his balance in the steady window (valu 6.0/6, alu
    12/12, load 2/2, flow 0.8/1); 666/1038 cycles have all four engines
    full. Cycle floors: valu 1020 (binder), alu 990, load 950, flow 797.
    Friction to the valu floor is only 18 cycles (ramp 4, steady 6,
    drain 8).
  * gathers by level: L4 312 remaining (39 unserved group-rounds), L5-L10
    256 each. Corsix's ">280" ~= our remaining L4 set; every unserved
    group-round is measured negative at our mix (l4_gmin count sweep
    monotone around (9,30); first-ever set-form composition sweep: 14
    alternatives tie or lose).
  * L5 dead 3 ways: scratch (needs 256 words, ~3 free, even one 8-word
    table OOMs), engine arithmetic (31 ops vs 8 loads on a valu-bound
    schedule 70 cyc above the load floor), window (37 load-full-valu-free
    cycles schedule-wide).
- THE JOINT CONDITION (the real finding): conversion activates only below
  ~950 cycles, i.e. AFTER ~400 valu + ~600 alu slots are removed. Corsix's
  levers run in his order — shrink the graph first, THEN convert gathers
  into the freed compute. (b) without (a) loses on every axis. Where his
  ~400-valu-slot reduction comes from is NOT yet explained by anything
  open here (hash closed G-20, idx closed G-21, routing at floor) —
  deep-reading the frontier writeups for the graph-shrink mechanism is
  the successor task (H-043).
- byproducts: epoch-1 served-pair composition is a free plateau
  ({29,31}/{28,31}/{29,30} tie 1038); set-form l4_gmin specs {0,31}/{0,1}
  CRASH (IndexError, the known idx_select/two_minus_fp_vec fallback
  hazard) — future set sweeps must check `correct` per point.
- reopen-if: any accept lands the schedule below ~950-990, or 256+
  scratch words free up, or an op-mix change makes valu no longer the
  binder. The 39 L4 group-rounds reactivate FIRST (15 ops/8 loads, zero
  new scratch — the standing l4_gmin sweep slides there on its own).

### G-24 Compare/select hash vocabulary — THE FINAL HASH-OP-COUNT ENTRY (H-038)
- claim: programs using compares (<, ==) and selects — the one vocabulary
  gap G-10/G-20 left open — might shorten the 11-op hash.
- evidence: closed negative, ~1.586T explicit candidates/nodes
  (fusion_search --cmpsel + tools/hash_cmpsel_probe.py; full per-target
  table in op-reduction STATE.md). 1-op probe 337,548 (0 hits; no trace
  node is 0/1-valued); forward depth-1-shorter 13.84B; depth-4 closures
  1.487T (head3/xr4/u2e/par_c_deep); MITM cmpsel at all 10 segment
  boundaries + full_hash 11->10 with NO waypoint assumption; 3 planted
  positive controls rediscovered. Compares' only appearance: sign-test
  respellings of already-known parity forms (worthless — parity is 0 ops).
- stated uncovered (CPU walls, same class as prior closures): interior
  compare thresholds pool-only; MITM engine-A k=4 cmpsel; kf=3 cmpsel.
- moral: FOUR independent tool classes (fusion/MITM G-10, CEGIS H-025,
  re-derivation G-20, cmpsel here) bottom out identically, and the
  frontier provably runs our exact form (H-043 SVG decode). Hash op-count
  research is DONE. Do not reopen without a leaderboard disclosure of a
  <11-op form or a depth-8+ search breakthrough.
- housekeeping: H-025 iter-12 uncommitted leftovers preserved at
  scratchpad h025_iter12_leftover_uncommitted.diff.

### G-25 The packing/placement axis at the current op stream (H-051)
- claim (user-directed): bounded-backtrack B&B with the floor model as an
  admissible bound could recover cycles the greedy packer loses.
- evidence: tools/backtrack_sched.py — exact op-stream capture (20,562
  ops + full hazard context), precedence DAG whose offline greedy
  reproduces all placements bit-exactly (1031), frozen-grader-verified
  reconstruction path. Provable TWO-SIDED interval bound: 1015 for ANY
  packing of this stream (valu-slot bound 1013, CP 426, energetic 1015).
  ~170k full re-schedules at 19ms each: exhaustive discrepancy-1 (d 1-2)
  over the FULL stream, pairs radius-3 at every regret jump, random
  triples, priority-list variants — best found = greedy's own 1031.
- REGRET PROFILE (the keeper): the 18 cycles over the valu floor are 18
  localized unit jumps: ramp 4 (vbroadcast RAW on setup loads), seam 1
  @538, seam 1 @831, r9-11 EPOCH SEAM 5 (c=913-932, groups 24-31 r9/r10
  hash+fold RAW chains, valu 2/6 while alu 8-12/12 — a mid-stream
  chain-staircase, NEW), drain 7 (cpLB overtakes engine bound at c=1001).
  Blocker weight 96.6/109 empty-valu-slot events are RAW: the frontier
  is not ready, not slot-starved.
- moral: with H-042 (spelling) and iter-4 (order/tie-breaks), all three
  scheduler axes are measured-closed at this op mix. The friction is
  DEPENDENCY STRUCTURE. The r9-11 seam (5 cyc) is an emission-structure
  or chain-shortening target (H-049's axis), not a packing one.
- reopen-if: the op stream changes materially (H-049 order win, H-047
  restructure) — the tool re-measures residual packing slack in ~2 min.

### G-26 Store-vacancy precompute / the engine-floor framing itself (H-053)
- claim (user-directed): the 98%-idle store engine can convert binder
  (valu) work into load work; lead candidate the 59 vbroadcast slots
  (pure movement), predicted -10..-16 floor.
- audit (exhaustive, all 20,565 slots; dev.py emission-site attribution
  + lane-exact global value numbering): only **88 slots (0.43%)
  re-derive an existing value**, and 87 still have the earlier copy
  resident. NO hidden scratch-pressure recompute reservoir (H-045 took
  it). Migratable set = 59 broadcasts + 28 duplicate table diffs.
  Everything else computes on runtime data; memory supplies, not computes.
- measured REJECT, three ways: bcast_via_mem (8 scalar stores + 1 vload,
  staging in the never-graded inp_indices region) costs +4.3 cyc/site
  (1 site 1027, 59 sites 1217); bcast_alu_copies 4 sites 1023 -> 59
  sites 1057; irreducible cost is 8 word-writes per replicated block
  (2 store slots/cyc = 4 cyc/site) since memory has no stride-0 read
  and no transpose.
- **THE DECISIVE RESULT — tools/free_slot_oracle.py (landed).** Route an
  op class to the 64-wide free `debug` engine (edges + 1-cyc latency
  preserved, slot cost zero) = an upper bound on ANY respelling.
  Freeing ALL 7,051 vector ops (alu 11,793->65, valu 6,056->525) gives
  **993 real cycles**. The entire compute census is worth 30 cycles.
  The valu floor (1010) is NOT CAUSAL — the schedule is RAW-bound.
  Marginal value of a valu slot ~0.004 cyc, not 1/6. Freeing all 59
  broadcasts: 1024 (+1, WORSE).
- also: _sched_vec's retire-time race SELF-EQUILIBRATES — freeing valu
  slots RAISES valu and lowers alu (floor 1010->1012, alu 983->961 at
  24 sites). Migrations can be silently undone; re-census after changes.
- also: the CP-bound ramp absorbs floor relief 1:1 (variant with LB 1009
  gained a ramp jump, regret 13->14) — "cycle-neutral but lower floor"
  is NOT automatically a win on this kernel.
- MORAL / METHODOLOGY CHANGE: retire ceil(slots/width) engine floors as
  the scoring frame. Score against the free-compute bound (993) and RAW
  structure. free_slot_oracle is the standing PRE-SCREEN — it would have
  closed H-053 in one run.
- reopen-if: the RAW structure changes materially (chain shortening,
  H-052), which would move the 993 bound itself.

### G-27 The flow prize: bubbles, select-readiness anti-correlation, flowmax (H-054)
- claim (F-17/LP/corsix-derived): ~33-60 cyc are locked behind the
  select-readiness x flow-bubble anti-correlation; breaking it reaches
  the floor-990 stream.
- CLOSED BY RELAXATION, not exhaustion (the strong form):
  * **Infinite-width flow** (tools/h054_width.py — strictly dominates
    EVERY legal flow-side mechanism): width 1/2/4/8 -> 1022/1023/1023/
    1023 while valu falls 6052->5903. Best over 19 order families at
    width 8: 1023. Flow's shadow price is **0 at every width**.
  * **Select free-slot oracle** (G-26 method): freeing all 395
    flow-capable sites -> 1026 (+4); all 1,560 vselects -> 1021 (-1);
    all 1,033 race sites -> 1020 (-2). The entire select class is worth
    **<=2 cycles**.
- burst data (for the record, now moot): flowmax bursts peak backlog 5,
  a 5-deep buffer absorbs all of them; the wait comes from flow's ~560
  non-race baseline ops, not bursts. Only 23/159 flow-lost sites satisfy
  wait<=slack; the rest need ~50 cyc of slack nobody has.
- mechanisms tried, ALL >=1022: flow_race_bias (1026), window-restricted
  bias (zero candidates exist in the bubble-rich windows), bias x budget
  (1024), batch-forcing the 23 feasible sites (1024), cadence de-sync
  over 19 order families x 6 biases (1022 incumbent, bias monotone-
  negative on every family), order re-search on the migrated stream
  (1023/1025).
- **[CORRECTED BY G-28 — the joint number below is max-of-floors, NOT superadditivity; reachable share is ZERO. Read shadow prices against each relaxed machine's own floors.]** per-engine shadow prices (tools/h054_shadow.py):
  flow 0, store 0, alu 12->16/24 = -2/-7, valu 6->8/12 = -6/-8,
  load 2->3 = **-7**. JOINT: valu8+alu16 = -14, alu16+load4 = -48,
  **valu8+load4 = -181 (841 cycles)**, all doubled = 612. Single-resource
  relief is worth 5-8 cycles anywhere; **valu+load relief is wildly
  superadditive**. c100-c800 runs valu 100% AND alu 100% AND load 100%
  simultaneously. The binding structure is an ALTERNATING valu<->load
  chain (vector compute <-> gather addresses), which is why relieving
  either alone does nothing.
- reopen-if: never for the flow axis. The successor is F-20 (find and
  shorten the alternating valu/load chain).

### G-28 Chain shortening + the valu<->load alternation (H-055) -- AND A CORRECTION TO G-27
- **CORRECTION FIRST: G-27's "-181 superadditivity" was a MISREADING.**
  h054_shadow.py's joint number is max-of-floors arithmetic, not a
  synergy. Read against each relaxed machine's OWN floors:
  baseline 6052 valu/11761 alu/1892 load -> floors 1009/981/946, max 1009;
  valu6->8 -> 805/753/**946**, max 946 (re-binds on LOAD);
  load2->4 -> **1008**/989/473, max 1008 (re-binds on VALU);
  valu8+load4 -> 803/788/473, max 803. The two floors sit 63 apart, so
  relieving both drops the max by 206. **Reachable share by chain
  shortening: ZERO.** Standing rule: always read shadow-price output
  against the relaxed machine's own floors (F-23).
- **The ceiling on chain shortening of ANY kind: 3 cycles.** Greedy with
  EVERY RAW/WAW lag set to 0 gives 1017 at the 1020 mainline (1016 at
  1022). Bound stack @1020: realized 1020 / all-lags-zero 1017 / valu
  slot floor 1006 / fungible 1000 / all-compute-free 993 / load floor
  946 / pure CP 541. CP is 541 levels vs 1020 realized = 479 slack.
- chain characterization (tools/h055_chain.py): CP has 719 ops --
  valu 499, flow 115, alu 91, **load 11**, store 3; only 17 valu<->load
  transitions total. The steady per-round chain is 13 levels with exactly
  ONE valu->load->valu handoff; 9 of 13 levels are hash.
- **PAIR-PRELOAD (the user's mechanism) CLOSED, stronger than G-18.**
  tools/h055_preload_oracle.py does DAG surgery at any subset of the 229
  gather sites. Two findings: (a) no memory re-layout is needed at all --
  `base = 2*gaddr+omf` is ALREADY parity-free and already hoisted a full
  round by race_idx_madd, and heap children are contiguous, so
  "deinterleaved left/right" is just `base` and `base+1`; (b) measured at
  1020 with real loads / with loads made FREE: 1 site +5/+3, 2 +9/+2,
  8 +14/+9, 16 +45/+9, 48 +173/+8, 128 +493/+17, all 229 +883/+78 --
  **positive at all 13 subset sizes in BOTH columns.** G-18 rejected it
  on load count; this rejects it with the load cost removed entirely.
  The latency prize is <= 0.
- secondary sites re-diagnosed: the DRAIN is NOT chain-bound (zeroing all
  lags among drain ops gives +0 at 1022, -2 at 1020) -- it is the last
  group's serial r14->r15 hash unable to start earlier because valu is
  saturated. The RAMP's 4 cycles are LOAD BANDWIDTH, not chain (c=0-5 run
  load 2/2 while valu takes 0/1/1/3/6/4; every valu op needs a scratch
  word only the 2-wide load engine can create); floor on that deficit ~2.
- load budget: 152 free load slots schedule-wide, **ZERO across cycles
  85-960** (876 consecutive saturated cycles). Scratch: 3 free; buying 16
  via pool sizes costs +17.
- ENVELOPE: at this op stream the reachable range is 1020 -> 1006 (slot
  floor) / 1000 (fungible). Everything remaining is <= 20 cycles and is
  ORDER/PACKING-shaped -- F-13-style order walks are the right and only
  remaining machine. Below 1006 needs fewer valu slots (hash closed
  G-20/G-24, idx closed G-21); below 993 needs fewer loads (contiguity
  0.00%, G-16). Both legs closed inside this organization.
- reopen-if: a different program organization (not this one's schedule).

### G-29 Emission-order local search at the 1020 mix (F-18) — CLOSED BY ENUMERATION
- claim: F-13's radius finding (+/-8 was a local optimum; +/-16/32 paid)
  should extend to +/-64, +/-128, unbounded, and compound moves.
- evidence: NEGATIVE, ~130k sim-verified evals. Radius <=64: 10,400 zero.
  <=128: 10,400 zero. Unbounded `free`: 21,536 zero. Compound (pairg
  9,533 / comp2 8,126 / block 3,813): 21,472 zero. Positive control from
  1022 reproduced 1022->1021->1020, so the machinery works.
- **EXHAUSTIVE 1-MOVE SCAN (tools/f18_exhaust1.py): every valid single
  displacement of the 1020 plan (each entry to every position in its
  group's feasible interval, radius unbounded by construction) — 26,415
  moves, ZERO below 1020.** Repeated at a plateau point 276/512
  positions away: 26,449 moves, also zero. The 1020 plan is a STRICT
  1-move local optimum at any radius (1023 was only +/-8-local).
- two carry-forward facts: (a) the PLATEAU IS ENORMOUS — 13,464 of
  24,389 correct neighbors (55%) measure exactly 1020, so order walks
  always *look* alive while doing neutral drift; 2,026 moves break
  correctness (ring-borrow windows). (b) RADIUS SATURATES — neutral-or-
  better fraction by displacement: <=8 57%, 9-32 54%, 33-128 56%,
  **>128: 0/38**. F-13's radius effect was real but bought only the
  +/-8 -> +/-32 step.
- compound moves closed by sampling only (2-move space ~7e8), but with
  the whole 1-move neighborhood provably flat-or-worse a 2-move win must
  be a strictly-paired escape, and 9.5k pairg proposals (the move that
  lifts the same-group barrier) found none.
- reopen-if: the MIX changes (orders are mix-specific per F-13's
  cross-application table — a new mix invalidates this artifact and the
  search must be re-run from scratch).

### G-30 Single-move order search + fine round windows at 1006 (F-34/F-35)
- CLOSED BY ENUMERATION, same status G-29 gave 1020: f18_exhaust1 at
  the 1006 plan = **25,550 single-entry moves, ZERO below 1006**
  (plateau 7,487 = 29%; 3,673 = 14% build an INCORRECT kernel). No round
  window, however fine, can pay at 1006 — the whole 1-move neighbourhood
  is enumerated and empty. Further order search must be MULTI-move.
- **Round-window productivity map** (from a common perturbed start,
  1006+18 random moves = 1015, ~1,200 evals/window). Only rounds 12-15
  pay: drain -6, all -6, r:12-13 / r:13-15 / r:14-15 / r:15-15 each -5,
  both -4, r:11-15 -4, r:8-15 -4, r:0-7 -3, r:5-10 -3, r:11-11 -3, and
  **r:0-4 / r:0-0 / mid / ramp = 0**. Round 15 ALONE beats H-057's
  coarser r:11-15. Fine round windows are a REAL axis with nothing to
  bite on at 1006 (63 chains / ~78k evals at the accept points: all flat).
- **F-35 audit-aware loop: two mechanism fixes, 56% recovery, 0 cycles.**
  (1) the mine fixpoint must be GROW-then-PRUNE — grow-only returns a
  plan that is NOT sound at a perturbed order (32 violations/40 rings at
  every dirty order tried; in-loop recovery 0/24 with grow-only).
  (2) only PLAN rings are prunable — a live-across on one of the ~20
  natively derived parity_ring_map rings is a property of the ORDER and
  unrepairable, so those points must be dropped. Fleet: 92 descents,
  34 dirty (37%), 19 recovered in-loop, 15 unrecoverable = ~56% of what
  H-057's discard-and-checkpoint threw away, converted to live walk
  state, for ZERO cycles. Dirtiness is SELECTION not noise: random moves
  off 1006/1007 audit dirty 2.0%/0.4% of the time vs 37% among descents.
  The naive non-basin-anchored loop drifts (1006->1007->1008->1015 in
  120 s) — must branch-and-return around the best clean point.
- 1006 bound stack: LB 995 / energetic 996 / fungible 992 / cp 512 /
  all-lags-zero 1004; regret 11 = ramp 4 + mid 3 + drain 4.
- basin evidence: 0 of 12 perturbed restarts re-found 1006 (best 1008).
- reopen-if: multi-move (see F-37), or any mix/organization change.

### G-31 Multi-move emission-order search (F-37) — ORDER AXIS CLOSED
- claim (from G-30): single moves are provably empty at 1006, so any
  order win must be a paired/tripled escape, and it must live in the
  only productive band (rounds 12-15).
- evidence: 438,247 multi-move evals, ZERO below 1006.
  * plateau in the band: 7,306 single displacements (source round
    12-15, destination unbounded), zero below 1006; 1,641 exactly 1006
    (22.5%) and 541 "slightly worse" (1007-1009) as +1/-2 raw material.
  * k=2 INTERACTING space EXHAUSTED: neutral x neutral 209,311,
    worse x neutral 92,175, worse x worse 25,570, plus the 12,789
    anchor-clash pairs re-run resolved — all >= 1006. The only pairs not
    evaluated are 4,498 whose composite violates per-group round order
    (not valid emission plans at all).
  * k=3 mutually-overlapping triples: 28,591 sampled, zero.
  * disjoint-span pairs: 69,811 sampled (6.4%), zero — and measured NOT
    additive (only 71% stay at 1006), so the overlap split was a
    prioritisation, not a proof.
  * k=4 deliberately not run (k=2 exhausted zero, k=3 flat).
- enabling fix worth keeping: f18's (i,j) reinsertion coordinates DO NOT
  COMPOSE (the second j is measured in a list the first move shifted).
  tools/f37_lib.py re-coordinatises moves as (src, anchor) in base-index
  space, which composes for arbitrary k; verified to reproduce f18's
  25,550 moves bit-for-bit at k=1.
- finding beyond the zero: **the plateau composes freely but never
  crosses** — 154,039 interacting pairs return to exactly 1006,
  including 20,848 where a +1..+3 penalty is fully cancelled by a
  neutral partner and 1,027 worse x worse pairs that cancel each other.
- 1006 bound stack (tools/f37_bounds.py): realized 1006 | LB 995 (valu
  995, alu 981, load 946, flow 797) | energetic 996 | fungible 992 |
  cp 512 | all-lags-zero 1004 | regret 11 = ramp 4 + mid 3 + drain 4.
- reopen-if: a different mix or organization (both closed by their own
  artifacts) — i.e. only if some OTHER axis moves first.

### G-32 Packing axis re-tested at the 1006 stream (F-39) — G-25 HOLDS
- justification for the re-open: G-25 closed packing at the 1031 stream,
  which no longer exists (organization, ring plan, gmin and order all
  changed since). Three prior stale closures had flipped sign under
  regime change (G-22->H-047, the convergence call->H-056, the phantom
  LB-992 prize->F-24), so this was the one untested closure.
- model still exact: capture 20,462 ops (was 20,562), `validate` reports
  exact_match true / 0 mismatches — offline greedy reproduces every
  captured placement; frozen-grader reconstruction verifies 1006 correct
  on 6 seeds. The constraint model did not drift with the organization.
- **386,090 full re-schedules, best = 1006** (i.e. greedy): priority-list
  variants 4 (best 1024, reverse-emission); exhaustive discrepancy-1 over
  the ENTIRE stream at d in {1,2} = 40,924 and d in {3,5,8} = 61,386;
  discrepancy-2 pairs at radius 3 around ALL 11 regret jumps, all
  engines = 283,780. k=3 deliberately not sampled (exhaustive disc-1 and
  exhaustive pairs-at-every-jump both empty).
- bounds at 1006: engine LB 995 / CP 512 / staircase 996-995 /
  **energetic interval LB 996** / fungible 992. **Open window 10**
  (was 16 at 1031) — a tighter negative than the original.
- regret 11 = ramp 4 (c=0,1,3,7) + mid 3 (c=805,864,915) + drain 4
  (c=978,984,993,997). The r9-11 epoch-seam CLUSTER is gone (replaced by
  3 isolated unit jumps) and drain fell 7 -> 4. **In the drain, cpLB
  strictly exceeds engLB from c=978 — those cycles are provably LATENCY,
  not packing.**
- verdict: all three scheduler axes (order G-30/G-31, spelling
  H-042/F-25, packing here) are measured-closed at the 1006 mix for the
  SECOND regime running. The residual 11 is chain structure; only chain
  shortening (capped at 2 by all-lags-zero = 1004) or a mix change moves.

### G-33 Scratch/parallelism trade (H-059) — AND THE "SCRATCH IS THE CONSTRAINT" FRAMING
- claim (Phase-2 charter): we hold 32 groups live and spend 1,533/1,536
  scratch words doing it, while valu runs 5.93/6 — so parallelism past
  engine saturation is wasted and fewer live groups should free hundreds
  of words at little cost.
- **BOTH HALVES OF THE PREMISE ARE FALSE.**
- group liveness is an EMISSION-PLAN property: a diagonal with
  lag(g+W) >= lag(g)+rounds keeps W groups live. Flag-gated
  `group_window=W` landed (default 0, bit-identical at {absent,0,32}).
  Words freed = exactly (32-W)*24, at ~0.1 cyc/word (9x cheaper than
  H-053's pool route) — but EVERY point loses:
  W=32 1006 | W=24 1045 (full chain) | W=20 1064 | W=16 1097 |
  W=12 1136 | W=8 1307 | W=4 2031.
- **MECHANISM (the real finding): the valu floor RISES as liveness falls**
  (1008 -> 1010 -> 1018) while the alu floor FALLS (993 -> 962 -> 933)
  at constant ~60.3k lane-ops. Fewer live groups => fewer independent ops
  at each `_sched_vec` decision => alu_offload wins fewer races => work
  concentrates on the 6-wide BINDER instead of the 12-wide slack engine.
  **The 5.93/6 valu occupancy was never spare ILP — it is what FUNDS the
  offload.** At W=24 the design's own slot floor (1010) already exceeds
  mainline's REALIZED 1006.
- freed scratch buys NOTHING, closed by relaxation not search:
  * temp pool INFINITE -> 1007; cond=32 -> 1009; both -> 1007 (up to
    2,429 words). Never below 1006 at any size.
  * complete non-borrowed parity rings (all 64, private words) deletes
    162 lane-ops and lands EXACTLY 1006 — the 40 borrowed rings already
    capture the mechanism's entire value. Falsifies H-058's ~7-cycle
    cond-retention estimate at the shipped stream.
  * select trees at L4/L5/L6 = **+30/+61/+94 with scratch FREE**. L5's
    254 extra words are real but were never the binding reason; L4 needs
    FEWER words than today and still loses. Discharges G-23's
    "reopen if 256+ words free" clause independently of H-058.
  * whole flag space at unbounded scratch: neutral-or-worse everywhere.
  * flow export does not compose (40 configs return unbiased greedy at
    BOTH streams) — G-27 confirmed on a second mix.
- **METHODOLOGY: stop citing the scratch budget as a constraint.** Three
  separate closures (H-041's L5 tables, H-045/H-048's ring starvation,
  H-053's pool purchase) were all STATED in scratch terms and are all
  actually VALU-SLOT statements. tools/h059_shadow.py is the pre-screen.
- caveat recorded: newest_parity_last_leaf_diff_tables' round-15
  dead-register pool assumes 32-group liveness and clobbers aliased
  registers; with it off, aliasing is correct at every W.
- reopen-if: the alu/valu assignment stops depending on live-group count
  (i.e. H-060's static partition works).

### G-34 Load-bound regret / regret-0 load saturation (H-061) — H-058's SURVIVOR IS CLOSED
- claim (the last of H-058's four branches): 940 is reachable if a
  scheduler realizes a load-100% stream at regret ~0 where ours measures
  ~70.
- **PROVED IMPOSSIBLE, with a new bound.** 2-D energetic argument valid
  for ANY packing: M >= t + k + ceil(#{est>=t, h>=k}/2). It evaluates to
  **naive load floor + 31 on every stream** (946->977, 986->1017,
  1002->1033, 1034->1065), and the free-compute oracle hits it within 2.
  So the ~70 decomposes as **31 provable ramp/drain + a constant 39 of
  compute contention** delaying addresses past their dependency-est.
  Neither term is a load-SCHEDULING term.
- **940 requires <= 1,758 steady-state loads; we issue 1,831.** The
  frontier is NOT scheduling ~1,880 loads at zero regret — under this
  served-levels structure that is arithmetically impossible.
- attribution: binding-edge census over all 1,892 loads = **raw 1,883,
  floor 9, ZERO WAR / WAW / mem edges**. 70% of blocking producers are
  the valu idx-recurrence multiply_add. **The load engine is a strict
  slave of valu.** Load idles in exactly two places: head [29..64] = 70
  slots and drain [958..1005] = 48; cycles **65-957 are 2/2 saturated
  for 893 consecutive cycles**. In every head-bubble cycle valu is 6/6
  AND alu is 12/12 — 100% compute-saturated, idle-but-blocked, with only
  9 of 1,892 loads address-independent, i.e. nothing could fill it.
- root of the head: the est-critical chain into the FIRST gather is 52
  ops spanning rounds 0-3 = four consecutive hash evaluations, BECAUSE
  levels 0-3 are served by selection rather than gathered. 1,831 of
  1,892 loads inherit that release date (t=51).
- fixes attempted, ALL EXACTLY ZERO (each an unsound upper bound, so the
  zeros are conclusive): deleting BOTH coarse mem clocks entirely
  (identical on all five streams); dropping every mem_prime gather-gate
  min_cycle (identical); offline load-issue priorities (none beat
  greedy-in-emission-order); prefetch distance (dependency-limited by
  construction — the first gather is already placed at wait 0).
  Context: 3-wide load hardware would buy 3 cycles at mainline.
- corrected stack at mainline: cp 512 / load 946->**977** / alu 981 /
  **valu 995** -> 1006, regret 11. Load is provably NOT the binder.
- **RULED IN (successor H-062):** lower t=51 by GATHERING instead of
  serving at levels 0-3 for the group-rounds that execute in the head
  bubble — converting compute into loads exactly where 70 load slots and
  ZERO compute slots are free. Opposite of the steady-state trade.
  Bounded <= 35 cycles gross.

### G-35 The "idle engine" hypothesis class (H-063) — RETIRED AS A GENERATOR
- three directions, all rejected:
  * **A. bulk-vload the shallow tables: ALREADY THE SHIPPED CODE.**
    dev.py:2146-2152 fetches the level-1..4 tree words (30 contiguous
    heap words) with 4 vloads at cycles 6-9, one flow add_imm each, no
    address arithmetic. Table construction is 59 ops, ALL retired by
    cycle 14 — the load bubble does not open until cycle 31, and cycles
    31-64 are 100% steady-state group-round work. Freeing all 78
    table-construction ops = **0**; freeing EVERY valu op in the head
    bubble = **0**; only the entire 252-op setup phase together = -13.
    **The ramp is a CHAIN, not slot pressure.** The residue is lane
    replication, which memory cannot do: 8 WAW-serialised vstores +
    1 vload = 9 cycles vs 1 valu slot for vbroadcast (executed, not
    asserted). And nothing can move IN: only 108 of 1,892 loads have
    est < 65 against 130 head slots, so 42 head load slots are unusable
    by ANY scheduler — every load needs an address, and address
    computation is the compute already saturating the window.
  * **B. "X +/- b between two live constants" sites: census complete,
    exactly THREE exist** (via reaching definitions, not addresses —
    an address-keyed pass gives ~3x false positives because st/nv are
    both position accumulator and raw parity). (1) steady gather-mode,
    ALREADY converted by H-029 (166 sites, both arms live); (2)
    epoch-exit, needs materialised arms, +9; (3) dead under c5_prexor.
    Fold family re-priced at SCRATCH_SIZE=1e6: auto_fold (1,)/(1,2,3)/()
    = +18/+23/+28; L4 pairs 0/4/6/8 = +10/+3/+21/+31. The shipped
    (1,2) x 3 pairs is a STRICT INTERIOR OPTIMUM in both directions.
  * **C. drain: cpLB > engLB at EVERY cycle 975-1005**, by ~2.5x in the
    last eleven. Nothing is deferrable in — deferral needs terminal
    work, and the only terminal work is the 32 result vstores, already
    at their ready cycles with 0-1 slack.
- **UNIFYING FINDING: the three "free" resources are unspendable for one
  reason — 99.6% of this op stream COMPUTES new values, while the idle
  capacity sits on engines that can only MOVE data.** Four independent
  closures of the same shape: flow (G-27), store (H-053/G-26), head
  load, drain load. **"Engine X is idle" is retired as a hypothesis
  generator on this kernel.**
- primitive catalogue (validated by execution on frozen_problem.Machine):
  P1 arbitrary 8-element permute = 8 scalar `store` + 1 vload (8 store
  slots + 1 load slot + 8 address regs); P2 lane rotation by k = 1-2
  vstore + 1 vload, 2 cyc latency; P3 8x8 transpose = 8 vstore + 8 vload
  (8 store + 8 load slots, zero compute). P3 does NOT rescue the
  sibling-pair vload (16 load slots vs 8, dead by G-34). The scalar
  `store` opcode remains entirely unused by the kernel.
- successor ruled in: **H-064 — attack the setup ramp as a 13-cycle
  CHAIN** (the only setup-side number that is not zero).

### G-36 Planned alu/valu partition vs the retire race (H-060)
- WEAK ACCEPT (-1) but NOT SHIPPABLE; axis closed.
- race-margin census (4,357 offloadable sites): 1,024 force_alu, 2,882
  valu-free (alu never priced), only **451 actually race** (10.4%).
  ~38% of race outcomes flip under a 1-cycle perturbation — fragile
  exactly as H-059 predicted. **The real degree of freedom is not the
  races**: at 2,427 of the 2,882 valu-free sites the alu spelling would
  have retired on the SAME cycle (+314 within 1), and that reservoir
  measures worth <= 0.
- sizing correction: the exchange rate is 8 alu slots per valu slot, so
  the floors equalize at **17 migrated sites (992/992)**, not 84 — only
  3 cycles of floor were ever available.
- sweep: 0 of 60 policy configs beat 1006. Bind walks 995 -> 990 while
  realized goes 1006 -> 1012 — **third independent confirmation that a
  lower engine floor is not a win on this kernel**.
- 0 improving single flips out of 4,357: the race's assignment is an
  exact local optimum. A neutral-plateau walk reached 1005 (7 seeds +
  debug_compares, ring audit OK/40, LB 992) but it must pin ALL 4,357
  sites (a 256-site sparse plan re-drifts to 1009 — G-26
  self-equilibration measured directly) and it is ORDER-COUPLED: +5
  median over 150 r12-15 order moves, winning only 16/150. It cannot
  enter the chain (ring re-mine at fixpoint, l4_gmin pinned by ring
  literals, order already optimal).
- **G-33's reopen-if DISCHARGED**: the partition DOES decouple the valu
  floor from liveness (drift +22 under the race -> flat/-6 at K<=4), but
  the cycle curve is unchanged (K=16: 1025/1053/1104 vs race
  1028/1053/1103). H-059's cost was never the floor — it is RAW/chain
  structure.

### G-37 The setup ramp as a shortenable chain (H-064) — LAST LEVER, ZERO
- **The premise was a CONTAMINATED MEASUREMENT.** H-063's "-13 for
  freeing the whole setup phase" came from tools/h063_oracle.py, which
  frees ops by rerouting them to the `debug` engine INSIDE A LIVE DEV
  BUILD. dev's adaptive engine races (alu_offload, idx/flow races) read
  scheduler occupancy, so the freed build emits a DIFFERENT PROGRAM:
  alu 11,600 vs the 11,696 a pure relaxation gives (96 fewer alu ops),
  flow 782 vs 775. Of its 13 cycles, 5 are bundles that became
  debug-only (cycles 0-3 and 997, which do not count) and ~8 are floor
  relief (valu 995->982) — exactly what G-36 retired.
- **CLEAN relaxation (program held fixed; tools/h064_oracle.py, offline
  greedy asserted place == real place every run): the ceiling is 2
  cycles**, and it is physically unreachable —
  const(c0) -> load ptr(c1) -> vload(c2) -> readable(c3).
  all 268 setup ops slot-free = 1004; + pinned to cycle 0 = 1004;
  + every setup->consumer edge lag 0 = 1004.
- the chain, named: every setup op has **slack >= 494** (cp 512). Three
  chains: est-critical prefix (#0 const(4) -> #9 dc_eight -> #15/#16
  dc_k0 -> #25 vbroadcast k0 -> #269 first hash madd); the 48-op `va`
  chain (four +32 chains, depth 8); the `lv` chain (one lv_addr
  register, WAR-serialized on the 1-wide flow engine).
- **the ramp's 4 cycles are the 24 free valu slots in cycles 0-7 — a
  DATA-ARRIVAL property, not chain depth.** No steady op can run before
  c3, and >=10 of the 24 are unfillable by any program on this ISA.
  Load is 2/2 across cycles 0-30 carrying all 60 setup loads.
- restructurings (realized, ring-free base 1026): va chain depth 8->2
  = exactly 0; parallel lv addresses on alu = +4; direct k0 const
  (est-chain 5->2) = +2; flow_residual_consts +3; flow_consts +5;
  derive_consts=False +6; vals_first +5; emit_order 0. Head capacity
  relaxations are ALL POSITIVE (+8..+14). **1006 is a razor-thin greedy
  optimum, same shape as G-32.**
- **H-062 DEAD**: only 29 L1-L3 group-rounds have min-est < 65, so the
  conversion costs 232 loads against 68 free head load slots (+82 cycles
  in the 893-cycle 2/2-saturated region), while freeing EVERY op in
  [31,65) measures only -3.
- **METHODOLOGY (the transferable lesson): a relaxation oracle must hold
  the PROGRAM fixed.** Freeing ops inside a build whose scheduler makes
  adaptive engine choices changes the program, and the resulting number
  measures the new program, not the relaxation. Always assert
  `offline place == real place` after freeing (h064_oracle does).
