# Strain P5-B — kf>=3 global hash MITM (Phase-5 funded search)

status: IN PROGRESS (infrastructure VALIDATED; slices running)
binary: `rust_harness/src/bin/global_mitm.rs` (new, self-contained; machinery
transcribed from fusion_search.rs H-016/H-025 verified code)

## What the binary adds over all prior searchers

1. **kf=3 FULL-SHAPE forward tables** — prior kf=3/4 arms were CHAINED-only
   (each temp consumed by the very next op). New: the PARALLEL shape
   t1=f(x); t2=g(x); t3=h(t1,t2) (the stage3/4 twin-madd merge shape),
   invisible to every prior kf>=3 attempt.
2. **kf=4 chained tables wired into engine C** (never wired before).
3. **Sharding**: `--fwd-shard I/N` over (l1,l2) candidate pairs
   (key = (idx1*1000003+idx2) % N), `--link-shard I/N` over engine C
   top-level links. Any slice fits an 8-min run on the 8-core/24GB box.
   Union over shards = full coverage (validated by selftest 3).
4. **--max-chain 6** (6-op suffix chains = 3 xor-shift macros under the
   >=5-op <=1-unary rule) → total reach kf3+meet+6 = **10 ops**, i.e. the
   11->10 question's depth, for these shapes. kf4+meet+5 = 10 likewise.
5. New targets: `full_hash_core` (myhash, lean 12-const core pool — the 10
   stage constants + s19+s16; fusion_search's 23-item pool is a proven kf=3
   memory wall), `round12` (TWO-INPUT 12-op round body myhash(x^y), never a
   MITM target before), `f2ap`/`e2xw` (the two 4-op cross-round spans P3-F
   named depth-3-unsearched), `planted_par` (selftest).

Vocabulary: 8 alu binops + madd over ALL pool triples (runtime multiplicand
INCLUDED — confirming P3-F: that was never a gap). cmpsel excluded (G-24),
div/mod excluded (P3-F). Finds verified on 10M+ random + 2^20 sweep +
structured edge battery before reporting (same as fusion_search).

## SELFTEST (2026-08-01): ALL PASS
- kf3-full finds the planted 8-op parallel-prefix form (madd33 || madd16896
  -> xor -> meet madd9 -> xsr16 -> xorC1 -> aff33), VERIFIED on 10M+.
- kf3-CHAINED (the entire prior kf3 shape family) does NOT find it —
  the parallel shape is a real coverage extension, not a re-spelling.
- Shard union (4 shards): exactly the shards containing the two operand
  orderings find it; union preserves coverage.
- Engine C throughput: ~11.5M chain nodes/s (154M nodes / 13.4s, 8 threads,
  536-link pool).

## Slice CLI (for parallel fan-out by the driver)

```
./rust_harness/target/release/global_mitm <target> \
  --ext {none|kf3full|kf3chained|kf4chained} \
  --max-chain {5|6} --fwd-shard I/N --link-shard I/N \
  --tab-cap 30000000 [--skip-base-tabs] [--engine-a K]
```
Each run prints a `CHECKPOINT target=... ext=... fwd_shard=... tabs=[...]
chain_nodes=... finds=... secs=...` line — append it below. Coverage of a
(target, ext, max-chain) combo is complete when all I in 0..N ran for its
fwd shards (x all link shards if link-sharded).

## Slice ledger (append CHECKPOINT lines as they complete)

CHECKPOINT target=full_hash_core ext=kf3full maxchain=6 fwd_shard=0/4 link_shard=0/1 tabs=[kf0:1,kf1:365,kf2:123401,kf3:14850325] chain_nodes=2118524244 finds=0 secs=408.0
CHECKPOINT target=full_hash_core ext=kf3full maxchain=6 fwd_shard=1/4 link_shard=0/1 tabs=[kf0:1,kf1:365,kf2:123401,kf3:14847537] chain_nodes=2118524244 finds=0 secs=405.3
CHECKPOINT target=full_hash_core ext=kf3full maxchain=6 fwd_shard=2/4 link_shard=0/1 tabs=[kf0:1,kf1:365,kf2:123401,kf3:14835166] chain_nodes=2118524244 finds=0 secs=403.1
CHECKPOINT target=full_hash_core ext=kf3full maxchain=6 fwd_shard=3/4 link_shard=0/1 tabs=[kf0:1,kf1:365,kf2:123401,kf3:14824788] chain_nodes=2118524244 finds=0 secs=403.4

**REGION CLOSED (2026-08-01): full_hash 11->10 AND ->9, kf3-FULL x chain<=6.**
No <=10-op form of myhash (k=9 included via the wanted mask) decomposing as
[any 0..3-op forward DAG prefix over the 12-const core pool, ALL shapes incl
parallel] + [optional solved xor/affine meet, even K to 2^12] + [invertible
suffix chain <=6 ops from the 1284-link pool]. 59.36M kf3-full entries,
4 x 2.118B chain nodes, ~27 min total.

CHECKPOINT target=f2ap ext=none maxchain=3 fwd_shard=0/1 link_shard=0/1 tabs=[kf0:2,kf1:646,kf2:190453] chain_nodes=1826439144 finds=0 secs=36.0
CHECKPOINT target=e2xw ext=none maxchain=3 fwd_shard=0/1 link_shard=0/1 tabs=[kf0:2,kf1:417,kf2:83640] chain_nodes=813153413 finds=0 secs=15.9
**P3-F next-step 2 CLOSED: both 4-op cross-round spans (f->a' and e->x',
primed basis) have NO 3-op form** — engine A full forward k<=3 (2.08B /
0.8B candidates, solved final constants) + engine C kf<=2+meet+chain<=3.

CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=0/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23091539] chain_nodes=2118524244 finds=0 secs=418.5
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=1/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23035034] chain_nodes=2118524244 finds=0 secs=417.2
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=2/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23071478] chain_nodes=2118524244 finds=0 secs=417.3
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=3/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23048164] chain_nodes=2118524244 finds=0 secs=420.1
(round12 shard 0 also ran engine A k<=3 full forward: 2.0B candidates, 0 hits)

CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=4/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23084986] chain_nodes=2118524244 finds=0 secs=428.7
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=5/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23038823] chain_nodes=2118524244 finds=0 secs=430.5
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=6/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23090255] chain_nodes=2118524244 finds=0 secs=429.9
CHECKPOINT target=round12 ext=kf3full maxchain=6 fwd_shard=7/8 link_shard=0/1 tabs=[kf0:2,kf1:780,kf2:294685,kf3:23050737] chain_nodes=2118524244 finds=0 secs=560.0

**REGION CLOSED (2026-08-01): round12 (2-input 12-op body myhash(x^y)),
kf3-FULL x chain<=6, all 8 shards NEGATIVE.** No form at <=10 total ops
(engine reach; wanted included 11 but max decomposable depth = 3+1+6 = 10)
in [any 0..3-op fwd DAG prefix over {x,y}+core pool] + [solved meet] +
[<=6-op suffix chain]. 184.5M kf3-full entries, 8 x 2.118B chain nodes.
Engine A also closed pure-forward k<=3 (2.0B candidates).

## kf4chained probe + resume protocol
- shard 0/512: ABORT tab_cap (>30M entries) -> chained-kf4 space is huge.
- shard 0/4096 COMPLETED NEGATIVE:
  CHECKPOINT target=full_hash_core ext=kf4chained maxchain=5 fwd_shard=0/4096 link_shard=0/1 tabs=[kf0:1,kf1:365,kf2:123401,kf4:7113097] chain_nodes=2118285916 finds=0 secs=1354.7
  7.11M entries, 6.3s build; engine C ran 22.6 min (~3x a kf3 slice —
  CPU sat ~370% not 690%, probe against the kf4 affine map is costlier;
  worth profiling before mass fan-out). Extrapolated total ~29B chained-4
  prefixes; full closure = 4096 slices x ~22 min ~ 64 box-days serial —
  driver parallel fan-out required. Slice command:
  `global_mitm full_hash_core --ext kf4chained --max-chain 5 --fwd-shard I/4096 --engine-a 0`
  (each slice independent; append its CHECKPOINT line here; closure =
  all I in 0..4096 present with finds=0). kf4+meet+chain5 = 10 ops reach.
