# Strain: critical-path

## Charter
Shorten the dependency chain that stalls the load stream and the skew
pipeline: parity/idx is the only value the next round's gather needs, yet it
waits on the full 12-op hash today. Owns code regions: hash emission block,
state-update block, gather prefetch logic in emit_group_round.

## Frontier
mainline 1130 (flags: tournament_levels=(1,2,3), alu_offload=True,
l4_gmin=(22,28), pool_sizes=(17,4), skew=(4,3), parity_conds=True). No
strain flag improves on it; `parity_early` exists as a correct, flag-gated
negative (see log). The 32 free words (pool_sizes=(17,3)) remain unspent —
this strain has no use for them (H-014 closed); hand them to H-006.

## Assigned
- H-002 (iter 1): parity-early (cheap bit0-of-hash chain). DONE: rejected.
- H-014 (iter 2): nv double-buffering. DONE: closed negative by direct
  measurement — the nv WAR/WAW edge binds ZERO of 1936 gather loads (see
  log); no kernel change made (none can win).
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

- iter 2 / H-014 nv double-buffering: CLOSED NEGATIVE (measurement-only; no
  kernel change made — none can win). Method: instrumented
  ListScheduler.emit to decompose every scalar gather load's ready() into
  its constraint components: c_raw = last_write[st+lane]+1 (address RAW),
  c_nv = max(last_write[nv+lane]+1, last_read[nv+lane]) (the WAW/WAR edge a
  double-buffer would remove), c_mem; then compared real placement against
  the counterfactual placement with the nv terms deleted.
  MEASURED (default 1130 config, debug_compares both True and False): of
  1936 gather loads (count audited: 176 @ r4 g<22 + 6x256 @ r5..r10 + 224 @
  r15 g<28), the nv hazard exceeds the address RAW for ZERO loads; the
  no-nv counterfactual moves ZERO loads earlier. Double-buffering cannot
  change a single placement — the default schedule IS the double-buffered
  schedule.
  Root cause is structural, not scheduling luck: nv's last read in round r
  is the hash's opening `val ^= nv` xor at depth 0 of the round (the debug
  vcompare lands no later — 64 debug slots/cyc), while the gather address
  st+lane is written only after the full hash + parity + gaddr conversion,
  ~12 dependency levels later. RAW-on-st strictly dominates WAR-on-nv for
  every gather, always, in every round shape (tournament exit, gather
  chain, L4 split).
  Robustness (nv-binding = 0 in ALL of): pool_sizes=(17,3); skew (4,2),
  (8,2), (8,1); l4_gmin=(0,0) (1536 gathers) and (32,32) (2048);
  parity_early=True (nv hosts the parity word and is read LATE by the >>31
  — still zero, since st is written later still); tournament_levels=()
  (3584 gathers).
  Second layer of the same negative: gathers are placed on average ~33 cyc
  AFTER their ready cycle (64,440 total slot-contention delay cycles over
  1936 loads; 1932/1936 contention-delayed) — the load engine runs a deep
  backlog of already-ready loads, so even a few cycles of WAR excess would
  vanish under the queue. Address earliness is ABUNDANT on the gather path;
  only load-slot DEMAND reduction can help the load engine now.
  Verification: default untouched (zero diffs to perf_takehome.py, so
  bit-identity is trivial); grader 9/9 at 1130. Reproduce: methodology
  above, script kept at scratchpad/measure_nv_war.py (iter-2 session).
  Reopen-if: an accepted change makes the gather address available BEFORE
  round r's nv consumers finish reading nv — i.e. gaddr computed from
  something earlier than round r's full hash (the H-002 family, itself
  closed G-8). Under the current address recurrence that inversion is
  impossible; treat H-014 as permanently closed unless the recurrence
  changes structurally.

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
- P-cp-4 (iter 2, supersedes P-cp-2): the 32 free words have NO load-side
  buffering use (H-014: the nv WAR edge never binds; addresses carry ~33
  cyc of average slack into a contention queue). Redirect the freed-words
  budget to H-006's vload-batch (fewer load SLOTS, the only load-engine
  lever left) — first measure how often a group's 8 gather addresses are
  contiguous/coincident; the same instrumentation hook works.
- P-cp-5 (strain redirect): with G-8, G-9 and H-014 all measured, every
  earliness/latency/buffering play on the gather path is dead: the gather
  stream is bounded ONLY by address RAW (already ~33 cyc slack) + load-slot
  supply, and the kernel overall by valu throughput (~1106 cyc-equiv floor
  at 1130). Critical-path's only live idea is H-010 under the zero-net-valu
  constraint; otherwise the strain should stay dormant until another strain
  lands a valu-relief accept (then re-run the G-8 flag per H-013).
