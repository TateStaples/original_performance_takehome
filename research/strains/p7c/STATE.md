# P7-C: scheduler dependency-model conservatism audit

Task: does dev.py's ListScheduler ever require MORE separation between ops
than problem.py's Machine actually needs? Every such edge class inflates
realized cycles wherever it binds.

Ledger: append after every finding.

## Ground truth from problem.py (VERIFIED by reading source)

`Machine.step` (problem.py:382-429):
- `self.scratch_write = {}` / `self.mem_write = {}` created fresh per bundle.
- `for engine, slots in instr.items():` -- iterates the INSTRUCTION dict's
  own key order (i.e. the order our compiler inserted engines), NOT
  ENGINE_HANDLERS order. ENGINE_HANDLERS is only a name->fn lookup table.
- Every engine handler reads `core.scratch[...]` (pre-bundle values) and
  `self.mem[...]` (pre-bundle values); every write goes to
  `scratch_write[...]` / `mem_write[...]`.
- After ALL engines: `for addr,val in self.scratch_write.items(): core.scratch[addr]=val`
  then the same for `mem_write` -> `self.mem`.
- `run()` (problem.py:240-241): `self.cycle += 1` only if the bundle has any
  non-`debug` engine key. Debug-only bundles are FREE.

Derived TRUE minimum separations (producer at cycle c):
| class | true min sep |
| RAW scratch (write dest -> read it)        | 1 |
| WAR scratch (read -> overwrite)            | 0 (reader sees pre-bundle value) |
| WAW scratch (two writes same addr)         | 0; last `scratch_write[a]=` assignment wins = later engine in instr-dict key order, then later slot_index |
| RAW mem  (store -> load)                   | 1 |
| WAR mem  (load -> store)                   | 0 |
| WAW mem  (store -> store)                  | 0; same last-wins rule |
| store's `src` scratch read                 | RAW 1 from src's producer |
| load's `addr` scratch read                 | RAW 1 from addr's producer |
| flow cond reads (select/cond_jump)         | RAW 1 |
No engine has multi-cycle latency: everything is exactly 1-cycle
producer->consumer, 0 for anti/output deps.

(entries appended below)

## F1 (MEASURED, tools/p7c_bind.py on the 1006 frontier): the three suspect
## classes essentially never bind

Instrumented `ListScheduler.ready` over all 25,718 calls of the shipped
1006 build, decomposing the max into its constraint classes:

    bind_raw 21450 (solebind 11859)   bind_war 7329 (solebind 3627)
    bind_waw 10198 (solebind **0**)   bind_mraw **0**
    bind_mwaw 20   (solebind 19, 665 cyc slack)
    bind_mwar 1    (solebind 1, 13 cyc slack)
    bind_min 11    (solebind 2, 1005 cyc slack)
    bundles=1006 empty=0 debug_only=0  floors {alu 981, valu 995, load 946,
    store 23, flow 797}

- **WAW-scratch (+1 vs truth 0) NEVER sole-binds** -> the conservatism is
  locally inert: every time it is at the max, RAW or WAR is too. (It only
  exceeds WAR when the previous write was dead, which never happens here.)
- **Coarse mem-RAW clock never binds at all** (0/25718).
- Coarse mem-WAW (already at truth via `store_pair=True`: +0) sole-binds 19x;
  coarse mem-WAR sole-binds once.

## F2 (MEASURED, tools/p7c_relax.py): tightening the model to truth is
## worth EXACTLY ZERO cycles, and the ceiling for any tightening is 11

Monkeypatched `ListScheduler.ready` on the 1006 frontier (seed 1):

    base    bundles=1006 cycles=1006 correct=True   (control reproduces)
    waw0    bundles=1006 cycles=1006 correct=True   (WAW-scratch -> truth 0)
    nomem   bundles=1006 cycles=1006 correct=True   (ALL 3 mem clocks DELETED)
    all     bundles=1006 cycles=1006 correct=True   (both)
    nowar   bundles=1011  (unsound; WORSE -- greedy non-monotonicity)
    noraw   bundles= 973  (unsound, all deps deleted; mix also shifts)

- Deleting the entire memory hazard model outright does not move a single
  cycle. So every memory-side conservatism (coarse RAW clock, coarse WAR
  clock, coarse WAW clock) is worth 0 at this frontier, and no
  region/address-disjointness refinement can pay.
- WAW-scratch at truth: 0 cycles (consistent with F1's solebind_waw=0).
- **Ceiling argument**: realized 1006 vs valu slot floor 995 -> at most 11
  cycles of the schedule are NOT valu-slot occupancy. Any dependency-model
  improvement whatsoever is bounded by 11 at the shipped census.
- `nowar` at 1011 shows the greedy scheduler is non-monotone in its
  constraint set: a strictly weaker model can schedule WORSE.

## F3 (MEASURED, tools/p7c_annot.py): the per-op read/write ANNOTATIONS are
## EXACT -- zero over-declaration anywhere

Compared the declared `(reads, writes, mem_read, mem_write)` of all 20,462
scheduled puts against the true sets implied by problem.py's handlers
(alu/valu/load/store/flow, VLEN expansion, const = no mem):

    OVER-declared reads  : NONE      UNDER-declared reads : NONE
    OVER-declared writes : NONE      UNDER-declared writes: NONE
    mem-flag mismatches  : 12x `store:vstore` declared mem_write=False

So the second possible source of conservatism (annotating a superset of an
op's real footprint, which would inflate the RAW/WAR clocks) is absent.
The 12 vstores that skip the mem-write clock are a deliberate
region-disjointness bypass, i.e. the opposite of conservative.

Census (shipped 1006): alu ^ 6506, alu >> 4160, load 1835, valu madd 2911,
valu ^ 1923, flow vselect 775, valu >> 504, valu & 493, alu << 355,
alu + 258, alu & 264, alu - 217, valu vbroadcast 59, valu - 76, vload 48,
vstore 46, flow add_imm 20, const 9, pause 2, alu | 1.

## F4 (MEASURED, tools/p7c_ident.py): the existing bypass flags already
## capture 100% of the memory-model tightening

Same relaxation (`all` = WAW-scratch at truth + ALL mem clocks deleted),
three configs, program digests:

    frontier1006        base=1006  relaxed=1006  (digests differ)
    no_store_pair       base=1013  relaxed=1006
    no_disjoint_region  base=1010  relaxed=1006

All three relaxed builds produce the IDENTICAL program (digest
5c84e9844d8f3c7f) -- as expected once the mem model is gone the mem flags
are inert. Readings:
- `store_pair` is worth 7 cycles and `store_disjoint_region` 4; both are
  ON in the shipped config, and with them on the residual value of a
  perfect memory model is **0**.
- The relaxed build is a DIFFERENT program of the SAME length (1006), and
  is correct on 10/10 seeds. So the model tightening is not merely inert,
  it is measured-neutral on a genuinely different schedule.

## F5 (VERIFIED by reading dev.py:240-282): `trial_place` (emit_any's
pricing path) duplicates the hazard logic with the same WAW +1 and models
NO mem hazards. Inert here: intra-encoding WAW never occurs (the only
multi-op encoding is the 8-lane alu split, whose lanes write distinct
addresses) and emit_any is never given a load/store micro-op.

## F6 (EMPIRICALLY VERIFIED, tools/p7c_semantics.py): ground truth confirmed
## on the real Machine, not just read off the source

    RAW same-cycle        s1=6    -> reader saw the OLD value  => RAW = 1 cyc
    WAR same-cycle        s1=10   -> reader saw old; write landed => WAR = 0
    WAW same engine       s5=40   -> the LATER slot wins
    WAW alu-key-then-flow s5=107  -> flow won
    WAW flow-key-then-alu s5=20   -> alu won
      => the same-cycle WAW winner is the engine whose key was inserted
         LATER into the bundle dict (`for engine, slots in instr.items()`,
         problem.py:395). NOT ENGINE_HANDLERS order -- that dict is only a
         name->function table. Within one engine, later slot_index wins.
    mem RAW same-cycle    load saw 999 (old), mem became 42 => mem RAW = 1
    mem WAR same-cycle    load saw 999, store landed          => mem WAR = 0
    empty bundles         program len 4 -> machine.cycle = 1
      => bundles with no non-debug engine key cost ZERO cycles
         (problem.py:238-241). The shipped program has 0 empty bundles and
         machine.cycle == len(program) == 1006, so nothing is hidden here.

## F7 (MEASURED, tools/p7c_slack.py): the schedule is SLOT-bound, not
## dependency-bound -- 11 cycles is the whole envelope

Per-cycle occupancy of the shipped 1006 program:

    alu   full 966/1006  idle  11  unused  311
    valu  full 975/1006  idle   2  unused   70   <-- the binder
    load  full 945/1006  idle  59  unused  120
    store full  17/1006  idle 977  unused 1966
    flow  full 797/1006  idle 209  unused  209

valu is saturated in 975 of 1006 cycles; only 70 valu slots go unused in
the entire program (= 11.7 cycles' worth), clustered at the head ramp
(cycles 0-7) and the drain (cycles 784-1005, mostly >=900). valu floor 995
vs realized 1006.

## VERDICT: the dependency-model axis is CLOSED

1. Model vs truth diff (all classes):
   RAW scratch 1 == 1 exact | WAR scratch 0 == 0 exact
   WAW scratch 1 vs 0  CONSERVATIVE -> measured 0 cycles (never sole-binds)
   mem RAW coarse whole-mem vs per-address -> measured 0 (never binds at all)
   mem WAR coarse whole-mem vs per-address -> measured 0 (binds once)
   mem WAW coarse+1 vs 0 -> ALREADY at truth via store_pair=True (worth 7)
   read/write annotations: EXACT, zero over-declaration (F3)
   engine latencies: all 1 cycle; no multi-cycle latency to over-model
   slot limits: match SLOT_LIMITS exactly; find_free hint is exact
2. Deleting the ENTIRE memory hazard model plus the WAW conservatism:
   1006 -> 1006, correct on 10/10 seeds (F2, F4).
3. Ceiling: any scheduling improvement at the shipped census is bounded by
   1006 - 995 = 11 cycles, of which 0 is attributable to dependency-model
   conservatism (F7).
4. Corollary for the frontier-gap question: an independently-built
   scheduler with a perfect dependency model could NOT beat 1006 by more
   than 11 at this op census. Any real frontier gap must come from a
   DIFFERENT (smaller) op census, not from scheduling.

Latent soundness note (not conservatism): 12 vstores declare
mem_write=False (`mem_prime_region_hazards=True` in the 1006 mix,
dev.py:2610-2615) and the coarse mem-RAW clock never binds anywhere, so
memory correctness rests entirely on the hand region-disjointness
arguments plus the explicit per-level min_cycles -- the coarse clock is
providing no backstop. Correct today (10/10 seeds); fragile to future
features that add mem readers.

Tools: tools/p7c_bind.py p7c_relax.py p7c_annot.py p7c_ident.py
       p7c_slack.py p7c_semantics.py  (all read-only; dev.py UNTOUCHED --
       every variant was a monkeypatch inside the tool, so no flag was
       needed and no default-OFF risk exists.)
