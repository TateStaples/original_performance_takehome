---
title: P5-B — kf>=3 global hash MITM (full-shape prefixes, chain-6, round12)
date: 2026-08-01
type: research
status: partial
task: Search the hash-equivalence regions all prior efforts left uncovered (kf>=3 forward prefixes, 2-round forms, runtime-madd), at scale, in Rust; hard negatives with precise coverage bounds are first-class results.
links: ["[[INDEX]]", "[[p3f-hash-10op-question]]"]
---

# Verdict

**REGIONS CLOSED (negative), no find.** Three genuinely-new regions were
searched to completion and one calibrated for parallel resume. No <=10-op
form of the 11-op hash, no <=10-op form of the 12-op round body, and no
3-op form of either 4-op cross-round span exists **within the precisely
stated spaces below**. Nothing is claimed beyond them.

# Infrastructure (new, validated)

`rust_harness/src/bin/global_mitm.rs` — self-contained binary, machinery
transcribed from the verified `fusion_search.rs` (H-016/H-025), extended
with capabilities that existed nowhere before:

1. **kf=3 FULL-SHAPE forward tables.** All prior kf>=3 tables were
   CHAINED-only (each temp consumed by the very next op — see
   `fusion_search.rs:1880-1947`), which cannot represent the parallel shape
   `t1=f(x); t2=g(x); t3=h(t1,t2)` — the shape of the hash's own stage-3/4
   twin-madd merge. The new builder covers chained + parallel = **all 3-op
   DAG prefixes** (every non-final temp referenced).
2. **kf=4 chained tables wired into engine C** (previously built only as a
   diagnostic, never searched).
3. **Sharding** (`--fwd-shard I/N` over (l1,l2) pairs; `--link-shard`) so
   every run fits an 8-min slice on the 8-core/24GB box; shard-union =
   full coverage (validated).
4. **Suffix chains to 6 ops** (`--max-chain 6`), so total decomposable
   depth reaches kf3+meet+6 = **10 ops = the 11->10 question's depth**.
5. New targets: `full_hash_core` (myhash over a lean 12-const core pool —
   the 10 fused-stage constants + s19 + s16; the 23-item fusion_search pool
   is a proven kf=3 memory wall), `round12` (**the 2-input 12-op round body
   `myhash(x ^ y)` as one function — never a MITM target before**),
   `f2ap`/`e2xw` (P3-F's two named 4-op cross-round spans).

**Selftest (all PASS, `--selftest`):** a planted 8-op parallel-prefix
function (madd33 || madd16896 -> xor -> affine meet -> xsr16 -> xorC1 ->
aff33) is (a) FOUND and 10M-input-verified by kf3-full engine C, (b) **NOT
found by the chained-kf3 family** — proving the parallel shape is a real
coverage extension, not a re-spelling — and (c) found by exactly the
fwd-shards containing its two operand orderings (union preserves coverage).

# Results (all bit-exact-verified machinery; finds would have been checked
# on 10M random + 2^20 sweep + structured edges — there were none)

## R1. full_hash 11 -> 10 (and ->9): CLOSED NEGATIVE in the new region

4 shards, each: kf0/1/2 base tables + 14.8M-entry kf3-full shard + engine C
chain-DFS to 6 ops (2.118B chain nodes/shard, 1284-link pool, solved
xor/affine meets with even-K lifts to 2^12). **Total 59.36M full-shape
3-prefixes x all suffix chains <=6 ops: 0 finds.**

New coverage vs prior art: H-025 stopped at kf<=2 + chain<=5 (total 8);
chained-kf3 was never run on the full hash at all (memory wall); parallel
3-prefixes and 6-op chains existed in no prior search. The k=9 and k=10
questions are both covered by the wanted-mask within these shapes.

## R2. round12 (12-op round body incl fold-in) at <=10: CLOSED NEGATIVE

The composite R(x,y) = myhash(x^y) as ONE 2-input function — the object the
Phase-5 arithmetic actually prices. 8 shards x (23M-entry kf3-full tables +
2.118B chain nodes): **184.5M full-shape 3-prefixes (over inputs {x,y} and
the core pool), 0 finds at any k <= 10.** Engine A additionally closed pure
forward k<=3 (2.0B candidates, solved final constants). This is the first
global search of the round body that does not assume the fold-in happens
first: prefixes freely mix x and y (e.g. madd(y, K, f(x)) shapes).

## R3. P3-F next-step: the two 4-op cross-round spans at depth 3: CLOSED

* `f2ap`: a' = stage0(sigma16(x) ^ y) — engine A full forward k<=3 (2.08B
  candidates) + engine C kf<=2+meet+chain<=3: **no 3-op form** (36s).
* `e2xw`: x' = sigma16(stage4(x)) ^ y — same machinery: **no 3-op form**
  (16s). Pools: stage constants + C5/C5s/C5i/K016/K0C5 variants (printed in
  the run logs / STATE.md).

## R4. madd with runtime multiplicand: CONFIRMED NOT A GAP (again)

`enumerate_level` generates `madd` over ALL pool triples including two- and
three-runtime-operand forms (this binary and `fusion_search.rs:199,409,504`).
Structural note: in the SUFFIX side of any MITM decomposition a runtime
multiplicand is impossible by construction (suffix links are unary in the
chain value) — so the only runtime-madd region not covered by forward
enumeration is "late op reading both the chain value and a second live
runtime value", which is outside every engine's shape family and is part of
the honest NOT-COVERED list below.

## R5. kf4-chained: calibrated, resume protocol published

Chained-4 prefix space over the core pool ~ 29B entries (7.11M per 1/4096
shard, 6.3s build). **Shard 0/4096 ran to completion: NEGATIVE, 1354.7s**
(engine C ~3x slower against the kf4 tab than the kf3 runs — profile
before mass fan-out). Full closure = 4096 independent slices x ~22 min
(kf4+meet+chain5 = 10-op reach) ~ 64 box-days serial — needs the driver's
parallel fan-out. Exact slice command + ledger format in
`research/strains/p5b/STATE.md`.

# COVERAGE MAP (before -> after)

| region | before P5-B | after P5-B |
|---|---|---|
| full_hash global MITM forward depth | kf<=2 (H-025) | **kf<=3 ALL DAG shapes** (core pool), 0 finds |
| suffix chain depth | <=5 | **<=6** (>=5-op chains <=1 unary link) |
| total decomposable depth | 8 | **10** (= the 11->10 bar; k=9 included) |
| 12-op round body as one 2-input function | never searched | **closed <=10** in MITM shapes; pure-forward closed k<=3 |
| 4-op cross-round spans at depth 3 | closed only at depth 2 (P3-F numpy) | **closed depth 3** (engine A) |
| kf=3 parallel prefix shape | in NO search (chained only) | in ALL P5-B searches |
| kf=4 | diagnostic build only | wired + calibrated; 4096-slice resume protocol |

**Still NOT covered (honest negative space):** (i) programs that do not
decompose as [<=4-op prefix][solved meet][invertible pooled-constant suffix]
— e.g. a late binary op over two live runtime values, or suffix constants
outside the 72-const link pool / 16 odd multipliers; (ii) forward constants
outside the 12-const core pool (the richer 23-item pool remains a kf=3
memory wall — its extra consts are derived products, partially reachable
via 1 extra op); (iii) kf=4 beyond shard 0 timing; (iv) full-shape kf=4;
(v) the 2-round composite at 19-22 ops — **structurally beyond exhaustive
MITM reach** (a 23-op function; max decomposable depth here is 10; only its
cross-boundary spans are searchable, and were — R3). The coordinator's
suggestion of per-c1 specialization at served levels also collides with the
build-time constraint (kernel is built from shape params only,
tests/submission_tests.py:24-26; the op stream cannot depend on node
values) — flagged back rather than searched.

# SEARCH VOLUME

* full_hash_core: 59.36M kf3-full prefixes x 2.118B chain nodes x 4 shards
  (probes: exact + xor-meet + affine-meet per node per tab).
* round12: 184.5M kf3-full prefixes, 8 x 2.118B chain nodes, + 2.0B
  engine-A forward candidates.
* spans: 2.08B + 0.81B engine-A candidates + 2.6B chain nodes.
* selftest: 3 planted controls, all behaving exactly as designed.
* Wall clock: ~105 min of slices, all <=~7-9 min each, checkpointed.

# FLOOR IMPACT

None realized — all negatives. Had R1/R2 found a 10-op body, the Phase-5
arithmetic (P5-A/P5-C) prices it at ~68 cycles/op of floor: k=10 floors
902/918 (needs ~170 vec-ops of support trim), k=9 floors 859/875 (clean
win). The negatives instead RAISE confidence that the frontier's k<=10 (per
P5-A's proof) is achieved by something OUTSIDE single-round op-identity
space: cross-round/amortized structure, or constants/shapes beyond these
pools. The highest-value unsearched region consistent with both P5-A's
proof and these negatives is the 2-round composite — which needs a
different tool class (CEGIS with fixed skeleton, or algebraic construction,
not enumeration).

# Resume protocol (for the driver)

See `research/strains/p5b/STATE.md` — every slice is one CLI call printing
a CHECKPOINT line; the ledger there is the source of truth for which
(target, ext, shard) combos are done. Ready-made queues: kf4chained I/4096;
round12 kf4chained (needs N~8192); richer-pool kf3full (add --pool support
or extend core_pool(); entries scale ~x4 per +4 consts).
