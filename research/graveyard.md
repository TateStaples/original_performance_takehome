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
- reopen-if: H-016 (MITM 6->5) finds a hit, or HASH_STAGES changes, or a
  non-adjacent/algebraic (non-compositional) identity is conjectured.

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
