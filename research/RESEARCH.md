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
