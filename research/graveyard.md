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
