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

(none yet — slices start now)

## Planned slice queue
1. full_hash_core --ext kf3full --max-chain 6 --fwd-shard {0..3}/4
   (reaches k<=10: THE 11->10 question for fwd3-general+meet+chain<=6 shapes)
2. round12 --ext kf3full --max-chain 6 --fwd-shard {0..7}/8 (2-input body)
3. f2ap, e2xw (engine A k<=3 + engine C, single slices each)
4. full_hash_core --ext kf4chained --fwd-shard 0/64 (timing probe for the
   kf4 resume protocol; full closure = 64 shards)
