# Strain: flow-balance

## Charter
Move work off the saturated valu/alu engines (98.2%/94.6%) onto the 30%-idle
flow engine and the load/store slack; exploit placement freedom the current
kernel leaves unused. Owns code regions: tournament select/cond blocks in
emit_group_round, ListScheduler placement policy.

## Frontier
mainline 1140 @ b68a302 (no strain-specific flags yet).

## Assigned
- H-001 (iter 1): parity-vector conds — kill cond-extraction masks.
Queued: H-007 (schedule-aware fold placement), H-006 (load-side), H-009, H-011.

## Iteration log
(append-only)

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
