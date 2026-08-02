---
title: P6-C — the native per-pair decider is REFUTED as a force multiplier
date: 2026-08-02
type: research
status: final (on the premise); the briefed artifact was NOT built, by design
task: build a native Rust bit-serial lift-and-prune per-pair decider to replace
      z3 for sandwich9-class shapes, then run it over the 71 open pairs and the
      p5k queue
links: [[../p5i/STATE.md]] [[../p5k/STATE.md]] [[../../RESEARCH.md]]
---

# Strain P6-C — pricing the "native per-pair decider"

status: DONE. **Negative result, with controls.** No Rust binary was written
and no queue status was changed: the two candidate native mechanisms were
priced first (as chartered: "controls first") and BOTH fail. Writing
`rust_harness/src/bin/pair_decider.rs` would have burned a builder on a
provably doomed artifact.

Scratch harness (not committed, scratchpad only):
`p6c_probe.py` (cone/prune/affinity measurements), `p6c_worker.py`
(z3 -> bit-blast -> tseitin -> DIMACS -> pysat/Cadical195 pipeline).

## 0. Headline

| candidate mechanism | verdict | evidence |
|---|---|---|
| bit-serial lift-and-prune over constant bits (the briefed design) | **DEAD at depth 0** | rung-1 survivor sets measured at 2^78..2^117 for the 71 open pairs; pruning is exactly the information-theoretic 1 bit/sample (no exploitable structure); out_0 is NONLINEAR in the constant bits so affine-congruence classes cannot represent the survivor set |
| direct CNF + modern CDCL (Cadical195) | **19x-130x SLOWER than z3** | (29,17): Cadical UNSAT 140.2s vs z3 7.4s. (30,16): Cadical >390s vs z3 3.0s. Verdicts agree where both finish |
| per-shape structural theory kills (window theorem etc.) | **the only real multiplier** | 46.9% of the queue's 2,871,468 (shape, shift) instances die free in 5.6s of Python |

**The premise in the brief ("z3 sits at 560s+/pair") is a misreading.**
Parsed from all 607 CHECKPOINT lines in `research/strains/p5i/STATE.md`:
z3 **refutations** take **median 3.6s, mean 8.0s, p90 11.8s, max 284.9s**
(n=223). The 560s figure is the *timeout on pairs z3 never decides*. The
wall is **non-termination, not slowness** — so a 100x-faster engine buys
nothing on the pairs that matter. This single fact re-prices the whole
charter.

## 1. Why lift-and-prune is dead at depth 0 (p5i sec 4, now measured)

p5i/STATE.md sec 4 asserted this; I re-verified it numerically rather than
inheriting it.

**Measured cone of rung 1** (`out mod 2`), 120 random-constant trials per
pair, flipping each of the 256 constant bits:

    (s1=17,s2=15)  K1=31 C1=31 M1=15 K2=15 C2=15 M2=0 K3=-1 C3=0
    (s1=16,s2=16)  K1=31 C1=31 M1=16 K2=16 C2=16 M2=0 K3=-1 C3=0
    (s1= 8,s2=24)  K1=31 C1=31 M1=24 K2=24 C2=24 M2=0 K3=-1 C3=0
    (s1=30,s2=28)  K1=31 C1=31 M1=28 K2=28 C2=28 M2=0 K3=-1 C3=0

(highest bit index whose flip ever changes out_0; K3=-1 means K3 is dead at
rung 1, as expected from the odd-K lemma.) This EXACTLY matches the v2
encoder's predicted widths Wb=min(32,s1+s2+k), We=min(32,s2+k), Ww=k. The
first output bit already reads **all 32 bits of K1 and of C1**.

**Rung-1 unknown-bit budget** = 2*Wb + 3*We + 3*Ww - 3 (odd-K pinning):

| pair | Wb | We | unknown bits | survivors after the 34-sample battery |
|---|---|---|---|---|
| (17,15) | 32 | 16 | 112 | 2^78 |
| (16,16) | 32 | 17 | 115 | 2^81 |
| (8,24)  | 32 | 25 | 139 | 2^105 |
| (26,27) | 32 | 28 | 148 | 2^114 |
| (30,28) | 32 | 29 | 151 | 2^117 |

**Is the pruning better than ideal?** No. 40,000 random-constant trials per
cell, checking out_0 agreement with myhash_0 on n battery samples:

    (16,16) n=1: 0.49980  n=2: 0.24757  n=4: 0.06120  n=8: 0.00350
    (8,24)  n=8: 0.00415        (30,28) n=8: 0.00415     ideal 2^-n = 0.00391

Exactly 1 bit of pruning per sample — the constraint behaves as a random
Boolean function of the constants. There is no structure for a prune to
exploit, so the explicit-set survivor count is the number in the table
above. **No representation trick rescues it either**: out_0 is not affine
in the constant bits (2000 trials of the 4-point additivity test
f(P)^f(P^d1)^f(P^d2)^f(P^d1^d2) == 0: **116/2000, 143/2000, 167/2000
violations** at (16,16), (8,24), (30,28)), so affine/congruence-class
representations cannot represent the survivor set exactly, and a sound
over-approximation prunes nothing at these densities.

Control 0: my `sandwich_ref` matches `p5i_z3pair.sandwich_py` on 200
random (P, s1, s2, x) — semantics are P5-I's exactly.

## 2. The CNF/CDCL route — built, controlled, and rejected

Pipeline: `p5i_z3pair2.encode_rung` (reused verbatim, so the truncation
soundness guard SELFTEST-TRUNC carries over) -> `Then(simplify, bit-blast,
tseitin-cnf)` -> DIMACS -> `pysat.solvers.Cadical195`. ~194k-221k clauses,
33k-38k vars at k=8; CNF construction 15-30s (Python-side literal mapping).

**Controls (all four pass):**

| control | expected | got |
|---|---|---|
| NEG (5,5) k=1 myhash — window-theorem-refuted pair | UNSAT | **UNSAT in 0.0s** |
| NEG (29,17) k=8 myhash — z3 REFUTED in 7.4s | UNSAT | **UNSAT in 140.2s** |
| POS (5,5) k=1 planted constants | SAT | **SAT in 3.7s** |
| POS (5,5) k=6 planted constants | SAT | **SAT in 150.5s** |

So the pipeline is sound in both directions (it does not fabricate UNSAT)
— and it is **19x slower on (29,17) and >130x slower on (30,16)** (z3 3.0s,
Cadical still running at 390s). z3's BV-level preprocessing, not its SAT
core, is doing the work on this family. A hand-rolled Rust CDCL would start
from a worse position than Cadical195.

**Bonus datum (confirms p5i sec 5's note quantitatively):** the SAT side
explodes with rung even on a trivial pair — (5,5) planted costs 3.7s at
k=1 but 150.5s at k=6, and (16,16) planted is unsolved at k=2 in 185s and
at k=8 in 390s. **No solver route will ever return FOUND.** Only refutations
are harvestable; that is a structural property of the family, not of z3.

## 3. What IS the multiplier: per-shape structural kills

`tools/p5k_queue.json` entries carry op DAGs with **free** shift amounts
(`["shr", src_slot]`), so every open shape carries 31^(#shr) shift
assignments. All 2,988 open shapes (2,956 QUEUED + 32 SCREEN-TIMEOUT) have
exactly 2 shrs => **2,871,468 (shape, shift) instances**.

The window theorem generalizes per-shape with no new proof: out_0 depends
on x mod 2^(D+1) where D = max over x->out paths of the summed shr amounts
(madd/xorc/xor2 are bit-triangular upward; only shr moves bits down). If
D <= 30 the universal witness x=0x4E005510 vs x^2^31 refutes for ALL
constants.

    total instances                       2,871,468
    killed FREE by the window theorem     1,345,350  = 46.9%   [5.6s of Python]
    residual needing a solver             1,526,118
    per-shape kill fraction: min 0.453, median 0.453, max 0.937

(median 0.453 = 435/961 = exactly sandwich9's window row, as it must be
for shapes with both shrs on a common path; the 0.937 shapes have their
shrs on parallel branches.)

## 4. Projected wall-clock for the queue (the number the brief asked for)

Calibrating on sandwich9's own experience — of the 482 pairs that entered
z3, 214 decided (44%, mean 8.0s) and the rest never did at <=600s:

    harvest only the decidable residual   5.42e6 CPU-s  =    63 CPU-days
    with 600s timeouts on the rest        5.15e8 CPU-s  =    16 CPU-years
    instances left UNDECIDED regardless   8.49e5        =  29.6% of the queue

Caveat (stated, not hidden): this assumes only the *window* theorem
transfers. sandwich9's other 248 theory kills came from the row-31/row-32
recursions, the sec-9 differential-count theorem and the sec-12
realizability filter — and P5-I3 measured that the diffcount theorem
transfers to only **30 of 3,005** shapes. If the **324 shapes that P5-I3
found fail transfer "only on technicalities"** were recovered, the residual
drops materially. **That recovery, not a per-pair engine, is the highest-EV
next unit of work.**

Throughput actually achieved by this strain: **~5.1e5 instances/sec** for
the free window kills (single-threaded Python) versus **~0.12 pairs/sec**
(z3, decidable only) and **~0.007 pairs/sec** (Cadical). The multiplier is
7 orders of magnitude — and it lives entirely in theory, not in engineering.

## 5. Sandwich9 open-pair status (refreshed from the live grind)

Reconstructed P5-I3's ALIVE list (71 pairs, sec 12.4) and intersected with
every REFUTED CHECKPOINT/CHECKPOINT2 line: the driver's 600s survivor grind
has since refuted **(27,18), (28,17), (29,16)**.

    sandwich9 ledger now: 961 = 479 theory + 217 z3 + 68 diffcount
                              + 136 realizability + 68 OPEN.   Still 0 FOUND.

## 6. What was NOT done, and why

- `rust_harness/src/bin/pair_decider.rs` — **not written.** Sec 1 refutes
  the design; sec 2 refutes the fallback. Building it would produce an
  artifact that is slower than the tool it replaces.
- `tools/p5k_queue.json` statuses — **not touched.** The window-theorem
  sweep kills *shift assignments*, not whole shapes (median 45.3% of a
  shape's assignments), so no shape is CLOSED. Same conservatism P5-I3
  applied.
- The 46.9% window sweep is a *measurement* here, not a certified closure:
  productionising it (per-shape certificates + a numeric guard with teeth,
  in the style of p5i_proto.py) is a clean, small, well-defined builder
  task and is the recommended follow-up.

## 7. Resume protocol

1. Recover P5-I3's 324 "technicality" shapes for diffcount transfer
   (`tools/p5i3_transfer.py`) — highest EV by a wide margin.
2. Productionise the sec-3 window sweep into a certified per-shape filter
   with witnesses; then re-run the sec-4 projection on the true residual.
3. Do NOT fund: any per-pair native decider, any CDCL port, any longer z3
   budget on 3-madd shapes (p5k sec 7 item 3 already said the last one).
