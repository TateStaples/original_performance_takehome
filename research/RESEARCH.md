# Kernel Research Loop — Dashboard

**Goal:** grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1107 | (iter-2) | `tournament_levels=(1,2,3), alu_offload=True, parity_conds=True, vsel_auto=(1,2,3), pool_sizes=(16,3), l4_gmin=(20,29)` |

## Floors (calibrated 2026-07-23, see tools/diagnose_kernel.py)

- Op-mix floor: valu still binding: 6439 slots / 6 = ~1073 cycle-equivalents
  at 1107 actual (34 cyc scheduling slack). flow 58.3%, alu 87.6%, load 89.6%.
- Scratch: 1519/1536 -- 17 words FREE (first headroom since iter 0).
- Flow-offload ceiling: floor -> ~962 if routing/idx arithmetic moves to flow (29.6% used)
- Load floor: 1,936 gathers / 2 per cyc = 968 (load 87.4% busy)
- Hash-only absolute floor: 49,152 lane-ops / 60 per cyc = 819
- Scratch: 1535/1536 words used at pool_sizes=(17,4); 32 words freeable at
  ZERO cycle cost via pool_sizes=(17,3) (H-002 side finding, verified 1140).

## Strain roster

| strain | charter | status |
|---|---|---|
| flow-balance | exploit idle flow engine + load-side tricks | active (iter 2: H-017) |
| critical-path | gather-path latency/buffering plays | NEARLY TAPPED: G-8/G-9/G-11 all measured-dead; only H-010 live; rotate next dry iter |
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

- iter 2 (in flight) | H-014 REJECTED (0 nv-bound gathers) -> G-11; H-017 vsel_auto ACCEPTED 1107 (-23), hard flip -> G-12, dispatch flipped; H-015 still running; re-sweep negative | best 1107
