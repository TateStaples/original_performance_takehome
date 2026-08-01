# P5-F: non-hash capacity hunt — exotic suppliers, affordance audit, inversion audit

Status: FINAL
Scout: P5-F, 2026-08-01. Brief: (a) frame the non-alu/valu units as compute
suppliers (LUT / mux / store); (b) lawyer-read problem.py for every semantic
affordance; (c) adversarially audit P5-A's budget inversion at C=904/889.
Tool: `tools/p5f_audit.py` (reproduces all arithmetic below from census
constants). Theory only; no kernel edits.

Coordinator mid-task updates absorbed: P5-E killed k=10's ~170-vec trim, so
the bar for this strain became "find >=13 (no-idx) / >=15 (with-idx) cycles
outside alu/valu, or declare none exists"; and the fold-in question was
cross-checked by P5-E (this strain settles the 336-vs-251 residual exactly).

## HEADLINE

**No route to >=13 cycles exists outside the hash.** The three exotic
suppliers are worth ~0-3.5 cycles combined (all in ramp/drain windows,
overlapping P5-E's respelling ledger); the affordance audit found no
unframed capability worth >=1 cycle at the optima; and the budget inversion
SURVIVES adversarial re-derivation — in fact it HARDENS by +2.1 cyc (k=10)
/ +4.3 cyc (k=9) once the fold-in is priced exactly. Within this machine's
semantics, k=9-or-bust stands. The k=9 slack (30/29 cyc per P5-C) absorbs
the +4.3 adverse correction with margin.

---

## (a) SUPPLIER VERDICTS

### a1. load-as-LUT: DEAD (no qualifying domain; capacity cap ~3 cyc even if one existed)

The affordance is real: `load dest, addr` computes `mem[scratch[addr]]` —
an arbitrary compile-time-known unary function over domain < 2,566
(problem.py:297-299). Constraints that kill it:

1. **Cost per vector-op replaced = 8 load slots + 1 addr op** (table_base +
   key add, unless the key register can be kept pre-biased). Load free
   slots at the CURRENT kernel: exactly **4 in steady 100-950**, ~90 ramp,
   ~82 drain (tools/occupancy_hist.py, this session). At the k=9 target
   designs: 62/64 total (P5-C D1/D2 census). Ceiling even at zero build
   cost: ~170/8 = **21 vec-ops ~ 3.5 cycles**, ramp/drain-locked.
2. **Table build is not free**: mem image is frozen (build_mem_image,
   problem.py:525-551; `mem[inp_values_p:] = inp.values` truncates to
   2,566 words) — every table entry costs 1 `const` (load slot!) + 1 store
   at runtime. The build consumes the same scarce engine the LUT uses.
3. **No qualifying subcomputation exists.** Exhaustive hunt over the
   kernel's narrow domains:
   - value path: 32-bit throughout (val, val^node, all hash stages) — no.
   - hash is nonlinear in val^node, so NO node-only partial-hash table can
     exist (would need hash(v^n) = f(v) op g(n): false for this hash).
   - idx domain (11-bit): the only useful idx->X map, idx->node_val, IS the
     existing gather (the forest is already the LUT, used maximally). Any
     other f(idx) currently costs 1 madd (gaddr' = 2*gaddr + omf+-par);
     LUT replacement = 1 add + 8 loads. Loses 8x.
   - parity path (1-bit): current cost is already 1 op (extract) and the
     consumers are flow-eligible selects/madd addends. LUT loses.
   - with-idx tail final assembly: final idx = 31 + 5 path bits from FIVE
     DIFFERENT rounds' val vectors; combining them costs the same Horner
     madds whether or not a 32-entry table finishes the job; per-lane
     lookup would add 8 loads/group. No win.
   - wrap: costs 0 (level-aligned rounds, P3-B). Nothing to replace.
   Driver's pre-check (wholesale hash-op LUT dies by 2 orders of magnitude
   on load capacity) confirmed independently: one hash op = 512 gr x 8
   loads = 4,096 load slots vs ~1,780 total capacity.

**One live scrap (defer to P5-E's respelling ledger, overlap):**
`const`-instead-of-vbroadcast for compile-time constant vectors: 8 load
slots (const writes any scratch word, 2/cyc) replace 1 valu vbroadcast.
Setup has 59 vbroadcasts (472 lane-ops); ramp free-load budget (~90) funds
~11 of them ~ **1.5-2 cycles**. Runtime-scalar broadcasts can also go
8 stores + 1 vload (store engine is 98% idle) — ramp store budget funds
~24 ~ up to +2 more IF valu is the binder in those exact cycles. Both are
setup-respelling moves, owned by P5-E; recorded here so the driver can
reconcile (numbers are ceilings, not realizable estimates).

### a2. flow-vselect-as-compute: CLOSED (the generalization is exactly the fold class, already modeled, and flow is oversubscribed)

Formal criterion: a valu op is mux-expressible iff its output is 2-valued
per lane AND a register whose nonzero-ness equals the choice bit already
exists (vselect tests !=0, problem.py:334-340; testing a BIT costs the
same v& you hoped to save). Census sweep (h058 buckets, this session):

| valu class | slots | mux-expressible? |
|---|---|---|
| multiply_add (hash 2048, idx 343, routing 504) | 2895 | no — wide-valued |
| v^ / v>> (hash) | 2427 | no — wide-valued |
| v& parity extract | 493 | no — output 2-valued but condition register does not pre-exist; the extract IS its creation |
| v- / omf-style parity-derived constants | 76 | YES — and already counted flow-eligible (P3-B: omf fungible; P5-A: folds + omf "1 flow slot else 1 valu") |
| vbroadcast | 59 | no (but see a1 const scrap) |

So the complete mux-expressible inventory = folds + omf + parity-derived
addends = the F-term of P5-C's fold-overflow model. **No new capacity: at
every target design flow is at C/C**, and the flow-escape closure in (c)
proves min folds > C in ANY load-feasible shape — flow slots are never
idle-and-usable at the optima. The 197 idle flow slots at the current 1038
kernel are the F-17 anti-correlation class (not reachable capacity).

### a3. store-engine tricks: all three DEAD for census

1. **Same-cycle mem write collision as select** (mem_write dict, last-wins
   in engine/slot order, problem.py:394-423): scratch collisions are
   compile-time (slot fields are literals) = "don't emit the first write";
   MEM collisions can be data-dependent via indirect store addrs — a real
   runtime select. Cost per scalar select: 2 stores + 1 readback load +
   >=1 addr op vs 1 flow slot / 1 valu vec-op for 8 lanes. Vector form:
   16 st + 8 ld + ~2 vec-ops vs 1. Loses >=8x on the scarce engine. DEAD.
2. **Store-then-load round trips** (N1 uniform shift, cross-group
   broadcast): no consumer exists — groups are independent walkers, tables
   are built once in setup, the kernel has no horizontal reduction.
   Broadcast-via-mem is the only instance with a target (a1 scrap). DEAD
   as a standalone supplier (confirms P5-C).
3. **Mem-as-scratch ring spill — the coordinator's priority question:
   DEAD, and the reason is sharper than P5-C frame 6's.** The ring
   shortage is LIVE-WINDOW CONCURRENCY, not storage: an uncovered
   (epoch,group) ring's 3 extra vectors (24 words, P3-E §1.2) are read AND
   written every served round of the epoch (accumulator fold P := 2P+b);
   between epochs they are dead and cost nothing to "store". Mem parking
   only relieves dead windows — which are exactly what the borrow miner
   already harvests (measured ceiling 40/64). To cover the remaining 24
   rings via mem the vectors must round-trip DURING the live window:
   >= 1 vload + 1 vstore per touched vector per served round =
   **~100-360 vloads (24 rings x ~4-5 rounds x 1-3 vectors)** vs 4 free
   steady load slots today / 62-64 at the k=9 designs — and the uncovered
   rings are mid-schedule, precisely where the free-load windows (0-100,
   950-end) are not. Even the most charitable reading (single-gap parking,
   1 round-trip per vector per epoch = 72 vloads) exceeds free slots and
   displaces serve-more at ~1.9 F-ops/load, i.e. >=137 F-ops spent to buy
   back the 97-vec residual. **Net negative under every reading. Ring
   coverage above 62.5% has NO route on this machine** (scratch capped by
   P3-E; mem capped here). This closes the last open leg of frame 6.

---

## (b) AFFORDANCE TABLE (problem.py read exhaustively, lines 65-434)

| affordance (line) | semantics | status | use / death reason |
|---|---|---|---|
| SLOT_LIMITS (65-72) | alu 12, valu 6, load 2, store 2, flow 1, debug 64 | exploited | the whole game |
| buffered write commit (393-423) | all reads see pre-cycle state; scratch_write/mem_write dicts committed after all engines | exploited | pair_writes; madd dest==a aliasing (accumulators) |
| double-write same scratch addr | compile-time last-wins (dict, engine insertion order then slot order) | dead | equivalent to not emitting the loser |
| double-write same MEM addr | runtime last-wins via indirect addrs — a data-dependent select | dead | costed a3.1: >=8x on scarce engines |
| `load` (297-299) | mem[scratch[addr]] — runtime gather AND arbitrary unary LUT | exploited (gather) / LUT dead | a1: no qualifying domain |
| `load_offset` (300-304) | dest+offset AND addr+offset both offset | dead-equivalent | identical to `load` with shifted compile-time operands; kernel doesn't use it; zero new capability |
| `vload`/`vstore` unaligned runtime base (305-308, 319-322) | any scalar base, contiguous 8 | exploited | descendant windows (P4-B), N1; phi measured 0.003 (P5-C) |
| `const` on LOAD engine (309-310) | 2 compile-time constants/cycle, no alu/valu cost | partially exploited (9 slots) | a1 scrap: ~11 more vbroadcast replacements fundable in ramp, ~1.5-2 cyc, P5-E's ledger |
| `store`/`vstore` (314-322) | runtime scatter, 2/cyc | exploited (46 slots) | 98% idle; no compute capability |
| `select`/`vselect` (328-340) | mux with built-in !=0 test | exploited | a2: inventory complete, flow saturated |
| `add_imm` (332-333) | scratch + arbitrary imm (mod 2^32, negatives fine), 1/cyc on flow | exploited (20 setup) | as hash-adder: closed by fold pressure ((c) below) — flow never idle at optima |
| `halt` (341-342) | stop; running off program end also stops free | exploited-by-omission | kernel uses no halt |
| `pause` (343-345) / enable_pause | pause if enabled; harness resume | required | 2 flow slots, matches reference yields; immaterial |
| `trace_write` (346-347) | append to trace_buf | dead | write-only buffer, never readable |
| `cond_jump`/`cond_jump_rel` (348-353) | runtime data-dependent branching — LEGAL | dead (N3) | unseeded data (tests/submission_tests.py:24-36) => any skip must be provably-always-taken => compile-time; wrap already free; costed dead by P5-C |
| `jump` (354-355) | loops shrink program LENGTH not cycles | dead | score is cycles |
| `jump_indirect` (356-357) | pc = scratch[addr], runtime-computed target | dead | subsumed by N3 |
| `coreid` (358-359) | id = 0 always (N_CORES=1) | dead | const cheaper |
| debug engine (396-414) | compare/vcompare assert only; debug-ONLY bundles cost 0 cycles (run(), 238-241) | dead as compute | writes nothing readable; free verification only |
| alu op set (243-276) | also `*`,`//`,`%`,`cdiv`,`<`,`==`,`|` single-slot; runtime shift amounts | dead-no-need | kernel needs only + - ^ & << >>; wrap is compile-time, no comparisons exist in census; `//`/`%` are shift/mask fungibles already counted |
| valu (278-293) | any alu op vectorized + multiply_add (the only 2-for-1) + vbroadcast from any word incl. vector lane | exploited | madd fusion is load-bearing in the 11-op hash |
| negative/OOB addresses | scratch values wrapped mod 2^32 => never negative; mem[>=2566] / scratch[>=1536] = IndexError | dead | no wrap trick exists |
| mem image (525-551) | frozen, exactly 2,566 words; `mem[inp_values_p:]` truncates | exploited | dead regions inventoried by P5-C; no shipping of precomputed tables |

No affordance beyond these exists in the Machine class: every handler and
every opcode above is the complete match set (NotImplementedError
otherwise). **UNFRAMED count after this audit: zero.**

## (c) INVERSION AUDIT — every assumption HOLDS; net correction is ADVERSE

Re-derived independently (tools/p5f_audit.py, run this session):

| # | assumption | verdict | numbers |
|---|---|---|---|
| i | every hash lane-op on alu/valu | **HOLDS, airtight** | the only other adders are flow add_imm (1 lane/cyc) and vselect muxes; in ANY load-feasible shape g<=214 => served>=298 gr => min folds = 1,334 > C (904 or 889): flow is oversubscribed by folds alone, zero idle slots for add_imm; LUT can't do 32-bit-domain hash ops |
| ii | idx floor 6,608 | HOLDS | P3-B enumeration; b0=5,888 retracted by P3-D; nothing in this audit touches it |
| iii | 8 loads per gathered gr | HOLDS | phi 0.003 (P5-C), rank lemma; no load-side affordance found (load_offset = load) |
| iv | hash 46,464 incl. fold-in | **HOLDS and is EXACT; correction ADVERSE for k<11** | census decomposes perfectly: madd 2048 = 4x512, shifts 1024 = 2x512, xors 2736 = 5x512 + 176 residual fold-ins => elided = 336 EXACTLY (two independent decompositions; settles P5-E's 336-vs-251 at 336). Exact law hash(k) = 512k + 176 vec-ops => removal unit 4,096 lane-ops not 4,224 => k=10 +2.1 cyc, k=9 +4.3 cyc worse than P5-A's model. NOT double-counted |
| v | setup ~600 | HOLDS (616 measured) | using 616 makes k=11 overruns 4.3/5.8 cyc (P5-A had 4.0/5.5) |
| vi | 60 lane-ops/cyc combined ceiling | **HOLDS** | flow's mux/add capacity already credited via the F-model and blocked by (i); load's LUT capacity has no target (a1); store/debug contribute 0 general compute |

Re-derived headlines: with-idx k=11 FREE-serving demand 54,496 > 54,240
(over 4.3 cyc); no-idx 53,688 > 53,340 (over 5.8 cyc). **The inversion
survives and hardens.** k=9's P5-C slack (30/29 cyc) absorbs the +4.3
fold-in correction: k=9 still clears both boards (~clears by 25).

## NET

- Route to >=13 cycles (rescue k=10) outside the hash: **NONE.** Binding
  reasons: flow oversubscribed by folds in every feasible shape (i);
  load's only unframed capacity (LUT/const) is ~1.5-3.5 cyc,
  ramp-locked, and overlaps P5-E's ledger; store round-trips lose >=8x on
  the load engine; ring coverage >62.5% is closed in BOTH directions
  (scratch: P3-E; mem: a3.3 live-concurrency argument).
- Route to >=30 cycles (reopen k=11): **NONE**, a fortiori.
- One prior-model correction delivered: exact hash law 512k + 176 (feeds
  P5-A/P5-C floors, adverse 2-4 cyc at k<11).
- Phase bet consequence: **k=9 (P5-D fan-out search / CEGIS) is the only
  live route on both boards.** This strain's audit means a k=9 find is
  also SUFFICIENT: no hidden capacity wall behind it (k=9 floors 859/875
  +4.3 = ~863/879 vs targets 889/904).

## Dead ends explored (for the record)

Node-only partial-hash tables (hash nonlinear in val^node — impossible);
idx-update LUT with leaf-wrap folded in (T[idx]+b*L[idx]: 1 load + 1 madd
vs current 1 madd + reused parity — loses); packed-parity tail LUT (packing
costs the Horner it replaces); store-collision vector select (16st+8ld+2v
vs 1); add_imm as steady-state scalar-hash helper (flow never idle at
optima); debug-engine anything (writes nothing); negative-index aliasing
(unreachable: all scratch values wrapped non-negative); data-dependent
drain skipping (must be always-taken => compile-time => already free).
