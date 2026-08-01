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

## 3. Slice ledger (append CHECKPOINT lines)

(pending)

## 4. CEGIS/Z3 (mission 3)

(pending)
