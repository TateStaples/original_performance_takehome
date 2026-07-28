---
title: P3-F — Does a 10-op form of the hash round body exist?
date: 2026-07-28
type: research
status: partial
task: Attack the 11-op round body globally (not segment-locally) for a 10-op form; a rigorous negative is worth as much as a find.
links: ["[[INDEX]]", "[[p3d-l4-final-round-service]]"]
---

# Verdict

**STILL OPEN**, but three named sub-gaps are now closed negative and the
op-removal question is reduced to three *exact* algebraic obstructions.
No 10-op form was found. Nothing is claimed as a find.

# 1. What the shipped 11-op round body actually is

Verified by reading `perf_takehome.py:1571-1590` (emission) and
`perf_takehome.py:410-437` (`_fused_hash_constants`), and reconstructed +
validated bit-exact in `tools/p3f_algebra.py`:

```
s  = carried state  (= true val ^ C5, the c5_prexor basis)
nt = per-node table entry (= node_val ^ C5)          <- free, precomputed
 1  x  = s ^ nt                      (fold-in)
 2  a  = x*4097 + C0                 madd   C0=0x7ED55D16
 3  t1 = a >> 19
 4  b  = a ^ C1                      C1=0xC761C23C
 5  d  = b ^ t1
 6  p  = d*33    + ap                madd   ap = C2+C3
 7  q  = d*16896 + aq                madd   aq = C2<<9
 8  e  = p ^ q
 9  f  = e*9 + C4                    madd   C4=0xFD7046C5
10  t2 = f >> 16
11  s' = f ^ t2                      (^C5 elided; parity rides inverted)
```

`tools/p3f_algebra.py` part 1: **1,021,609 cases** (147x147 = 21,609 edge
pairs covering 0, 1, 2, 2^31, 2^32-1 and every `2^k`, `2^k±1`, `~2^k` shift
boundary, plus 1,000,000 random `(val, node_val)` with node_val in [0,2^30)
as `Tree.generate` produces) — **0 mismatches** against `problem.myhash`.

Structure: **4 madds + 2 shifts + 5 xors**, laid out as
`[madd] [3-op block A] [madd madd xor] [madd] [3-op block C, spans the round
boundary]`. Exactly one xor (the `^C5` of stage 6) has already been removed,
by `c5_prexor`.

# 2. WHAT G-10 COVERED (and the gap attacked here)

From `research/graveyard.md` G-10 / G-20 / G-24, stated precisely:

* **G-10 (H-003)**: exhaustive **per adjacent segment**, ~400B candidates —
  every adjacent cut of the 11-op chain at depth *current-1*, plus fold-in
  head 5->4 (130.6B), cross-round tail 5->4 (126.3B), parity-from-c <=4
  (66.2B). Self-test rediscovers the known stage2∘3 fusion. Explicitly
  **NOT a global minimality proof** (global space ~10^28).
* **G-10 update (H-016)**: MITM negative on **all 10 boundaries**, 2.36T+16B
  nodes.
* **G-10 update (H-025)**: same MITM machinery end-to-end on the whole hash
  with **no waypoint assumption**, negative at **depth <= 7 forward / 10
  total**, 2.9T + 1.03B + 2.12B candidates. CEGIS inconclusive (k=4 wall).
* **G-20 (H-036)**: re-derivation / conjugation. Key results reused here:
  (a) every node of the 11-op DAG costs exactly 1 op, so shared new
  intermediates can never win; (b) xor-conjugation transports free through
  xorshifts but is **blocked by madd stages**; (c) parity costs 0 ops.
* **G-24 (H-038)**: compare/select vocabulary, ~1.586T candidates, negative.

**Stated-uncovered by all four**: (i) forward-prefix depth kf>=3 in the
global MITM (P-7's ~1000x cost, unattempted); (ii) op vocabulary — `//`,
`%`, `cdiv` were never used as general ops by any searcher
(`rust_harness/src/bin/fusion_search.rs:97-98`: `BIN_OPS` = Add, Sub, Mul,
Xor, And, Or, Shl, Shr; `+Lt, Eq` under `--cmpsel`; no Div/Rem/CDiv).

**Already covered, contrary to the brief's hypothesis**: runtime-operand
`multiply_add` IS in the searcher —
`rust_harness/src/bin/fusion_search.rs:199 Inst::MultiplyAdd(usize,usize,usize)`,
generated at `:409` and matched at `:504-511`. That angle is not a gap.

# 3. New result A — the three exact obstruction constants

The removable-op question reduces, inside the affine/xor-conjugation family,
to a single lemma.

**Lemma (XOR<->ADD dichotomy).** There exists `c` with `y ^ K == y + c
(mod 2^32)` for *all* `y` **iff** `K in {0, 2^31}`.
*Proof:* `y=0` forces `c=K`; then `y=K` gives `0 == 2K (mod 2^32)`, so
`K in {0, 2^31}`. Numerically confirmed (all 32 single-bit K + 200 random
K, 0 exceptions) in `tools/p3f_algebra.py` part 2.

This is what blocks every "push the xor into a neighbouring madd" move,
because a madd's addend is an **additive** slot (and may be a runtime
per-node vector, which is exactly the freedom one would want to exploit).
`g19` and `g16` are involutions (2*19>=32, 2*16>=32) and GF(2)-linear, both
verified numerically, so a xor can always be conjugated *through* them for
free — that is the whole content of `c5_prexor`.

Applying the lemma to each of the two remaining "spare" xors:

| # | op we would remove | move | required condition | actual value | verdict |
|---|---|---|---|---|---|
| O1 | op 1, `x = s ^ nt` | absorb `nt` into the previous round's stage-5 madd addend (per-node runtime addend is legal!) | `g16^-1(C5 ^ node_val) in {0, 2^31}`, i.e. `node_val in {0xB55A4F09, 0x355ACF09}` | see **CORRECTION** in section 8 | **impossible** (build-time argument, not a range argument) |
| O2 | op 4, `b = a ^ C1` | push backward through `g19` into the stage-1 madd addend | `g19^-1(C1) in {0, 2^31}` | `g19^-1(0xC761C23C) = 0xC761DAD0` | **no** |
| O3 | op 4, `b = a ^ C1` | push forward into the stage-3/4 madd addends | `C1 in {0, 2^31}` | `0xC761C23C` | **no** |

O1 is the important one and is new in this exact form: it says the fold-in
xor is not removable *by any choice of node-value table transform*, because
the node value must cross a multiply before it is used, and only `0` and
`2^31` survive that crossing. The same argument kills the "keep state in a
transformed basis across rounds" family: conjugating by any GF(2)-linear map
just relocates the xor without changing the op count (verified by hand
below), and conjugating past a madd requires the lemma's condition.

Concretely, carrying `f` instead of `s'` gives
`x = g16(f ^ g16(C5 ^ nv))` = xor, shift, xor = still 3 ops; carrying `e`
gives madd, then the same 3. Every waypoint in the chain yields 11.

**Scope of this argument:** it is a complete negative for the family
"current DAG + arbitrary xor/affine conjugation + arbitrary per-node table
transform". It is **not** a global proof; a 10-op program with a different
DAG shape is not excluded.

# 4. New result B — the `//` / `%` / `cdiv` vocabulary gap, closed at depth 1 and 2

`tools/p3f_algebra.py` part 3 — **1-op probe** over the two-round trace DAG
(nodes `s, nt, x, a, t1, b, d, p, q, e, f, t2, s', nt2, <round 2 repeats>`),
all ordered `(source, target)` pairs, with `//`, `%`, `cdiv` constants
*solved* (range intersection for `//`/`cdiv`, divisor intersection for `%`,
plus constant-on-the-left `c//u` and both-runtime `u//v`, `u%v`,
`cdiv(u,v)`):

* **16,200 (op, source, target) questions screened** on 48 structured+random
  samples; 10 screen hits; **4 confirmed** on 200,000 further samples, and
  all 4 are definitional restatements of shifts already in the program
  (`a // 524288 == a>>19`, `f // 65536 == f>>16`, both rounds).
  **Zero new 1-op collapses.**

`tools/p3f_depth2.py` — **2-op question for each of the three 3-op blocks**,
with the extended vocabulary:

| block | question | op1 candidates enumerated | hits |
|---|---|---|---|
| A: `a -> d` (`>>19, ^C1, ^t1`) | 3 ops -> 2 | 6,280 | 0 |
| B: `d -> e` (`madd p, madd q, ^`) | 3 ops -> 2 | 11,494 | 0 |
| C: `f -> x'` (`>>16, ^, ^nt2`), cross-round, `nt2` a **free** per-node operand | 3 ops -> 2 | 21,624 | 0 |

Enumerated subspace, stated exactly: **op1** = any op whose operands are all
runtime trace nodes (binop / `madd(u,v,w)` / `u//v` / `u%v` / `cdiv(u,v)`),
or a shift by 0..31, or an op with a constant drawn from a 31-entry
structured POOL (all hash constants and their `g19`/`g16`/negation/shift
transforms); **op2** = *any* op with its constant **solved** against the
target (xor/add/sub/rsub/and/or/shift/affine-madd/`//`/`%`, plus all
two- and three-runtime-operand forms). Exhaustive over "op1 carries no free
32-bit constant outside the POOL"; **sampled**, not exhaustive, over the
full 2^32 constant space in op1 (that region is G-10's ~400B, base
vocabulary only).

**Positive controls (all rediscovered by the same machinery):**
`g19(a) = a ^ (a>>19)` in 2 ops; `s' = f ^ (f>>16)` in 2 ops;
`e` from `{d,p}` in 2 ops (`madd(p,0x200,0xBB372800)` then `^p`, and the
`madd(d,0x4200,0xACCF6200)` spelling). Machinery is not silently broken.

# 5. Angles from the brief and what happened to each

| angle | outcome |
|---|---|
| Global re-factorization (whole round as one function) | **not attacked at scale** — this is the kf>=3 MITM gap; out of a 100-call budget. Untouched. |
| Unused ISA `//`, `%`, `cdiv` | **closed negative** at 1 op (16,200 questions) and at 2 ops per block (39,398 pairs). Only definitional shift restatements appear. |
| Unused ISA `<`, `==`, `|`, `*` | already closed by G-24 (compare/select, 1.586T) and G-10 (`Or`/`Mul` are in `BIN_OPS`). |
| `multiply_add` with runtime multiplicand | **not a gap** — already in the searcher (`fusion_search.rs:199,409,504`). |
| Algebraic restructuring across the round boundary (basis transform + node-table transform) | **closed negative** by the XOR<->ADD lemma, O1/O2/O3 above. This is the strongest new result. |
| Level-dependent forms (node value from a 2^d table; level 0 is a single value) | **negative.** At level 0 the node value is one broadcast register, so `nt` is a *constant vector*; block C becomes `g16(f ^ K)` with constant `K` — still 3 ops, since removing the last one needs `K in {0,2^31}` (lemma) and `K` is a runtime-random tree value. The 2^d-entry served tables give strictly less freedom than level 0, so they are covered a fortiori. |

# 6. FLOOR IMPACT (hypothetical only — nothing found)

Hash census is 5,808 vec-ops at 11 ops/group-round => **528 group-rounds**.
A 10-op body would remove 528 vec-ops. Using the brief's own conversion
(512 vec-ops ~ 68 cycles, i.e. ~7.5 vec-ops/cycle with alu offload), that is
**~70 cycles**, taking the P3-C/D/E floor band 944-952 down to **~874-882**
and putting 940 comfortably inside the space. The leverage claim in the
PHASE-3 ANSWER is arithmetically correct. **No such body was found.**

# 7. What I would do next (in priority order)

1. **The kf>=3 global MITM.** This is the only structurally uncovered
   region and it is the one that matters. Requires extending
   `fusion_search.rs`'s MITM engine-A to k=4 forward and renting real
   compute (P-7 estimated ~1000x). Everything cheaper has now been tried by
   five independent tool classes.
2. **Depth-3 version of `tools/p3f_depth2.py`** for the two 4-op
   cross-boundary spans (`e -> x'` and `f -> a'`), which the depth-2 slice
   cannot see. Needs the Rust searcher, not numpy.
3. **A madd-count lower bound.** If one can prove 4 madds are necessary
   (three Z-multiplications separated by GF(2)-nonlinear maps, plus the
   two-multiple xor of stages 3+4), then combined with sections 3 and 4 the
   10-op question closes: 4 madds + 2 shifts + 5 xors with two xors proved
   irremovable leaves no slack. This is the cheapest remaining route to a
   real proof and was not attempted here.

# Dead ends explored (recorded so they are not retried)

* Absorbing `nt` into the stage-5 madd addend — O1, dead by the lemma.
* Absorbing `C1` backward or forward past a madd — O2/O3, dead by the lemma.
* Carrying state at any waypoint (`f`, `e`, `a`, `d`) — all give 11.
* Making the last serving fold produce `s ^ nv` directly: the fold is
  `nv = E + b*D` (a madd, `perf_takehome.py:1312`); an xor-basis respelling
  `(s^E) ^ (b*D')` still needs 2 ops, so it ties, never wins.
* `//`/`%`/`cdiv` as general ops — sections 4.

# Files

* `/Users/tatestaples/Code/original_performance_takehome/tools/p3f_algebra.py`
  — reconstruction + 1,021,609-case bit-exact validation, the lemma, the
  three obstruction constants, the extended 1-op probe.
* `/Users/tatestaples/Code/original_performance_takehome/tools/p3f_depth2.py`
  — depth-2 slice with `//`/`%`/`cdiv` + POOL constants + positive controls.

---

# PART 2 — the lower-bound attempt (coordinator's follow-up)

Tool: `tools/p3f_bound.py` (read-only). Everything below is either proved or
labelled as verified-by-enumeration with the enumeration stated.

## 8. CORRECTION to section 3 (O1)

**My first report was wrong on one detail.** I said the two node values that
would let the fold-in be absorbed are out of range. In fact

* `0xB55A4F09 = 3,042,594,569 >= 2^30` — out of range, as stated;
* **`0x355ACF09 = 895,143,689 < 2^30` — IN RANGE.** A single tree node can
  carry it, with probability `2^-30`.

The conclusion survives, but the *reason* must be replaced by a stronger one:

> The kernel is built from `(forest_height, n_nodes, batch_size, rounds)`
> **only** (`tests/submission_tests.py:24-26`); node *values* live in memory
> and are never available to the builder. So the emitted op stream cannot be
> specialised on a node value at all, and even a runtime specialisation would
> save 1 op on 1 node out of `2^(h+1)-1`.

Also checked (`p3f_bound.py` section A): the node table is *already*
maximally free — `T(nv) = g16(C5 ^ nv)` uses the whole transform freedom, and
the required entry `M` is then **uniquely determined** by `nv`, so there is no
residual choice a cleverer table could exploit. The madd's *multiplier* slot
is no help either (`e*B + A` is Z-affine in `e`, so the same lemma applies).
Positive controls confirm that `M in {0, 2^31}` really would be absorbable.
**O1 stands.**

## 9. THE BOUND

### 9a. Unconditional: **N >= 2**, proved.

For fixed `nt`, `R(., nt)` is a bijection of `Z/2^32` (a composition of
bijections). Every 1-op form is therefore either non-injective — `u%c`,
`u//c (c>=2)`, `u&c`, `u|c`, `u<<k`, `u>>k (k>=1)`, `u<c`, `u==c`, `cdiv`,
`u*c (c even)` — and immediately excluded, or it is Z-affine / GF(2)-affine in
`s`: `s^c`, `s+c`, `c-s`, `s-c`, `s*c (c odd)`, `madd(s,c,c')`, plus the
`nt`-mixing forms. `p3f_bound.py` section D refutes all of these by
constant-solving (0 hits for the whole round; both positive controls —
`s^nt` and `4097x+C0` — are rediscovered). **This is the strongest bound I
can prove by invariant reasoning, and it is useless for the 940 question.**

### 9b. Conditional: **N >= 11**, modulo one explicit hypothesis.

**Hypothesis (S).** *P is stage-respecting*: for each `i in 1..6` some value
of `P` equals `phi_i(stage_i)` for a GF(2)-affine bijection `phi_i`, and no
op of `P` is shared between two different stage segments.

**Claim.** Under (S), `|P| >= 11`, so the shipped program is optimal.

Ingredients, each independently verified:

1. **Stages 1, 3, 5 cost >= 1.** Trivial. They are met at 1 (madd), because
   `v + (v<<S) + C = madd(v, 2^S+1, C)`.
2. **Stages 2, 4, 6 cost >= 2.** Their combine is `^`, which no madd can
   absorb. Verified by depth-1 refutation *with full availability of every
   earlier trace value* (`p3f_bound.py` section D):
   `a -> g19(a)^C1`, `a -> g19(a)`, `f -> g16(f)`,
   `d -> (33d+ap)^(16896d+aq)`, and the same three targets given
   `{s,nt,x,a,t1,b,d,p,q,e,f}` — **0 one-op forms in every case**.
   Met at 2 in the shipped program.
3. **The fold-in `^nv` costs 1 and is irremovable** — O1, section 8.
4. **Stage 2's constant `^C1` costs 1 and is irremovable** — O2/O3,
   section 3. (Stage 4's constant is absorbed into `ap`/`aq`; stage 6's is
   absorbed by `c5_prexor`; stages 1/3/5's ride the madd addend.)

Sum: `1 + 2 + 1 + 2 + 1 + 2` (stages) `+ 1` (fold-in) `+ 1` (C1) = **11**.

**What (S) does NOT cover — and this is the whole gap.** A program that never
materialises any stage output, or that shares an op between segments. That
is exactly the region G-10 called "inexhaustive at global scale" and the
region H-025's MITM left open at forward depth `kf >= 3`. **The 10-op
question is still open, and (S) is a real assumption, not a technicality.**

## 10. BARRIERS — why the three proposed invariant lines cannot close it

Each is refuted by an explicit short program with the same invariant value as
the target, so the invariant cannot separate 10 from 11.

| line | barrier witness | cap |
|---|---|---|
| 3. bit-dependency / downward reach | `out = (s < 0xB3A7F001)`: bit 0 of the output depends on **32/32** bits of `s` after ONE op (verified with targeted witnesses, `p3f_bound.py` C). And section B shows the target's maximum required net downward displacement is exactly 31, which a single `>>31` realises. | **<= 1 op** |
| 1. degree / 2-adic filtration | GF(2) algebraic degree, exact on a random 12-variable restriction: `deg(s*s) >= 11/12` vs `deg(target) = 12/12`. One or two ops already reach the target's degree. Any Z/2^32-degree or associated-graded invariant is dominated by the same effect: a single `*` is already maximally nonlinear. | **<= 2 ops** |
| 2. XOR<->ADD alternation, applied globally | The lemma gives a group-theoretic separation (`Aff_Z ∩ Aff_GF2 = {id, +2^31}`, order 2), so a *chain* of bijections would be bounded by alternation length. But the target is **not** a chain: `g19(a)` reads `a` twice, `Phi(d)` reads `d` twice, `g16(f)` reads `f` twice. Straight-line programs are DAGs, and word-level fan-out breaks the group-word model entirely. | **not applicable without a fan-out theory** |

Counting is also barred: with free 32-bit constants there are at most
`(14 * 13^3 * 2^32)^10 ~ 2^510` ten-op programs against `2^(32*2^64)`
functions — counting shows *almost every* function is hard and says nothing
about a named one.

**Honest conclusion.** Proving `N >= 11` for a named function over a
word-level ISA with free constants is a circuit lower bound of a kind no
known technique delivers; every invariant that is cheap enough to compute is
saturated by a 1- or 2-op program. **The only sound route to `N >= 11` is
exhaustive refutation of the 10-op space**, i.e. exactly the kf>=3 MITM. I
recommend the coordinator treat "is 940 reachable via a shorter hash" as
*open but unfalsifiable within this project's compute budget*, and price
decisions on the 944-952 floor.

## 11. What Part 2 changes

* O1's justification is repaired and strengthened (build-time, not range).
* The shipped 11 ops are now proved optimal **under hypothesis (S)**, with
  every ingredient separately verified — that is a materially stronger
  statement than G-10/G-20/G-24 (which were per-segment enumerations with no
  stated hypothesis).
* Three invariant families are formally barred, so no further effort should
  be spent on them.
