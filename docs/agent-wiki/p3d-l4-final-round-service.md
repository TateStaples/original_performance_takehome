---
title: P3-D L4 final-round service — safe b3l fallback + NEGATIVE measurement
date: 2026-07-28
type: change
status: awaiting-review
task: Cash P3-D's "the level-4 serving assignment is dominated" finding — move the 26 L4 group-rounds served at round 4 to round 15, finding the b3l_fold_diffs register funding the assert at perf_takehome.py:729-736 blocks.
links: ["[[INDEX]]"]
---

## What changed

Only `dev.py` (64 insertions, 5 deletions). `perf_takehome.py`, `tests/`,
`problem.py`, `research/strains/p3*`, `tools/p3*.py` untouched.

- **`dev.py:840`** — new `build_kernel_scheduled` kwarg
  `b3l_safe_leaf_fallback: bool = False`.
- **`dev.py:1173-1191`** — docstring entry for the flag.
- **`dev.py:3085-3107`** — the final-round `depth_first_fold` FALLBACK (taken
  when the b3l dead-register pool cannot fund another served group privately)
  now passes `leaf_dead_temp_a/b=None` under the flag instead of
  `lv[0..31]`, and does not set `two_minus_fp_vec_clobbered`.
- **`dev.py:2671-2694`** — under the flag, `make_newest_parity_last_diffs`
  additionally refuses the private path unless the pool funds **every**
  served group (all-or-nothing), otherwise it hands every served group the
  shared-pool fallback and never pops the pool.
- **`dev.py:1371, 1415`** — flag threaded through the two `temp_pool_coloring`
  re-dispatch call sites.

With the flag OFF the emitted bundle stream is bit-identical (verified, see
below).

## Decisions & assumptions

- **The assert was never about the leaf temps being scarce; it was about the
  leaf temps being *the wrong registers*.** `depth_first_fold` already
  supports `leaf_dead_temp_a/b=None`, in which case `race_leaf` degrades to a
  plain flow `vselect` off the broadcast tables and the fold's entire working
  set is the group's own tournament pool (`tm/tmM/t/condA/condB`) — zero extra
  scratch, provably no `lv` reuse. The shipped fallback hard-codes
  `lv[0..31]`; `lv[24..31]` **is** `omf1_vec`/`two_minus_fp_vec` and
  `lv[0..15]` hosts `idx_boundary_select`'s arms, which is the entire H-029
  corruption. Passing `None` is therefore a correct, zero-cost-in-registers
  funding answer. Cost: the 4 leaf selects can no longer race to valu, so they
  serialize on the 1-wide flow engine.
- **I did not weaken or delete the `:729-736` assert.** It lives in
  `perf_takehome.py`, which I was told not to touch; `dev.py`'s equivalent
  guard is the dynamic `two_minus_fp_vec_clobbered` assert pair at
  `dev.py:3548/3557`, which remains armed on the flag-OFF path.
- **The private dead-register pool cannot be extended to 26.** Supply is
  `2*(32-S) - 3R` (st+nv of the S-complement, minus served groups' ring
  bases); demand is `8 + 5R + 9(S-R)`. Both `R=0` and `R=S` give **S ≤ 5**.
  At S=26 supply is 12 vectors against a demand of 242. The scratch ledger
  (`tools/h058_census.py`: 1533/1536 words) confirms there is no free scratch
  to make up the difference, and the ring donors for epoch-1 slices already
  consume 30 of the 32 vectors of blocks 0-1. Recycling the temps across
  groups does not rescue it either: at S=26 only 12 donor vectors exist and
  the 8 shared diff vectors alone need 8 of them. **So: 5 is the maximum
  privately funded final-round served group count, and that is the same 5 the
  assert already allowed.** The flag's contribution is that 5 stops being a
  cap on *service* and becomes a cap only on the *fast spelling*.
- **NEW BUG FOUND, and the reason for the all-or-nothing rule.** Opening the
  fallback makes *partial* funding reachable for the first time, and partial
  funding pops deep into the dead-register pool's tail — which is **not
  dead**. An unserved group's `nv` only dies after that group's own round-15
  fold-in xor and its `st` after its round-15 gather issue, both still ahead
  of the pool writes for late groups. Measured: `l4_gmin=(32,24)` (8 served /
  24 unserved, 44 pops) builds a kernel that runs and returns **the wrong
  answer** (`correct: false`), and `(32,12)` pops past the end of the pool
  (`IndexError`). The old "fund everyone or assert" invariant was
  incidentally keeping pops shallow. I therefore made the flag preserve that
  invariant exactly: private path only when the pool funds every served
  group, otherwise no pool use at all. Both failures disappear.
- **Which 26 to serve.** `l4_gmin=(32, 6)` — epoch-0 threshold 32 serves
  nothing at round 4, epoch-1 threshold 6 serves groups 6..31 = 26 at round
  15. This is the exact swap P3-D specifies.
- **All probes are ring-free.** `tools/h061_common.py` documents that the
  1006 ring plan's borrow windows were mined at `l4_gmin=(6,31)` and that
  carrying it across a gmin change is unsound. Ring-free mainline is 1026;
  with rings it is 1006.

## How it was verified

Gates (repo root, `python3`):

```
python3 tests/submission_tests.py
  -> Ran 9 tests ... OK ; CYCLES: 1006 (x9) ; Speedup 146.85
python3 -c "git diff --stat tests/"  ->  (empty)
git diff --stat  ->  dev.py | 69 +++++--   1 file changed, 64 insertions(+), 5 deletions(-)
python3 tools/h058_census.py
  -> 1006 cycles; scratch_next_addr 1533 / 1536; L4 served 27 / 64 group-rounds
python3 tools/diagnose_kernel.py  ->  clean, 21/47 instruction types
```

**Flag OFF bit-identity** (new `dev.py` vs `git show HEAD:dev.py`, comparing
`kb.instrs` bundle-for-bundle):

```
mainline-ring bundles 1006 1006 IDENTICAL
noring-6,31   bundles 1026 1026 IDENTICAL
noring-6,27   bundles 1040 1040 IDENTICAL
```

**Flag ON sweep** (`tools/h061_common.py` harness: BASE_KWARGS + h059_curve
MIX + the 1006 emission plan, ring-free, seed 1). `nob3l` =
`reverse_newest_parity_fold=()`; all others have b3_last on with the safe
fallback. Every row `correct: true`.

| l4_gmin | served @r4 / @r15 | cycles | floor (binder) | regret | alu | valu | load | flow |
|---|---|---|---|---|---|---|---|---|
| (6,31) **baseline** | 26 / 1 | **1026** | 1011 (valu) | 15 | 11873 | 6062 | 1892 | 846 |
| (6,31) nob3l | 26 / 1 | 1032 | 1010 (valu) | 22 | 11841 | 6059 | 1892 | 843 |
| (6,27) | 26 / 5 | 1040 | 1020 (valu) | 20 | 11977 | 6115 | 1860 | 863 |
| **(32,6)** nob3l | **0 / 26** | **1190** | 1029 (valu) | 161 | 10737 | 6169 | 1900 | 820 |
| **(32,6)** safe b3l | **0 / 26** | **1358** | 1060 (valu) | 298 | 10633 | 6355 | 1900 | 976 |
| (32,12) | 0 / 20 | 1323 | 1041 (valu) | 282 | 10609 | 6246 | 1948 | 908 |
| (32,16) nob3l | 0 / 16 | 1190 | **1015** (valu) | 175 | 10513 | 6089 | 1980 | 755 |
| (32,16) safe b3l | 0 / 16 | 1314 | 1033 (valu) | 281 | 10489 | 6198 | 1980 | 854 |
| (32,20) | 0 / 12 | 1251 | 1020 (valu) | 231 | 10649 | 6115 | 2012 | 803 |
| (32,24) | 0 / 8 | 1224 | 1022 (load) | 202 | 10601 | 6054 | 2044 | 756 |
| (32,27) | 0 / 5 | 1131 | 1034 (load) | 97 | 10793 | 5979 | 2068 | 676 |
| (32,31) | 0 / 1 | 1120 | 1050 (load) | 70 | 10713 | 5928 | 2100 | 659 |
| (6,16) | 26 / 16 | 1224 | 1055 (valu) | 169 | 11665 | 6327 | 1772 | 1043 |
| (6,6) | 26 / 26 | 1294 | 1151 (flow) | 143 | 11729 | 6508 | 1692 | 1151 |

Pre-fix rows (safe fallback without the all-or-nothing rule), kept as the
evidence for the pool-tail bug: `(32,24)` -> 1196 cycles **correct: false**;
`(32,12)` -> `IndexError: list index out of range`.

## Result: NEGATIVE — P3-D's actionable claim does not hold on the shipped kernel

Apples-to-apples move (b3_last off at both ends, `(6,31)` -> `(32,6)`):

```
alu    11841 -> 10737   (-1104 slots)
valu    6059 ->  6169   (+110 vec-ops = +880 lane-ops)
load    1892 ->  1900   (+8)
flow     843 ->   820   (-23)
alu+valu lane-ops  60313 -> 60089   (-224)
```

Three of P3-D's four premises fail:

1. **The saving is -224 lane-ops, not -624.**
2. **It is not fold-neutral.** valu rose by 110 vec-ops. "Identical folds"
   is false — moving service across the epoch boundary changes the
   epoch-exit index reconstruction and the c5-elision pattern, not just the
   address count. (Load-neutrality *is* confirmed: +8 slots.)
3. **The relief lands on the wrong engine.** The index work that disappears
   is alu-hosted (`idx_recurrence_race` gives the Idx madds alu spellings);
   alu had ~90 cycles of slack. The work it displaces to round 15 lands on
   valu and flow, which are the binders. valu floor 1010 -> 1029.

**This is unfalsifiable by better scheduling or a re-mined ring plan.** The
*lowest engine floor* of any round-15-heavy point measured is **1015**
(`(32,16)` nob3l), against the shipped mainline's **realized 1006**. Even a
zero-regret schedule with a perfect ring plan cannot reach the number we
already have. The direction is monotone: every point that serves anything at
round 15 beyond the shipped 1 is worse than `(6,31)`, and the axis is closed.

This is the G-36 pattern again (a lower count of one engine's ops producing
more realized cycles), and it is the third instance of the frame-relativity
note in memory: P3-D's model priced index in undifferentiated "lane-ops"
against a machine whose binder is a specific engine with a specific spelling.

## Known limitations / follow-ups

- **Out-of-scope bug to file: the b3l dead-register pool tail is unsound.**
  `dev.py:2649-2656` orders donors earliest-dead-first but has no liveness
  bound on how deep a consumer may pop. It is safe today only because the
  `2*unserved >= 8 + 9*served` invariant keeps pops shallow. Anything that
  makes partial funding reachable — my flag before the all-or-nothing rule,
  or any future gmin retune — silently miscompiles. The pool should carry an
  explicit safe depth (or per-donor first-write slot) rather than relying on
  a caller-side inequality. `perf_takehome.py` is not currently exposed
  (its assert forbids partial funding outright), so this is latent, not live.
- The all-or-nothing rule makes the flag conservative for ring-heavy
  configs: a config with e.g. 5 ringed served groups whose demand `8+5*5=33`
  fits but whose conservative-free demand does not would be handled by the
  exact ringed accounting I implemented, but any config where only *some*
  served groups could be funded now funds none. Given the pool-tail bug that
  is the right default; a liveness-bounded pool would let it be relaxed.
- Nothing was ported to `perf_takehome.py`, by contract and because the
  measurement is a loss. The flag's default stays OFF.
- Not investigated (explicitly out of scope): C1* retained-parity redesign,
  ring coverage, K<32, and re-mining an emission order or ring plan at
  `(32,6)` — the floor argument above makes the last one pointless anyway.
