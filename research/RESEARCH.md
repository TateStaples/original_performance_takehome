# Kernel Research Loop — Dashboard

**Goal:** grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1064 | (iter-5) | prev + `derive_consts=True, alu_val_addrs=True` |

## Floors (calibrated 2026-07-23, see tools/diagnose_kernel.py)

- Op-mix floor: valu 6262/6 = ~1044 cyc-equiv at 1070 actual. CRITICAL
  (H-006 profile): cycles ~100-950 are TRIPLE-saturated (load+valu+alu
  ~100%); aggregate slack (alu 93.9%, load 89.8%) is setup/drain artifact.
  Only PROPORTIONAL multi-engine op removal (hash: valu+alu together) moves
  the middle; scheduling slack lives in the ~120-cycle drain tail.
- Flow-offload ceiling: floor -> ~962 if routing/idx arithmetic moves to flow (29.6% used)
- Load floor: 1,936 gathers / 2 per cyc = 968 (load 87.4% busy)
- Hash-only absolute floor: 49,152 lane-ops / 60 per cyc = 819
- Scratch: 1535/1536 words used at pool_sizes=(17,4); 32 words freeable at
  ZERO cycle cost via pool_sizes=(17,3) (H-002 side finding, verified 1140).

## Strain roster

| strain | charter | status |
|---|---|---|
| flow-balance | exploit idle flow engine + load-side tricks | active (iter 2: H-017) |
| scheduler | (retired iter 4: charter measured-complete -- the 26-cyc gap is latency/throughput-bound, not order-fixable; successors H-023/H-024) | RETIRED |
| op-reduction | fewer lane-ops via algebra (hash fusions, idx folds) | active (iter 2: H-015) |
| sweep | pure-compute parameter grid (no LLM) | active (background, H-005) |

Retirement: 3 consecutive dry iterations -> retire, promote from backlog/graveyard (reopen-if satisfied).
Global: 6 dry iterations -> one cross-pollination iteration. Status report to user every ~5 iterations.

## Iteration log

(one line per iteration: `iter N | H-ids tested | results | best after`)

- iter 1 (in flight) | H-005 sweep: 978 configs, 0 < 1140, params exhausted (phases 1+2). H-002 parity-early: REJECTED (chain exists, depth 8 vs 10, but valu-throughput-bound; 1145-1198) -> G-8; H-008 tested under enabler: REJECTED (1270+) -> G-9; side finding +32 scratch words free via (17,3). H-003 fusion search: CLOSED negative (~400B candidates, no shorter form) -> G-10, byproducts 2-op parity + C5-commute -> H-015 (mainline candidate, -45..-60 predicted) + H-016. H-001 parity_conds: ACCEPTED 1130 (-10), mainline flipped, alu 94.6->87.0. ITERATION 1 CLOSED: 1 accept, 3 high-value negatives (G-8/G-9/G-10), 2 new mainline candidates queued (H-015, H-017) | best 1130

## Milestones

- 2026-07-23: loop initialized at 1140 (commit b68a302). Target 1000.
- 2026-07-23: iter 1 -> 1130 (H-001 parity_conds). First loop accept.
- 2026-07-23: iter 2 -> 1107 (H-017 vsel_auto). Crossed 1111 (the old op-mix floor).
- 2026-07-23: iter 2 close -> 1088 (H-015 c5_prexor composed). 88 to target.

- iter 2 CLOSED | H-014 REJECTED (0 nv-bound gathers) -> G-11; H-017 vsel_auto ACCEPTED (-23) -> 1107, hard flip -> G-12; H-015 c5_prexor ACCEPTED composed (-19) -> 1088 (driver fixed vsel_auto arm-order interaction + composed retune: va=(1,2), gmin=(15,29)); re-sweep negative | best 1088
- iter 3 (in flight) | sweep phase 3: vsel_auto=(1,3) accepted (-1) -> 1087; H-019/H-004+18/H-010 agents running | best 1087
- iter 3 | H-010 honest zero -> G-13; critical-path RETIRED, scheduler strain rotated in (H-021). H-019, H-004+18 still running | best 1087
- iter 3 | H-019 emit_any ACCEPTED 1070 (-17); sel_race -> G-14; alu 93.9% (racing ceiling reached). H-004+18 agent still running | best 1070
- iter 3 CLOSED | accepts: H-019 emit_any (-17) + sweep va13 (-1); H-010 -> G-13 (strain rotated); H-004+18 -> G-15 (rebalancing exhausted; code subsumed by idx_race). Best 1140->1070 in 3 iterations. Route to <1000: op REMOVAL (H-016) + slack harvest (H-021) + endgame load-side (H-006) | best 1070
- iter 4 (in flight) | sweep phase 4: 0/493 below 1070 (optimum sharp); H-016/H-021/H-006 agents running | best 1070
- iter 4 | H-006 CLOSED permanently -> G-16 (0% contiguity, no scratch-indexed reads, L4-full +75, triple-saturated middle). H-016/H-021 still running | best 1070
- iter 4 | H-021 honest zero, friction mapped (13 drain latency + 9 setup load + 4 seams), strain retired with successors H-023/H-024; H-016 MITM still running | best 1070
- iter 4 CLOSED | H-016 MITM comprehensive negative (2.36T candidates; fusion dead at every cut; G-10 hardened); iter-4 tally: 4 investigations, 4 high-value negatives, mainline 1070 unchanged. Iter 5 in flight: H-023 drain fix, H-024 setup ramp; H-025 (CEGIS) queued | best 1070
- iter 5 (in flight) | H-024 ACCEPTED 1064 (-6): setup consts on alu + va addrs off flow; H-023 drain fix still running | best 1064
- iter 5 CLOSED | H-024 ACCEPTED (-6) -> 1064; H-023 REJECTED -> G-17 (drain unreachable by restructure). Iter 6: cross-pollination + H-025 CEGIS | best 1064
