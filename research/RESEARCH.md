# Kernel Research Loop — Dashboard

**Goal:** grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1070 | (iter-3) | `tournament_levels=(1,2,3), alu_offload=True, parity_conds=True, c5_prexor=True, vsel_auto=(1,2), u_race=True, l4_race=3, idx_race=True, pool_sizes=(16,4), l4_gmin=(13,28)` |

## Floors (calibrated 2026-07-23, see tools/diagnose_kernel.py)

- Op-mix floor: valu 6262 slots / 6 = ~1044 cycle-equivalents at 1070 actual
  (26 cyc slack). alu 93.9% (near-saturated!), flow 61.9%, load 89.8%.
  BOTH compute engines converging: placement racing at ceiling; remaining
  route to <1000 = lane-op REMOVAL (valu toward <6000) + slack harvest.
- Flow-offload ceiling: floor -> ~962 if routing/idx arithmetic moves to flow (29.6% used)
- Load floor: 1,936 gathers / 2 per cyc = 968 (load 87.4% busy)
- Hash-only absolute floor: 49,152 lane-ops / 60 per cyc = 819
- Scratch: 1535/1536 words used at pool_sizes=(17,4); 32 words freeable at
  ZERO cycle cost via pool_sizes=(17,3) (H-002 side finding, verified 1140).

## Strain roster

| strain | charter | status |
|---|---|---|
| flow-balance | exploit idle flow engine + load-side tricks | active (iter 2: H-017) |
| scheduler | close the actual-vs-valu-floor gap (26 cyc friction) | NEW (rotated in iter 3; critical-path RETIRED: G-8/G-11/G-13) |
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
