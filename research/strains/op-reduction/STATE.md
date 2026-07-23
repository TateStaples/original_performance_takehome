# Strain: op-reduction

## Charter
Reduce total lane-ops by algebra/search: hash is 49,152 ops (69% of all
work; floor 819 if nothing else existed), Idx is 8,592. Every op removed
per eval is ~68 cycles. Owns code regions: rust_harness/src/problem.rs
(searcher), the fused-hash constants block in perf_takehome.py.

## Frontier
mainline 1140 @ b68a302 (no strain-specific flags yet).

## Assigned
- H-003 (iter 1): machine-search for fusions beyond the 11-op form
  (incl. fold-in xor and parity extraction in the searched expression).
Queued: H-004 (fold p:=2p+b away), H-012 (floor recalibration).

## Iteration log
(append-only)

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)
