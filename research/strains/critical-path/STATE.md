# Strain: critical-path

## Charter
Shorten the dependency chain that stalls the load stream and the skew
pipeline: parity/idx is the only value the next round's gather needs, yet it
waits on the full 12-op hash today. Owns code regions: hash emission block,
state-update block, gather prefetch logic in emit_group_round.

## Frontier
mainline 1088 (flags: tournament_levels=(1,2,3), alu_offload=True,
parity_conds=True, c5_prexor=True, vsel_auto=(1,2), pool_sizes=(17,4),
l4_gmin=(15,29), skew=(4,3)). No strain flag improves on it; `parity_early`
and `spec_fold` exist as correct, flag-gated negatives (see log). STRAIN
CLOSED after iter 3 (H-010 measured zero/negative — see the closure
recommendation P-cp-6 below).

## Assigned
- H-002 (iter 1): parity-early (cheap bit0-of-hash chain). DONE: rejected.
- H-014 (iter 2): nv double-buffering. DONE: closed negative by direct
  measurement — the nv WAR/WAW edge binds ZERO of 1936 gather loads (see
  log); no kernel change made (none can win).
- H-010 (iter 3): parity speculation under zero-net-valu. DONE: rejected
  (honest zero at best; every forced form negative; see log). Flag
  `spec_fold` kept in-tree, default off, default bit-identical.
H-008 re-closed with H-002 (see log).

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

- iter 3 / H-010 parity speculation (zero-net-valu): REJECTED — honest
  zero at best, negative in every forced form. Flag `spec_fold` landed
  (default off, default BIT-IDENTICAL — verified instr-stream equality vs
  d145f99; grader 9/9 at 1088).
  Design (per the brief): xor distributes over select, so the fold-in
    vl ^ select(b, O, E) == select(b, vl^O, vl^E);
  the level's candidates are pre-xored into vl both ways (force-alu
  elementwise xors) and the parity-dependent select runs LAST on flow,
  feeding the first hash madd directly — per-site valu delta <= 0 by
  construction, chain shorter by 1 level. Sites built: L1 (2 xors + 1
  vselect), L2 (4 xors + 3 vselects; b0-copy + p-fold unchanged).
  MEASURED (mainline 1088; run_variant, all correct=true):
    hard L1 (spec_fold=1)         1108  (+20)
    hard L2 (spec_fold=2)         1152  (+64)
    hard L1+L2 (spec_fold=(1,2))  1203  (+115)
    auto race, tie->A             1088  (0)   B wins 1/64 sites
    auto race, tie->B ("auto")    1088  (0)   B wins 2/64 sites
    auto:1 (B may pay 1 cyc)      1092  (+4)
    auto:2                        1094  (+6)
  ("auto" = per-site trial emission of both forms with scheduler-state
  snapshot/rollback, keeping whichever completes vl earlier — the same
  hard-flip-vs-race pattern as G-12 -> H-017, but here the race says the
  status quo is already pointwise optimal at 62-63 of 64 L1 sites.)
  VALU-SLOT PROOF (slot census, default vs variants):
    default  valu 6365 (97.5%)  alu 11497  flow 558
    auto     valu 6365 (=)      alu 11513  flow 558   -> at the 2 sites B
      won, path A was ALREADY zero-valu (dual_fold had picked flow, the
      fold-in xor had picked alu): there were no valu slots left to shed.
    hard L1  valu 6382 (UP 17)  alu 11848  flow 560   -> the forced-alu
      speculated xors displace other alu-raced elementwise ops back onto
      valu; global valu INCREASES despite per-site zero-net-valu.
    auto:1   valu 6389 (UP 24)  — same displacement, plus 4 lost cycles.
  Root cause (sharpens G-8/G-12 into a general principle): under
  alu_offload + vsel_auto racing, every fold/fold-in op at the shallow
  tournament sites is already placed on the cheapest engine per cycle;
  speculation can only ADD net ops (+1 xor per site), and at 97.5% valu /
  88% alu there is no absorbing slack — the marginal alu op cascades back
  into valu. The -1 dependency level is worthless: only 1-2 of 64 sites
  are even locally latency-bound, and committing B there moves global
  cycles by zero.
  Reopen-if: valu AND alu both gain >=8% headroom (then the +1 xor is
  genuinely free and the level shortening could bite near skew
  boundaries); retest is one command per mode (spec_fold=1 / "auto").

## Proposed hypotheses
(agent appends; driver promotes to backlog.md)

- P-cp-1: valu-pressure-first. This strain's latency lever is dead while
  valu is the binding engine; re-run `parity_early` (one command) after any
  accepted valu-offload/op-reduction change (H-003/H-007/H-001). Suggest
  the driver add pe combos to the sweep grid so this re-test is free.
  RE-CHECKED 2026-07-23 after H-029/idx_select (a valu-relief accept,
  -78 valu slots at the flag level): NOT a one-command re-test anymore.
  `build_kernel_scheduled` has an explicit `assert not pe_levels,
  "c5_prexor is incompatible with parity_early"` (perf_takehome.py:932) —
  parity_early and c5_prexor cannot coexist as currently implemented, and
  c5_prexor is a load-bearing accepted stack (H-015). Testing parity_early
  standalone (c5_prexor=False, mem_prime=()) would compare against a
  worse, non-mainline baseline and answer the wrong question. Reopening
  this needs someone to reconcile parity_early's bit-extraction scheme
  with c5_prexor's own domain-shifted parity bookkeeping first — real
  engineering, not a flag flip. Downgrading from "one command" to a
  scoped sub-task; still worth doing if op-reduction lands a bigger
  valu-relief accept later (H-025), since the payoff compounds.
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
- P-cp-6 (iter 3, STRAIN CLOSURE per P-cp-5 and the rotation policy):
  H-010 was the strain's last live idea and it measured zero/negative
  (three consecutive measured rejections: G-8, G-11, H-010). RECOMMEND:
  close/rotate the strain. Driver actions: (a) add a graveyard entry for
  H-010 — suggested text: "G-13 Parity speculation at shallow tournament
  folds (H-010): vl^select(b,O,E)==select(b,vl^O,vl^E) landed as
  `spec_fold` (hard / auto-raced / tolerance modes); ALL >= 1088 — hard
  L1 1108, L2 1152, both 1203, auto 1088 (B locally wins 2/64 sites),
  auto:1 1092. Slot census: global valu goes UP in every forced form (the
  +1 speculated xor displaces alu-offloaded ops back onto valu at 88% alu
  busy). Reopen-if: valu AND alu both gain >=8% headroom."; (b) the
  strain's standing latency-retest hooks remain H-013's one-command
  re-runs (parity_early, spec_fold) after any future valu-relief accept —
  no dedicated agent needed; (c) reallocate this strain's iteration slot
  to flow-balance (H-018/H-019 attack the same 1073-floor slack from the
  slot-count side, which iter 3 confirms is the only live currency).
