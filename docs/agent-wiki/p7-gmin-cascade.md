---
title: P7-G — the gmin screen's 10-cycle lead is an artifact of a stale emission order; (6,31) wins the full cascade
date: 2026-08-03
type: change
status: awaiting-review
task: Parameterize the P7-TAR ring derivation over l4_gmin and the with-idx tail, run the full cascade (per-gmin ring plan -> rebuild -> measure -> 10-seed verify) for the screen's candidates (9,30) and (8,31), tail OFF and ON, and report whether either beats the shipped mainline (1006) or the with-idx best (1034).
links: ["[[p7-tail-aware-rings]]", "[[p7-polish-stack]]", "[[p7-t2-partial-lazy-position]]"]
---

# P7-G — gmin cascade

**VERDICT: NEGATIVE, and the screen's lead inverts.** At the full shipped
stream the shipped `l4_gmin=(6,31)` is the best of the three candidates at
every layer of the cascade — ring-free, native-rings-only, and with a ring
plan derived at that gmin. `(9,30)`, which led the driver's ring-free screen
by 10 cycles, lands **1023** (mainline candidate, vs **1006** shipped) and
**1049** with the tail (vs **1034**). `(8,31)` lands **1015 / 1041**.

The 10-cycle lead was measured on a base that lacks the **h057 emission
order**, and that order is worth **−23 cycles at (6,31) but only −9 at
(9,30)**. The order was mined at (6,31); its value is strongly gmin-specific,
and it alone re-ranks the three candidates. Rings then compound in the same
direction (−19 / −13 / −7).

## 1. What changed (files)

* **`tools/p7g_remine.py`** (new). The P7-TAR derivation, parameterized over
  `--gmin E1,E2`, `--tail {on,off}` and `--order FILE`.
  `tools/p7tar_remine.py` is **imported, never modified**: its
  `derive`/`fixpoint`/`mine` resolve `build` from their own module globals, so
  this module installs its own `build` there for the duration of a run. The
  search logic is therefore bit-identical to the reviewed P7-TAR one and the
  whole delta is in kwargs. Also provides `--verify FILE --seeds N` (replays a
  saved plan with `ring_liveness_assert` at its auto-ON default and checks
  values, plus final indices under `--tail on`, against `reference_kernel2`).
* **`research/strains/p7/p7g_plan_{6_31,8_31,9_30}_{off,on}.json`** (new,
  evidence). Derived drop-sets + ring plans, one per cell of the table below.
  Written under `research/strains/p7/`, **not** `tools/`, per P7 (c) open
  issue 4 (a bare plan file in `tools/` invites a stale-plan accident).
* **`research/strains/p7/STATE.md`** — "gmin cascade (P7-G)" section appended.
* `dev.py`, `perf_takehome.py`, `tests/` — **untouched**. No flag was needed:
  every lever this used (`l4_gmin`, `parity_ring_plan`, `parity_ring_drop`,
  `store_final_indices`, `emission_plan`) already exists.

## 2. The cascade

Base = `h061_common.kwargs()` (BASE_KWARGS + h059 MIX + the h057 1006 emission
order), with `l4_gmin` overridden and the ring plan **derived from empty at
that gmin** (drop-and-rebuild liveness fixpoint, then greedy donor mining off
the realized trace, iterated to convergence).

| gmin | tail | ring-free | native rings only | derived plan | rings | 10-seed |
|---|---|---|---|---|---|---|
| **(6,31)** shipped | off | 1026 | 1017 | **1007** (shipped plan: **1006**) | 39 | 10/10 values |
| (8,31) | off | 1028 | 1018 | **1015** | 38 | 10/10 values |
| (9,30) | off | 1030 | 1023 | **1023** (mining makes it WORSE: 1027) | 20 | 10/10 values |
| **(6,31)** | on | — | 1043 | **1034** | 31 | 10/10 values+indices |
| (8,31) | on | — | 1042 | **1041** | 30 | 10/10 values+indices |
| (9,30) | on | — | 1052 | **1049** | 30 | 10/10 values+indices |

**Derivation calibration (the control that makes the rest readable).**
Re-deriving at the shipped `(6,31)` from an EMPTY plan reproduces the mainline
to within **1 cycle** (1007 / 39 rings vs the shipped 1006 / 40), and at
`(6,31) --tail on` it reproduces `tools/p7tar_best_plan_1034.json`
**byte-identically** (same 17 mined entries, same 6 native drops, 1034). So
the derivation is not systematically weak, and the +8 / +16 gaps for the other
gmins are real, not derivation loss.

`(9,30)` is the one cell where **mining rings makes things worse** (native-only
1023 → 1027 with 21 mined entries); `derive()` keeps the best iterate, so the
reported 1023 is the native-only build. That is itself a symptom of the stale
order: the mined donors' borrow windows are placed against an emission order
that was tuned for a different service profile.

## 3. Where the driver's 10 cycles went

The screen (`research/strains/p7/gmin_sweep_noring.json`: (6,31)=1049,
(8,31)=1045, (9,30)=1039) was run on the **1049 ringless base**, i.e.
`BASE_KWARGS` + `l4_gmin`, with no emission plan. Reproduced exactly, then
each layer added back:

| gmin | bare BASE+gmin | + h059 MIX flags, no order | + h057 order (ring-free) | + derived rings |
|---|---|---|---|---|
| (6,31) | 1049 | 1049 | **1026** (−23) | **1007** (−19) |
| (8,31) | 1043 | 1045 | **1028** (−17) | **1015** (−13) |
| (9,30) | 1038 | 1039 | **1030** (−9) | **1023** (−7) |

* The h059 MIX flags (`c5_primed_gather_levels=(5,6)`, the two `mem_prime_*`)
  are **gmin-neutral**: ±2 cycles, ranking unchanged. They are not the
  absorber.
* The **h057 emission order is the absorber**, and it is not a constant
  offset: −23 / −17 / −9. It re-ranks the candidates on its own, before rings.
* Rings then add −19 / −13 / −7 in the same direction. Both order-specific
  layers pay most where they were mined.

This is the mechanism behind the mainline sitting at (6,31): (6,31) is *not*
the best serve profile for a raw stream — on the bare base it is the **worst**
of the three (1049 vs 1038) — it is the profile the two expensive
order-specific layers were co-optimized with, and those layers are worth more
than the raw serve-profile difference.

## 4. Is (9,30) only losing because its order is stale?

That is the honest steelman, so it was measured rather than argued: a fresh
emission-order search at `(9,30)`, ring-free, on the h059 MIX flags
(`tools/emission_order_search.py`, `EOS_OVERRIDES` pointed at that mix).

* `phase1` (structured families: lags/blocks/wave_order/group_order/
  interleave/stage_rr/tail_df + pairwise compositions): 53 evals, **best 1039
  = the default order, params `{}`**. No structured family beats the default
  at this gmin.
* `local` (window-restricted single-entry displacement, `--window all`,
  jumps ±{1,2,4,8,16,32}, 4 workers, 23,556 evals over 1500 s): 1039 →
  **1035**, 4 descents, last improvement at t≈190 s, then flat for 1300 s.
* Full cascade on that order (`--order`, rings re-derived on it): natives 1037,
  mining adds nothing → **1037**, verified 10/10 seeds
  (`research/strains/p7/p7g_plan_9_30_off_neworder.json`).

**The staleness hypothesis does not survive.** The freshly-mined (9,30) order
is WORSE for (9,30) than the inherited h057 one at every layer:

| (9,30) with… | ring-free | + rings |
|---|---|---|
| inherited h057 order | **1030** | **1023** |
| order mined at (9,30) (phase1+local) | 1035 | 1037 |

and both are far from (6,31)'s 1026 / 1006-1007. (9,30)'s problem is not that
it is running someone else's order.

**Asymmetry disclosed.** h057 is the product of a far larger search than this
one (G-30/G-31/F-37: 25,550 single-entry moves + 438,247 multi-move evals,
k=2 exhausted at the (6,31) mix). A 25-minute local descent at (9,30) is a
*screen*, not a matched search. What it establishes is that the 17-cycle gap
is not cheaply recoverable — not that no order exists. Cost to close that
properly: an f18/f37-scale re-mine at (9,30), then a ring re-derivation on
top, for a candidate that starts 17 behind.

## 5. Decisions & assumptions

1. **Monkeypatch `p7tar_remine.build` rather than copy `derive`/`fixpoint`/
   `mine`.** Copying risks silent divergence from the reviewed derivation; the
   brief forbids editing the original. Installing `build` into the imported
   module's globals keeps the search bit-identical and confines the delta to
   kwargs. Proven by the byte-identical reproduction of the 1034 plan.
2. **Derive from EMPTY at every gmin, including (6,31).** Comparing a
   gmin's freshly-derived plan against the shipped hand-carried plan would
   confound "worse gmin" with "weaker derivation". The (6,31) re-derivation is
   the control; it costs 1 cycle, so the comparison is read at 1007 vs 1015 vs
   1023 (and reported against 1006 as well).
3. **Tail-off builds do not set `b3l_safe_leaf_fallback`.** The mainline does
   not, and the flag changes the stream; forcing it on would make the
   candidates non-comparable to the 1006 mainline. Tail-ON builds set it
   because `store_final_indices` asserts it (P7 (c) issue 3).
4. **Ring-free screening first, before paying for derivations.** The five-cell
   ring-free screen on the MIX base (1026/1028/1030/1032/1028) already inverted
   the driver's ranking; the derivations were run anyway because the brief asks
   the full-stream question and rings are gmin-specific, but the screen is what
   set the expectation.
5. **Emission-order search run ring-free.** Rings are derived *after* an order
   (they are mined off that order's realized trace); mining the order with a
   ring plan in place would fix a plan that the order search then invalidates.
6. **The liveness audit is necessary, not sufficient.** Every reported cell is
   backed by a 10-seed value (and, under the tail, index) comparison against
   `reference_kernel2`, not by the audit.
7. **Derived plans stored under `research/strains/p7/`, not `tools/`** — see
   P7 (c) open issue 4.
8. **`(9,31)` and `(10,31)` were screened ring-free (1028 / 1032) but not
   cascaded.** (9,31) ties (8,31) ring-free; it was dropped because the brief
   named (9,30) and (8,31) and the ranking was already unambiguous.

## 6. How it was verified

* `python3 tools/p7g_remine.py --verify <plan> --seeds 10` on all six derived
  configs: **6/6 PASS**, 10/10 seeds each. Tail-ON cells check the 256 final
  indices (`mem[inp_values_p−256 : inp_values_p]`) against reference as well
  as the values; the tail-ON verify builds run with `ring_liveness_assert` at
  its auto-ON default and pass it.
* Cycle counts are seed-invariant on every cell (the schedule is
  data-independent), which is itself a consistency check.
* Fidelity of the parameterized tool: `(6,31) --tail on` reproduces
  `tools/p7tar_best_plan_1034.json` byte-identically (plan and drop compared
  entry-by-entry) at 1034 cycles.
* `python3 tests/submission_tests.py` → **Ran 9 tests, OK, CYCLES: 1006**
  (unchanged; nothing was ported).
* `git status` / `git diff --stat`: no modification to `dev.py`,
  `perf_takehome.py`, `problem.py`, or `tests/`.

## 7. Port recommendation

**Do not port.** `perf_takehome.py` stays at `l4_gmin=(6,31)`, 1006. The
with-idx board number stays 1034 at (6,31). No candidate came within 9 cycles
of either.

## 8. Known limitations / follow-ups

1. The (9,30) emission re-mine is a screen, not a matched search (§4). If the
   loop ever wants to reopen serve-profile tuning, the honest experiment is
   an f18/f37-scale order re-mine **per gmin**, budgeted like the original —
   and the prior is now that it must find ≥17 cycles to matter.
2. `derive()` keeps the best iterate but never prunes a mined plan. At (9,30)
   the mined plan is a 4-cycle regression over native-only, so a greedy prune
   over its 21 entries might recover a few cycles. Not run: it cannot close 17.
3. The screen's ring-free base and the strain's ring-free base are different
   configs (1049 vs 1026) and were both called "ring-free". Any future gmin
   screen should be run on `h061_common.kwargs(gmin, rings=False)`, which is
   the one that includes the emission order.
4. `tools/p7g_remine.py --tail off` never exercises `ring_liveness_assert`
   (its auto-ON default is rings AND tail). Tail-off ring safety is covered by
   the 10-seed value check only, exactly as the mainline's is.
