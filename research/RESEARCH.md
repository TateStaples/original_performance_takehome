# Kernel Research Loop — Dashboard

**Goal (PHASE 2, user-directed 2026-07-28): a fundamentally different kernel DESIGN targeting the 940-class frontier.** Phase 1 converged at 1006 with every axis closed (see graveyard G-16..G-32); tuning the current design is done. Phase 2 asks what a sub-940 kernel must look like STRUCTURALLY, then builds it. Phase-1 goal kept for reference: grader-verified `CYCLES: < 1000` (`python tests/submission_tests.py`, all 9 tests green).
**Loop:** autonomous, indefinite (no auto-stop). Driver checklist: `research/LOOP.md`.

## Current best (mainline)

| cycles | commit | config |
|---|---|---|
| 1006 | F-33 port | H-057: F-24 non-uniform-diagonal organization + re-mined 20-ring plan + l4_gmin(6,31) + round-window-walked order; ring audit clean over 40 rings, bundle stream bit-identical to dev |

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
- iter 14 | H-045 PARTIAL ACCEPT: parity_ring cond retention (dead-window cross-block register borrowing, 480w at zero net alloc) + gmin slide -> strain frontier 1034 (-4), first win since restart; superadditive slices confirm the coupled prize; blockers: 384 more ring words for full retention (mid-schedule fully live), flow leg needs joint scheduling (H-042 re-scope) not spelling. F-1 mainline port spawned | best 1038 (frontier 1034)
- iter 29 (PHASE 2, TERMINAL) | H-064 ZERO -> G-37, and it invalidates its own premise: H-063's -13 was a CONTAMINATED measurement (freeing ops inside a live dev build changes the program, because the scheduler's engine races read occupancy — 96 fewer alu ops emitted; 5 of the 13 cycles were debug-only bundles and ~8 was floor relief). Clean relaxation with the program held fixed: **the setup ceiling is 2 cycles and is physically unreachable** (const c0 -> load ptr c1 -> vload c2 -> readable c3). Every setup op has slack >= 494. The ramp's 4 cycles are the 24 free valu slots in cycles 0-7 — a DATA-ARRIVAL property, not depth. All eight restructurings >= 0; head capacity relaxations all POSITIVE. H-062 dead (29 eligible group-rounds, 232 loads against 68 free slots). **LOOP FINISHED AT 1006.** | best 1006
- iter 28 (PHASE 2) | H-063 REJECTED -> G-35 and H-060 WEAK-ACCEPT-BUT-CLOSED -> G-36. H-063: the bulk-vload idea was ALREADY THE SHIPPED CODE (dev.py:2146-2152, 4 vloads at cycles 6-9); table construction retires by cycle 14 while the bubble opens at 31; freeing ALL table construction = 0, freeing every head-bubble valu op = 0, only the whole 252-op setup = -13 (the ramp is a CHAIN); only 108 of 1,892 loads have est<65 so 42 head slots are unusable by ANY scheduler; exactly THREE "X+/-b" sites exist and the shipped fold config is a strict interior optimum; the drain is cpLB>engLB at every cycle. **UNIFYING: 99.6% of the stream COMPUTES while every idle engine only MOVES — four closures of one shape; "engine X is idle" RETIRED as a generator.** H-060: only 451 of 4,357 sites actually race, the race is an exact local optimum (0 improving flips), a full plan reaches 1005 but must pin all 4,357, re-drifts at 256, and is order-coupled (+5 median) so it cannot enter the chain; bind 995->990 gave realized 1006->1012 — third confirmation a lower floor is not a win. Primitives catalogued (P1 permute 8 store+1 load, P2 rotation, P3 transpose 8+8). Successor: H-064, the ramp as a 13-cycle chain | best 1006
- iter 27 (PHASE 2) | H-061 CLOSED -> G-34, and it CLOSES H-058's SURVIVOR. New 2-D energetic bound (valid for any packing) = naive load floor + 31 on every stream, so the ~70 load-bound regret is 31 provable ramp/drain + 39 compute contention — NEITHER is a load-scheduling term. **940 requires <=1,758 steady loads; we issue 1,831 — arithmetically impossible under this served-levels structure, so the frontier is NOT scheduling ~1,880 loads at zero regret.** Attribution: all 1,892 loads are RAW-gated (zero WAR/WAW/mem), 70% by the valu idx madd — the load engine is a strict slave of valu; cycles 65-957 are 2/2 saturated for 893 consecutive cycles; the two idle windows are 100% compute-saturated. Every fix measured EXACTLY zero, including deleting both coarse mem clocks outright. Corrected stack: load 946->977, valu 995 binds. RULED IN: H-062, invert the serving decision in the head bubble | best 1006
- iter 26 (PHASE 2) | H-058 + H-059 both closed. H-058: **H-044's 931.6 was WRONG by ~80 cyc** (double-subtracted gather-address combines + dropped Setup); the algorithm's joint floor is 960.8/962.7 by two independent models; honest target ~960 floor / ~975 realized; latency is not the wall (K>=11 suffices, we run 32); **for 940 exactly one of four things must hold and three are closed — the survivor is a scheduler realizing a load-100% stream at regret ~0 where ours measures ~70**. H-059 REJECTED -> G-33: group liveness is an emission-plan property; EVERY W<32 loses (W=24 1045, W=16 1097) because **the valu floor RISES as liveness falls — the 5.93/6 occupancy was never spare ILP, it is what funds the alu_offload race**; freed scratch buys nothing at any size (pools infinite -> 1007, full private rings -> exactly 1006, select trees +30/+61/+94 with scratch FREE). METHODOLOGY: three closures previously stated in SCRATCH terms are actually VALU-SLOT statements | best 1006
- iter 25 | F-39 NEGATIVE -> G-32: the PACKING closure HOLDS on the 1006 stream (the one closure never re-measured after the regime change). 386,090 full re-schedules — exhaustive discrepancy-1 over the entire stream at five delay values, exhaustive discrepancy-2 pairs at all 11 regret jumps, priority-list variants — best is greedy's own 1006. Model still bit-exact (20,462 ops, 0 mismatches). Open window 10 (was 16 at 1031), energetic LB 996. Drain cycles are provably LATENCY (cpLB > engLB from c=978). **LOOP CONVERGED AT 1006**: order (G-30/G-31, enumerated k=1 and k=2), spelling (5 derivations, empty), packing (G-32), organization (~82k screened), hash (4 tool classes), idx (G-21), loads (G-16/18/22/28), flow (G-27), op-migration (G-26), chain (G-28, cap 2 at this stream) — all closed with evidence. Residual 11 = ramp 4 + mid 3 + drain 4, of which only ~2 are chain-shaped
- iter 24 | F-37 NEGATIVE -> G-31, ORDER AXIS CLOSED: 438,247 multi-move evals, zero below 1006. k=2 INTERACTING space EXHAUSTED in the only productive band (rounds 12-15), k=3 sampled flat, disjoint pairs sampled flat and measured non-additive. The plateau composes freely but never crosses (154,039 interacting pairs return to exactly 1006, incl. 20,848 penalty-cancelling and 1,027 worse-x-worse cancellations). Enabling fix: f18's (i,j) coordinates do not compose; f37_lib re-coordinatises to (src, anchor) base-index space. Bound stack at 1006: LB 995 / energetic 996 / fungible 992 / cp 512 / all-lags-zero 1004 / regret 11 (ramp 4 + mid 3 + drain 4)
- iter 23 | F-34/F-35 NEGATIVE on cycles -> G-30, but CLOSES the single-move order axis at 1006 by enumeration (25,550 moves, zero below; 29% plateau, 14% incorrect). ROUND-WINDOW MAP: only rounds 12-15 pay (drain/all -6, r:15-15 alone -5 beating H-057's coarser r:11-15 -4; r:0-4/ramp/mid = 0). Audit-aware loop: two real mechanism fixes (mine fixpoint must be GROW-then-PRUNE; only PLAN rings are prunable, native ring violations are order properties) recovering 56% of discarded descents — for ZERO cycles. Dirtiness is SELECTION not noise (37% among descents vs 2% among random moves). Only live order axis left: F-37, multi-move (k=2..4) confined to rounds 12-15 | best 1006
- iter 22 | F-33 MAINLINE FLIPPED -> 1006. Port proved BIT-IDENTICAL to dev's stream (1006 bundles, same scratch_next_addr 1533); ring audit clean over 40 rings re-run against the SHIPPED literals (read back out of the file and re-resolved against the live scratch map, not the searched config); 10 seeds green with value-trace compares on. Porter trap recorded: root_nv (scalar, addr 6) vs root_nv_vec (broadcast vector, addr 40)
- iter 22 | H-057 ACCEPTED -> frontier 1006 (-5), F-33 port dispatched. The F-25 chain (re-mine rings -> re-slide gmin -> re-walk) REPRODUCED on a different organization: -5 on F-24's diagonal, -7 on the second — **the CHAIN is the lever, not the diagonal**. NEW AXIS: **ROUND windows beat position windows** — position windows plateaued at 1010 over 62k evals/10 chains, every step below came from r:11-15 or drain. **Ring soundness is SEARCH-SHAPING**: ~half of walked orders invalidate their own plan and the DIRTY points are the FASTER ones; re-mining costs 1-3 but re-conditions the stream (1010 clean -> 1008 dirty -> re-mine -> 1007 dirty -> re-mine -> 1006 clean); always re-mine FROM EMPTY. ORGANIZATION SEARCH CLOSED (~82k screened, zero below greedy 1019); greedy ranking INVERTS under the chain, so walk more than the top candidate. Spelling empty for the fifth time | best 1006
- iter 21 | F-24 TIE at 1011 by an independent organization (8 blocks of 4, NON-UNIFORM lags (0,3,6,6,10,10,13,14) — every H-056 candidate had used lags=s*b). **CORRECTS H-056: the LB-992 prize DOES NOT EXIST** — the energetic staircase bound for those streams is 1011 (gmin>=16 lowers the slot floor while RAISING the release staircase); screen on max(lb_total, energetic) from now on. Also: GREEDY CYCLES predict walk outcome better than LB (LB-996 streams walk to 1019; greedy-1019 streams walk to 1011), and a measure is 20x cheaper than an LB screen -> rank on greedy, LB-screen survivors (29,296 organizations in 28 min). The two 1011s are NOT additive as tested. Successor H-057: run F-25's full ring/gmin/order chain on F-24's diagonal, and continue the diagonal search (still descending when budget ran out) | best 1011
- iter 20 | F-25 ACCEPTED -> frontier 1011 (-4) and F-29 MAINLINE FLIPPED -> 1011, ALSO FIXING A SOUNDNESS DEFECT. **Ring plans are ORDER-SPECIFIC**: borrow windows are timed against the emission order, so H-056's organization change invalidated the carried H-048 4-ring plan — the driver confirmed the 1015 mainline reported 16 LIVE-ACROSS violations over 24 rings (donors st9/st11 of ring (0,6)) while still measuring correct on every seed (grader does not catch it). That plan was worth ZERO cycles there. Re-mined 23-ring plan at the new order audits CLEAN (0 violations / 43 rings), driver-verified 1011 on TEN seeds; ported bundle stream bit-identical to dev's. STANDING RULE: after any order/organization change, re-mine + re-audit the ring plan; never carry one across orders. How the predicted ~6 converted: 4, by a DIFFERENT mechanism — op deletion at a 1-move optimum with a 68% plateau converts at ZERO; the chain was rings -> floor (LB 1003->998) -> floor funds the serving slide (-1) -> changed stream reopens the order landscape (-3). f18_exhaust1 clean at both 1015 (25,637 moves) and 1011 (25,641). Spelling re-derived = EMPTY at this organization | best 1011
- iter 20 | H-056 ACCEPTED -> 1015 (-5), MAINLINE FLIPPED. **THE CONVERGENCE CALL WAS WRONG and the reopen was right: the mainline organization was one of the WORST points in the space by lower bound** (even4/stag3/block LB 1013 vs even8/stag2/zip LB 1001 vs even16/stag1/zip LB 996). 28,316 candidates screened across 3 ring regimes (ranking identical -> not a ring artifact). Three monotone findings: ZIP (group-granular wave interleave) beats BLOCK at every partition/stagger by 2-9 LB cyc; finer partitions on tighter staggers lower LB; the mechanism is the VALU CENSUS (6076->5971) because emission order decides alu-vs-valu race outcomes. **F-13's "orders are mix-specific" has an exact converse: MIXES ARE ORDER-SPECIFIC, and the organization is the coarse handle.** Order descent was ~30x faster on the low-LB stream (2.5k evals for 1028->1020 vs F-13's 213k for 1034->1020) — a lower-LB stream is a better-conditioned landscape. Zero code changes (organization is expressible through emission_plan alone). LB 992 and 996 streams EXIST and are barely walked. G-28's "everything left is <=20 and order/packing-shaped" is SUPERSEDED — the organization axis moves the FLOOR | best 1015
- iter 19 | F-18 NEGATIVE -> G-29, order axis CLOSED BY ENUMERATION: exhaustive 1-move scan (26,415 moves, radius unbounded by construction) finds ZERO below 1020; repeat at a far plateau point also zero. The 1020 plan is a STRICT 1-move local optimum. Radius saturates (>128 displacement: 0/38 neutral-or-better). Plateau is 55% neutral — order walks always LOOK alive. **CONVERGENCE: every axis at this program organization is now closed with evidence** (hash G-10/G-20/G-24, idx G-21, loads G-16/G-18/G-22/G-28, packing G-25, spelling+flow G-27, op-migration G-26, chain G-28 (cap 3), order G-29, serve-more H-047). Envelope 1020 -> 1006. Next: H-056 re-opens the ORGANIZATION itself (skew/block/epoch/grouping) with per-candidate order re-search — every prior organization experiment predates the current order regime, exactly the pattern that made H-047 pay
- iter 19 | H-055 CLOSED NEGATIVE -> G-28, WITH A CORRECTION: G-27's "-181 superadditivity" was a MISREADING of max-of-floors (valu relief re-binds on the load floor and vice versa; the floors sit 63 apart). **Chain shortening of ANY kind is capped at 3 cycles** (all-lags-zero = 1017 at the 1020 mainline). Pair-preload closed harder than G-18: it needs NO memory re-layout (base is already parity-free and hoisted; children are contiguous) and is POSITIVE at all 13 subset sizes even with loads made FREE. Drain is NOT chain-bound (valu saturation); ramp is LOAD BANDWIDTH not chain. ENVELOPE: 1020 -> 1006 (slot floor) / 1000 (fungible); everything left is <=20 cyc and order/packing-shaped -- order walks are the only remaining machine at this organization | best 1020
- iter 18 | F-13 ACCEPTED -> 1020 (-2), MAINLINE FLIPPED (driver-ported literal swap; 9/9 green twice). KEY: the axis was JUMP RADIUS, not restart seed — H-049's +/-8 move set was a local optimum (0 wins over 62k evals re-running it); +/-16/+/-32 descended. 213k sim-verified evals. Orders are MIX-SPECIFIC (measured: F-13 order on H-049 mix = 1027, H-047 order on H-049 mix = 1027) — the plan toolchain must be re-run per candidate mix. New regret at 1020: LB 1006, CP 541, regret 14 = ramp 4 + mid/seam 6 + drain 4; the gain came entirely from the mid/seam band. Ramp and drain UNMOVED under 213k evals — chain-bound, H-055's territory. F-18 queued: radius escalation (+/-64/128, compound moves) untested
- iter 18 | H-054 REJECTED -> G-27, closed BY RELAXATION not exhaustion: INFINITE-WIDTH FLOW (dominates every legal flow mechanism) gives 1022/1023/1023/1023 at width 1/2/4/8 — flow's shadow price is **0**; the entire select class is worth <=2 cyc. The 33-cyc flow prize never existed. **REAL FINDING: per-engine shadow prices — flow 0, store 0, alu -2, valu -6, load -7 alone, but valu8+load4 = -181 (841 cyc).** The binding structure is an ALTERNATING valu<->load chain (vector compute <-> gather addresses); c100-c800 runs valu+alu+load all 100%. Loop pivots to H-055 (shorten the alternation; the user's deinterleaved pair-preload is its primary mechanism, now re-measured JOINTLY since load+valu relief is superadditive) | best 1022
- iter 17 | H-053 REJECTED -> G-26, and it RETIRES THE SCORING FRAME: exhaustive 20,565-slot audit found only 0.43% re-derivation (no reservoir); broadcast migration costs +4.3 cyc/site; and the new tools/free_slot_oracle.py proves **ALL compute free = 993 real cycles** — the entire compute census is worth 30 cyc, the valu floor is NOT causal, the schedule is RAW-bound. Engine floors retired as the metric (LOOP.md step 0a); oracle is now the standing pre-screen. Also: _sched_vec's retire race self-equilibrates (freeing valu RAISES valu, lowers alu); CP-bound ramp absorbs floor relief 1:1. H-054's prize re-bounded 33 -> ~29 and its 990 target shown unreachable | best 1022
- iter 17 | H-047 PARTIAL ACCEPT -> frontier 1022 (-1): G-22's mem_prime(5,6) CONVERTS +1 -> -1 under per-candidate order re-search (2x2: priming's -184 alu slots fund the gmin slide, valu floor 1011->1010; each leg alone ties/loses). Serve-more CLOSED by floor arithmetic (+7.2 valu slots/serve at greedy spellings); e1<27 CRASHES (omf1_vec wall, F-16). **F-17 STRATEGIC: flowmax probe finds a FLAG-REACHABLE op stream at any-packing floor 990 (valu 995/flow 989 — corsix's ratio emerges) whose actual schedule is 1104; the full 33-cyc gap is the select-readiness x flow-bubble anti-correlation. ALL future flow/emission work must be evaluated on that stream — baseline-mix evaluation understates by ~15 floor cyc.** F-15 MAINLINE FLIPPED -> 1022 (also ported ignore_mem_write_hazard into perf's scheduler; off-shape sweep improved: h6 1020->1014, h8 1079->1077, h9 1062->1060) | best 1022
- iter 16 | H-051 CLOSED NEGATIVE -> G-25 (packing axis: interval LB 1015 for ANY packing, 170k trials never beat greedy; regret profile localizes all 18 friction cycles; NEW r9-11 epoch seam found). H-049 PARTIAL ACCEPT: emission-order search -> frontier 1023 (-8; ramp/drain-seam moves; structured families ALL closed; epoch seam order-resistant; order absorbs the spelling prize — F-9 pin reverted). F-12 MAINLINE FLIPPED -> 1023. TRIANGULATION: spelling (H-042) + packing (G-25) + order (H-049) all exhausted — below ~1023 requires op/chain changes (H-047 restructure is the remaining lever). Day tally: 1038 -> 1023
- iter 15 | H-042 PARTIAL ACCEPT (frontier 1031 = plan-space optimum; selection-under-fixed-order EXHAUSTED; full 384-word retention now cost-neutral; LP's valu->flow direction never pays — winning flip is the reverse; residual ~55-cyc prize is EMISSION-ORDER-shaped -> F-11 beam or H-047). F-9 MAINLINE FLIPPED -> 1031 (site 354 mapped 1:1, zero drift, flag-free (13,29) pin). Restart tally: 1038 -> 1031 in one day, 6 accepts, 6 permanent closures
- iter 15 | H-048 PARTIAL ACCEPT (frontier 1032: 4 plan rings, relief-funded gmin slide; 384-word supply PROVEN, conversion re-routed to H-042/F-8; trace-liveness soundness caveat). F-6 MAINLINE FLIPPED -> 1032 (named-vector derivation, zero drift). H-038 CLOSED NEGATIVE -> G-24 (1.586T cmpsel candidates; hash closed by 4th tool class, FINAL). H-042 unparked re-scoped (flow leg + ring-hazard placement), running | best 1032
- iter 14 | F-1 MAINLINE FLIPPED -> 1034 (port exact; also root-caused a real dev/perf drift: perf keyed temp pools by g%size vs dev's global emission-index rotation — WAW serialization difference, now baked with comment). Iter 14 tally: 2 answers (H-043/H-044), 1 accept chain (H-045+F-1, -4), milestone recorded | best 1034
- iter 14 | H-044 CLOSED ANSWERED: ideal-floor LP (tools/ideal_floor.py, validated) — best serving mix under infinite scratch = 931.6 (serve L1-L3 + 31/64 L4, prime L4/L5/L6, 918 flow selects, conds retained from parity vectors); 940 NEEDS ZERO NEW ALGEBRA, but is UNREACHABLE with the as-built mix by any compute removal (load floor 951 binds). Gap: 1038 -24-> 1014 -63-> 951 -20-> 932. Marginal rate at optimum ~97 lane-ops/cyc; loads live again (G-22 verdict was mix-relative). H-045 re-scoped to the full flow-saturation build and spawned | best 1038
- iter 14 | H-043 CLOSED ANSWERED: frontier hash IS our 11-op form (corsix SVGs decoded — all onset closures CONFIRMED); the gap mechanism is valu->flow select EXPORT (exits the 60-lane-op budget, ideal ~988) + select-tree/load rebalance via joint selection x scheduling. G-22/G-18 flagged with scope holes under algo-first (friction-based rejections, op removal real). Queued: H-045 flow-maximization (ideal -50), H-046 idealized priming reopen, H-047 L5+ select trees (940 provably requires a level off the load engine: 2x940=1,880 < 1,900 loads). H-044 (ideal model) + H-038 still running | best 1038
- iter 13 | H-039 REJECTED -> G-22 (mem_prime crossover already behind L5: lane-ops drop -144 but off slack engines, waves displace the critical path; corrects H-026 mechanism note; -116-loads supply side has NO mechanism — load-count leg fully closed inside current organization; byproduct: front 0-60 load window reachable via dead-reg staging). H-041 spawned (select-tree gather conversion, the frontier's named lever). H-038 still running | best 1038

## Phase 2 charter (2026-07-28): design, not tuning

Phase 1 ended at 1006 with all axes closed by enumeration/relaxation.
The frontier (940 under our exact rules) provably runs OUR hash form
(H-043 decoded corsix's diagrams), so its advantage is STRUCTURAL.

**[CORRECTED 2026-07-28 by H-058] H-044's 931.6 "ideal floor" is WRONG by
~80 cycles** — tools/ideal_floor.py double-subtracted the 1,848
gather-address combines (the classifier files st-writes as Idx and
st-reads as Routing) and dropped the 616-lane-op Setup bucket. Do not use
its layer-2 numbers as a target. **The joint slot floor of this algorithm
is 960.8 (measured-slope regression) / 962.7 (structural ISA cost model)
— two independent models converging — with compute, load and flow all
binding simultaneously (corsix's 7.5:2:1 ratio re-derived from our own
census). Honest target for this algorithm: ~960 floor, ~975 realized.**
Reaching a 940 FLOOR needs -270 vec-ops; REALIZING 940 needs a floor near
920, i.e. -429 vec-ops (-3,432 lane-ops, 5.8%), because regret is ~20
cycles while compute binds but ~70 once LOAD binds — a 940 design must
run load at 100%.

**The binding arithmetic for any sub-940 design.** Hash is fixed at
46,656 alu+valu lane-ops (closed by four tool classes). At 940 cycles
the alu+valu capacity is 940*60 = 56,400 lane-ops, leaving **9,744 for
everything else**. Our current non-hash spend is ~13,651 lane-ops
(Idx ~7,552 + Routing alu/valu ~5,513 + Setup ~586). **So a 940 design
must do the index+routing work in ~29% fewer lane-ops than ours, or
move that work onto engines with slack.**

Slack inventory at 1006: load floor 946 vs valu floor 995 -> **load has
~49 cycles of headroom while valu binds**; flow 797/1006; store 46/2012
(idle, but stores cannot compute and reads cost load slots). Note this
inverts the Phase-1 intuition: at this balance the profitable direction
is MORE gathers and FEWER selects, not the reverse.

**[CORRECTED by H-058] Scratch was never the binding reason select trees
lose.** The serve/gather crossover is structural: serving level d costs
2^d-1 flow slots or 3*2^(d-1)-2 vec-ops per group-round vs 8 loads + 1
vec-op to gather, and in engine-cycles the crossover falls exactly
between L4 (2.93 valu-cyc vs 4.13 load-cyc) and L5 (6.13 vs 4.13) —
where the shipped kernel already sits. L5 loses 2.1 cyc/group-round and
L6 loses 8.4 REGARDLESS of free scratch. This closes G-23's "reopen if
256+ words free" clause. Freed scratch is worth ~97 vec-ops (~7 cycles)
of remaining COND RETENTION, nothing more.

**The scratch/parallelism trade (original framing, now narrowed).** Our
design keeps 32 groups live simultaneously and spends 1,533/1,536 scratch
words doing it, which is why select-tree serving died three ways (H-041:
L5 needs 256 lane-broadcast words). But valu runs at 5.93/6 — we have
ILP to spare. A design holding FEWER groups live would free hundreds of
words at no obvious throughput cost, changing which serving strategies
are affordable. Never tested.

### H-058 verdict (2026-07-28): what 940 would require

Latency is NOT the wall: free-slot oracles measure compute-free 977,
compute+gathers 650, +selects 331, everything-free 314. A group's 16
rounds are serial, so K live groups give generations of C*K/32 covering
a 314-cycle span => K >= 11 suffices at 940; today's K=32 has 626 cycles
of slack.

**For 940 to exist under our rules, exactly one of four things must be
true, and three are closed by our own artifacts:**
1. a shorter hash — closed by four tool classes (~4e12 candidates),
2. cheaper index maintenance — at floor (950 measured vs 960 theoretical);
   the address recurrence is constant-free only if forest_values_p == 1,
   and relocating the forest costs +27.3 vec-ops (126 load-cycles),
3. cheaper routing — the ISA has no scratch-indexed read and no permute,
   so per-lane routing is exactly "1 load" or "2^d-1 selects", nothing else,
4. **a scheduler that realizes a load-100% stream at regret ~0 where ours
   measures ~70.** <- THE ONLY OPEN ITEM.

(4) is a scheduling hypothesis and should be posed against
tools/backtrack_sched.py on a deliberately load-bound stream (s4 <= 13)
where regret is largest and easiest to attribute.

## Phase 2 closing summary (2026-07-28)

**Final: 1006 cycles, grader-verified 9/9, speedup 146.85x.** Session
trajectory 1038 -> 1006 (-32, 3.1%) across nine accepted changes, each
ported flag-free into perf_takehome.py and independently re-verified
(bundle stream bit-identical to dev, ring audit clean over 40 rings,
10 seeds with value-trace compares).

**Why the loop stopped.** Not budget — the hypothesis space is closed:

| axis | closed by | evidence |
|---|---|---|
| hash op-count | four independent tool classes | ~4e12 candidates (G-10/G-20/G-24) |
| index algebra | algebraic impossibility | G-21, re-derived by H-058 |
| routing | ISA structure | no scratch-indexed read, no permute: per-lane routing is exactly 1 load or 2^d-1 selects |
| load count | saturation + contiguity | 0.00% lane contiguity; 893 consecutive 2/2 cycles (G-16/G-34) |
| emission order | enumeration | k=1 (25,550 moves) and k=2 interacting space (438k evals) both empty (G-30/G-31) |
| packing | 386,090 re-schedules | greedy never beaten; energetic bound (G-25/G-32) |
| organization | ~82,000 candidates | zero below greedy 1019 (G-29 area) |
| flow / store / idle engines | relaxation | infinite-width flow = 0; four closures of one shape (G-27/G-35) |
| scratch | relaxation | freed scratch buys nothing at any size (G-33) |
| alu/valu assignment | exact local optimum | 0 improving flips of 4,357 (G-36) |
| setup ramp | clean relaxation | ceiling 2, physically unreachable (G-37) |

**The bound.** Algorithm floor 960.8 / 962.7 (two independent models).
Realized ceiling ~975. We are at 1006 with regret 11 = ramp 4 (data
arrival) + mid 3 + drain 4 (latency, cpLB > engLB at every cycle
975-1005).

**On 940.** Proved unreachable under this served-levels structure:
940 requires <= 1,758 steady-state loads and we issue 1,831 (G-34). The
frontier is therefore NOT scheduling our load stream better — it must
have a materially different op census. We verified corsix's published
hash is identical to ours (H-043), but that entrant scores 971/994; the
940 holder (@josusanmartin) has published nothing, so their structure is
inferred, never observed. That is the one honest unknown left.

**Methodology yield** (the durable output). Five rules now in LOOP.md,
each bought with a wrong answer: score against realized cycles not
engine floors; "engine X is idle" is not a hypothesis generator; never
state a constraint in scratch terms; read joint shadow prices against
each relaxed machine's own floors; and a relaxation oracle must hold the
program fixed. Plus standing pre-screens (free_slot_oracle, h054_shadow,
h055_preload_oracle, h059_shadow, h063_oracle, h064_oracle,
backtrack_sched, f18_exhaust1) that ceiling a hypothesis in seconds.

---

## Phase 3 charter (2026-07-28): THEORY-ONLY until a design's floor clears 940

**User directive:** "focus on theoretical / structural research until we get a
code design that can theoretically match the record." Phase 3 therefore has a
DIFFERENT ACCEPTANCE BAR than Phases 1-2:

> A Phase-3 result is accepted iff it exhibits a DESIGN (op multiset +
> dependency structure) whose *simultaneous* engine floors are all < 940.
> Cycle deltas on the shipped kernel are NOT the metric and are not
> required. A design that is unimplementable today but whose census clears
> 940 is a WIN; a +/-3 cycle tuning win is NOISE and out of scope.

### The exact arithmetic every Phase-3 hypothesis is scored against

Measured census @1006 (tools/h058_census.py, this commit):

| bucket | alu+valu lane-ops | load slots | flow slots |
|---|---|---|---|
| Hash    | 46,464 | 0     | 0   |
| Idx     |  7,600 | 0     | 0   |
| Routing |  4,809 | 1,832 | 775 |
| Setup   |    616 | 60    | 22  |
| **total** | **59,489** | **1,892** | **797** |
| **floor** | **991.5** | **946** | **797** |

Capacity at 940 cycles: alu+valu 56,400 lane-ops; load 1,880 slots; flow 940
slots. **All three must clear simultaneously.**

**The budget chain (this is the whole problem):**
- Hash is fixed at 46,464 (closed by four tool classes, ~4e12 candidates).
- 56,400 - 46,464 = **9,936 lane-ops for everything that is not hash.**
- Index maintenance has a hard 2-vec-op/group-round floor (parity extract +
  address madd) = 8,192 lane-ops. => any design of this shape floors at
  (46,464+8,192)/60 = **911 cycles.**
- That leaves **1,744 lane-ops (218 vec-ops) for setup + ALL serving
  overhead + wrap.** We currently spend 616 (setup) + 4,217 (serving
  overhead & wrap) = 4,833.

> **PHASE-3 TARGET, stated exactly: cut non-hash, non-idx-minimum alu/valu
> from 4,833 lane-ops to <= 1,744 (-64%), while keeping loads <= 1,880 and
> flow <= 940.** Everything else is already at or below budget.

**Why this is not obviously impossible.** Serving levels 0-4 by tournament is
what buys the load budget (2,264 lane-rounds served; gathering everything
would need 4,156 loads = floor 2,078). The overhead is not the vselects
themselves (those live on flow, which has 143 slots of headroom at 940) but
the ~527 vec-ops of position-accumulator / condition-prep arithmetic on
alu+valu that support them. **Migrating or eliminating that support
arithmetic is the single named path to 940.**

### What was held fixed through ALL of Phases 1-2 (the frames to break)

1. **Lane binding** — walker<->lane is fixed for all 16 rounds. Never varied.
   Permute costs 8 store + 1 vload (store engine is 46/2012 = idle).
2. **Serving mechanism** — levels are served by broadcast-table tournaments
   with a position accumulator. No other mechanism has ever been costed.
3. **Index representation** — a single live address per lane. Biased/1-based,
   redundant, or split (level-offset) representations never costed.
   NB the memory image is FROZEN (tests import build_mem_image from
   frozen_problem), so forest_values_p == 7 is a hard constant, not a choice.
4. **Group granularity** — 32 groups of 8, all live. K<32 never tested.

### Phase-3 rules

- No mainline edits. No flag flips. Deliverables are COST MODELS and PROOFS.
- Every design candidate must be reported as a full census row (alu+valu
  lane-ops / load slots / flow slots) so it can be scored against the table
  above. A design that reports only "saves N ops" is not a result.
- All Phase-1/2 standing pre-screens and the five methodology rules in
  LOOP.md still apply, in particular: a relaxation oracle must hold the
  program fixed, and "engine X is idle" is not a hypothesis generator.
- Negative results are first-class: a proof that the 1,744-lane-op budget is
  unreachable closes the 940 question permanently, which is the real
  deliverable if no design clears.

### CHARTER CORRECTION (P3-B, 2026-07-28): the index floor was 24% too high

The charter's "index minimum = 2 vec-ops/group-round x 512 = 8,192 lane-ops"
is WRONG on both factors, and the "any design of this shape floors at 911
cycles" line that follows from it is wrong by 26-38 cycles.

**Only 448 of 512 group-rounds emit any index work.** The wrap (L10->L0) and
the final round cost exactly ZERO -- no compare, no select, not even a parity
extract -- because the kernel aligns round r to level `r mod 11`, making the
wrap deterministic and round 10's parity discardable (perf_takehome.py:
1604-1605, invariant stated at :541). Level-alignment is worth 8,192 lane-ops
against a non-aligned design and is already banked.

**Cost is level-dependent, not uniform.** A transition costs 1 op (parity
only) if its successor is tournament-SERVED, 2 ops if its successor gathers
from an already-packed predecessor, k ops if it must pack k-1 loose bits, and
0 if its successor is level 0 or it is the last round. Measured
(tools/p3b_attrib.py): L0->L1 1.00, L1->L2 1.00, L2->L3 1.41, L3->L4 3.59,
L4->L5 4.06, L5..L10 exactly 2.00 valu + 1 flow, wrap 0.00, round 15 0.00.
Total 898 vec-ops = 7,184 lane-ops measured against a floor of **6,608**
(or 5,888 if the epoch-2 L4 gathers go to zero).

> **Design-floor line, corrected: (46,464 + 6,608)/60 = 884.5 cycles** at
> today's serving policy, or 872.5 under a b=0 L4 policy. NOT 911.

**Second misattribution: Routing's 504 `multiply_add` slots (4,032 lane-ops)
are NOT address arithmetic.** They are tournament table selects spelled as
`cond*diff + lo`, emitted by `race_sel`/`race_leaf`/`dual_fold` whenever the
scheduler's race puts a select on valu instead of the 1-slot flow engine
(perf_takehome.py:1456, :1474-1477, :1486-1489, :1539-1545). They belong to
the SERVING axis. This matters because it is a spelling already under
scheduler control: flow has ~143 slots of headroom at 940 and every vselect
moved off valu is -8 lane-ops.

**Corrected budget chain.** The absolute cut is invariant at 3,089 lane-ops
(fixed by the census total), but the pool it must come from is larger:

| index floor used | non-hash non-index budget @940 | current spend | required cut |
|---|---|---|---|
| charter's 8,192 | 1,744 | 4,833 | -3,089 (-64%) |
| **P3-B 6,608 (today's policy)** | **3,328** | **6,417** | **-3,089 (-48%)** |
| P3-B 5,888 (b=0 policy) | 4,048 | 7,137 | -3,089 (-43%) |

**Third correction: the index axis is not at floor.** It carries 576 lane-ops
of slack (352 of it the deliberate alu-spelling of 44 madds -- a race that
trades census for realized cycles per G-36; ~224 genuine accumulator slop at
L2->L4), and up to 1,296 if the L4 policy changes. The charter listed this
axis as closed; it is 92% done, not done.

**Coupling discovered (important for design enumeration): serving a level
makes its PREDECESSOR transition cheaper on the index axis too.** The served-
level set S does not merely trade flow slots against load slots -- it also
moves index cost. Any enumeration that treats the three engine costs as
separable in S is wrong.

**What P3-B closed.** The 2-vec-op floor is PROVED for gathered-successor
transitions (1,548,224 structural forms enumerated, 0 solutions) and REFUTED
for tournament-served transitions (floor 1). The wrap is at floor (zero).
The -6 address bias already costs 0 alu/valu lane-ops -- absorbed by a flow
vselect between two live constants -- and carrying the address itself is the
UNIQUE zero-extra-op affine representation (`idx+1`, `idx+3`, level-offset
split, and redundant-state forms are each +1,280 lane-ops; the memory-table
advance is +1,280 LOAD slots on the one engine already over budget).
New ISA fact: `val | 0xFFFFFFFE` = parity-2 is the only single-op parity form
with a free additive bias -- 5 families survive a 12,048-form search --
useful only if flow becomes the binding engine. Full detail:
research/strains/p3b/STATE.md.

Remaining soft joint: the ">= 4 madds to pack 5 loose bits" step is an
operand-arity argument, not a machine-checked enumeration. If a 3-op packing
exists the floor drops another 256 lane-ops.

### P3-A RESULT (2026-07-28): a serving design clears 940 on all three engines

**Floor 939, simultaneously feasible.** `tools/p3a_opt.py` scanned cycle
target x serving profile; the minimum simultaneously-feasible floor is
**939 cycles** at s=221 served group-rounds (L1 64 + L2 64 + L3 64 + L4 29),
227 gathered, 1,139 folds. Model calibrated against the shipped kernel to
within 55 lane-ops (0.1%).

| # | design | alu+valu | load | flow | floors /60 /2 /1 | @940 |
|---|---|---|---|---|---|---|
| S0 | shipped @1006 | 59,489 | 1,892 | 797 | 991.5/946.0/797 | FAIL av+3,089, ld+12 |
| **C1\*** | **ring + free-form folds + add_imm->alu + 4 store-broadcasts, s=221** | **56,272** | **1,880** | **940** | **937.9/940.0/940.0** | **PASS** |
| C2 | sum-of-products (no vselect at all) | 61,960 | 1,880 | 229 | 1032.7/940/229 | FAIL av+5,560 |
| C3 | store-broadcast all 48 vectors | 56,072 | 1,935 | 940 | 934.5/967.5/940 | FAIL ld+55 |
| C4/C5 | serve more (s=250 / s=256) | 58,888/59,512 | 1,692/1,644 | 940 | 981.5/991.9 | FAIL av |
| C7 | gather everything (s=0) | 54,088 | 3,644 | 450 | 901.5/1822/450 | FAIL ld+1,764 |
| C8 | C1\* keeping the packed accumulator | 57,472 | 1,916 | 958 | floor 958 | FAIL @940 |
| C9 | C1\* + omf constant-select eliminated | 55,128 | 1,840 | 920 | floor **920** | PASS |

**The two levers that do it.**
- **T2 (load-bearing): the position accumulator is pure overhead for serving.**
  Retain the raw parity bits per level -- they are the parity extract's own
  write, so they are free -- and read tournament conditions directly. This
  zeroes cond.mask (624) + pos.fold (1,128) + pos.seed (320) = -2,072
  lane-ops, and pays +2 valu ops only at each gather boundary (35 exits,
  +70 vec-ops). Net -1,512. **With the packed accumulator kept, the best
  floor is 958** -- this lever alone is the difference.
- **T3: move the 20 setup `add_imm` slots OFF flow onto alu** (-160 alu+valu
  lane-ops, +20 flow slots). Also load-bearing: without it C1\* FAILS.

**T1 (derived, not load-bearing at the optimum): every tournament node is
freely flow-`vselect` OR valu-`madd` at 1 op.** A node combining constant
subtables A/B is either `vselect(b, B[q], A[q])` or `madd(b, (B-A)[q], A[q])`
-- and in the madd form the child table is the elementwise DIFFERENCE, which
is again constant and precomputable at setup. **Therefore no interior node
ever needs a runtime subtract**; `race_sel`'s sub+madd interiors and
`make_newest_parity_last_diffs` are artifacts of the newest-first tree shape
and are removable. This matters whenever flow has slack.

**Why serving more or less both lose.** At the optimum load and flow bind
EXACTLY and simultaneously (flow = C, load = 2C) with alu+valu holding ~1.5
cycles of slack. The marginal trade is: +1 served L4 group-round = -8 load
slots but +15 folds, and since flow is saturated those folds land on valu.
Exchange rate **1 load slot ~ 1.875 valu vec-ops**. C2 (sum-of-products) is
exactly isomorphic to the select tree, not cheaper: Horner over d parity bits
costs the same 2^d-1 nodes but every node becomes valu-only, converting 1,139
flow-eligible ops into valu ops.

**Budget line, restated correctly.** The charter's "1,744 lane-ops" pool was
an artifact of the wrong index floor (P3-B). The pool that actually binds is
ALL non-hash alu+valu, which is what the capacity algebra sees: shipped
**13,153 -> best achievable 10,032**, against a hard ceiling of **10,064** at
940. Clears by 32 lane-ops. Required cut is **-23.5%, not -64%**.

### Honest status: this clears the BAR, not yet the RECORD

1. **939 is a floor, not a realized count.** Shipped regret is ~11-15 cycles
   (floor 991.5 -> realized 1006). A design whose floor is 939 with two
   engines exactly saturated realizes ~950-960. Under the Phase-3 acceptance
   bar as written ("simultaneous engine floors all < 940") C1\* PASSES; it
   does not imply a realized 940. **C9 (floor 920) is the design that would
   plausibly realize ~935 -- that is the real target.**
2. **The margin is at model resolution.** 128 lane-ops (16 vec-ops, 0.23%).
   Two inputs carry that much uncertainty alone: SETUP_VEC_MIN = 70 (shipped
   measures 83) and the exit count (35). P3-C's independent calculator is
   deliberately NOT being told these numbers, so its enumeration is a genuine
   cross-check rather than a confirmation.
3. **C1\* needs K<=16 live groups.** Retained parities cost 3 vectors/group
   (768 words at K=32) where the packed `st` cost 256; at K=32 it overruns
   SCRATCH_SIZE=1536 by ~85 words. H-058 measured K>=11 suffices for ILP at
   940, but **K<32 is charter frame #4 and has never been tested.** This is
   now the largest untested assumption in the design.

**Open cross-axis question (dispatched to P3-B).** The `omf` two-way constant
choice in `gaddr' = 2*gaddr + omf +/- par` consumes 227 flow slots at the
optimum. P3-A modelled its elimination as FREE, giving C9's floor of 920;
P3-B showed it currently costs zero alu/valu because it rides a flow vselect
between two live constants. With flow now SATURATED, that slot is no longer
free -- each one displaces a fold onto valu. Whether the elimination is free,
costs +N, or is impossible decides 939 vs 920. Full detail:
research/strains/p3a/STATE.md.

### P3-C RESULT (2026-07-28): independent enumeration; the served-level shape is closed

`tools/p3c_design_cost.py`, validated against the shipped kernel at **+0.08%**
on alu+valu lane-ops (59,537 vs 59,489), 0.00% on load and store and scratch,
+1.57% on flow (13 slots of `race_sel`/`race_copy` engine drift -- a
scheduling race, not a design property). Enumerated ~405k designs: every
subset of {L1..L10} fully served x every partial count at one further level x
the optimal fold split.

**Minimum max-floor as built = 964.8** (L1-L3 full + 23 of 64 L4;
57,887 lane-ops / 1,924 load / 965 flow; floors 964.8 / 962.0 / 964.8 -- a
genuine three-way tie, which is why no local move helps). Shipped
(L1L2L3+L4x27) models at 970.8, i.e. we sit 6 cycles off the best design of
our own shape.

**Every optimum has the SHIPPED SHAPE: L1-L3 fully served, L4 partial,
L5-L10 gathered. The served-level axis is closed by exhaustion.** Best
L5-serving design is 994.0 (best case 981.2) -- it loses by 30-47 cycles
BEFORE scratch is consulted, independently re-confirming G-33 from a new
direction.

Relaxed-coefficient optima (same enumeration):

| coefficients | min max-floor | 940? |
|---|---|---|
| as-built index + as-built support | 964.8 | no |
| index at P3-B floor (6,608), support as built | 959.7 | no |
| index as measured, ALL support free | 950.6 | no |
| index at floor AND all support free | 946.0 | no |
| **index at 5,888 (b=0) AND all support free** | **937.4** | **yes** |

**K (live groups) is CENSUS-NEUTRAL.** K in {32,24,16,11,8} gives identical
58,246 / 1,892 / 971 and moves only scratch (1,533 / 1,341 / 1,149 / 1,029 /
957). It cannot participate in the 940 arithmetic -- a census restatement of
G-33. This is good news for P3-A's C1*, whose retained-parity ring overruns
scratch at K=32: **K=16 costs nothing on the census and needs only 1,149
words**, and H-058 measured K>=11 sufficient for ILP at 940. Charter frame #4
is thereby answered on the census axis (though not yet on latency).

**Dead end recorded (do not repeat):** `tournament_levels=(1,2,3,4)` in dev.py
measures ~7 ops/group-round for "level 4", appearing to falsify `2^d-1`. It is
an INVALID BUILD -- dev's fold emitter has explicit branches only for L==1/2/3
and its final `else` is labelled `# L == 3`, so a 4th level silently re-runs
the 8-way fold over 16 candidates.

### THE OPEN QUESTION: is the ~937.5 cell self-consistent? (P3-D dispatched)

P3-A (937.9) and P3-C (937.4) are almost certainly describing the SAME cell:
P3-A's index composition is 3,584 + 2,376 = 5,960 ~ P3-B's b=0 optimum of
5,888, and P3-A's T2 is exactly "all support arithmetic free". Two independent
models converging on ~937.5 would be strong evidence -- **except that the cell
may be self-contradictory.**

P3-B's 5,888 index floor is reached only "if the epoch-2 L4 gathers go to
zero", i.e. by SERVING more level-4 group-rounds. P3-C's enumeration prices
exactly that trade and finds it LOSES monotonically: L4x27 970.8 -> L4x28
972.3 -> L4x29 973.8, because each additional served L4 group-round costs ~15
folds against -8 load slots. **If the index saving can only be bought by
paying the fold cost, the 937 cell does not exist and both numbers are wrong
in the same way** -- both models appear to have swept index cost and the
served-level profile as INDEPENDENT parameters when they are the same decision
variable (the coupling flagged in the P3-B correction above).

P3-D is adjudicating with a single joint model in which index cost is DERIVED
from the design rather than swept. Until it reports, the honest status is:

> **We have a design whose modelled floors clear 940 on all three engines, in
> a cell whose self-consistency is unverified.** The defensible claim today is
> the range 946-965: 946.0 if all serving support arithmetic can be removed at
> 100% ring coverage, 964.8 if it cannot. Both are above 940.

### P3-B ROUND 2 (2026-07-28): C9 is dead -- the floor stays 939, not 920

**VERDICT: IMPOSSIBLE.** The `omf` select cannot be eliminated. P3-A's C9
(floor 920) is not a valid design.

The mechanism: the `omf` op is **fungible flow-or-valu** (spell it
`madd(par, one_vec, omf_vec)` and it leaves flow entirely), exactly like the
tournament nodes in P3-A's T1. The only representations that remove it
(`idx+1`, `idx+3`) replace it with a *valu-only* address-recovery op. My
break-even arithmetic in the dispatch was right in the numbers and wrong in
the conclusion: **the 1,816 lane-ops freed on the fold side are exactly the
1,816 spent recovering `A = S+4`.** Reproduced inside P3-A's own model
(`tools/p3b_omf.py` imports `p3a_model.py` unmodified): C1* and a corrected
C9 are **bit-identical -- 56,272 / 1,880 / 940, floors 937.9/940.0/940.0**.
At C=920 both need 56,432 lane-ops against a 55,200 cap and 1,880 loads
against an 1,840 cap: fails on two engines.

The tell that the representation change does no work: those same 1,816
lane-ops are buyable *without* changing representation at all, just by
re-spelling the 227 `omf` selects as madds.

**Dominance theorem (any design, any cycle target).** Shipped pool cost is
`max(0, L+g-rem)`; biased-representation cost is `g + max(0, L-rem)`. If
`L >= rem` they tie; if `L < rem` the shipped form strictly wins. At the
optimum L=680 > rem=479, hence the exact tie. There is no cycle target at
which the rebias wins.

**Lemma 1 upgraded to all 2^32 constants** by closed-form conditions per
opcode: the complete one-op parity output set is exactly **{p, p-2, p*2^31}**,
and parity always enters with coefficient +1 (so complement forms are closed
too). For state `idx+b` the addend is `p+(1-b)`, free only for b=1 or b=3;
but loadability pins b=7, giving addend `p-6`, and `-6` is not in {0,-2}.
**Jointly unsatisfiable.** Per-level re-bias is refuted the same way: the
addend is free iff `b_{d+1} in {2b_d-1, 2b_d-3}`, but every gathered level
pins `b_d=7`, requiring 13 or 11; levels 5-10 gather consecutively so all
five transitions are pinned simultaneously.

The Horner exit was also checked for shavings: its residual constant is +38
and the free per-stage injections are only 0 and -2 (all non-positive), so
exits pay one fungible op too. `idx_selects = g = 227` is correct.

**Consequence for the record.** The best floor now defensible is 939 (if the
cell survives P3-D), which realizes ~950-960. **We do not have a design that
would realize 940.** The index axis is closed as a source of further margin:
any additional headroom must come from REMOVING COMPUTE, not from re-spelling
the recurrence. Full detail: research/strains/p3b/STATE.md §9.

### P3-D ADJUDICATION (2026-07-28): SELF-CONSISTENT -- and both models missed why

**VERDICT: the ~937.5 cell is self-consistent.** But the reason is one
neither prior model states, and my dispatch's suspicion was wrong.

**The mechanism: WHICH ROUND, not how many.** P3-B's 5,888 index floor is
NOT bought by serving more L4 group-rounds (P3-C correctly prices that as a
monotone loss). It is bought by serving the SAME number of L4 group-rounds
**at round 15 instead of round 4** -- identical folds, identical loads,
-768 lane-ops of index. Both rounds are level 4 (`level(r) = r mod 11`), but
round 15 is the LAST round and therefore never needs an address. Serving at
round 4 earns zero index credit because the pack merely moves to round 5 (an
exact cancellation -- P3-C's own coupling lemma); serving at round 15 earns
-3 madds per group-round. The source already knows this:
perf_takehome.py:1494, "unless last round (nothing reads st after)".

**JOINT OPTIMUM** (16,384 per-group schedules x mixtures, index DERIVED
per-round rather than swept):

| C | alu+valu | load | flow | store | floors | schedule | index derived |
|---|---|---|---|---|---|---|---|
| 939 | 56,296 | 1,878 | 939 | 94 | 938.3/939.0/939.0 | 29 groups `SSSS.GGGGGGG.SSSSS` + 3 groups `SSSS.GGGGGGG.SSSSG` (L1-L3 both epochs, L4 at round 15 only, 29/32) | 448 extracts + 297 madds = 5,960 |

Bit-identical to P3-A's C1*.

**ERROR ATTRIBUTION.** P3-A **survives**: `p3a_opt.py:64-66` derives the index
cost (`exits = 32 + max(0, 32-n4)`) and charges folds and loads in the same
call, so its sweep was never independent. P3-C **fails on its 946.0 and 937.4
rows**: its `idx_slack` is a free additive constant applied uniformly to all
405k designs, granting 5,888 to designs that genuinely cost 6,656, and its
`index_cost` is level-indexed with successor smearing so it cannot express
"round 15 not round 4" at all. The joint model reads **953 as-built** (vs
P3-C's 964.8) and **939 support-free** (vs P3-C's 950.6).

### ACTIONABLE, ON THE SHIPPED KERNEL: the L4 assignment is dominated

`l4_gmin = (6, 31)` (perf_takehome.py:669) serves **26 L4 group-rounds at
round 4 and only 1 at round 15** -- the dominated assignment. Moving those 26
to round 15 is worth **624 lane-ops of index at zero fold and zero load
cost** (~10 cycles of floor). The blocker is the assert at
perf_takehome.py:729-736 (`2*final_unserved >= 8 + 9*final_served`), which
caps the final round at 5 served groups because `b3l_fold_diffs` needs
register funding from unserved groups. **That is an allocation/scratch
constraint, not a structural one** -- exactly the shape G-33 warns about, and
admissible to relax under LOOP.md 0b's idealized-machine frame.

### Status of the 940 question, stated honestly

**Floor-wise: YES, reachable -- with 1 cycle of margin that needs four legs
to hold simultaneously.** The support headroom at 940 is only 16 vec-ops, so
all of: T2 ring at ~100% coverage, setup at 70 vec-ops (+1 cycle if it is
really 83), T3 (+2 if omitted), and ideal fold spelling (+4 if the shipped
`race_sel` spelling is kept). **Realized: NO -- ~950-960.**

**Two named unknowns now decide whether C1* is real at all:**

1. **Ring coverage is uncosted.** T2 assumes the retained-parity ring covers
   ~100% of served group-rounds; the shipped kernel runs 20-43 rings. At 62
   vec-ops of residual support the floor is 945; at 160 it is 953. The whole
   claim lives in that interval.
2. **K<=16 is census-neutral but may not be cycle-neutral.** T2 at 100%
   coverage needs 6 vectors/group = 1,533 of 1,536 words, which forces
   K<=16 (K=32 would need 2,301). P3-C's K-neutrality basis checks out on the
   census -- but **G-33/H-059 MEASURED that every W<32 loses on realized
   cycles.** Under our own first methodology rule (score against realized
   cycles, not engine floors) the measurement outranks the model. **C1* may
   be floor-feasible and simultaneously unrealizable.**

T3 verified legal but re-priced: flow `add_imm` is scalar (problem.py:332)
and alu has NO immediate form (problem.py:243-276), so it needs the existing
`+32`-chain trick (perf_takehome.py:1053) -- 24 lane-ops, not 20. Still
load-bearing (941 without it).

### P3-D RETRACTION (2026-07-28): C1* does not survive. 940 is NOT cleared.

**Corrected joint floor: 945-946 (best case 942). The Phase-3 bar is not met.**

Call-site attribution (`tools/p3d_attrib.py`, a direct per-slot diff of the
two builds) splits G-38's residual three ways:

1. **The entire -1,104 alu delta is a SPELLING SWAP, not index credit.**
   `vec("^", vl, vl, nvsrc)` (dev.py:3213/:3218) moves 1,104 alu slots into
   138 valu vec-ops -- 1,104 -> 1,104 lane-ops, exactly neutral. This is
   H-053/G-36 self-equilibration running backwards. G-38's inference that
   "the index work that disappears is alu-hosted" is FALSE; the index work is
   valu-hosted.
2. **The index credit is CONFIRMED at -632 lane-ops** (predicted -624), all
   at `race_idx_madd` + the `-` combine (dev.py:3301/3305, the epoch-exit
   gaddr reconstruction). **The -3 madds/group-round rule holds.**
3. **The genuine residual is +488 lane-ops (+61 vec-ops) of FOLD machinery**
   -- `_sched_madd`, `dual_fold`, `race_sel` -- with no alu counterpart at any
   of those sites, i.e. genuinely more ops. That is +2.35 vec-ops per
   round-15-served group-round, or +2.96 correcting for the differing serve
   counts (which also accounts for the whole +8 loads, so per-group-round
   load-neutrality IS confirmed).

**C1* recomputed with the penalty charged per round-15 service:**

| penalty | floor | census |
|---|---|---|
| 0 (P3-A/P3-D original) | 939 | 56,272 / 1,880 / 940 |
| 2.35 vec-ops | **945** | 56,654 / 1,890 / 945 |
| 2.96 vec-ops | **946** | 56,719 / 1,892 / 946 |
| 4.0 vec-ops | 948 | -- |

At 940 it is over by 254-319 lane-ops (4.2-5.3 cycles) plus load and flow.
**This lands on 946.0 -- exactly P3-C's independent best-case cell. The two
models now agree from opposite directions**, one having swept index cost as
a free parameter and the other having derived it, and both arriving at ~946.

**Artifact vs intrinsic.** It is NOT the `depth_first_fold` /
`leaf_dead_temp=None` degradation -- the apples-to-apples pair ran b3_last
OFF at both ends, so that path was untaken. It IS partly a spelling knob:
dev.py:3118 selects `w_fold = vsel | dual_fold | madd`, tuned at `(6,31)`
and never re-tuned at `(32,6)`; `dual_fold` emits 2 valu ops where `madd`
emits 1, and +296 of the +488 sits on dual_fold rows. **But recovering ALL
of it still gives 942. No re-tune restores 939.** Best explanation for the
intrinsic part: at round 4 the pair tournament's inputs (folded `st`, the L3
winner) are by-products the group needs anyway for round 5; at round 15
nothing else consumes them (perf_takehome.py:1494).

P3-D's Section-1 corollary (move the 26 to round 15 for -624 lane-ops) is
**RETRACTED**. G-38 stands as the mainline verdict, with its reopen gate
now requiring a floor below **946**, not below 1006.

### Phase-3 status: the structural floor is 942-946, and 940 is out of reach

Two independent models, built from opposite directions and disagreeing at
every intermediate step, converge on a floor of **~946**, realizing **~965**.
The record is 940 REALIZED, which needs a floor near 925 -- **157 vec-ops
(0.31 per group-round) below anything this design space contains.** That is
not a tuning gap or a rounding error; the record holder is doing something
structurally outside every frame we have enumerated.

Remaining unaudited item, named by P3-D: **both P3-A's and P3-C's models
calibrate per-LEVEL rather than per-SITE, and every partially-served level
other than L4 is unaudited for the same defect.** Until that is checked, the
946 itself carries the same class of error that produced the phantom 939.

### P3-E (2026-07-28): the two unknowns are ONE constraint, and it measures NO

**C1* STATUS: ARTIFACT at 939; REAL at 948.**

100% ring coverage *is* K<=16 -- they are the same constraint, not two.

**Ring coverage ceiling = 40/64 group-epochs = 62.5%**, binding constraint
scratch words. `tools/h059_ringmax.py` funds exactly 40 of 64;
`tools/audit_ring_windows.py` independently tops out at 36. Word arithmetic
agrees to one ring: T2 needs 24 extra words per covered (epoch, group) =
1,536 at 100%, against 3 spare + 960 borrowed = 62.7% available. Residual
support scales as 259*(1-coverage) vec-ops, so 62.5% coverage costs 97
vec-ops => **floor 948** (952 with the shipped fold spelling). **939 would
need >=94% coverage.**

**K<=16 is not realizable: it costs +75 realized cycles.** One base, only
`group_window` toggled: W=32 1028/1028, W=24 1049/1053, W=20 1060/1073,
**W=16 1074/1103**. C1* needs the aliased column (that is what frees the
words), so the penalty is +75 -- **more than C1*'s entire 56-cycle floor
advantage.** Attribution: valu floor +21.7 (offload race -- and the race
column reproduces G-36's 1028/1053/1103 exactly) plus regret +53.3 (chain/
ILP plus WAR from register reuse). Census stays flat at ~60.3k and scratch
at K=16 is 1,149 words, **confirming P3-C's K-neutrality model exactly** --
K is census-neutral and cycle-expensive at the same time.

**G-33 CORRECTION.** Its penalty table mixed bases: the W=32 entry was the
RINGED 1006 while the W<32 entries were ring-free from base 1026. True
penalties are +21/+45/+75, not +39/+58/+91 -- **G-33 overstated the K
penalty by ~20 cycles.** The conclusion nevertheless generalises to C1*,
and not marginally: 56 < 75.

Open (uncosted, both directions): T2 deletes `st`, and `st` vectors are ~40%
of the mined ring donors, so the 40 rings may not survive a T2 re-mine.
Optimistic bound if they do and coverage reaches ~79% is 944.

### PHASE-3 ANSWER: 940 is unreachable. Three models converge on 944-952.

| model | route | floor |
|---|---|---|
| P3-C | independent enumeration, ~405k designs | 946.0 |
| P3-D | joint model, index derived, penalty measured | 945-946 (942 best case) |
| P3-E | measured ring ceiling + measured K penalty | 948 (944 optimistic, 952 shipped spelling) |

Three models, built from different directions and disagreeing at every
intermediate step, converge on **944-952 floor, realizing ~965-970**.

**The record is 940 REALIZED, which needs a floor near 925 -- about 157
vec-ops (0.31 per group-round) below anything this design space contains.**

**Why no further lever of that size exists inside the space.** At 940 the
budget is 7,050 vec-ops. The hash alone is 5,808 (82.4%), closed. Index at
its proved floor is 826. Serving needs 1,139 folds plus 227 `omf` selects =
1,366 flow-eligible ops against at most 940 flow slots, so >=426 land on
valu. 5,808 + 826 + 426 + ~70 setup = 7,130 vec-ops > 7,050, and the load
engine fails independently (227 gathered group-rounds = 1,876 loads against
1,840 at 920). Every one of those terms is now individually closed by
enumeration, measurement, or algebra.

**Therefore: if 940 exists under these rules, the hash must be shorter than
11 ops.** It is the only term large enough to matter, and it is the one whose
closure is weakest -- G-10 was exhaustive PER ADJACENT SEGMENT of the 11-op
chain, explicitly "inexhaustive at global scale". corsix published a hash
identical to ours and scores 971/994; the 940 holder has published nothing.

### P3-F (2026-07-28): no 10-op hash found; the question is narrowed, not closed

**VERDICT: STILL OPEN.** No 10-op form of the round body exists in the
regions searched, but the search is not exhaustive at global scale.

**What the prior closure actually covered** (now stated precisely): G-10 was
exhaustive *per adjacent segment* at depth current-1 (~400B candidates) --
every chain cut, fold-in head 5->4, cross-round tail 5->4, parity <=4. H-016
added a MITM over all 10 boundaries (2.36T). H-025 added a full-hash MITM
with no waypoint at **depth <=7 forward / 10 total** (2.9T). The gap P3-F
attacked: forward-prefix depth >=3 globally, plus the `//`/`%`/`cdiv`
vocabulary, which `rust_harness/src/bin/fusion_search.rs:97` omits from
`BIN_OPS` entirely.

**New negatives.**
- The `//`/`%`/`cdiv` vocabulary gap is **closed negative**: 16,200 questions
  over the 2-round trace DAG with constants solved, exhaustive over that
  vocabulary. 4 hits, all definitional (`a // 524288 == a >> 19`).
- Depth-2 per 3-op block: 6,280 / 11,494 / 21,624 op1 candidates, **0 hits**
  (exhaustive where op1 has no free constant outside a 31-entry structured
  pool; sampled over the full 2^32 op1-constant space).
- **Exact lemma: `exists c such that y^K == y+c (mod 2^32) for all y` iff
  `K in {0, 2^31}`** (y=0 gives c=K; y=K gives 2K=0). Since a madd's addend
  is the only additive slot, **no xor can cross a madd.** This proves the
  fold-in `^nv` and the stage-2 `^C1` are irremovable within the entire
  conjugation / basis-transform / node-table-transform family -- which is the
  family `c5_prexor` belongs to, so the one known-non-empty class of
  cross-round identities is now bounded.
- Obstructions recorded: O1 removing the fold-in needs
  `node_val in {0xB55A4F09, 0x355ACF09}` while node values are uniform in
  [0, 2^30); O2 `g19^-1(C1) = 0xC761DAD0`; O3 `C1 = 0xC761C23C`.

**Hygiene:** the shipped 11-op form was re-validated bit-exact on 1,021,609
cases (21,609 edge pairs covering 0, 1, 2^31, 2^32-1 and every shift
boundary, plus 10^6 random). Zero mismatches.

**Confirmed leverage:** a 10-op body removes 528 vec-ops ~ **70 cycles**,
taking the floor from 944-952 to **~874-882**. The prize is real; the form
is not found.

**Only structurally uncovered region: the kf>=3 global MITM (~1000x
compute).** Rather than fund that, P3-F has been redirected to the cheaper
and more decisive question it raised itself: **is there a LOWER BOUND
argument?** If >=4 madds are provably necessary, then combined with the two
irremovable xors the 10-op question closes outright -- a proof, not another
exhausted region. That is now the phase's open item.

## Phase 3 closing summary (2026-07-28): 940 is out of reach; here is exactly why

**Result: no design in this space theoretically matches 940.** The
structural floor is **944-952**, realizing ~965-970. Mainline stays at
**1006**, grader 9/9 — Phase 3 was theory-only by charter and shipped no
cycle change.

### The three-model convergence

| model | route | floor |
|---|---|---|
| P3-C | independent enumeration, ~405k designs | 946.0 |
| P3-D | joint model, index derived per-round, penalty measured | 945-946 |
| P3-E | measured ring ceiling + measured K penalty | 948 |

Built from different directions, disagreeing at every intermediate step,
converging at the end. The record of 940 REALIZED needs a floor near 925 —
**157 vec-ops (0.31 per group-round) below anything this space contains.**

### Why nothing but the hash can close it

At 940 the budget is 7,050 vec-ops. **The hash alone is 5,808 — 82.4%.**
Index at its proved floor is 826. Serving needs 1,139 folds plus 227 `omf`
selects = 1,366 flow-eligible ops against at most 940 flow slots, forcing
>=426 onto valu. Total 7,130 before setup, and the load engine fails
independently (1,876 loads against 1,840). Every term individually closed:

| term | closed by |
|---|---|
| index recurrence | 1,548,224 structural forms, 0 solutions; parity set {p, p-2, p*2^31} over ALL 2^32 constants |
| `omf` select | algebraic dominance theorem: tie when L>=rem, strict loss otherwise, at every cycle target |
| served-level shape | exhaustive over ~405k designs; every optimum is the shipped shape |
| serving mechanism | sum-of-products isomorphic to select trees; T1/T2/T3 costed |
| ring coverage | measured ceiling 40/64 = 62.5%, three independent checks |
| K (live groups) | census-neutral (model) AND +75 realized cycles at K=16 (measured) |
| hash | 11 ops; no 10-op form found, no lower bound provable |

### The one honest opening, and why it is not closable here

**If 940 exists under these rules, the hash must be shorter than 11 ops.**
A 10-op body is 528 vec-ops ~ **70 cycles**: floor 944-952 -> ~874-882.

P3-F narrowed but did not close it:
- Prior closure stated precisely at last: G-10 exhaustive PER ADJACENT
  SEGMENT; H-016 MITM over all 10 boundaries; H-025 full-hash MITM at depth
  <=7 forward / 10 total.
- Vocabulary gap closed negative (`//`, `%`, `cdiv` were absent from
  `fusion_search.rs` BIN_OPS): 16,200 questions, exhaustive, 4 hits all
  definitional.
- **Lemma: `exists c: y^K == y+c (mod 2^32) for all y` iff K in {0, 2^31}.**
  A madd's addend is its only additive slot, so **no xor can cross a madd**
  — proving the fold-in `^nv` and stage-2 `^C1` irremovable across the whole
  conjugation / basis-transform / node-table-transform family, the family
  `c5_prexor` belongs to.
- O1 additionally survives on a structural argument: the kernel is built from
  `(forest_height, n_nodes, batch_size, rounds)` only, so the op stream can
  **never be specialised on a node value** — and the transformed node table
  `T(nv) = g16(C5^nv)` leaves no residual freedom.

**A lower-bound proof is formally barred.** All three invariant routes are
saturated by 1-2 op programs, with explicit witnesses (`tools/p3f_bound.py`):
bit-dependency — `out = (s < 0xB3A7F001)` makes output bit 0 depend on 32/32
bits of `s` in ONE op (cap <=1); degree/2-adic — `deg(s*s) >= 11/12` vs
target 12/12 (cap <=2); XOR/ADD alternation — the target has fan-out, so the
chain-of-bijections model does not apply; counting — non-constructive.
**Unconditionally provable: N >= 2. N >= 11 holds only under a
stage-respecting hypothesis that is exactly the thing in question.**

**Therefore "940 via a shorter hash" is OPEN BUT UNFALSIFIABLE at this
budget.** The only sound route left is exhaustive refutation via the kf>=3
global MITM, ~1000x the compute spent so far. Not funded; the user's call.

### Corrections this phase made to our own record

1. Charter's index floor 8,192 -> **6,608**; design-floor line 911 -> 884.5.
   Only 448 of 512 group-rounds emit index work.
2. Routing's 504 madds are **tournament selects**, not address arithmetic.
3. **G-33's K-penalty table mixed bases** (ringed W=32 against ring-free
   W<32), overstating the penalty by ~20 cycles: true +21/+45/+75.
4. P3-D's round-15 corollary **retracted** after measurement (G-38).
5. P3-F corrected its own O1 range claim mid-phase; the obstruction survives
   on stronger grounds.
6. **Latent miscompile found and contained**: with partial b3l funding
   reachable, the dead-register pool's tail is not dead — `l4_gmin=(32,24)`
   built a kernel that ran and returned the WRONG ANSWER. Unreachable behind
   the flag's preserved all-or-nothing invariant; `perf_takehome.py` never
   exposed. Filed separately.

### Methodology note

Phase 3's headline number was wrong twice before it was right, and both
times two models agreed while sharing an unexamined assumption. 939 survived
one adjudication and died to a measurement (G-38). **Convergence between
models is not evidence when the models share a frame; only measurement
broke it.** That is the sixth rule this project has bought with a wrong
answer.

---

## Phase 4 charter (2026-07-29): assume corsix is RIGHT and find our error

**User directive:** autoresearch the contradiction, **assuming the published
source is correct.** This inverts the usual frame: the question is not "does
corsix's claim survive our census" (we already answered that three ways in
G-23 and again in P3-C) but **"what must be true about their design, or wrong
about our rejection, for their claim to hold?"**

### The contradiction, stated exactly

**Their claim** (corsix.org/content/anthropics-compiler-challenge, scores
971 and 994): >280 gathers can be replaced by **selection trees over
preloaded node values**, after which valu:load:flow is balanced to 7.5:2:1
in every individual cycle, with instruction selection and scheduling done as
ONE joint search.

**Our rejection** (G-23 at the 1038 census, three independent ways; then
P3-C's ~405k-design enumeration at 1006): every optimum has the SHIPPED
shape — L1-L3 served, L4 partial, L5-L10 gathered. Every unserved L4
group-round measures negative (l4_gmin sweep monotone around (9,30); 14
set-form alternatives tie or lose). L5 serving loses by 30-47 cycles BEFORE
scratch is consulted.

**What we already verified about them, and it checks out:** H-043 decoded
their diagram SVGs and their hash is bit-for-bit our 11-op fused form. Our
own census independently re-derived their 7.5:2:1 balance. So they are not
working from a different hash or a different machine model.

### The lead that makes this worth funding

**P3-C's predicted max-floor for the best L5-serving design is 994.0. corsix
scores exactly 994.** Either a coincidence, or our model prices their design
correctly and they realize it at ZERO regret where we measure 11-15 cycles of
regret — which would itself be the finding, since it would mean the gap is
scheduling after all, contradicting Phase 3's census-gap conclusion.

### What "assume they are right" licenses

Under this charter, a Phase-4 result may conclude that one of our own closed
entries is WRONG. G-23 and P3-C's shape enumeration are explicitly IN SCOPE
for refutation. Phase 3 found the same class of defect twice (per-level
rather than per-site calibration; two models agreeing while sharing an
unexamined frame), so the prior is NOT that our closures are safe.

Specifically open for challenge:
1. **Is the routing theorem's `2^d - 1` cost law actually right?** It is the
   load-bearing assumption behind every serve/gather decision. "Selection
   trees over PRELOADED node values" may mean a tree over fewer than 2^d
   candidates, which the law does not model.
2. **Is our L4 sweep's negativity a census fact or a friction artifact?**
   G-23 rejected on measured cycles at a fixed emission order and spelling;
   corsix's claim is explicitly about doing selection and scheduling JOINTLY.
   A move that loses under our greedy could win under joint search.
3. **Does the 7.5:2:1 balance mean what we assumed?** We read it as a
   steady-state average we already achieve. They state it per INDIVIDUAL
   cycle. Those are different claims, and 666/1038 of our cycles having all
   four engines full is not the same as the ratio holding cycle-by-cycle.

### Rules

- Phases 1-3 rules still bind, with ONE exception: "engine X is idle is not a
  hypothesis generator" and "a lower floor is not a win" are heuristics
  earned on OUR design; do not use them to dismiss a mechanism that the
  source claims works. Cost it instead.
- Any refutation of G-23 or P3-C must be by MEASUREMENT or exhaustive
  enumeration, not by re-argument.
- Reading the primary source is preferred over inferring from it. We have
  decoded their diagrams once; do it again for the census.

### Phase 4 interim (2026-07-30): three results, harvested from tools after all
### three scouts died to repeated API/connection errors

All three P4 scouts failed mid-turn (P4-A three times, P4-B and P4-C once
each) with `Connection closed mid-response`. None wrote a STATE file, but
P4-B and P4-C had already written their TOOLS to disk, so the driver ran
them directly. The results below are the driver's own runs of those tools.

**1. The 994 coincidence DISSOLVES (`tools/p4b_994.py`).** The max-floor
distribution is dense near every published score, so a numeric match is
worthless as evidence:

| score | designs within +/-0.5 | within +/-2 |
|---|---|---|
| 958 | 0 | 0 |
| 971 | 1 | 4 |
| 981 | 1 | 4 |
| 994 | **3** | 7 |
| 1002 | **6** | 13 |

Three different designs land within half a cycle of 994 (`L1L2L3+L4x15`,
`L1L2L3+L5x17`, `L1L2L4+L3x15`). And the tell: **our own shipped shape
models at 970.8, which matches corsix's 971 just as well.** Both matches are
noise. Note also the L5x17 design needs 1,789 scratch words and **no
L5-serving design fits at K=32 at all**.

**2. The `2^d - 1` cost law SURVIVES -- for a sharper reason than we had
(`tools/p4b_width.py`).** The per-lane reachable set really is far narrower
than `2^d`: using the group's position one level up, the candidate width is
**at most 16 at EVERY level** (at d=10 that is 16 against 2^10 = 1024;
mean 15.89). And descendant sets are contiguous in memory -- the depth-k
descendants of node v are exactly `[2^k*v + 2^k - 1, 2^k*v + 2^(k+1) - 2]`,
so k=3 descendants are one vload each.

**But the narrowing is never LANE-UNIFORM.** Measured "all 8 lanes share an
ancestor": **0 of 256 group-rounds** at every level >= 3 for every k in
{1,2,3}. A tournament reads broadcast table vectors, so it needs a candidate
set common to ALL EIGHT LANES -- and the only lane-common set at level d is
the whole level. That is why `2^d` is forced. **This is a better statement
of the routing theorem than "no permute": the width is set by lane-
uniformity, not by the absence of a shuffle.** (Also recorded: walkers are
i.i.d. so any static lane->walker assignment gives the same distribution,
and the data is unseeded, so the instruction stream cannot depend on it.)

**3. G-23 AUDIT: one leg sound, one leg overstated.**

*Sound -- the L4 sweep is NOT a spelling artifact* (`tools/p4c_retune.py`).
The worry was P3-D's dual_fold defect: a plan tuned at one `l4_gmin` and
reused across the sweep. Re-tuning at each point measures friction of only
**1-2 cycles, flat across points**: (9,30) 1038->1037, (6,31) 1049->1047,
(6,39) 1053->1051. Inter-point gaps are 14+ cycles, so the ordering is
preserved and G-23's negativity is a census fact. **Audit clean.**

*Overstated -- "we already run his balance" is 64%, not "already"*
(`tools/p4c_ratio.py`). corsix states 7.5:2:1 per INDIVIDUAL cycle; we read
it as a steady-state average. Measured per-cycle:
- exactly 7.5:2:1: **666 cycles (64.2%)**
- compute full: 939 (90.5%)
- **compute-full but NOT at the ratio: 273 cycles (26.3%)**
- **idle-flow AND compute-full: 205 cycles** -- each one vec-op of binder
  relief available in principle (~27 cycles total)
Flow sits at 76.8% utilization with 197 idle slots inside the steady window.
So G-23's first leg is weaker than recorded. **Caveat that keeps it from
being a lever: F-17 already measured this exact class -- a flow-maximized
stream with floor 990 whose realized schedule is 1104, the 33-cycle gap
being select-readiness x flow-bubble anti-correlation.** The 205 is an
upper bound in principle, not reachable capacity.

**Still not done: nobody has read the primary source.** P4-A failed three
times before fetching anything usable. That remains the phase's open item
and the only route from inference to observation.

### Phase 4 RESOLVED (2026-08-01): the contradiction was our own paraphrase

The driver fetched the primary source directly (three targeted fetches; the
scouts' fetch attempts had failed on infra errors). Verbatim findings:

**corsix's actual cost table** (quoted in full in the fetch log):
level d select-style = `2^(d-1) x ("flow" or "valu") + (2^(d-1)-1) x
("flow" or 2x "valu")` -- i.e. **exactly our 2^d - 1 law**, split into
2^(d-1) leaf selects (1 op) and 2^(d-1)-1 interior selects costed at
"flow or 2x valu". Our T1 theorem (precomputed difference tables) makes
interiors 1 valu op, i.e. **our cost model is slightly CHEAPER than the
source's own**.

**">280 gathers can be gainfully replaced"** counts from the PURE-GATHER
baseline (512 gathered group-rounds). We serve 283. **We already implement
the source's recommendation, 3 group-rounds past their threshold.** G-23's
reading of ">280" as "280 beyond ours" was the whole contradiction.

**"7.5:2:1" in the article is the MACHINE's capacity ratio** ("the 7-1/2
'valu' cells, 2 'load' cells, 2 'store' cells, and finally 1 'flow' cell")
-- hardware description, not an achieved per-cycle census claim. P4-C's 64%
measurement audited a claim the source never made (our H-040 summary had
hardened corsix's framing into a stronger claim than the text supports).

**The article contains NO final cycle count, NO census, NO hash-op
reduction, NO index-handling details.** Its only performance statement is
"it was possible to make everything fit into a grid less than 1000 cells
tall". The 971/994 figures were always leaderboard data, not writeup data.

**VERDICT: contradiction dissolved. G-23 stands. The public frontier's
methods remain unpublished below ~1,100 cycles.** Phase-4's real yield is
hygiene: our ledger paraphrases had drifted stronger than the source; the
routing law survived an adversarial audit and gained a sharper proof
(lane-uniformity, not permute-absence).

## Phase 5 charter (2026-08-01): MAX EFFORT, both boards, theory-first

**User directive (verbatim goal):** top the leaderboard for BOTH the index
and no-index benchmarks; autoresearch theoretical/algorithmic optimizations
and do NOT transition to implementation/layout until there is a theoretical
basis for matching/beating the best known feasible result; be creative and
do not assume results found on different regimes still apply; iterate until
matching the best scores.

**LEADERBOARD REFRESH (fetched 2026-08-01, both boards moved):**

| board | #1 | #2 | #3 | our position |
|---|---|---|---|---|
| With Indices (full contract) | **saifalharthi 904** (3 subs) | josusanmartin 940 (41) | jamespayor 958 | 1038 stale entry; current kernel NOT eligible (see below) |
| Without Indices | **saifalharthi 889** (71 subs) | wouterkool 892 | ogotaiking 908 | 1006 eligible |

New facts: the same person now tops both boards, 904/889, delta 15. They
ground the no-idx board first (71 submissions) then ported to with-idx in
only 3 submissions. adrianleb 922 and others new since 7-27. The frontier
moved 940 -> 904 (with-idx) and 892 -> 889 (no-idx).

**BOOKKEEPING DISCOVERY: our shipped kernel never writes inp.indices back**
(`inp_indices_p` appears only in a debug map; tests check values only). So
our 1006 is a WITHOUT-INDICES artifact. The with-indices contract costs us:
round-15 index computation (currently 0 ops by design) + 32 vstores; public
paired deltas run 9-23 cycles. **Targets: 889 no-idx (gap -117) and 904
with-idx (gap ~ -111 after adding writeback).**

**THE STRUCTURAL IMPLICATION.** Phase 3 proved our design space floors at
944-952. A 904 with-indices entry exists. **Therefore the frontier is
outside our enumerated design space -- not better-scheduled inside it.**
Per the user's directive, prior closures are hereby treated as
REGIME-SCOPED: each was proved under frames (11-op hash, per-walker-
per-round evaluation, static lane binding, served-levels serving, 32x8
grouping, level-aligned rounds) that must now be individually escaped, not
respected. The Phase-3 arithmetic says any sub-911 design must break the
hash term or the per-round evaluation structure itself; at 904 the budget
is 54,240 lane-ops and our hash alone is 46,464 + idx floor 6,608 + serving
minimum -- the frames CANNOT all survive.

**Phase-5 rules:**
- Theory-first: no mainline implementation until a design's full census
  clears the target on all engines simultaneously (both boards separately).
- Every prior graveyard entry is citable but NOT binding if the candidate
  design breaks the frame the entry was proved under. State the frame.
- The kf>=3 global hash MITM is now FUNDED (max effort): it is the largest
  open region and 82.4% of the budget sits on the hash.
- No-idx board is a first-class target: round-15 val-only tail, no final
  idx anywhere, and any relaxation the missing writeback enables must be
  re-derived from zero rather than assumed small.

### P5-A RESULT (2026-08-01): 904/889 CANNOT exist at k=11 — the hash frame must break

Budget inversion (`tools/p5a_budget.py`, full k x g grid in strains/p5a):

**k=11 is infeasible at both targets even if serving costs ZERO compute.**
hash 46,464 + idx floor 6,608 + setup ~600 (+808 with-idx tail) exceeds the
lane budget at 904 and 889 outright; and load fails independently. At 889,
free serving still leaves 53,672 > 53,340.

| k (hash ops/round) | 904 | 889 |
|---|---|---|
| 11 | infeasible (>=3 simultaneous frame-breaks, two being proved floors) | infeasible even with free serving |
| 10 | infeasible pure (+10.5cyc, load-binding); FEASIBLE with vload contiguity phi>=0.039 (~9 group-rounds vload-able) | needs phi>=0.066 |
| **9** | **FEASIBLE inside our regime, g in [191,218], 55.5cyc slack** | **FEASIBLE, g in [192,214], 44.5cyc slack** |

Slack at k=9 covers P3-E's ~13cyc support residual plus 11-15cyc regret, so
**k=9 plausibly REALIZES both targets, not merely floors them.**

**Serving innovation alone can never rescue k=11** (min k under free-serving
fantasy = 10). The frontier's gap MUST come from the hash — either a
shorter per-round form or cross-round fusion (which enters the arithmetic
as effective k < 11). This concentrates the entire phase on P5-B (find
k<=10) and P5-C's contiguity question (phi ~ 0.04-0.07 makes k=10
sufficient).

**No-idx relief for us: exactly 0** (round-15 idx cost already 0; nothing
in the census targets 2054..2309). The public 15-cycle with/without delta
is purely the tail OTHERS pay. **With-idx tail for us: +808 lane-ops,
realized +16** by injection into the captured schedule (tools/p5a_tail.py)
— our eligible with-idx entry today would be ~1022. Implementation deferred
per theory-first rule.

### P5-C RESULT (2026-08-01): phi is a red herring; serve-more supplies the load
### relief; k=10 is NOT enough — P5-B needs k=9

**The phi question dissolves.** Natural vload contiguity measures **0.003**
(vs the 0.039-0.066 needed), and every sort/regroup route is strictly
dominated: the **rank lemma** (new, N4) shows any dynamic walker regrouping
needs per-walker ranks = prefix sums ~ 160 vec-eq + 512 stores per bit-pass;
the sorted-children merge property IS real (0/1400 violations,
tools/p5c_sort.py) but a 2-run merge still costs a full pass per round.
Sort-route floor at k=10: 969 vs serve-more's 902. **The load relief a k=10
design needs (82-112 slots) is available INSIDE the existing space: serve
11-14 more L4 group-rounds (-8 ld +15 folds each; 29 available; the b3l
assert capping round-15 serves is relaxable via frame-6 spill).**

**But k=10 still misses.** With serve-more load relief and support priced
honestly (P3-C coefficients, folds spilling to valu):

| k | no-idx floor (target 889) | with-idx floor (target 904) |
|---|---|---|
| 10 | 902 (miss by 13) | 918 (miss by 14) |
| **9** | **859 (clears by 30)** | **875 (clears by 29)** |

**Reconciliation with P5-A's k=10 row** (which said phi>=0.039 suffices):
P5-A idealized serving support to zero; P5-C priced it. The models differ
exactly at the frame boundary — per the Phase-3 convergence rule, the
conservative merged statement stands: **k=10 is feasible only with ~170
vec-ops of support trim that no one has identified (ring is load-blocked;
respelling ~30-60; setup ~13). k=9 clears both targets robustly under BOTH
models, with margin that covers regret.** Corroboration: the model's
with-idx writeback delta at k=10 is 16; the frontier's observed 904-889
delta is 15.

Frames closed: sorting (rank lemma), speculation (select-count identity:
2^(d+1)-1, second hash +11 vec/gr), grouping/epoch/packing (i.i.d. +
symmetric walk + parity-set wash). New primitives recorded: **N1 uniform
cross-lane shift = 1 vstore + 1 vload** (the ledger's 8st+1vld price is for
ARBITRARY permutes; uniform shifts are 4x cheaper — filed for future use),
N2 alu as compile-time lane-crossing engine, N3 data-dependent branching is
legal on this ISA (cond_jump) but costed dead.

**TOP-2 target designs (if k=9 exists):** D1 with-idx = k=9 + serve-more x18
+ lean writeback: floor 875 at C=904 (52,230/54,240 lanes, 1,746/1,808 ld).
D2 no-idx = k=9 + serve-more x22: floor 859 at C=889. Both pass with
realized margin.

> **Phase-5 status: everything now hangs on P5-B. The question "does a 9-op
> round body (or equivalent cross-round fusion, effective k<=9.5 per round)
> exist?" is the whole game for both boards.** Fallback if only k=10 exists:
> the ~170-vec support-trim hunt becomes decisive (queued as contingent,
> not spawned).

### P5-B RESULT (2026-08-01): funded regions ALL NEGATIVE; one structural gap named

`rust_harness/src/bin/global_mitm.rs` (validated by planted positive AND
negative controls; a planted 8-op parallel-prefix form was found and
10M-verified by the kf3-FULL family and proven invisible to the chained-kf3
family — confirming all PRIOR kf>=3 coverage was chained-only):

- **full_hash 11 -> 10 or 9: CLOSED in region.** 59.36M full-shape 3-op
  prefixes (12-const core pool) x meet x suffix chains <=6; 4 x 2.118B
  chain nodes; 0 finds. Prior art stopped at kf<=2 + chain<=5.
- **round12 (fold-in + 11, first search NOT assuming fold-in-first): CLOSED
  <=10.** 184.5M full-shape prefixes over {x,y}+pool; 8 x 2.118B nodes;
  plus pure-forward k<=3 (2.0B). 0 finds.
- **Both 4-op cross-round spans: CLOSED at depth 3.**
- Runtime-multiplicand madd: NOT a coverage gap (forward enumeration covers
  it; structurally impossible in suffixes).
- kf4-chained: shard 0/4096 negative (22.6 min; ~3x kf3 cost, CPU 370%/690%
  -- profile before mass fan-out). Full closure ~64 box-days serial.
  **Driver is grinding slices 1-12 in background (2-concurrent batch).**
- Correction accepted: the driver's per-c1 served-level specialization idea
  is DEAD -- the op stream cannot depend on node values (kernel built from
  shape only, tests/submission_tests.py:24-26).

**THE NAMED GAP: every suffix family searched to date -- across G-10, H-016,
H-025, P3-F, and P5-B -- is a CHAIN (no fan-out). But the real 11-op form
itself has fan-out in its back half (a, d, f each read twice, per P3-F).
A 9/10-op sibling with fan-out in its suffix would have been invisible to
ALL coverage to date.** This is now the highest-probability hiding region,
and P5-D is on it. The <=19-op 2-round composite is beyond enumeration
entirely (needs CEGIS/algebraic synthesis -- also P5-D).

Not-covered list (explicit): kf4 grind 4095/4096 slices, full-shape kf4,
richer-than-12-const pools, fan-out suffixes, 2-round composite.

### Phase-5 addendum (2026-08-01): user directive — explore outside the hash

P5-F dispatched on the three non-hash routes that remain genuinely
unexplored:
(a) **exotic compute suppliers** — load-as-LUT (a load computes an arbitrary
unary function over the 2,566-word image; never framed as compute),
flow-vselect-as-mux-compute beyond serving, store tricks (same-cycle
write-conflict select, mem-as-spill for ring state);
(b) **machine-semantics affordance audit** — a lawyer's read of problem.py
for every unframed semantic (load_offset, write-commit ordering, dict
last-wins writes, unaligned vload bases, const-on-load, immediates,
branching, aliasing under buffered writes);
(c) **audit of P5-A's inversion assumptions** — including whether the
46,464 hash figure double-counts fold-ins already elided by c5_prexor.

Driver pre-check recorded: wholesale hash-on-LUT dies by 2 orders of
magnitude on load capacity; k=11 remains dead even with exotic suppliers
UNLESS the audit finds an assumption hole — the scout's job is the margins
(free ramp/drain load slots ~170, narrow-domain subcomputations) and the
audit. In-flight: P5-D (fan-out hash), P5-E (k=10 trim), kf4 batch 1-12.

### P5-E RESULT (2026-08-01): k=10 FAILS both boards — the trim does not exist

Total legitimate trim: **60-71 vec-ops** (482-568 lane-ops) against the
1,218-1,374 required — and honest costs P5-C's floors omitted (+776 ring
residual, +56 r15 penalty, +128/op slider correction, +16-104 setup) exceed
the trim entirely. Best-case k=10 floors: **902 no-idx / 919 with-idx**,
short 13/15 before regret, realized miss 24-37. The verdict holds even with
every SPECULATIVE trim granted.

Trim ledger (sourced): T-omf -112/-88 (derived; double-count risk flagged),
T-c5-on-round-4-serves -88/-64, T-idx15 -72 (measured rate), T-dual
-210..-296 (speculative). **Everything else is 0**: T1/T3/C1-respell/setup
are already inside the baseline pool (double-count audit); round-0/11
specialization is 0 (stage 1 is already one madd; priming VALUES is
strictly negative; round-10 ^C5 already elided via the primed root); k=10
frees only ~32 scratch words = 1.3 rings (coverage 62.5% -> 64.5%,
negligible).

Audit finds of independent value: (1) **the hash slider overcredits** —
census 46,464 = 12 ops x 512 gr x 8 minus ~336 C5-elision vec-ops, so the
per-op removal unit is 4,096 lane-ops, not 4,224 (+128/op adverse to every
prior k-feasibility number — applied); (2) P5-A's 808-lane with-idx tail is
wrong for T2-style designs (packed accumulator deleted) — P5-C's 192-vec
form stands; (3) partial answer to P5-F's fold-in question: the 46,464
already NETS the c5_prexor elisions, no double-count.

**k=9 survives honest repricing, margins roughly halved**: floors 857-868
(no-idx) / 874-885 (with-idx); realized 868-883 / 885-900; clears 889 by
+6..+21 and 904 by +4..+19.

> **Phase-5 status after P5-E: k=9 or bust, within the alu/valu frame.**
> P5-D hunts k=9 in the fan-out-suffix + CEGIS space; P5-F audits the frame
> itself (exotic suppliers, affordances, inversion assumptions); kf4 batch
> grinds. If all three return negative, the honest position will be that
> the frontier's mechanism remains unidentified after exhausting every
> region we can name — and the next step would be funding the full kf4/
> richer-pool/CEGIS program at much larger compute.

### P5-F RESULT (2026-08-01): the non-hash space is CLOSED — no route to >=13
### cycles exists outside the hash; the inversion HARDENS

All three exotic suppliers dead (`tools/p5f_audit.py`, strains/p5f/STATE.md):
- **load-as-LUT: DEAD.** No qualifying narrow domain exists (the hash is
  nonlinear in val^node, killing node-only tables; idx->node_val IS the
  gather; parity and the tail are already 1-op). Capacity cap ~21 vec-ops
  (~3.5 cyc) even if a domain existed. Only scrap: const-for-vbroadcast
  ~1.5-2 cyc, ramp-locked.
- **vselect-as-mux: CLOSED.** Mux-expressible = 2-valued output with a
  pre-existing condition register = exactly the folds + omf selects already
  in the F-model; flow is oversubscribed at every feasible shape.
- **store tricks: DEAD x3.** Collision-select loses >=8x; N1 round-trips
  have no consumer; **ring-spill-to-mem is infeasible** because the ring
  shortage is LIVE-WINDOW concurrency (accumulators touched every served
  round): ~100-360 mid-schedule vloads needed vs 4 free steady load slots
  (62-64 at k=9 designs). **Ring coverage >62.5% is now closed in BOTH
  directions** (scratch: P3-E; memory: here).

**Affordance audit: 23 rows, UNFRAMED count ZERO.** Every semantic in
problem.py is either already exploited or dead with a stated reason. The
ISA inventory behind the idx-floor and routing arguments is complete.

**Inversion audit: all six assumptions HOLD, and the bound HARDENS.**
New airtight leg for the flow question: any load-feasible shape has
g<=214 => served>=298 => min folds 1,334 > flow capacity at both targets —
**flow never has an idle slot** (kills scalar add_imm offload and every
idx-on-flow hybrid at the root). The elision question is settled exactly:
**hash(k) = 512k + 176 vec-ops** (elisions = 336; two independent census
decompositions agree). k=11 free-serving overruns re-derived at +4.3/+5.8
cycles (was +4.0/+5.5).

**Net: k=9 (P5-D's search) is the only live route, and it remains
sufficient — adjusted floors ~863 (no-idx) / ~879 (with-idx) vs targets
889/904.**

### P5-G RESULT (2026-08-01): zero public mechanisms — but the frontier's METHOD
### is documented, and it reframes the search

25 sources mined (full table strains/p5g/STATE.md). NEW-technique count: 0.
Frontier players deliberately withhold (Nareg: "Anthropic has asked for
solutions to remain private"). But three strategic findings:

**1. The 889-940 frontier is AGENT-SEARCH operations, not secret human
insight.** josusanmartin (923/940) runs a public problem-agnostic
optimization harness (github: problem-agnostic-optimization-skill,
scorebench); his own words on Discord: "I don't even know what the kernel
does, and here I am." stool233 (926) = Codex harness + scheduler-aware
profiler. saifalharthi (904/889): 71 submissions to 889, then 3 to 904
(delta 15 ~ our modeled writeback 16 — corroborates our tail model).
**Implication: whatever the frontier found, it was found MECHANICALLY. If
k<=9.5 is right, a shorter hash form is discoverable by automated search —
which points at stochastic superoptimization (STOKE-style), not derivation.**

**2. This names OUR sharpest coverage gap: ARBITRARY CONSTANTS.** Every
MITM we have run uses a 12-const structured core pool. A 9/10-op form
using a magic constant outside that pool is invisible to ALL coverage to
date — and constant-mutation is exactly what stochastic search does
natively. The gap is now: (fan-out suffixes) x (arbitrary constants),
jointly reachable by MCMC and by nothing we have run.

**3. Nareg Amirian Megan: 966 no-idx, mechanisms withheld, pillars "op
reduction + ALU/vector co-use + DAG scheduler." 966 sits EXACTLY at our
predicted realized ceiling (floor 944-952 -> realized ~965-970).** This
independently validates the Phase-3 model: 966-class results need NO
k<11 — our own design space reaches them. The unexplained band is only
889-958.

Also: dougall = Dougall Johnson confirmed (nothing published);
josusanmartin's VLIW module quotes "contract-aware omission only when
output semantics prove state is unobserved" (we already bank this: no-idx
relief, mem_prime tree-trashing, scratch unobserved) and lists "fuse
stages... change representation/primitive" as escapes — consistent with
our k-reduction theory, no new mechanism named. Unmined channels:
Paradigm optimization-arena (JS-walled), kerneloptimization.fun API
(server broken).

**ACTION: P5-H dispatched — STOKE-style stochastic superoptimizer
(MCMC over 9-11-op programs, arbitrary-constant moves, correctness
cascade), the search class the frontier's own method points at.**

### P5-D RESULT (2026-08-01): fan-out gap quantified and partially closed;
### "sandwich9" is the headline open shape

**Shape census (exact DP, brute-validated to n=6):** n=10 fan-out wiring
shapes = **1.145 x 10^12** — global enumeration is impossible, permanently.
The enumerable increment is the join-at-4 family (494 shapes): searcher
built (`fanout_mitm.rs`), selftest ALL PASS including a negative control
proving P5-B's family was blind to the planted fan-out form.

**New lemmas:** (A) `v +/- (v>>s)` is never bijective mod 2^w, so
additive-shift links are provably absent from chain suffixes; (B) add-joins
absorb into madd addend slots while xor-joins do not => **g=xor is the
priority tier** (the real form's own join type).

**CEGIS closures (z3, sample-UNSAT = sound):**
- **span7->5: ALL 10 templates UNSAT** — the <=19-op 2-round composite has
  no local entry point left at the round boundary.
- hash11->9 deletion shapes: 16 UNSAT / 12 TIMEOUT / 0 found.
- **sandwich9 (madd/sigma/madd/sigma/madd — THE natural 3-madd 9-op shape,
  all constants+shifts+multipliers free): TIMEOUT at 424s = OPEN.** The
  single most plausible 9-op shape is undecided.

**MITM:** joined-kf3 g=xor slice 0/16 NEGATIVE (24.2M joined prefixes x
2.118B chain nodes). PROVEN-EMPTY registry written for cross-checking any
P5-H stochastic find (a find inside a closed family = a bug in one searcher).

**Driver fleet actions (this iteration):** slice 1 running (P5-D handoff);
fleet launcher armed — g=xor slices 2-15 then g=add 0-15, sequential,
preempting further kf4 batches per P5-D's economics (32 box-hours covers
the whole join-at-4 class vs 64 box-days for kf4). **sandwich9 relaunched
by the driver at 3h solver budget** (`tools/p5d_sandwich9.py`, background).
kf4 batch: 6 more slices complete, all negative (7/4096 total).

### Iteration close-out (2026-08-01 evening): workflow intel, sandwich9 undecided,
### session-limit interruption

**Deep-research workflow (98 agents; 34 + synthesis killed by the session
limit) — 12 claims verified 3-0 before the cutoff; unverified extractions
recovered from the journal by the driver:**
- **corsix (Pete Cawley) publicly confirmed on X (Mar 5, 2026) that the
  sub-1000 results on vliw-challenge.fly.dev are LEGIT** and that Vogel's
  Lean-"proven" 1,081 load-bound must therefore be flawed — i.e. the
  frontier BREAKS the 2,089-load assumption (load elimination via serving;
  consistent with our serve-more analysis). He also states
  kerneloptimization.fun "doesn't verify properly" (its 1,001-cycle entries
  are harness exploits) — that board is now excluded from consideration.
- Two targeted extraction passes over corsix's article re-confirm: **no
  mention of hash-op reduction or cross-round fusion anywhere** — his
  disclosed technique set is exactly what we ship (Phase-4 reconciliation
  stands).
- fiigii/ai-comp publicly documents WITHIN-round cross-stage fusion
  (stages 2+3 -> two independent madds + xor) — this is our existing
  KQ/AQ fusion, already in the 11-op form. Nothing new.
- Vogel's 1,105 = Claude-Code orchestration; his 1,081 "lower bound" is
  refuted by the frontier's existence (its premise: 2,089 unavoidable
  loads).
- wouterkool GitHub: zero related artifacts (29 repos enumerated).
- dougall CONFIRMED as the operator of vliw-challenge.fly.dev itself
  (announced it on Mastodon 2026-02-01) — the board's legitimacy has a
  named maintainer with a public track record.

**sandwich9: still OPEN after a 10,800s z3 solve (iter=0 timeout).** The
single most plausible 9-op shape remains undecided. Next escalations
(queued for after the session-limit reset): (a) shift-split grind — fix the
two sigma shifts (961 (s1,s2) pairs), each sub-problem far smaller,
parallelizable, sound per-pair; (b) P5-H MCMC restricted to the sandwich9
shape (~10 free 32-bit params — ideal stochastic target). P5-H died on the
session limit mid-calibration; resume after reset.

**kf4 batch complete: shards 0-12/4096 all negative** (~29B chained-4
prefixes extrapolated; grind preempted by the fanout fleet per P5-D
economics). Fanout fleet: slice 1 g=xor still running; launcher armed for
slices 2-15 + g=add tier.

### Fleet update (2026-08-01 late): join-at-4 family closed for xor and add

All 31 slices negative: full_hash_core kf3-join g=xor 16/16 and g=add 16/16
at <=10 ops (each slice ~24.2M joined prefixes x 2.118B chain nodes). The
enumerable increment of the fan-out space is now closed for the two
highest-priority join types (Lemma B ranked xor first as the real form's
own join type; add partially P5-B-redundant). g=sub and g=rsub tiers
launched (32 slices, 2-concurrent). P5-H resumed post-reset with the
sandwich9 shape as its first restricted-MCMC campaign — z3 cannot decide
that shape (424s and 10,800s both timeout at iter=0), so stochastic
evidence is the only remaining probe of the most plausible 9-op shape.

### P5-H RESULT (2026-08-02): STOKE built + calibrated; zero finds; two lemmas
### make sandwich9 exactly attackable

Infrastructure validated by planted controls: free-shape gate PASS (a
planted 12-op re-fused to a validated 10-op in 150s after move/temperature
tuning; two calibration finds validated at 10,065,992 vectors each).

**Campaigns, all zero finds:**
- **Transformation mode (the strongest negative): chains sat ON the real
  11-op form with fusion + arbitrary-constant moves for 1.50B proposals —
  no correct 10-op neighbor ever appeared.** First evidence covering the
  arbitrary-constant space around the known form.
- Round body (t2): 2.07B proposals, best error 179/1024 bits — the
  avalanche wall; free-shape MCMC cannot descend below ~180.
- sandwich9 restricted: 20.9B proposals, best-err 336 — but the planted
  from-scratch gate plateaus at 335, so **this negative is existence-blind
  (proven weak by its own control).** sandwich9 remains undecided by all
  three tool classes: MITM cannot reach it, z3 times out (424s + 10,800s),
  MCMC is existence-blind.

**New exact tools:** (1) odd-multiplier lemma — myhash is bijective, so all
sandwich9 K's must be odd (prunes 7/8 of K-space); (2) analytic back-half
inversion (fixed back-half constants make the last madd+sigma invertible).

**ACTIONS:** P5-I dispatched — bit-serial lift-and-prune exact solver for
sandwich9 (madd triangularity + bounded shift-coupling => per-(s1,s2)
refutation or discovery, 961 independent pairs; sound refutation, full
validation on any survivor). Driver grinding 10 more s9 basin-hopping
slices in background. Fleet tier 2 (g=sub/rsub) running.

### P5-J RESULT (2026-08-02): t1 killed by a cut-vertex lemma; the split-grind
### method is calibrated; workflow fanned out on the remaining 10

- **New sound lemma (cut-vertex):** myhash bijective + increasing slot ids
  => every cut-slot segment is bijective => a cut madd forces K odd (sound
  pre-constraint on 10/12 templates) and a cut shr REFUTES the template
  outright (image <= 2^31 cannot equal a bijection). **t1=[2,3] CLOSED by
  the lemma alone — no solver.**
- **t7=[4,7] 89% decided by shift-split grind:** 853/961 combos — 806
  UNSAT, 47 hard-TIMEOUT, 0 SAT. Stragglers cluster where the deleted
  structure most resembles the real form (the s2=16 column).
- Monolithic z3 escalation is proven futile (all 60s iter=0 even with
  odd-K); the split method runs 1-5s/combo. ~2,300 solves executed.
- **Workflow `p5j-template-grind` launched: one agent per remaining
  template (t9 priority, t0 last) + a t7-finisher — each grinding its
  961-combo space with validated-SAT stop conditions.** Ledger:
  strains/p5j/STATE.md.

### P5-K RESULT (2026-08-02): the 9-op question is SHAPE-COMPLETE

Funnel over the template vocabulary {madd, shr, xorc, xor2}: 514.9B raw
sequences -> 1.151B valid -> 522.2M after two NEW SOUND THEOREMS ->
458,161 canonical shapes materialized across the 7 closest-to-real strata,
ranked in `tools/p5k_queue.json` (2,956 QUEUED; ownership-marked;
sandwich9 = rank 328).

**New theorems:**
- **MINIMUM-SHR: one shr provably cannot compute myhash for ANY constants**
  (s<=30 by bit-window; s=31 by constancy of a directional derivative,
  concrete witnesses recorded). >=2 shrs required — a strong structural
  filter on the whole space.
- **Cut-bijectivity (K2):** a shr at any DAG cut vertex is dead (myhash is
  bijective). Kills all pure chains; the funnel arithmetic closes exactly.

**Corrections to the running picture:** P5-J's queue is really 7 shapes,
not 12 — DEL[2,3] is K2-dead (independently re-deriving P5-J's own t1
closure), DEL[4,6] reduces to 8 ops, and P5-D's "16 UNSATs" decompose as
10 degenerate reductions + 4 real shapes.

**Screens:** 36 z3 screens -> 4 UNSAT (madd-degenerate prefixes), 32
timeout-at-iter=0, 0 SAT. **The perfect tier (808 known shapes, all
madd/sigma-structured with exactly 2 shrs) is z3-resistant AS A CLASS —
P5-I's per-(s1,s2) bit-serial machinery is the designated solver for the
entire tier.** Caveat: the (3,2,1,3) stratum was capped at 8.3% of its
DFS; 678 of the 808 perfect-tier shapes came from it, so the tier is a
LOWER bound — the driver has launched the uncapped completion run
(background, ~40 min).

Everything now converges on one instrument: **P5-I's exact solver
consuming p5k_queue.json in rank order.** The workflow grinds P5-J's
(reduced) template list in parallel.

### Usage-limit wave + recovery (2026-08-02 early AM)

The Fable-5 quota killed P5-I (mid-slice, method proven: "refutation is
cheap-or-never at 25s, all landing at rung k=8"), P5-L (mid-write-up), and
the workflow's t7-finisher; the 10 template-grind agents were force-
returned PARTIAL and their z3 processes died with them. **Tally at the
cut: ~2,250 combos decided across 10 templates, ALL UNSAT, zero SAT.**
t9 is ~87% done, t3 ~97%.

Recovery actions:
- Template grind moved to DRIVER-OWNED background processes (3-proc,
  full bands, immune to model quotas): scratchpad/tgrind.sh ->
  research/strains/p5j/fleet_status.txt on completion.
- P5-I2 and P5-L2 relaunched on model=opus, each inheriting its
  predecessor's incremental STATE.md (the persist-early discipline paying
  off exactly as designed).
- Stratum (3,2,1,3) completion run finished (uncapped enumeration output
  in scratchpad; to be merged into the queue on next harvest).

### P5-L2 RESULT (2026-08-02): THE <=19-OP 2-ROUND COMPOSITE IS REFUTED —
### cross-round fusion is dead; everything reduces to the single-round 9-op question

Complete mechanism accounting over the decomposable space: **total savable
ops = 0** against a required >=5 (>=3 under the most conservative
double-count reading — refuted either way):

| mechanism | max savable | argument |
|---|---|---|
| mask absorption into fold-ins | 2, ALREADY BANKED in the 24-op census | node-table transform |
| sigma-sigma layer merge | 0 | merged layer costs 4 = 2+2 separate (GF(2) exact) |
| madd<->sigma commutation | 0 | z3-UNSAT one direction; NEW TOP-BIT LEMMA the other |
| shorter sigma / mask transport | 0 | sigma floor 2; masks cannot cross madds |
| fold-in into madd addend | 0 | v^y == v+f(y) only for y in {0, 2^31} |
| cross-boundary madd fusion | 0 | needs one of the above |

**New top-bit lemma** (two independent validations: exhaustive width-6/7
with positive controls, and a full 2^32 scan at width 32): a madd commutes
through sigma_s only when **K == +/-1 (mod 2^s)** — and the real form's
(4097, 16) and (33, 19) pairs both fail it. GF(2) side: L19*L16 =
I ^ S16 ^ S19 has rank 32 and minimum implementation cost 4 ops (the
elegant `t = v^(v>>3); out = v^(t>>16)` factorization via S16+S19 =
S16(I+S3)) = exactly the cost of the two layers separately.

**Consequence: effective k<=9.5 via cross-round fusion is DEAD. The
composite question reduces EXACTLY to the single-round m<=9 question,
which P5-I2 (bit-serial exact solver) + the P5-K queue now decide alone.**
Residual scope gap (pre-existing, shared with P3-F): non-decomposable
global restructurings — the (S)-hypothesis gap — not covered by any
accounting argument.

### Fleet complete (2026-08-02): join-at-4 family CLOSED for all four join types

63/63 slices negative across g=xor, add, sub, rsub (each ~24.2M joined
prefixes x 2.118B chain nodes). The entire enumerable increment of the
fan-out space is closed. Tier 3 launched: round12 --join-r y g=xor (the
nv-fanout hole, 48 slices, 1-concurrent behind the template grind).

### P5-I2 RESULT (2026-08-02): sandwich9 754/961 refuted exactly, 0 found,
### 207 survivors — and a theorem that may mass-filter the whole queue

- **New top-bit differential-count theorem (proved + sharp numeric guard,
  0 violations in 528 trials):** for s1+s2 >= 32, the count
  N = #{x : out_0(x ^ 2^31) != out_0(x)} is ≡ 0 mod 2^(33-s2) for EVERY
  constant choice. Computed N_myhash = 2^18 * 8289 (full-domain sweep) =>
  **all s2 <= 14 pairs refuted at once** (68 kills, no solver).
- **Mirror theorem** (on the inverse): valid but vacuous for this shape —
  recorded so nobody re-derives it.
- **v2 width-truncated encoder** (sound, selftested both directions):
  2.8-8.6x faster; 35 more pairs closed.
- **The z3 wall is real**: survivors sit at 560s+/pair; battery size,
  rung choice, and specialized batteries all fail to move it. 207 open
  pairs, one contiguous block, all s2 >= 15.
- Driver launched the 600s/pair escalation grind over the survivors
  (~11.5h). **P5-I3 dispatched (opus)** on the two highest-leverage
  follow-ups: the unpushed n_1-realizability arithmetic (may kill pairs
  solver-free) and the tier-wide mass-filter application of the theorem
  to the entire p5k queue (every queue shape has >=2 shrs, so the
  divisibility argument may transfer — with the transfer conditions to be
  proved, not assumed).

### P5-I3 RESULT + grind status (2026-08-02 morning)

**The realizability arithmetic works: 136 of sandwich9's 207 survivors die
with NO solver** (exact condition, not merely sound: (q, n_1) depend only
on t = s1+s2-31; achievable n_1 for K2 ≡ k (mod 2^(u+1)) is exactly the
window [m(k,u), 2^u - m(k,u)] with a descent-lemma lower bound; verdict
verified against 660+182 planted trials, 32.7% teeth). **sandwich9 ledger:
961 = 479 theory + 209 z3 + 68 differential-count + 136 realizability +
~71 open** (shrinking — the 600s survivor grind has already refuted pairs
beyond the sec-11 list). Still ZERO found.

**Mass filter: the differential-count theorem transfers to only 30 of
3,005 queue shapes** — a bijectivity precondition (T6a) is load-bearing,
caught by the numeric guard on a shape that passes every other condition
(104/198 violations). Each transferred shape narrows 961 -> 174 open
pairs. 324 more shapes fail transfer only on technicalities (cut test /
even-K split) and are recoverable with more work. Queue statuses left
untouched (nothing actually closed) — correct conservatism.

**Template grind (driver): 9,187/9,610 distinct combos UNSAT, 0 SAT,
423 stragglers** -> targeted 600s escalation launched (3-proc, per-combo).
Fleet tier 3 (round12 y-fanout) and the sandwich9 survivor grind continue.

## Phase 6 charter (2026-08-02): the contradiction narrows to TWO premises

P6-A's elimination (tools/p6a_premise.py; full table strains/p6a/STATE.md):
**P3 (loads), P5 (serving law), P7 (setup) are IMPOSSIBLE as explanations —
even set FREE, k=11 still overruns 904/889 by +4.0/+5.5 cycles.** P2/P4/P6
require violations of proved enumerations or verified source. Two premises
remain live:

- **P1 (hash census): needs only k <= 9.75/9.59 effective** — an 11-12%
  leak, and the (S)-gap (non-decomposable restructurings) is still open.
- **P8 (our reading of "correct"): the boards validate by SERVER-SIDE
  SIMULATION** (verified: the client only builds; the server returns
  {passed, cycles}) **against an UNKNOWN number of instances.** An
  **ε-approximate hash** — wrong on a fraction ε of the 2^32 inputs —
  passes a one-random-instance validation with probability (1-ε)^4096:
  ε=1e-4 -> 66%, ε=1e-6 -> 99.6%. **Our tools reject ε > 1.05e-8; a
  32-probe validator accepts ε <= 3.3e-3. Four decades of forms exist that
  WE discard and a sampling validator would bless.**

**Resubmission GAMBLING is refuted** (wouterkool 892 in 5 subs, glentaggart
981 in 1; position gambles are 256-walker conjunctions with p ~ 1e-15).
The ε-hash is different in kind: high per-instance pass rate, no
resubmission needed. The board operator's own words (dougall, Mastodon,
2026-02-01): the previous board "got overrun by python/rng-exploit
submissions" — the community board exists to stop exploits, but its
instance policy is unpublished.

**Transfer audit (which of OUR negatives survive ε-tolerance):** z3
sample-UNSATs and the bijectivity lemmas survive (sample-UNSAT refutes
even approximate agreement on those samples). **P5-I2/I3's exact-count
kills do NOT survive — 204 sandwich9 pairs RE-OPEN under ε.** MITM
finds=0 counted verified-exact matches only, so ε-near forms would not
have been counted as finds — but conversely, STOKE's cascade (65k -> 10M)
would have logged any 65k-passer that failed 10M validation, and none was
ever logged: weak evidence AGAINST ε-forms in the searched families.

**Phase-6 program:** R1 ε-audit (does any searched family contain ε-near
forms? re-mine MITM probe-match counts + STOKE checkpoints + ε-tolerant
sandwich9); R2 round-0 30-bit-domain hash shortening (SOUND, P5-E left it
unsearched, ~8.5 cyc realistic); R3 served-level-local conjugation
(~2 cyc overhead, a NEW MITM target family); R4 ask the board operator
the validation policy (NEEDS USER CONSENT).

> **STANDING DECISION FLAG FOR THE USER: pursuing ε-approximate kernels
> as RESEARCH (do they exist? is that what the frontier runs?) is in
> scope. SUBMITTING one is a different act — a kernel that is wrong on a
> known fraction of inputs, passing a sampling validator — and will not
> be done without explicit user instruction.**

### P6-B RESULT (2026-08-02): the ε-window is EMPTY — P8 demoted; the
### contradiction re-narrows to P1's (S)-gap

- **The decisive reframe: STOKE's battery (116-232 vectors, not the 32 the
  charter assumed) is ε-BLIND for ε <= 1e-3 — an ε-form would score ZERO
  cost with p = 0.79-0.89 and the chains would have locked onto it. Zero
  hits in 2.95e10 proposals therefore means P5-H's negatives were ALREADY
  ε-tolerant reachability negatives.** No ε <= 3.3e-3 form exists in any
  searched family.
- Deletion forms: all 11 single-op deletions, constants hill-climbed for
  minimum disagreement: **min ε̂ = 0.99951** (4,094 of 4,096 probes wrong).
  Not near; catastrophically far.
- The exact-count kills mostly SURVIVE ε: **887/871/790 of 961 sandwich9
  pairs stay refuted at ε = 1e-6/1e-5/1e-4** (re-opens 3/19/100, not
  P6-A's 204 ceiling — its battery-size figure corrected).
- Relaxed-z3 CEGIS priced and correctly NOT run (~530 CPU-h for a
  question the above answers).
- **Recommendation adopted: P8 is demoted from "second live premise" to a
  re-labelling of P1's (S)-gap.** The ε-question and the standing user
  decision flag are moot in reachable space (the flag stays on record for
  the counterfactual).

**The contradiction now rests on a single premise: P1 via the
non-decomposable-restructuring gap — or on something outside every frame
eight phases have named.** Live exact questions: the 71 never-refuted
sandwich9 pairs (grinding at 600s), 423 template stragglers (escalating),
the 2,956-shape queue. Sound unfunded finds from P6-A now funded: R2
(round-0 30-bit-domain short hash — a DOMAIN-RESTRICTED search, sound for
32 group-rounds, ~8.5 cyc) and R3 (served-level-local conjugation MITM
family, ~2 cyc overhead).
