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
