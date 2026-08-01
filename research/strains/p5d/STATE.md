# Strain P5-D — fan-out suffix MITM + shape census + CEGIS (Phase-5)

status: IN PROGRESS

## 0. Coordinator update folded in (2026-07-28, mid-task)

k=10 is DEAD on both boards (P5-E: no ~170-vec trim; best k=10 floors
902/919). Priorities now: (1) 9-op single-round fan-out forms — highest-
reach tiers FIRST (joined-kf3, reach covers k=9 via the wanted mask);
(2) 2-round composite <=19 ops ahead of 10-op single-round shapes in CEGIS
triage; (3) 10-op finds are structural evidence only, not wins. Floor
arithmetic correction: per-op removal = 4,096 lane-ops (~68 cycles); a
validated 9-op form floors 857-868 (no-idx, target 889) / 874-885
(with-idx, target 904). Slices keep wanted<=10 (k=9 probes are included at
identical cost; a 10-op hit costs nothing extra and is evidence).
binary: `rust_harness/src/bin/fanout_mitm.rs` (new; machinery transcribed from
global_mitm.rs, P5-B validated)
tools: `tools/p5d_census.py` (DP validated vs brute force n<=6)

## 1. SHAPE CENSUS (mission 1) — DONE 2026-08-01

Model: n-op programs, op p reads a nonempty set of 1..3 runtime slots from
{x, t_1..t_{p-1}} (3 = madd), rest constants; output = t_n; all temps + x
referenced. Counting WIRING shapes (op identities and constants abstracted).
Syntactic classification (chain rewrites make covered counts LOWER bounds):

| n | total shapes | P5-B covered (lv<=3) | P5-D join@4 (NEW) | kf4chained adds | lv>=5 (unreachable by any enumeration) |
|---|---|---|---|---|---|
| 9  | 10,325,475,541 | 146 | 304 | 192 | 10,325,474,683 (99.999%) |
| 10 | 1,145,484,095,402 | 236 | 494 | 312 | 1,145,484,093,658 (99.999%) |
| 11 | 165,934,062,171,430 | 382 | 798 | 504 | ~all |

**VERDICT of census: full enumeration of fan-out shapes is IMPOSSIBLE
(1.1e12 wiring shapes at n=10 BEFORE op-type and constant assignment).**
The only enumerable increment over P5-B is the single-r join family with the
join at op <= 4 (last "violation" at position 4 of join type): that is
fanout_mitm's region, and it TRIPLES the covered shape count. Everything
with a violation at position >= 5 (13.8% of shapes are single-r joins deep,
86.2% multi-fanout/madd-fanout) is CEGIS/algebraic-only territory.
Note: the real 11-op form itself has lv=11 syntactically, but algebraic
rewrites (xor commutes with shr: sigma-triples fold into XsR links with
adjusted constants) reduce it to MITM-decomposable — which is why the
syntactic classes are lower bounds and why link-pool design matters more
than raw shape counts.

## 2. fanout_mitm design (mission 2)

Program family searched (NEW coverage vs P5-B):
  [<=3-op FULL-SHAPE DAG prefix over pool consts, m = final, r = any runtime
   slot (x, y, t1, t2; unreferenced temps allowed iff they become r)]
  -> join j = g(m, r)   (g forward-computed; invertibility NOT required)
  -> [optional solved xor/affine meet (engine C)]
  -> [invertible pooled suffix chain <= 6 ops]
Total reach: 3 + 1 + 1 + 6 = 11 (wanted mask caps at 10; k=9 included).
Join vocab g: basic {xor, add, sub, rsub}; ext {and, or, mul, shl/shr both
orders (runtime shift amounts)}; maddk {m*K+r, r*K+m for the 16 odd link
multipliers}. Joined tabs are keyed exactly like P5-B fwd tabs (exact +
xor-norm + affine-canon with 2^12 even-K lifts), so engine C is unchanged.

Redundancy note (important): joined-kf2 with g in the DAG vocab is SUBSUMED
by P5-B's kf3full closure (a kf2+join = a 3-op DAG). The genuinely new
regions are: (a) joined-kf3 = 4-op forward reach for join-final shapes,
(b) maddk joins with the 12 non-pool odd multipliers at any kf,
(c) r = y (node value read twice) for round12 — the "late binary op over
two live runtime values" hole named in P5-B's not-covered list.

Optional --gen-shift-links: adds v+(v>>s), v-(v>>s), (v>>s)-v as invertible
2-op chain links (generalized xorshift; fan-out of the chain value beyond
xor) with iterative inverses, roundtrip-asserted at startup.

## 2b. Validation + two lemmas (2026-08-01)

SELFTEST ALL PASS (`fanout_mitm --selftest`):
- sp1 (6-op plant, XOR-join at op 4, r=t1): FOUND+verified by joined-kf3;
  NOT found by the no-join P5-B family (base+kf3full+chain) — the join is a
  real coverage extension. Shard union (4 shards): exactly the shards with
  the plant's orderings find it.
- sp2 (r = x input fan-out, joined-kf2): FOUND. sp3 (DAG leaves t1 dangling,
  join adopts it): FOUND — the unused-temp-as-r rule works.
- LEMMA A (additive-shift): v+(v>>s), v-(v>>s), (v>>s)-v are NEVER bijective
  mod 2^w (exhaustive w=12, witnesses at w=32; e.g. f(0)=f(0xFFFFFFFF) for
  s=31 add). Every unary link of a chain suffix of a bijection must be
  bijective, so additive xorshift-analogues are PROVABLY absent from all
  chain suffixes — excluding them is a theorem, not a coverage gap.
- LEMMA B (join absorption, found BY the selftest negative control): an
  ADD-join whose r lands next to a madd folds into the madd's runtime addend
  slot (9*t2+C4+t1 = madd(9,t2,t1) then solved affine meet absorbs C4), so
  g=add joins adjacent to madds are already inside P5-B's closure; XOR-joins
  are not (P3-F XOR<->ADD lemma). g=xor is therefore the highest-value join
  family, g=add second (only non-madd-adjacent placements are new).

## 3. Slice ledger (append CHECKPOINT lines)

Calibration (2026-08-01): full_hash_core --kf 3 --join-g xor --join-r all
--fwd-shard 0/16: joined tab = 24,209,166 entries in 748s (single-threaded
build; the relaxed unused-temp rule + r=x inflate ~6.5x over a plain kf3full
shard), RSS ~3.5GB — /16 sharding is RAM-safe alongside the driver's kf4
grind. Engine C phase timed below. Full closure of one g over 16 shards is
a DRIVER-FLEET job (~30 min/slice contended), not in-session — same
precedent as P5-B's kf4chained handoff.

(CHECKPOINT lines appended as slices complete:)

## 4. CEGIS/Z3 (mission 3)

Machinery: tools/p5d_cegis.py. Soundness: UNSAT on a sample-constraint set
=> template impossible for the whole function (samples are necessary
conditions); SAT => constants extracted and verified OUTSIDE z3 on 2^20
sweep + 10M randoms; TIMEOUT reported as OPEN never closed.

Controls: full 7-op span template (1 madd) = FOUND+VERIFIED (z3 even found
an alternate constant family with multiplier -4097 — sign symmetry).
Full 11-op hash template with 4 free multipliers = TIMEOUT at 150s even
with concrete shifts — z3 QF_BV cannot handle >=3 chained free 32-bit
multipliers at this budget; madd-heavy 9-op templates will report TIMEOUT
(=OPEN), madd-light ones (deletions that remove madds) can resolve.
Width-reduction ladder is UNSOUND here (right shifts break the truncation
homomorphism mod 2^w) — noted and not used.

Runs:
- span7->5 (PRIORITY 1 entry to the <=19 two-round composite): ALL 10 valid
  2-deletion templates of the primed boundary span M(e,y') =
  stage1(stage0(sigma16(e)^y')) at 5 ops: **UNSAT — closed at full constant
  freedom** (log: scratchpad cegis_span.log; 10 further variants cascade to
  !=5 ops, skipped as out-of-question). Combined with P5-B's round12<=10 and
  span-depth-3 closures, the <=19 composite now has NO known local entry
  point: savings would have to come from >=5-op nonlocal restructuring
  spanning >=3 stage groups — outside every tool's reach.
- hash11->9 2-deletion family: (pending)

## 5. Resume protocol (driver fleet)

Slice command (one CHECKPOINT line each; append here):
  ./rust_harness/target/release/fanout_mitm full_hash_core \
    --kf 3 --join-g G --join-r all --max-chain 6 --fwd-shard I/16
Closure of (target, g) = all I in 0..16 present with finds=0.
Priority order (Lemma B + real-form structure):
  1. full_hash_core g=xor      (16 slices; the real form's join type)
  2. full_hash_core g=add,sub,rsub (48 slices; add partially P5-B-redundant)
  3. round12 --join-r y g=xor  (the nv-fanout hole; needs I/48 sharding —
     calibrate slice 0 first; r=x,t1,t2 tiers after)
  4. g=ext (and/or/mul/shifts), g=maddk (28 non-pool odd-K joins; needs
     finer sharding, ~I/128, or per-K runs)
~30 min/slice under kf4 contention, ~3.5GB RSS at /16. RECOMMENDATION: the
joined-kf3 fleet should PREEMPT the kf4chained grind (32 box-hours for tier
1-2 vs 64 box-days; covers the census's entire join-at-4 class vs the
spine-only slice of it).
