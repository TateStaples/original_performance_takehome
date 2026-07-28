# P3-E: ring coverage and K — the two unknowns that decide C1\*

date: 2026-07-28 · status: final · baseline: dev.py at 2eaeec6 (clean, no
builder edits observed during this run) · mainline 1006

**VERDICT.** C1\* at floor 939 is an ARTIFACT. Its load-bearing leg (T2 at
~100% ring coverage) is scratch-infeasible at K=32 — the measured ceiling is
**40 of 64 group-epochs = 62.5%**, which puts the floor at **948** — and the
K≤16 that would make 100% coverage feasible measures **+75 realized cycles**
(1028 → 1103) on a controlled common base. That is more than C1\*'s entire
floor advantage. **The real, non-artifact C1\* is the K=32 / 62.5%-coverage
design at floor 948 (952 with shipped fold spelling), realizing ~960-975.**

---

## 1. RING COVERAGE — measured ceiling 40/64, floor 948

### 1.1 The measurement

`python3 tools/h059_ringmax.py` (unmodified, pre-existing tool):

```
{"case": "mainline(1006)",             "bundles": 1006, "scratch": 1533, "rings": 40}
{"case": "no rings",                   "bundles": 1026}
{"case": "all-64 rings (private words)","bundles": 1006, "scratch": 1533,
                                        "extra_rings": 24, "extra_words": 576}
{"case": "one slice + private rest",   "bundles": 1007, "scratch": 1533}
```

* the borrow mechanism (H-045 structural slices + H-048 mined plan) funds
  **exactly 40 of the 64 (epoch, group) rings** at the shipped order/mix;
* pushing to 64/64 costs **576 private words that do not exist** — the
  machine has 1,536 and the design already spends 1,533.

`python3 tools/audit_ring_windows.py` (its own config, `l4_gmin=(7,30)`)
independently tops out at 20 structural + 16 mined = **36/64**, "unfunded
remaining: 28". So 40 is the best mined figure and it is **order- and
mix-specific** (F-25 standing rule: ring plans must be re-mined from empty
when order or `l4_gmin` change).

### 1.2 The scratch arithmetic, checked against a measurement

Per covered (epoch, group) T2 needs **3 more vectors = 24 words** than the
packed design (P0..P3 + val + nv = 6 vec vs st + val + nv = 3). 100%
coverage therefore needs 64 × 24 = **1,536 extra words**. Available:

| source | words |
|---|---|
| real scratch spare at K=32 | 3 (1,536 − 1,533) |
| borrowed dead windows (40 triples, measured ceiling) | 960 |
| **total** | **963 = 62.7% of 1,536 ≈ 40/64** |

The borrow ceiling and the word ceiling agree to within one ring — they are
the same constraint counted two ways.

P3-C's scratch model `24K + 16·te + 285` is **confirmed by measurement**: a
K=16 aliased build reports `scratch_next_addr = 1149`, exactly P3-C's table
entry.

### 1.3 Coverage → residual support → floor

T2 removes 259 vec-ops (cond.mask 78 + pos.fold 141 + pos.seed 40) *for the
group-rounds it covers*; an uncovered served group-round keeps the packed
accumulator and pays the full rate, so residual = 259·(1 − coverage).
`tools/p3e_ringfloor.py` feeds that into P3-D's own joint model
(`p3d_joint.solve(..., mask=residual)`):

| coverage | rings/64 | residual vec | min C | min C (+4% shipped fold spelling) |
|---|---|---|---|---|
| 100.0% | 64 | 0 | **939** | 943 |
| 93.8% | 60 | 16 | 940 | 944 |
| 87.5% | 56 | 32 | 942 | 946 |
| 78.1% | 50 | 57 | 944 | 948 |
| 71.9% | 46 | 73 | 946 | 950 |
| **62.5%** | **40** | **97** | **948** | **952** |
| 50.0% | 32 | 130 | 950 | 954 |
| 37.5% | 24 | 162 | 954 | 957 |
| 0.0% | 0 | 259 | 962 | 966 |

**At the measured ceiling the floor is 948**, i.e. of the brief's three
candidates (939 / 945 / 953) the truth is between the last two and closer to
953 than to 939. 939 needs ≥ 94% coverage, which needs ~1,440 of the 1,536
extra words, which is unreachable at K=32 by a factor of 1.5.

### 1.4 Two caveats on the 40, in both directions

* **downward:** the mined donors are heavily `st` vectors (audit plan shows
  `st0..st15`, `st25`, `st26`, plus `nv16..nv31`, `lv`, `root_nv_vec`) — and
  T2 *deletes* `st`. Those donors vanish under T2; the freed 256 words come
  back as real scratch (≈10.7 rings), so the pool is roughly conserved, but
  the plan must be **re-mined from empty** and 40 is not guaranteed to
  survive. Not measured (would need the T2 program, which does not exist).
* **upward:** 40 is a *greedy mined* figure at one order, not a proof of
  optimality. Unknown headroom, bounded above by the word count (§1.2),
  which caps coverage at ~63% + whatever `st`-deletion returns (~+11 rings
  → ~79% → floor 944) if the bootstrapping works out. Even the optimistic
  bound does not reach 940.

### 1.5 Prior warning worth restating

Going 40 → 64 rings on the *shipped* program bought **exactly zero** cycles
(1006 → 1006, G-33; reproduced above). That does not transfer directly — T2's
rings do far more work than the shipped ring — but it is the only realized
evidence about marginal ring value that exists, and its sign is zero.

---

## 2. K VERDICT — NOT realizable; K=16 costs +75 realized

### 2.1 The controlled measurement

Everything below on ONE base: ring-free 1006 mix + `lazy_val_loads`
(`h059_alias.base_mix()`), per-W searched diagonals
(`h059_alias.BEST_LAGS`, `zip` interleave), seed 1, frozen grader. The only
thing toggled is `group_window=W`, i.e. whether the register *aliasing* that
actually frees the scratch is on.

| W | plan only (liveness, scratch NOT freed) | + aliasing (scratch freed) | correct |
|---|---|---|---|
| 32 | **1028** | 1028 | yes |
| 24 | 1049 | 1053 | aliased build incorrect (known G-33 caveat) |
| 20 | 1060 | 1073 | yes |
| **16** | 1074 | **1103** | yes |

**C1\* needs the aliased column** — the whole point of K≤16 is to free the
words. So the price of K=16 is **1028 → 1103 = +75 cycles**.

K=11 cannot be aliased (32 is not a multiple of 11). Plan-only, per-W tuned,
on the `NORING` base: W=32 1024 / W=24 1045 / W=20 1056 / W=16 1071 /
W=11 **1139** / W=8 1247. So K=11 is worse than K=16 by ~65 more.

Robustness: a second W=16 diagonal search (seed 11, 2,189 evals vs the
first's 1,002) reached only 1075 plan-only — 1071/1074 is a solid local
optimum, not a loose sample.

### 2.2 Attribution — which half transfers to C1\*

Engine census at the same three points (`tools/p3e_kfloor.py` and the
inline probe):

| point | alu slots | valu slots | load | binder floor | realized | regret | scratch |
|---|---|---|---|---|---|---|---|
| W=32 | 11,913 | 6,045 | 1,892 | valu 1007.5 | 1028 | 20.5 | 1,533 |
| W=16 plan-only | 11,489 | 6,118 | 1,892 | valu 1019.7 | 1074 | 54.3 | 1,533 |
| W=16 aliased | 11,137 | 6,175 | 1,892 | valu 1029.2 | 1103 | 73.8 | **1,149** |

Total lane-ops are flat (~60.3k) — **K is census-neutral, P3-C is right**.
The +75 splits:

* **+21.7 of valu FLOOR** — dev's `alu_offload` race wins less often as ILP
  thins (alu 11,913 → 11,137, valu 6,045 → 6,175). This half is
  scheduler-specific, and **G-36 already showed it does not help**: with the
  planned static partition the floor drift disappears but the cycle curve is
  unchanged (1025/1053/1104 vs race 1028/1053/1103 at W=32/24/16 — my race
  column reproduces 1028/1053/1103 exactly). Removing the floor rise simply
  moves the cost into regret.
* **+53.3 of REGRET** — chain/ILP thinning plus the WAR anti-dependence
  created by reusing group g's registers for group g+16. Any K=16 schedule
  on any design pays this; it is not a dev artifact.

**Does it generalise to C1\*?** The mechanism does (inference, not
measurement): C1\* binds alu+valu 938.3 / load 939.0 / flow 939.0 — a
three-way exact tie with *zero* engine slack, so it has strictly less room
to absorb chain latency than the shipped program, which carries ~60 cycles
of alu slack. Its regret at K=16 should be ≥ 74, not less. The load-idle
profile makes the mechanism concrete: at W=16 a **new mid-program load
bubble appears at cycles ~510-615** (68 idle load slots) that does not exist
at W=32, on top of a longer drain — and load is the engine C1\* saturates
exactly (1,878 of 1,880).

### 2.3 Reconciliation with G-33 / H-059 — the prior is CORRECT but overstated

G-33's published table (`W=32 1006 | W=24 1045 | W=20 1064 | W=16 1097`)
**mixes two bases**: the W=32 entry is the RINGED mainline (1006) while the
W<32 entries come from `h059_curve.py`, which is deliberately ring-free
(base 1026 measured, 1024-1028 tuned). On a common base the penalty is
**+21 / +32..45 / +75**, not +39 / +58 / +91 — G-33 overstates it by ~20
cycles, and better W=16/W=20 diagonals exist than it recorded.

**The prior result nevertheless generalises to C1\*'s configuration.** The
correction changes the magnitude, not the sign or the verdict: C1\*'s entire
floor advantage over mainline is 995 (shipped valu floor) → 939 = 56 cycles,
and 56 < 75. The direction of the inequality is not close.

---

## 3. C1\* STATUS

**ARTIFACT at 939. REAL at 948.**

| variant | ring coverage | K | floor | realized estimate |
|---|---|---|---|---|
| C1\* as claimed | 100% | ≤16 | 939 | ~1025+ (939 + ~11-21 regret + 75 K-tax) — **worse than mainline** |
| C1\* as buildable | 62.5% (measured ceiling) | 32 | **948** (952 w/ shipped fold spelling) | ~960-975 |

The failing leg is **T2 at ~100% coverage**, and it fails twice over:
scratch-infeasible at K=32 (§1.2, ceiling 62.5% ⇒ floor 948), and the K≤16
that would fix it costs more realized cycles than the design's whole floor
advantage (§2.1). The two unknowns in the brief are not independent — **they
are the same constraint**: 100% coverage *is* K≤16, so unknown 1 collapses
into unknown 2, and unknown 2 measures NO.

The surviving claim: a K=32, 62.5%-coverage C1\* has floor **948** and would
plausibly realize ~960-975 — a real ~35-45 cycle improvement over 1006 if
someone builds it, but **not 940, and not by an engine-floor route**.
G-36's standing warning applies to the realized estimate (three independent
confirmations that a lower engine floor is not automatically a win).

---

## 4. Tools written (read-only w.r.t. the kernel)

* `tools/p3e_kcurve.py` — ring-free K curve on a common base.
* `tools/p3e_ringfloor.py` — coverage → residual support → min feasible C,
  driving `p3d_joint.solve` unmodified.
* `tools/p3e_kfloor.py` — per-engine slot floors / regret split at W=32 vs 16.

## 5. What I did NOT do

* Did not build C1\*; every C1\*-side number is P3-A/P3-D's model, only the
  coverage input and the K input are mine.
* Did not re-mine a ring plan under a T2-shaped program (that program does
  not exist) — §1.4's downward caveat is therefore uncosted.
* Did not measure K=11 aliased (arithmetically impossible at 32 groups).
* Did not touch `tests/`, `problem.py`, `perf_takehome.py`, or `dev.py`.
