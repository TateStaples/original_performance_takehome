# Strain: critical-path

## Charter
Shorten the dependency chain that stalls the load stream and the skew
pipeline: parity/idx is the only value the next round's gather needs, yet it
waits on the full 12-op hash today. Owns code regions: hash emission block,
state-update block, gather prefetch logic in emit_group_round.

## Frontier
mainline 1140 (flags: tournament_levels=(1,2,3), alu_offload=True,
l4_gmin=(22,28), pool_sizes=(17,4), skew=(4,3)). No strain flag improves on
it; `parity_early` exists as a correct, flag-gated negative (see log).

## Assigned
- H-002 (iter 1): parity-early (cheap bit0-of-hash chain). DONE: rejected.
Queued: H-010 (parity speculation). H-008 re-closed with H-002 (see log).

## Iteration log
(append-only)

- iter 1 / H-002 parity-early: REJECTED for cycles; math LANDED as flag.
  Derivation (verified bit-exact, 200k samples + in-kernel debug_compares):
  parity = bit31(c*Km + Cm), Km=k4*(2^31+2^15), Cm=C4*(2^31+2^15)+(C5&1)<<31,
  where c is the pre-stage-4 hash value; carry-free at bit31 because below
  it only the d<<15 addend is nonzero. Gives clean 0/1 parity via one madd
  (parallel with stage-4) + >>31 at DEPTH 8 vs 10 today. The +1 valu madd is
  irreducible: (a) bit16(d) needs exact low-17 carries of c = p^q (xor of
  two madds, non-affine), so any parity chain shares hash ops 1-8; (b) the
  carry-free bit31 construction forces an even multiplier, so m can't
  replace the stage-4 madd (non-invertible). No shorter/cheaper chain exists
  under this ISA; the only question was whether -2 latency levels beat +1
  valu op. MEASURED: no, everywhere. Kernel is valu-THROUGHPUT-bound (98.2%):
  each applied group-round costs ~1/6 cyc, earliness reclaims ~0.
    default 1140 (bit-exact) | pe=True 1198 | (0,)1150 (1,)1152 (2,)1152
    (3,)1149 (9,)1145 (4..9)1168 -- cost tracks madds/6 at every subset.
  H-008 (G-1 reopen, full L4): l4_gmin=(0,0) alone 1270; +pe(3,) 1284;
  +pe(True) 1339. Parity-early does NOT remove the L4 stall: the select
  chain after st is ~7 dependent levels on saturated valu/flow; 2 levels of
  parity earliness is immaterial. G-1 stays closed; H-008 re-closed.
  Skew tightening: (4,2) 1191 alone, 1215/1195/1191 with pe -- no help.
  SIDE FINDING (free scratch!): pool_sizes=(17,3) == 1140 exactly -- one
  cond-pool slot (32 words) is FREE at the current shape. Scratch was the
  blocker for G-3/H-006; 32 words are now available. (Control: (13,4) costs
  +12, so trade cond slots, not t1 slots.)
  Reopen-if for pe: valu drops well below ~95% busy (e.g. H-007 moves folds
  to flow, or H-003 shortens the hash) -- then +1 madd is cheap and the
  2-level earliness may pay; the flag is ready to re-measure in one run.

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)

- P-cp-1: valu-pressure-first. This strain's latency lever is dead while
  valu is the binding engine; re-run `parity_early` (one command) after any
  accepted valu-offload/op-reduction change (H-003/H-007/H-001). Suggest
  the driver add pe combos to the sweep grid so this re-test is free.
- P-cp-2: spend the 32 freed words (pool_sizes=(17,3)) on load-side state:
  e.g. a 4-vector nv double-buffer ring for the deepest gather levels to
  decouple round r+1's gather writes from round r's nv reads (removes the
  WAR chain load->xor->load), or hand them to H-006's vload-batch checks.
- P-cp-3 (H-010 refinement): parity speculation at levels 0..2 only --
  compute both children's fold contributions and select late. Note from
  this iter: it must ADD ZERO net valu ops to pay; design the select as a
  reuse of the existing tournament madd, not an extra one.
