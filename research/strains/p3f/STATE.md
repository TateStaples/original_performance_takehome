# Strain P3-F — the 10-op round-body question

status: STILL OPEN (no find; two sub-gaps closed negative)
full record: docs/agent-wiki/p3f-hash-10op-question.md

## One-line answer
No 10-op form found. The fold-in `^nv` and the stage-2 `^C1` are proved
irremovable inside the conjugation / basis-transform / node-table-transform
family by an exact lemma; the `//`,`%`,`cdiv` vocabulary gap named by the
brief is closed negative at depth 1 and depth 2. The only structurally
uncovered region left is the kf>=3 forward-prefix global MITM.

## The lemma (new, exact)
There is a `c` with `y ^ K == y + c (mod 2^32)` for all `y` **iff**
`K in {0, 2^31}`.  (y=0 forces c=K; y=K forces 2K==0.)
Consequence: a xor can never be absorbed into a madd's addend, which is the
only additive slot available. `g19`, `g16` are GF(2)-linear involutions, so
xors transport freely *through* them (that is `c5_prexor`) but never *past*
a madd.

Obstruction constants (tools/p3f_algebra.py part 2):
* O1 remove fold-in: needs `node_val in {0xB55A4F09, 0x355ACF09}`; node
  values are uniform in [0, 2^30). Impossible.
* O2 push `^C1` back through g19: `g19^-1(0xC761C23C) = 0xC761DAD0`. No.
* O3 push `^C1` forward into the stage-3/4 madds: `C1 = 0xC761C23C`. No.

## Searches run (all negative)
* 1-op probe, two-round trace DAG, `//`/`%`/`cdiv` with solved constants
  plus runtime forms: 16,200 questions; 4 confirmed hits, all definitional
  (`a//524288 == a>>19`, `f//65536 == f>>16`).
* depth-2 slice per 3-op block (A: a->d, B: d->e, C: f->x' cross-round with
  `nt2` as a free per-node operand): 6,280 / 11,494 / 21,624 op1 candidates,
  0 hits. Three positive controls rediscovered.

## Corrections to the brief
* runtime-multiplicand `multiply_add` was ALREADY in the searcher
  (rust_harness/src/bin/fusion_search.rs:199, 409, 504) — not a gap.
* level-dependent forms give nothing: level 0's single broadcast node value
  makes `nt` a constant vector, and block C is still 3 ops because removing
  the last one needs the lemma's condition on a runtime-random tree value.

## Next
1. kf>=3 global MITM (only real gap; ~1000x compute).
2. Depth-3 slice for the two 4-op cross-boundary spans (`e->x'`, `f->a'`),
   needs Rust.
3. Prove 4 madds are necessary — combined with the two irremovable xors
   this would close the 10-op question outright. Cheapest route to a proof.

## Tools
tools/p3f_algebra.py   (validation 1,021,609 cases, lemma, 1-op probe)
tools/p3f_depth2.py    (depth-2 slice, POOL constants, positive controls)
