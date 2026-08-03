# Where the Cycles Go

*A top-down explainer of this kernel's theoretical bottlenecks, and the
assumptions underneath them.*

*Anthropic Original Performance Take-home · research phases 1–7 ·
2026-07-23 → 2026-08-03*

---

## 0. Read this first

**The task.** Emit a program for a small VLIW/SIMD simulator that computes a
fixed workload correctly. Your score is simulated cycles. Lower is better.
Full statement in [problem.md](problem.md), machine in [isa.md](isa.md).

**Where things stand.**

|                    | ours (grader-verified) | public frontier | gap  |
| ------------------ | ---------------------- | --------------- | ---- |
| no-indices board   | **1006**               | 889             | −117 |
| with-indices board | **1034**               | 904             | −130 |

**The one-sentence summary of nine phases of research:** we can account for
essentially every cycle we spend, we have shown (as strongly as anything here
can be shown) that the work cannot be done in much under ~945 cycles the way
we do it — and somebody is doing it in 889, which means one of the
assumptions in [§7](#7-the-assumption-ledger) is wrong and we have not been
able to find which.

**What this document is for.** You have not been part of this research. The
goal is to hand you the entire load-bearing structure — the arithmetic, the
four bottlenecks, and every assumption they rest on — compactly enough that
you can attack it fresh. Every claim is stated with what it is grounded in,
so you can tell a measured fact from a modeling choice. Sections 1–4 are
background; §5 is the bottlenecks; §7 is the part most likely to contain the
error.

Detailed derivations live in `research/RESEARCH.md` (phase log) and
`research/strains/*/STATE.md`; refuted ideas in `research/graveyard.md`
(G-1..G-39).

---

## 1. The machine: what one cycle buys you

A program is a list of **bundles**. One bundle = one cycle. A bundle may fire
several independent **engines** at once, and each engine may fire several
**slots** in that cycle, up to a hard per-engine limit:

| engine  | slots/cycle | what it does                                                      |
| ------- | ----------- | ----------------------------------------------------------------- |
| `alu`   | 12          | scalar integer ops                                                |
| `valu`  | 6           | the same ops, 8-wide (`VLEN = 8`)                                 |
| `load`  | 2           | `mem[scratch[addr]]`, `vload` of 8 contiguous words, or a literal |
| `store` | 2           | `mem[scratch[addr]] = scratch[src]`                               |
| `flow`  | 1           | `select` / `vselect`, jumps, `add_imm`                            |
| `debug` | 64          | assertions; free, ignored by the grader                           |

Counting one 8-wide `valu` op as 8 **lane-ops**, one cycle supplies at most:

> **60 lane-ops** (12 alu + 6×8 valu) · **2 load slots** · **1 flow slot**

So a C-cycle program has a hard capacity of `60C` lane-ops, `2C` loads, `C`
flow slots. At the frontier scores that is:

| target         | lane-ops | loads | flow |
| -------------- | -------- | ----- | ---- |
| 904 (with-idx) | 54,240   | 1,808 | 904  |
| 889 (no-idx)   | 53,340   | 1,778 | 889  |

**All three must clear simultaneously.** Most of the analysis below is just
this inequality, applied carefully.

Four ISA facts do more to shape the design than anything else, and are worth
internalizing before reading on:

1. **Vector operands must be 8 *contiguous* scratch slots.** There is no
   shuffle, no permute, no gather, no strided vector access. Getting eight
   arbitrary values into one vector costs 8 stores + 1 vload.
1. **The only data-dependent addressing in the machine is the scalar
   `load`.** `store`'s source is a compile-time slot; there is no
   scratch-indexed *read* other than `load`.
1. **`flow` is one slot per cycle.** But `vselect` is 8-wide, so the flow
   engine retires 8 lane-decisions per cycle — which is why branchless
   selection trees are affordable at all.
1. **`debug` is free.** Correctness checking during development costs nothing
   at grading time.

*(Grounding: read directly off `Machine` in `problem.py`. Never overturned in
nine phases.)*

---

## 2. The workload: what has to happen

A perfect binary tree of height 10 (2047 nodes, 30-bit values), flat in
memory, heap-indexed: node `i`'s children are `2i+1` and `2i+2`.

256 independent **walkers**, each with a running 32-bit value, all starting
at the root. For 16 **rounds**, every walker does:

```python
val = myhash(val ^ tree[idx])          # 6-stage integer mixer
idx = 2*idx + (1 if val % 2 == 0 else 2)
idx = 0 if idx >= n_nodes else idx     # fell off the bottom -> back to root
```

Graded output: the final `values` (both boards) and final `indices`
(with-indices board only).

Two structural facts about this workload drive every design decision:

**(a) Depth is a function of the round alone.** Every walker starts at the
root and descends exactly one level per round, wrapping to the root from the
bottom row. The tree has 11 levels and there are 16 rounds, so a walker's
depth in round `r` is exactly `r mod 11` — *identical for all 256 walkers*.
Nobody's depth depends on their data; only *which node at that depth* does.
This is what makes vectorization and level-specialized code possible at all,
and the current kernel exploits it hard (see §5.2 — it is worth 8,192
lane-ops on its own).

**(b) The only data-dependent operation is fetching `tree[idx]`.** The hash
is pure arithmetic on private state. The index update is arithmetic plus one
bit of the hash output. So the work splits cleanly into three terms:

- **hash** — pure, embarrassingly vectorizable, and by far the largest;
- **index maintenance** — extract parity, advance the address;
- **node-value delivery** — get each lane the right `tree[idx]`. The only
  term that touches memory, and the only one with a real design space.

---

## 3. The current design in one page

Everything below assumes this shape, so it is worth reading even though it is
not itself a bound.

- **Grouping.** 256 walkers ÷ `VLEN` 8 = **32 groups** of 8 lanes. A walker
  is pinned to its lane for all 16 rounds. 32 groups × 16 rounds = **512
  group-rounds** — the unit everything is priced in.
- **Level alignment.** Round `r` is compiled specifically for level
  `r mod 11`, so the wrap is deterministic rather than a runtime compare, and
  each level gets code sized for it.
- **Node-value delivery is level-dependent** — this is the core trade:

| level  | nodes at that level | how the value is delivered                                                                    | cost per group-round |
| ------ | ------------------- | --------------------------------------------------------------------------------------------- | -------------------- |
| L0     | 1                   | it's a constant                                                                               | ~0                   |
| L1–L3  | 2, 4, 8             | **served**: candidate values held in broadcast vectors, a `vselect` tournament picks per lane | `2^d − 1` selects    |
| L4     | 16                  | partly served, partly gathered                                                                | mixed                |
| L5–L10 | 32 … 1024           | **gathered**: 8 scalar `load`s, one per lane                                                  | 8 loads              |

  "Serving" spends compute and flow slots to avoid loads; "gathering" spends
loads to avoid compute. The chosen split is what balances the two scarce
engines. Gathering everything would need 4,096 loads → a 2,048-cycle floor;
serving everything is impossible past L4, since the tournament doubles per
level.

- **The hash runs 11 ops per round per group** in a fused, vectorized form
  (the naive transliteration of the 6 stages costs far more).

**Glossary.** *lane-op* — one 8-wide vector op counts 8, one scalar op counts

1. *group-round* — one group of 8 walkers advancing one round; there are 512.

*k* — ops per round per group in the hash; currently 11. *served* /
*gathered* — the two delivery mechanisms above. *census* — a measured count
of every emitted op, bucketed by purpose.

---

## 4. Where 1006 cycles actually go

Measured census of the shipped stream (`tools/h058_census.py`) — counted from
the emitted program, not modeled:

| bucket                          | alu+valu lane-ops | load slots | flow slots |
| ------------------------------- | ----------------- | ---------- | ---------- |
| Hash                            | 46,464            | 0          | 0          |
| Index maintenance               | 7,600             | 0          | 0          |
| Routing / serving               | 4,809             | 1,832      | 775        |
| Setup                           | 616               | 60         | 22         |
| **total**                       | **59,489**        | **1,892**  | **797**    |
| **implied floor (÷60, ÷2, ÷1)** | **991.5**         | **946**    | **797**    |

Read that table twice. **The hash is 78% of all compute.** The compute floor
is 991.5 and we run 1006, so scheduling slack is ~14 cycles — the schedule is
essentially tight, and *only removing operations moves the score*. Every
strategy that is really "schedule it better" is worth at most ~11–14 cycles,
and each has been measured (§8).

---

## 5. The four bottlenecks

Each subsection states the claim, what it is grounded in, and — most
importantly — **what would have to be true for it to be wrong**.

### 5.1 The hash: 46,464 lane-ops, ~774 cycles by itself

**Claim.** The 6-stage `myhash`, composed with the `^ node_val` input mix and
the parity extraction, can be evaluated in 11 vector ops per group-round, and
no fewer. Total cost obeys an exact law:

> `hash(k) = 512·k + 176` vec-ops → at k=11, **46,464 lane-ops ≈ 774 cycles**

so **one op removed from the round body is worth ~68 cycles** — more than
every other lever in this document combined. That is why nine phases pointed
most of their compute at it.

**Where that law comes from** (`tools/p5f_audit.py`, decomposing the measured
census — it is a fit to the emitted stream, not an a-priori derivation). The
46,464 lane-ops = 5,808 vec-ops split cleanly by opcode:

| opcode         | lane-ops | vec-ops | =                 |
| -------------- | -------- | ------- | ----------------- |
| `multiply_add` | 16,384   | 2,048   | 4 × 512           |
| shifts         | 8,192    | 1,024   | 2 × 512           |
| xors           | 21,888   | 2,736   | 5 × 512 **+ 176** |

4 + 2 + 5 = 11 ops per group-round × 512 group-rounds = 5,632, leaving 176.
The `512·k` term is the round body, run once per group-round; the **176 is
the unelided `val ^ node_val` fold-in** — there are 512 of them, but 336
vanish because the node table is pre-xored at construction, so the fold is
free for those group-rounds. (The 336 checks out two independent ways:
`512 − 176`, and `12·512 − 5,808`.)

This matters because the residual is *not* part of the round body. An earlier
model divided 5,808/11 = 528 and priced op removal at 4,224 lane-ops; the
correct unit is 512 vec-ops = **4,096 lane-ops**. The correction is adverse —
a k=10 form is 2.1 cycles worse than that model predicted, k=9 is 4.3 worse.
**Soft spot:** the k-invariance of the 176 is an argument (fold-in count is a
property of the serving/table structure, not of round-body length), not an
enumeration. A shorter form that changed how folds absorb into the table
would move that constant.

**Grounding.** k=11 is a *search* result, not a proof. All of the following
came back negative:

- exhaustive segment fusion (~4×10¹¹ candidates)
- boundary meet-in-the-middle (2.36×10¹²) and full-hash MITM to depth 7
  (2.9×10¹²)
- CEGIS/SMT: all 9-op deletion shapes UNSAT over 9,285+ shift combinations
- shape-complete enumeration of all 458,161 candidate 9-op wiring shapes,
  with 49.2% of 2.87M instances killed by exact theorems
- an MCMC superoptimizer over arbitrary constants (30B+ proposals) whose
  positive controls confirm it *can* rediscover the real 11- and 12-op forms
  from scratch — and which found nothing shorter
- cross-round fusion (a 2-round composite in ≤19 ops), refuted for all
  decomposable mechanisms by a seam-cancellation theorem

**Why there is no proof, and why that matters.** A formal lower bound is
*barred*, not merely absent: every natural invariant (bit-dependency,
algebraic degree, operator alternation) saturates at 1–2 ops with explicit
witnesses. Unconditionally, all that can be proved is N ≥ 2. "N ≥ 11" holds
only under a *stage-respecting* hypothesis — that an optimal form keeps the
hash's stage structure recognizable. The space that hypothesis excludes is
exactly the space enumeration cannot reach: ~1.1×10¹² wiring shapes at n=10,
with ~28% of the shape queue undecidable at any compute we can afford. This
hole has a name in the research log: **the (S)-gap**.

**How it breaks.** A 10-op or 9-op form exists somewhere in the (S)-gap; or a
representation change (different state encoding, auxiliary state carried
across rounds, a form that is not the hash but agrees with it on every input
that actually occurs) sidesteps the per-round framing entirely. Note that the
approximate-hash escape was checked and is empty: the MCMC battery was
ε-blind, so its 29.5B negatives already cover ε ≤ 3×10⁻³, and deletion forms
measure ε ≈ 1.

### 5.2 Index maintenance: 6,608 lane-ops floor (~110 cycles)

**Claim.** Advancing `idx` costs at minimum 6,608 lane-ops across the whole
run — 1 op (parity extract) per group-round when the successor level is
served, 2 (parity + address `multiply_add`) when it gathers.

**Grounding, and a correction worth noting.** The original charter claimed
8,192 (a flat 2 ops × 512 group-rounds). That was **wrong by 24%**: only 448
of 512 group-rounds emit index work at all, because level alignment (§3)
makes the wrap and the final round free. Cost is also transition-dependent,
not uniform. The corrected floor was then hardened: 1,548,224 structural
one-op forms enumerated with zero solutions, and the complete single-op
parity set over all 2³² constants is `{p, p−2, p·2³¹}`. Carrying the raw
address turns out to be the *unique* zero-extra-op representation — every
rebiasing (`idx+1`, `idx+3`, level-offset split) costs +1,280 lane-ops, and
advancing through a memory table costs +1,280 *loads*, on the engine already
tightest.

**How it breaks.** A representation that made the address free would need
base+displacement addressing, which this ISA lacks. Realistically this axis
holds ~576 lane-ops of slack (~10 cycles), not a breakthrough — it has
survived every audit unchanged.

### 5.3 Routing and serving: one load, or `2^d − 1` selects, per lane-set

**Claim.** To give 8 lanes their 8 distinct node values at level d, you
either gather (8 scalar loads) or run a select tournament over broadcast
candidates (`2^d − 1` vselects). There is no third mechanism.

**Grounding, and a sharpened proof.** The naive argument is "the ISA has no
permute and no scratch-indexed read." An audit found that incomplete and
replaced it with something stronger: the per-lane reachable node set is ≤16
at every level, but it is **never lane-uniform** — across 256 sampled
group-rounds, *zero* share a common ancestor at any level ≥3. Since
tournaments read broadcast (lane-uniform) vectors, tournament width is forced
by lane-uniformity, not by the missing shuffle. The optimal served/gathered
split was then closed by exhausting ~405,000 serving designs; the winner is
the shipped shape (L1–L3 full, partial L4, gather L5–L10). It cross-checks
against a published third-party cost table and comes out slightly cheaper.

**How it breaks.** Anything that makes lanes share ancestors — regrouping
walkers by subtree between rounds — collapses tournament widths. Which leads
directly to:

### 5.4 Loads: 8 scalar loads per gathered group-round

**Claim.** Gathered levels cannot use `vload`, so each gathered group-round
costs 8 load slots (4 cycles of load-engine capacity).

**Grounding.** `vload` requires 8 *contiguous* addresses. Measured natural
contiguity among lane address sets is **0.003**; a k=10 design would need
0.039, and 0.066 on the no-idx board. Every route to manufacturing
contiguity dies on cost: sorting or regrouping walkers needs per-walker
ranks, i.e. prefix sums, at ~160 vector-equality ops + 512 stores *per bit
pass per round*. The "sorted children stay sorted" merge property is real
(0 violations in 1,400 trials) but a merge still costs a full pass per round.

**How it breaks.** Practically, it doesn't — an audit priced this one at
"impossible as an explanation: even with **zero** loads the target still
fails." It is here because it is the assumption people reach for first.

---

## 6. The inversion: the thing that should bother you

Now put §1 and §5 together. This is the central result of the research and
the reason the project is stuck.

**At k=11, the frontier scores are arithmetically impossible — even if
everything else were free.**

At 889 cycles the entire lane-op capacity is 53,340. But:

```
hash (k=11)          46,464
index floor           6,608
setup                  ~600
                    --------
                      53,672   >  53,340
```

That is with **serving, routing, and all overhead priced at exactly zero** —
a fantasy machine that delivers node values for nothing. It still doesn't
fit, and the load engine fails independently. Six premises behind this
arithmetic were individually audited; three are "impossible as explanations
even when free," the rest verified from simulator source.

**k=10 doesn't rescue it either.** With every legitimate trim applied and
support priced honestly, k=10 lands 13–15 cycles short of both boards.

> **So the frontier is running at an effective k ≤ 9.75** — a hash round body
> more than a full op shorter than anything nine phases of search could
> produce — **or it is doing something outside every frame this document
> names.**

Both branches are uncomfortable. The first requires a form living in the
(S)-gap that a well-controlled superoptimizer missed. The second requires a
mechanism nobody here has thought of. The bounds have been audited hard
enough that "we just made an arithmetic error" is the least likely
explanation — but it is not zero, and finding it would be the single most
valuable outcome of a fresh read.

---

## 7. The assumption ledger

**This is the section to attack.** Everything above is downstream of these.
Each row: what is assumed, what it rests on, what it costs to be wrong.

### Verified from the simulator source (very unlikely to be wrong)

| #   | assumption                                                                         | grounding                                                           |
| --- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| A1  | 60 lane-ops / 2 loads / 1 flow per cycle                                           | `SLOT_LIMITS`, `VLEN` in `problem.py`                               |
| A2  | no permute/shuffle/gather; vector operands must be 8-contiguous                    | `valu` / `load` op list                                             |
| A3  | scalar `load` is the only data-dependent read                                      | ISA op survey                                                       |
| A4  | `debug` slots are free and grader-ignored                                          | cycle counter in `Machine.step`; grader sets `enable_debug = False` |
| A5  | the memory image is frozen (so `forest_values_p == 7` is a constant, not a choice) | tests import `build_mem_image` from `frozen_problem`                |

### Modeling assumptions (defensible, audited — but they are choices)

| #   | assumption                                                                             | grounding                                                                                            | if wrong                                          |
| --- | -------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| B1  | **the hash needs ≥11 ops per round**                                                   | ~4×10¹² candidates, four independent tool classes, positive controls passing; **no proof exists and one is formally barred** | −68 cycles per op. This is the whole game.        |
| B2  | **the round body is the right unit** — the hash is evaluated once per walker per round | never varied; cross-round fusion refuted only for *decomposable* mechanisms                          | unknown, potentially large                        |
| B3  | index maintenance floors at 6,608 lane-ops                                             | 1.5M forms enumerated; unique zero-cost representation proved                                        | ~±10 cycles                                       |
| B4  | node values arrive only by gather or tournament                                        | lane-uniformity argument + 405k serving designs exhausted                                            | large, if a third mechanism exists                |
| B5  | walker↔lane binding is static for all 16 rounds                                       | never varied in any phase; permute priced at 8 stores + 1 vload                                      | would collapse tournament widths (§5.3)           |
| B6  | 32 groups of 8, all live simultaneously                                                | K<32 never tested at the design level; W<32 liveness variants measured worse                         | changes scratch/liveness pressure                 |
| B7  | one live address per lane is the index representation                                  | biased/redundant/split forms each priced at +1,280 lane-ops                                          | small                                             |
| B8  | rounds are level-aligned (`r mod 11`)                                                  | worth 8,192 lane-ops vs. non-aligned; verified in shipped code                                       | it is a gain, not a constraint                    |
| B9  | exact bit-for-bit correctness on all 4,096 walker-rounds is required                   | the grader compares final memory                                                                     | approximate-hash escape investigated, empty       |
| B10 | scratch (1536 words) is a real constraint                                              | 1533/1536 currently used                                                                             | relaxation experiments show freed scratch buys ~0 |

### Assumptions about the frontier itself (weakest links)

| #   | assumption                                                      | grounding                                                                                            | if wrong                                               |
| --- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| C1  | the 889/904 entries solve the same problem under the same rules | leaderboard scraped; same VM, same params; an earlier "different rules" theory was disproved and turned out to be our own paraphrase error | the entire §6 inversion dissolves                      |
| C2  | the frontier's hash is our 11-op form                           | one competitor's published diagrams were decoded and matched ours                                    | would mean B1 is false and they found the shorter form |
| C3  | our census attributes ops to the right buckets                  | measured from the emitted stream — and it previously mis-attributed 4,032 lane-ops of tournament selects into the wrong bucket, caught by audit | shifts which axis looks binding                        |

If you have limited attention, spend it on **B1, B2, B4, B5, and C1**.

---

## 8. What has already fallen (so you don't re-find it)

Every bound in this project that mattered was wrong at least once, and in
every case measurement or an adversarial audit found it — never re-argument.
The corrections, compressed:

| claim                                            | fate                                                                                                 |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------- |
| engine slot-floors as the scoring metric         | **retired**: freeing *all* 7,051 vector ops bought 30 cycles. The schedule is dependency-bound, not slot-bound. |
| a 931.6-cycle "ideal floor"                      | **wrong by ~80** — double-subtracted gather combines, dropped setup                                  |
| load-count floors of 1,015 / 1,081               | **artifacts** — they hold the gather count fixed                                                     |
| a 939-cycle achievable floor (two models agreed) | **phantom, twice** — the models shared a frame; measurement broke the tie at 945–948                 |
| a specific −2,072 lane-op restructuring          | **phantom** — built and measured: it costs exactly the upkeep it deletes                             |
| structural floor 944–952, realized ~965–970      | **stands** — three independent models converged *after* their shared errors were removed, and an external 966-cycle entrant sits exactly at the predicted realized ceiling |
| 1006 is a local optimum                          | **verified at the shipped stream**: a 31-axis retune moves nothing                                   |
| the scheduler's dependency model hides a tax     | **closed at zero**: exactly three conservatisms exist versus true commit semantics, none ever sole-binds; deleting the entire memory-hazard model still schedules 1006 correctly. Any scheduling gain at this census is ≤ 11 cycles (valu is saturated in 975 of 1006 cycles). |

**The methodology rules those errors bought.** Cheap to adopt, and each one
was paid for:

1. Score against **realized cycles**, never engine floors — a lower floor
   measured *worse* three separate times.
1. A relaxation oracle must **hold the program fixed**: the scheduler races
   on engine occupancy, so freeing ops silently emits a different program
   (this manufactured a phantom −13).
1. **Convergence between models is not evidence when the models share a
   frame.** Only measurement breaks the tie.
1. Calibrate **per-site, not per-level** (this defect class appeared three
   times).
1. **Guard every theorem numerically** before mass application — form-guards
   caught three false theorems that would have over-killed the search space.
1. **Plant positive and negative controls in every searcher** before trusting
   its negatives.
1. Screen any representation-change proposal for **seam cancellation** —
   every GF(2)-linear conjugation yields an op-identical chain.

---

## 9. Where a fresh perspective is most likely to pay

Ranked by expected value, given everything above:

1. **The (S)-gap (§5.1).** The one region a shorter hash could hide in, and
   the only place a k≤10 form is still possible. It is large (~10¹² shapes)
   and ~28% of it is undecidable by per-candidate search, so progress needs a
   *structural* idea, not more compute.
1. **Break B2 — the per-round evaluation frame.** Cross-round fusion is
   refuted only for mechanisms that decompose into per-round pieces. What the
   refutation does not cover is state carried across rounds in a different
   representation.
1. **Break B5/B4 jointly.** Static lane binding is why lanes never share
   ancestors, which is why tournaments are wide, which is why loads are the
   second-tightest engine. Regrouping was priced and rejected *given* prefix
   sums — is there a cheaper regrouping that exploits the fixed tree shape
   instead of sorting?
1. **Audit C1/C3 — the frontier comparison, and our own census.** The
   cheapest possible resolution of §6 is that we are comparing against
   something we have mis-modeled. That has already happened once.
1. **Not worth your time:** scheduling, packing, emission order, op spelling,
   flow-engine utilization, `vload` contiguity, index representation. Each is
   closed with measured evidence, and each is worth ≤ ~14 cycles even if
   fully won.

---

**Bottom line.** The cycle budget is understood to within ~15 cycles. The
bottleneck is the hash — 78% of all compute, ~774 of the 1006 cycles. Under
every assumption we can justify, the published 889 should not exist. The
bounds are honest and adversarially audited; the mystery is real; and it
lives, most likely, in one of the five assumptions flagged at the end of §7.