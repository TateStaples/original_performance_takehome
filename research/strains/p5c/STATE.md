# P5-C: Structural-frame sweep (creative axis) — STATE

Status: FINAL
Task: enumerate every structural frame held fixed across Phases 1-4; cost
breaking each against the 904 (with-idx) / 889 (no-idx) budgets. Amended
mid-task by coordinator: P5-A proved k=11 infeasible for both targets under
ANY serving cost; decisive question became phi (fraction of gathered
group-rounds servable by vload) >= 0.039 (904) / 0.066 (889) at k=10.
Frame 8 skipped per coordinator (P5-A resolved: our no-idx relief is 0).

Budgets: capacity at C = 60C pool (alu+valu lane-ops) / 2C load / C flow / 2C store.
904: 54,240/1,808/904/1,808.  889: 53,340/1,778/889/1,778.

## HEADLINE

1. **phi as framed is achievable in effect but vload/sorting is NOT the cheap
   supplier.** The load relief the 10-op-hash design needs (82-112 slots) is
   supplied inside the existing space by serving 11-14 more L4 group-rounds
   from the already-resident broadcast table (-8 load, +15 flow-eligible
   folds per gr; 29 unserved L4 group-rounds available). Every sorting/vload
   route is strictly dominated (below). Natural (unsorted) contiguity
   measures phi ~= 0.003 << 0.039 — dead.
2. **k=10 is NOT sufficient: floors land 902 (no-idx) / 918 (with-idx),
   short of 889/904 by 13-16 cycles (~170 vec-ops).** k=9 floors at
   859/875 and clears both boards with realistic regret margins.
   => P5-B needs k=9, or k=10 plus ~170 vec-ops of support trimming that
   Phase 3 could not find (ring extension is load-blocked, see frame 6).
3. The model's with-idx minus no-idx delta at k=10 is 16 cycles — matching
   the frontier's observed 904-889=15 almost exactly, supporting the reading
   that the frontier is a shorter-hash + more-serving design, not an exotic
   evaluation structure.

Tools: `tools/p5c_frames.py` (capacity LP, fold-overflow model),
`tools/p5c_sort.py` (walk simulation, 400 trials, real myhash dynamics).

## Verified ISA/machine facts (problem.py, this session)

- SLOT_LIMITS alu 12 / valu 6 / load 2 / store 2 / flow 1 (problem.py:65-72);
  pool = 12 + 6*8 = 60 lane-ops/cycle. VLEN 8, SCRATCH 1536.
- `store (addr, src)`: mem[scratch[addr]] = scratch[src] — **runtime scatter
  legal**, 1 slot/word (:316-318). `load`: runtime gather (:297-299).
  vload/vstore contiguous 8, runtime scalar base (:305-308, :319-322).
- **N1 (new ISA fact): runtime-UNIFORM cross-lane shift = 1 vstore + 1 vload**
  (vstore base, vload base+k, k runtime). Ledger's 8st+1vld price is for
  arbitrary permutations only. Gives 8-lane horizontal reduction in 3 steps.
- **N2 (new): alu is a compile-time lane-crossing engine** — alu operands are
  arbitrary scratch addresses (:243-245): any FIXED cross-lane pattern at
  1 lane-op/word, 12/cycle. Runtime patterns must round-trip mem.
- vbroadcast src may be any scratch word incl. a lane of a vector (:280-282):
  broadcast-from-lane after vload = 1 valu op.
- **mem is exactly 2,566 words**: build_mem_image's `mem[inp_values_p:] =
  inp.values` truncates (problem.py:531-551); stores past 2565 IndexError.
  Dead regions only: indices 2054-2309 (256w, dead from cycle 0 no-idx),
  initial values 2310-2565 (256w after setup), forest L7-L10 words 134-2053
  (1,920w, dead after rounds 7-10 respectively).
- Walk (problem.py:505-518): level(r) = r mod 11; epoch 2 = rounds 11-15 at
  L0-L4; final idx is at LEVEL 5 (5 bits, rounds 11-15). Input unseeded
  (:449,:467) — instruction stream cannot depend on data (P4-B).

## Frame-by-frame verdicts

### Frame 1 — speculative both-children evaluation: DEAD (proof)
At served level d+1, "hash both candidates then select hashed values" =
2 tournaments over 2^d (2^(d+1)-2 sel) + 2 hashes + 1 select vs
1 tournament (2^(d+1)-1 sel) + 1 hash: select counts are IDENTICAL
(2(2^d-1)+1 = 2^(d+1)-1); the second hash is pure overhead: **+11 vec-ops
per speculated group-round, savings exactly 0.** The hoped-for "delete the
node-value serve" does not materialize: the serve doubles instead.
Gather-side speculation (load both children, select after): -1 valu +8 load
+1 flow per gr — load is at exactly 2C at every optimum: dead. We are
throughput-bound; latency relief has no census value.

### Frame 2 — dynamic walker regrouping / sorted vloads: DEAD (cost model + measurement)
- **Rank lemma (the closure): any dynamic regrouping needs collision-free
  placement = per-walker ranks; ranks = (segmented) prefix sums over 256
  walkers.** Rank-free padded scatter collides with certainty at any
  affordable padding (multinomial occupancy, <=1,920 spare mem words).
  Cheapest prefix spelling: alu chain over compile-time scratch addrs,
  255 lane-ops/bit-pass (N2); vector Hillis-Steele with N1 shifts is worse.
  Physical move is scalar scatter: per 1-bit stable-partition pass
  ~160 vec-eq + 512 store + 64 load. Sort to 2^a buckets = a passes:
  a=2: 320 vec-eq + 1,024 st + 128 ld; a=4: 640 + 2,048 st (store-infeasible).
  Per-round maintenance = 1 pass/round: dead outright.
- **Sorted-children merge lemma CONFIRMED** (p5c_sort.py: 1,400 transitions,
  0 violations): sorted parents + stable partition by new bit => exactly <=2
  sorted runs. The merge is real and IS cheaper than a sort — but the merge
  is still one partition pass (~160 vec-eq + 512 st) per round. Epoch 2
  re-scrambles ancestors (fresh bits from root) => own sort needed.
- Post-sort purity measured: P(group node-pure) = 91.6% (sort at L2),
  80.8% (L3), 58.4% (L4); window serve costs used below include straddle.
- Window serve after level-a sort (candidates = 2^k contiguous descendants):
  k=1: -7 ld +1 valu; k=2: -7 ld +3 valu +2 flow-elig; k=3: -7 ld +7 valu
  +6 flow-elig per gr (vload + broadcast-from-lane + newest-bit tournament).
- **LP verdict (p5c_frames.py): the full sort+window-L5 package is dominated
  at every k on every board** — e.g. k=10 no-idx: sort route floor 969 vs
  serve-more-L4 route 902. Reason: serve-more costs 15 flow-eligible ops/gr
  with zero stores/vloads; the sort route pays 320 vec-eq + 1,024 st up
  front for the same load relief.
- **Natural contiguity (no sort), measured on real walks:** P(8 lanes in an
  unaligned 8-window): L5 0.0002, L6-L10 ~0; 16-window: L5 0.0295
  (~0.94 gr/round at 0.75 credit), L6+ ~0. Total natural phi ~= 0.003 vs
  0.039 needed — and exploiting it needs data-dependent branching whose
  per-group test (~6 ops + 1 flow, every group-round) exceeds the expected
  savings. DEAD. (L4's "P(win<=16)=1.0" is trivial: the level IS 16 words —
  that is serving, already in-space.)

### Frame 3 — grouping/repacking: DEAD (proof, inherited + N2 note)
Walkers i.i.d., input unseeded => any static assignment is
distribution-identical and the stream cannot condition on data (P4-B).
Tournament cost per group-round and gather cost are grouping-invariant.
N2 makes any compile-time repack cheap (1 alu op/word) but there is nothing
to buy with it — census invariant.

### Frame 4 — epoch asymmetry: VERIFIED NONE
problem.py:505-518: epoch 2 (rounds 11-15) is structurally identical to
rounds 0-4 (all walkers re-enter root at round 11); the only asymmetries are
round count and the round-15 tail (no successor work), both already banked
(P3-B: wrap and last round cost 0). Nothing new. Moved on per brief.

### Frame 5 — packed/narrow bookkeeping: DEAD (lemma-based)
Two-groups-per-vector position accumulators: the shared madd
(acc' = 2 acc + b_packed) saves 1 op per pair-round but building b_packed =
b_A + b_B*2^16 costs >=1 op: exact wash at best. P3-B's complete one-op
parity output set {p, p-2, p*2^31} contains no 2^16-scaled form, so the
packing addend cannot be produced in the extract itself; unpack at gather
boundaries adds more. >= break-even everywhere, no win.

### Frame 6 — store engine + dead mem as scratch extension: DEAD for census, ALIVE for allocation
Inventory (verified): 256w indices (cycle 0, no-idx), 256w initial-values
(post-setup), 1,920w forest L7-L10 (after rounds 7-10). Store slots free:
~1,780 at the optimum. **But every staged word must come back through a
LOAD, and load sits at exactly 2C at every optimum found** (k=11: 1,890 =
2x945; k=10+serve-more: 1,802/1,808; k=9: 1,714 vs 1,718): there are never
free load slots to read staging back. Ring-coverage extension (P3-E's 62.5%
-> 100%, worth 97 vec-ops) costs ~96 vloads: displaces its own benefit via
the serve-more exchange rate (~180 F-ops) — net negative. **Real value:
spill target for register allocation — specifically relaxing the b3l
funding assert (perf_takehome.py:729) that caps round-15 L4 serving at 5
groups, which is exactly what serve-more-L4 needs relaxed.**

### Frame 7 — cross-epoch software pipelining: SKIPPED (per brief)
The per-walker value chain is the only serializer; any slack is generic
scheduling, no structural op saving. No census delta.

### Frame 8 — no-idx from zero: SKIPPED (coordinator: P5-A resolved, relief 0)
Retained for the record: lean with-idx writeback = 4 madds + 1 extract +
1 bias-add per group (final idx at level 5 = 31 + 5 path bits, Horner) +
32 vstores ~= 192 vec-ops + 32 st. Used in the with-idx rows below.

### New frames found (beyond the briefed 8)
- **N1 uniform cross-lane shift (1 vst + 1 vld)** — ISA fact, corrects
  ledger price for the uniform case; enables cheap horizontal reductions.
  No standalone census win found.
- **N2 alu as compile-time lane-crossing engine** — 12 lane-ops/cycle of
  cross-lane compute for fixed patterns. Load-bearing in the rank lemma
  costing; no standalone win.
- **N3 data-dependent control flow (cond_jump)** — legal, never used in any
  phase; makes cycle count input-dependent. Costed: per-site test+branch
  (~6 ops + 1 flow every group-round) vs expected savings at measured
  natural clustering (0.03-3%): strictly negative. Only pays on clustered
  layouts, which frame 2 shows are unaffordable. DEAD.
- **N4 rank lemma** (under frame 2): the general closure for ALL dynamic
  data-movement schemes on this ISA.

## Capacity results (tools/p5c_frames.py; fold-overflow model)

Decomposition of the P3 ~946 floor design: pool_base 53,286 (zero overflow),
F = 1,366 flow-eligible (folds + omf), load 1,890, store 96.
Law: feasible at C iff pool_base + 8*max(0, F - C) <= 60C, load <= 2C, store <= 2C.

| design | pool_base | F | load | floor | binds |
|---|---|---|---|---|---|
| k=11 as-is (no-idx) | 53,286 | 1,366 | 1,890 | **945** | pool+load |
| k=10 + serve-more-L4 x11 (no-idx) | 49,062 | 1,531 | 1,802 | **902** | pool/flow |
| k=10 + sort+window-L5 (no-idx) | 53,414 | 1,558 | 1,794 | 969 | pool/flow |
| k=9 + serve-more-L4 x22 (no-idx) | 44,838 | 1,696 | 1,714 | **859** | pool/flow |
| k=11 + writeback (with-idx) | 54,822 | 1,366 | 1,890 | 967 | pool/flow |
| k=10 + serve-more x7 + writeback | 50,598 | 1,471 | 1,834 | **918** | pool/flow |
| k=9 + serve-more x18 + writeback | 46,374 | 1,636 | 1,746 | **875** | pool/flow |

Serve-more supply: 29 unserved L4 group-rounds = up to 232 load slots at 15
F-ops/gr. Needed at k=10: 112 (no-idx) / 82 (with-idx). phi thresholds are
met by serving, not vloads.

## TOP-2 DESIGNS

**D1 (with-idx, target 904): k=9 hash + shipped serve shape + serve-more-L4
x18 + lean writeback.** Census at C=904: pool 46,374 + 8*max(0,1,636-904)
= 52,230 <= 54,240; load 1,746 <= 1,808; flow 904/904; store 128 <= 1,808.
Floor 875, realized estimate ~885-895 <= 904. PASSES with margin.

**D2 (no-idx, target 889): k=9 hash + serve-more-L4 x22.** Census at C=889:
pool 44,838 + 8*max(0,1,696-889) = 51,294 <= 53,340; load 1,714 <= 1,778;
flow 889/889; store 96. Floor 859, realized ~870-885 <= 889. PASSES.

Fallback if only k=10 exists: floors 902/918 — both boards MISSED by 13-16
cycles; the shortfall (~170 vec-ops) has no identified supplier (ring
extension load-blocked; fold-respelling worth ~30-60; setup ~13).

## FRAME TABLE (ranked by cycles-unlocked x plausibility)

| rank | frame | verdict | cycles unlocked | evidence |
|---|---|---|---|---|
| 1 | serve-more-L4 (in-space, unlocked by shorter hash) | ALIVE, census above | 43 (945->902 at k=10); required leg of D1/D2 | p5c_frames.py |
| 2 | frame 6 dead-mem staging | census DEAD (load at exactly 2C); ALIVE as allocator spill to relax perf_takehome.py:729 | 0 floor; enables serve-more realization | region map verified |
| 3 | frame 2 sort/vload | DEAD: dominated at every k, natural phi 0.003 | 0 (sort route is +24 to +67 vs serve-more) | p5c_sort.py, p5c_frames.py, rank lemma |
| 4 | N3 branchy code | DEAD: test cost > expected savings | 0 | p5c_sort.py contiguity |
| 5 | frame 1 speculation | DEAD: +11 vec/gr, savings identically 0 | 0 | select-count identity |
| 6 | frame 5 packing | DEAD: wash by parity-set lemma | 0 | P3-B {p,p-2,p*2^31} |
| 7 | frame 3 grouping | DEAD: i.i.d. + unseeded | 0 | P4-B |
| 8 | frame 4 epochs | verified symmetric | 0 | problem.py:505-518 |
| 9 | frame 7 pipelining | scheduling only | 0 | value-chain argument |

## Honest caveats
- serve-more-L4 floors assume folds spill to valu at 8 lane-ops each and
  ignore realized-schedule regret; P3-E measured serving penalties are real
  (the +2.35-2.96 vec/gr round-15 penalty from P3-D applies to the round-15
  subset of the added serves; adding it moves D1/D2 floors by +2-4 cycles —
  margins hold).
- The 192-vec writeback estimate is a design sketch, not measured.
- Sort costs are my own cost model (two independent spellings agree within
  2x); a cleverer rank scheme below ~100 vec-eq + ~300 st per pass would
  reopen frame 2 — I could not construct one and believe none exists on
  this ISA (rank lemma), but that is an argument, not an enumeration.
