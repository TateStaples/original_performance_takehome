# Kernel Research Loop — Dashboard

**Goal:** grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1140 | b68a302 | `build_kernel_scheduled(tournament_levels=(1,2,3), alu_offload=True, l4_gmin=(22,28), pool_sizes=(17,4), skew=(4,3))` |

## Floors (calibrated 2026-07-23, see tools/diagnose_kernel.py)

- Op-mix floor of current design: ~1111 (alu+valu saturated: valu 98.2%, alu 94.6%)
- Flow-offload ceiling: floor -> ~962 if routing/idx arithmetic moves to flow (29.6% used)
- Load floor: 1,936 gathers / 2 per cyc = 968 (load 87.4% busy)
- Hash-only absolute floor: 49,152 lane-ops / 60 per cyc = 819
- Scratch: 1535/1536 words used — NO headroom; new state must be traded, not added.

## Strain roster

| strain | charter | status |
|---|---|---|
| flow-balance | exploit idle flow engine + load-side tricks | active (iter 1: H-001) |
| critical-path | cut the dependency chain stalling the load stream | active (iter 1: H-002) |
| op-reduction | fewer lane-ops via algebra (hash fusions, idx folds) | active (iter 1: H-003) |
| sweep | pure-compute parameter grid (no LLM) | active (background, H-005) |

Retirement: 3 consecutive dry iterations -> retire, promote from backlog/graveyard (reopen-if satisfied).
Global: 6 dry iterations -> one cross-pollination iteration. Status report to user every ~5 iterations.

## Iteration log

(one line per iteration: `iter N | H-ids tested | results | best after`)

- iter 1 (in flight) | H-001 flow-balance, H-002 critical-path, H-003 op-reduction (agents running); H-005 sweep phase 1 DONE: 0/150 beat 1140 (defaults locally optimal), phase 2 running | best 1140

## Milestones

- 2026-07-23: loop initialized at 1140 (commit b68a302). Target 1000.
