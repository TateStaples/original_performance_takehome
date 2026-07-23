# Strain: critical-path

## Charter
Shorten the dependency chain that stalls the load stream and the skew
pipeline: parity/idx is the only value the next round's gather needs, yet it
waits on the full 12-op hash today. Owns code regions: hash emission block,
state-update block, gather prefetch logic in emit_group_round.

## Frontier
mainline 1140 @ b68a302 (no strain-specific flags yet).

## Assigned
- H-002 (iter 1): parity-early (cheap bit0-of-hash chain).
Queued: H-008 (full L4/L5, blocked on H-002), H-010 (parity speculation).

## Iteration log
(append-only)

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
