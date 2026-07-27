# Kernel Research Loop — Dashboard

**Goal:** grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1038 | 3174858 | H-031 mem-hazard fix + H-030 tie-break + H-029 idx_select on the 1053 stack |

## Floors (recalibrated 2026-07-27 at 1038, see tools/diagnose_kernel.py + tools/export_dashboard.py)

- **Total compute floor: 60,841 alu+valu lane-ops / 60 per cyc = 1,015.**
  We are 23 cycles above it — scheduling slack is nearly exhausted; only op
  REMOVAL moves the number. Purpose split (lane-ops): Hash 46,656 / Idx
  7,448 / Routing 6,249 / Setup 488.
- Per-engine: valu 6,125/6 = 1,021 (binding, 98.3% util); alu 11,841/12 =
  987; load 1,900/2 = 950 (2/2 for 850 consecutive cycles in 100-950,
  176 free slots all in setup+drain, structurally unreachable).
- Hash floors: alu 10,584/12 = **882 (hash-internal binding engine)**; valu
  4,509/6 = 752; combined 46,656/60 = 778 (was 819 — hash shed 2,496
  lane-ops since 2026-07-23). Within the hash, alu binds; globally, valu
  binds. Rebalancing prize between them = 104 cyc, but both squeeze.
- Latency is NOT the wall: dependency-only span (no slot limits) = 439
  cycles vs 1,038 actual. Gathers wait mean 25.5 cyc for SLOTS, not
  addresses (13/1,851 placed at dep-ready).
- Scratch: 1533/1536 words used (3 free).
- **Leaderboard RESOLVED (H-040, 2026-07-27, see strains/cross/STATE.md):
  892 sits on the relaxed "Without Indices" board (paired entries show the
  no-idx relief is only 9-23 cyc); under OUR exact rules the public
  frontier is 940 (@josusanmartin), then 958/981/994/1002. Same problem,
  same VM, same params — no rule difference to hunt. Our 1038 appears on
  both boards.**
- **The 1,015 "floor" is an ARTIFACT: it holds the gather count fixed.**
  Corsix (971/994, corsix.org/content/anthropics-compiler-challenge):
  >280 gathers can be replaced by selection trees over preloaded node
  values, then valu:load:flow balanced to 7.5:2:1 in every individual
  cycle — instruction selection and scheduling as ONE joint search.
  Austin Wallace (austinwallace.ca/kernel): beam search over bundle
  packing beats greedy. G-20/G-21 (hash + idx closures) remain correct;
  the op MIX, not the op count of the current mix, is the frontier lever.
  Realistic target under our rules: ~940.

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
- iter 6 | CROSS-POLLINATION: H-026/H-027/H-028 ACCEPTED composed (-11) -> 1053; each ~0 alone. Valu floor ~1035. H-025 CEGIS still running — the remaining op-removal lever | best 1053
- iters 7-11 (logged in commits only, catch-up): H-029 idx_select ACCEPTED -> 1043; H-030 tie-break ACCEPTED -> 1041; H-031 mem-hazard fix ACCEPTED -> 1038; H-025 closed after 11 sub-iterations (kf<=3 closed all 6 segments, kf=4 CPU wall); H-033 rejected; H-034/P-16/H-007-followup negative ports | best 1038
- iter 12 (in flight, loop restart off 892-leaderboard analysis) | spawned H-035 (idx-fold-into-madd), H-036 (hash re-decomposition), H-037 (load_offset); sweep phase-5 restarted at base 1038. H-037 CLOSED NEGATIVE -> G-19: load_offset is a compile-time alias of load (operands are immediates; +offset folds at assembly) — premise false, delta exactly 0; census should not list it as an opportunity. Path to -116 loads: mem_prime generalization (H-026) or collision-sharing (repays itself in vselects) | best 1038
- iter 12 | H-036 CLOSED NEGATIVE -> G-20: re-derivation probe (340,023 candidates, 2-round trace DAG) found zero long-range coincidences; structural proof sharing can never win (every DAG node already costs 1 op); xor/affine conjugation domains analytically closed; parity-from-prefix moot (already 0 ops). Hash op-count now closed by 3 independent tool classes (MITM, CEGIS, re-derivation) — STOP reopening; 892 route must be H-035 idx folding + load/schedule shape. H-035 still running | best 1038
- iter 12 CLOSED | H-035 REJECTED -> G-21 (fold algebraically impossible: parity-isolating multiplier is only 2^31; steady floor extract+madd+combine already reached; best case 4x short of 892 gap; idx_boundary_select landed flag-gated OFF, cycle-neutral, frees 283 alu/valu slots). Tally: 3 investigations, 3 high-value negatives (G-19/G-20/G-21), mainline 1038 unchanged. STRATEGIC RESULT: G-20+G-21 close BOTH internal 892 levers — the lane-op arithmetic cannot reach 892 in the current program organization. Iter 13 queued: H-038 (compare/select hash vocabulary, the one sanctioned reopening), H-039 (mem_prime generalization, only path to -116 loads), H-040 (characterize 892 externally). Sweep phase-5: 119+ configs, 0 winners | best 1038
- iter 13 | H-040 CLOSED ANSWERED: 892 = no-indices board + different organization; same-rules frontier 940; the 1,015 floor is a fixed-gather-count artifact. Loop redirected: H-041 select-tree gather conversion + per-cycle engine-mix balance (corsix: >280 gathers convertible, valu:load:flow 7.5:2:1), H-042 beam-search bundle packing (wallace: beats greedy). H-038/H-039 still running | best 1038
- iter 13 | H-041 REJECTED -> G-23 (we ALREADY run the frontier's 7.5:2:1 balance — steady window co-saturated, valu binder floor 1020, friction only 18; L4 at equilibrium on count AND composition axes; L5 dead 3 ways; conversion activates only below ~950 after ~400 valu/~600 alu removal). MODE CHANGE (user directive): ALGO-FIRST under idealized machine (infinite scratch + perfect allocation) — fitting/allocation PARKED (H-042 parked); new algo strain: H-043 (frontier writeup mechanism extraction), H-044 (ideal-machine cost model + serving-strategy solve) | best 1038
- iter 14 | H-044 CLOSED ANSWERED: ideal-floor LP (tools/ideal_floor.py, validated) — best serving mix under infinite scratch = 931.6 (serve L1-L3 + 31/64 L4, prime L4/L5/L6, 918 flow selects, conds retained from parity vectors); 940 NEEDS ZERO NEW ALGEBRA, but is UNREACHABLE with the as-built mix by any compute removal (load floor 951 binds). Gap: 1038 -24-> 1014 -63-> 951 -20-> 932. Marginal rate at optimum ~97 lane-ops/cyc; loads live again (G-22 verdict was mix-relative). H-045 re-scoped to the full flow-saturation build and spawned | best 1038
- iter 14 | H-043 CLOSED ANSWERED: frontier hash IS our 11-op form (corsix SVGs decoded — all onset closures CONFIRMED); the gap mechanism is valu->flow select EXPORT (exits the 60-lane-op budget, ideal ~988) + select-tree/load rebalance via joint selection x scheduling. G-22/G-18 flagged with scope holes under algo-first (friction-based rejections, op removal real). Queued: H-045 flow-maximization (ideal -50), H-046 idealized priming reopen, H-047 L5+ select trees (940 provably requires a level off the load engine: 2x940=1,880 < 1,900 loads). H-044 (ideal model) + H-038 still running | best 1038
- iter 13 | H-039 REJECTED -> G-22 (mem_prime crossover already behind L5: lane-ops drop -144 but off slack engines, waves displace the critical path; corrects H-026 mechanism note; -116-loads supply side has NO mechanism — load-count leg fully closed inside current organization; byproduct: front 0-60 load window reachable via dead-reg staging). H-041 spawned (select-tree gather conversion, the frontier's named lever). H-038 still running | best 1038
