# P6-A — Premise ledger, gambling dossier, Phase-6 charter (2026-08-02)

Brief: formalize the contradiction (904/889 exist AND the k<=9.5 inversion holds AND
the k=9 search is converging empty), enumerate every premise, derive the REQUIRED
VIOLATION MAGNITUDE per premise, audit P8 (the boards' validation contract) with the
INSTANCE-GAMBLING hypothesis, deliver the Phase-6 charter.

Status: FINAL. Tool: `tools/p6a_premise.py` (all numbers below reproduce).

---

## 0. THE CONTRADICTION, STATED EXACTLY

At k=11 (hash census intact) with every other premise at its proved value, the best
achievable cell in the P5-A/P5-F model overruns by:

| target | best g | overrun | lane over | load over |
|---|---|---|---|---|
| 904 with-idx | 233 | **+58.5 cyc** | +3,440 lanes | +117 slots |
| 889 no-idx | 231 | **+65.0 cyc** | +3,876 lanes | +130 slots |

**Decisive structural fact: even with loads FREE and serving FREE and setup FREE, k=11
still overruns by +4.0 cyc (904) / +5.5 cyc (889)** (hash 46,464 + idx 6,608 + setup 600
[+ tail 808] vs 60C). So P3 (loads), P5 (serving law) and P7 (setup) CANNOT explain the
frontier in any combination. Only P1, P2, P4, P6, P8 can.

## 1. PREMISE TABLE

Required violation = how much that premise alone must leak, all others held.

| # | premise | proof strength | required violation for 904 / 889 | plausibility |
|---|---|---|---|---|
| P1 | hash census 46,464 lane-ops (= 512k+176 vec-ops) | shape-complete inside 4 tool classes, per-round straight-line equivalence; **(S)-gap: non-decomposable global restructurings unsearched** | k <= **9.75 / 9.59** ops/round, i.e. leak 5,120 / 5,780 lanes (11.0% / 12.4% of the hash) | **the live one** — matches P5-A/C's k<=9.5 |
| P2 | index floor 6,608 lanes | 1.5M-form enumeration + all-2^32-constants lemma (P3-B) | cut by **5,120 / 5,780 lanes = 77% / 87%** of the whole index cost | very low: needs the floor to be ~5x wrong |
| P3 | 8 loads per gathered group-round | rank lemma + measured contiguity 0.003 | **IMPOSSIBLE — even 0 loads/gr leaves +4.0/+5.5 cyc** | closed as an explanation |
| P4 | 60 lane-ops/cycle (12 alu + 6 valu x 8) | **VERIFIED FROM SOURCE**: problem.py:65-74, VLEN=8 (problem.py:74) | need **>= 66 / 68** lane-ops/cycle | ~zero (flow's extra 8/cyc is already modeled separately and P5-F proved flow saturated) |
| P5 | serving cost 2^d-1 | lane-uniformity | **IMPOSSIBLE — free serving still overruns** | closed as an explanation |
| P6 | 512 group-rounds / 4,096 hash evaluations | value chain is sequential per walker; walkers i.i.d. | **11.0% / 12.4% fewer evaluations (451 / 510 of 4,096)** | very low: no sharing mechanism exists between independent random walkers |
| P7 | setup ~600 lanes, wrap at 0 | census + deterministic wrap (all idx start at 0 => level(r)=r mod 11) | **IMPOSSIBLE — setup=0 still overruns** | closed as an explanation |
| P8 | our reading of the validation contract | **partially verified, partially inferred (this doc, sec 2)** | see sec 3: an eps-approximate hash needs eps ~ 1e-6..1e-4 to be invisible | **the second live one** |

Additional premises found and added:

| # | premise | status |
|---|---|---|
| P9 | the score is the SIMULATED cycle count of the submitted instrs, not len(instrs) | inferred-strong: no absurdly-low entries exist; loops (cond_jump) are legal so len(instrs) scoring would be trivially exploitable to ~60 |
| P10 | the graded shape is exactly build_kernel(10, 2047, 256, 16) | **VERIFIED**: /static/pyodide-worker.js:49 |
| P11 | the graded semantics == our frozen grader | **VERIFIED**: /static/problem.py is BYTE-IDENTICAL to tests/frozen_problem.py (19,826 bytes) |
| P12 | the board's pipeline has been constant since Feb 2026 | unverified; corsix's Mar-2026 "legit" statement covers sub-1000 at that date only |

## 2. GAMBLING DOSSIER — (i) WHAT THE SERVER ACTUALLY VALIDATES

Sources (fetched 2026-08-02, treated as data):

- **`/static/pyodide-worker.js:29-59`** — the CLIENT runs the submitter's
  `perf_takehome.py` in Pyodide, calls `kb.build_kernel(10, 2047, 256, 16)`, and returns
  `json.dumps(kb.instrs)`. **The client never simulates and never sees an instance.**
- **`/static/main.js:206-247`** — `submitToServer(pythonCode, instrs)` gzips
  `{python_code, instrs}` and POSTs to `/api/submit`; the response carries
  `{passed, cycles, error}`. **The client sends no cycle count and no correctness claim**
  => the server independently simulates the instruction stream and decides pass/fail.
- `/api/submit` GET => 405 (Flask/werkzeug), POST unauthenticated => `{"error":"Not logged in"}`.
  No public server source. `Ray-234/vliw-challenge` is a competitor's solution repo, not the site.
- **The operator's own words** (dougall = Dougall Johnson, board operator, announcement
  2026-02-01, https://mastodon.social/@dougall/115995126852328657, quoted verbatim as data):
  > "I've had some fun and learned a lot from the 'Anthropic's Original Performance
  > Take-Home' optimisation challenge ... The old scoreboard (kerneloptimization.fun)
  > required Twitter login and **got overrun by python/rng-exploit submissions**, so
  > here's a new one that requires Mastodon for auth, in case anyone has been playing:
  > https://vliw-challenge.fly.dev/"

  Only one reply in the thread (@nietras "999"). No other post by dougall in the full
  2025-12-30..2026-08-02 window mentions the board (120 statuses paginated and grepped).

**Verdict on the policy:** the server generates and holds the instance itself; the
submitter's Python is out of the scoring path by design, explicitly as an anti-RNG-exploit
measure. **What remains UNKNOWN (no public artifact answers it): the NUMBER of validation
instances per submission and whether the instance is fresh per submission.** The reference
harness we were given uses 8 fresh unseeded instances for correctness plus 1 for timing
(tests/submission_tests.py:57-59, "Note the random generator is not seeded here").

**Fixed-instance attack is dead regardless**: to exploit a fixed instance you would have
to hardcode outputs, requiring exfiltration of ~2,047 x 30 = 61,410 bits of tree data
through a per-submission oracle that returns ~11 bits (the cycle count). 71-696
submissions supply <1.5% of that.

## 3. GAMBLING DOSSIER — (ii) CANDIDATE GAMBLES, EXACT p

Instance law (problem.py:415-437): 2,047 node values and 256 initial values are i.i.d.
uniform on **[0, 2^30)**; all indices start at 0; idx' = 2 idx + 1 + (val&1) with wrap to 0
at idx >= 2047 => **level(r) = r mod 11 for every walker** (levels 0-4 get 2 rounds each,
levels 5-10 one round each). 4,096 hash evaluations per instance.

| gamble | saving | exact p (1 instance) | E[subs] | verdict |
|---|---|---|---|---|
| **G1 partial-table serving** (serve s of 2^d nodes at level d) | m folds/gr | (1-m/2^d)^(256 x rounds_at_d); e.g. d=4 drop 1: 4.5e-15; d=5 drop 1: 3.0e-4; d=6 drop 8: 1.4e-15 | astronomical | **DEAD** — the gamble is a conjunction over 256 walkers, so any saving worth >4 cyc costs >=10 orders of magnitude of p |
| **G2 eps-approximate hash** (a k-op form differing from myhash on a fraction eps of 2^32) | 1-2 ops/round = 8.5-17 cyc/op | (1-eps)^4096 | see below | **THE ONLY VIABLE CLASS** |
| **G3 contiguity gamble** (vload a group-round) | 3.5 load-cyc/gr | 0.003^n | 333 for ONE gr | dead (needs ~50 gr) |
| **G4 skipped wrap / hazard margins / truncated columns** | - | p=1 | - | **NOT gambles**: the wrap and level schedule are deterministic (all walkers start at idx 0), already banked in the census |

**G2 arithmetic (the load-bearing table):**

| eps | bad inputs of 2^32 | p(1 instance) | p(8 instances) | E[subs] 1-inst |
|---|---|---|---|---|
| 1e-3 | 4,294,967 | 0.0166 | 4.8e-15 | 60 |
| 3e-4 | 1,288,490 | 0.293 | 5.4e-5 | 3.4 |
| 1e-4 | 429,497 | 0.664 | 0.038 | 1.5 |
| 1e-5 | 42,950 | 0.960 | 0.721 | 1.0 |
| 1e-6 | 4,295 | 0.996 | 0.968 | 1.0 |

- eps for p=0.5 on one instance: **1.69e-4**; for p=0.99: **2.45e-6**; for p=0.99 on eight
  instances: **3.07e-7**.
- **Detection thresholds of our own tools**: a 32-probe MITM meet still matches at
  eps=3.3e-3; the 10M-vector verify only passes at eps<=1.05e-8. **Between eps 1e-8 and
  1e-4 lies a four-order-of-magnitude window in which a form is rejected by every
  searcher we run and accepted by the real validator with probability 0.66-1.00.**

**This reframes P8 entirely.** The interesting regime is NOT "gamble at p=1.4% and
resubmit 71 times". It is eps <= 1e-5, where the kernel passes essentially always,
nobody (including its author, and including corsix inspecting it) can tell it is not
exact, and no resubmission grinding is needed. Validation is by sampling; our whole
search demands equality on all 2^32. **A competitor using an agent harness that validates
by running submission_tests.py would ACCEPT such a form without ever knowing.**

## 4. GAMBLING DOSSIER — (iii) VERDICT

1. **Instance gambling in the brief's sense (low-p, resubmit-until-pass) is NOT a viable
   explanation of 904/889.** Every position-based gamble is a 256-walker conjunction and
   dies by 10+ orders of magnitude (G1, G3). Submission counts are not evidence: anboto1
   has 696 submissions and only 955 cycles, so high counts are ordinary agent iteration.
   The 71-then-3 pattern is a 24x inconsistency in implied p (1.4% then 33%) and argues
   against a per-submission gamble.
2. **The eps-approximate hash IS viable and is the honest form of the hypothesis** — it
   needs no resubmission, no dishonesty, and survives every social check (corsix's
   "legit", dougall's own 950, no call-outs), because an eps<=1e-5 kernel is
   indistinguishable from a correct one without exhaustive verification.
2b. **Board refresh 2026-08-02 (both boards unchanged since 08-01) is decisive against
   low-p gambling**: no-idx = saifalharthi 889 (71 subs), **wouterkool 892 (5 subs)**,
   ogotaiking 908 (18), **adrianleb 922 (3)**, josusanmartin 923 (138), alan_wang 924 (5),
   stool233 926 (4), ligeng_zhu 927 (8); with-idx = saifalharthi 904 (3), josusanmartin
   940 (41), jamespayor 958 (5), **glentaggart 981 (1)**, corsix 994 (2), paul1365972
   995 (1), tmalesinski 996 (1), dougall 1002 (2). **892 — three cycles off the top — was
   reached in FIVE submissions.** Any gamble in that entry must have p >~ 0.2, i.e.
   eps <~ 3.5e-4. The whole 889-927 band is populated by low-submission accounts, so the
   sub-950 mechanism is reproducible, not lucky.
3. **The 904-889 delta of 15 does NOT discriminate**: our writeback-tail model predicts
   16 under exactness and under approximation alike.
4. **Transfer audit — which of our closures still hold if exactness is relaxed to eps<=1e-4:**
   - **TRANSFER (still refute approximate forms):** all z3 sample-UNSAT closures (9,187
     template combos, span7->5, the P5-J grind) — an eps=1e-4 form satisfies a 34-sample
     battery with p=0.997, so UNSAT kills it too. Also all lemmas whose violation is
     MACROSCOPIC: MINIMUM-SHR, cut-bijectivity K2, the `v+/-(v>>s)` lemma, the top-bit
     commutation lemma (a cut shr wrongs ~half the domain, not 1e-4 of it).
   - **DO NOT TRANSFER:** exact-count congruences and window arguments — P5-I2's
     differential-count theorem (N ≡ 0 mod 2^(33-s2)) and P5-I3's n_1-realizability
     windows are exact-arithmetic facts about a form that equals myhash everywhere;
     an eps-form's N may differ by up to eps*2^32. **204 of sandwich9's 961 (s1,s2)
     pairs (68 + 136) re-open under the eps-relaxation.**
   - **UNRESOLVED:** MITM "finds=0" counts only VERIFIED candidates (global_mitm.rs:465-487
     pushes to `finds` only when `verify` passes; probe-collisions print
     "FALSE-POSITIVE" to stdout, and the captured logs contain only CHECKPOINT lines).
     So the MITM closures do NOT yet transfer: an eps<=1e-3 form would have matched the
     32 probes, printed as FALSE-POSITIVE, and been discarded. **A single re-run with
     probe-match counting settles this (~35 min/slice).**

## 5. PHASE-6 CHARTER (ranked)

**R1 — eps-RELAXATION AUDIT (highest value, cheapest, never attempted).**
The premise most likely to be false is our reading of "correct" (P8), and it is the only
premise whose violation costs the frontier nothing.
- E1: re-run ONE already-closed MITM slice (`global_mitm.rs`) with a counter for
  32-probe matches and a mismatch-density report instead of a boolean verify. Decisive:
  it tells us whether the enumerated families contain near-exact 9/10-op forms. ~35 min.
- E2: re-open the 204 sandwich9 pairs killed by exact-count arguments, under an
  eps-tolerant encoding.
- E3: change STOKE's cost from Hamming-bit error to **input-error density** over a
  65,536-sample battery, target eps<=1e-4 at 9-10 ops. (Existing cascade already fires
  at err=0 on a 256-battery; log the density distribution of the best candidates.)
- **DECISION REQUIRED FROM THE USER before any eps-form is submitted**: an eps-kernel is
  knowingly not equal to the reference. Recommendation: pursue R1 as an EXPLANATION probe
  (does the frontier's score become reachable at all?) and do not submit a
  probabilistically-correct kernel without an explicit user call.

**R2 — ROUND-0 30-BIT DOMAIN (sound, unsearched, P5-E flagged and never funded).**
problem.py:415-437: every value < 2^30, and every walker starts at the root, so round 0's
hash input v0^root is provably < 2^30 (top two bits zero) for all 32 group-rounds. A form
that need only agree on a 2^30 subdomain is a strictly weaker requirement than anything
searched. Ceiling: 11 ops x 32 gr x 8 = 2,816 lanes = 47 cyc if round 0 were free;
realistic 2-op win = 512 lanes = 8.5 cyc. Reuse `s9_exact` / `global_mitm` with probes
drawn from [0,2^30) and the target myhash restricted to that domain.

**R3 — REPRESENTATION CHANGE / CONJUGATION (the named (S)-gap, made concrete).**
Search cheap bijections phi (madd by odd K, xorshift, xor-const, and <=2-op compositions)
for which **H_phi = phi o myhash o phi^-1** admits <=9 ops; the fold-in stays an xor
because phi linear => phi(x^n) = phi(x)^phi(n). This is invisible to every search to date
(all target myhash itself) and is exactly the non-decomposable restructuring P3-F/P5-L2
named as their residual scope gap. **Costing already done here:** a GLOBAL phi is dead —
it requires transporting all 2,047 node values (256 vloads + 256 vstores >= 128 cyc)
against <=8.5 cyc saved per op. But a **level-local phi over the SERVED levels only**
(31 node values, transformed in scratch for ~4 vec-ops/op) costs only phi/phi^-1 at the
~3 served<->gathered transitions (32 vec-ops per op per transition, ~1.6-3.2 cyc total)
and would apply to 10 of 16 rounds. First experiment: feed H_phi as the MITM target for
~50 candidate phi; existing tool, new target.

**R4 — CHEAP PREMISE RE-VALIDATION (do first, minutes).**
Re-fetch `/api/scoreboard` (both boards) to confirm 904/889 still stand and check for new
entries; this also re-dates P12. Optionally (needs user consent, it is a public post):
**ask dougall directly on Mastodon how submissions are validated** — he is the operator,
he answers replies, and one sentence from him collapses the entire P8 branch.

**R5 — CLOSED, do not fund further:** P3 (loads), P5 (serving law), P7 (setup) cannot
explain the frontier even at zero cost. P4 and P10/P11 are verified from source. P2 and P6
would each need a ~80% / ~12% violation of a machine-checked floor with no candidate
mechanism.

## 6. FILES / EVIDENCE

- `tools/p6a_premise.py` — premise-violation solver + gambling arithmetic (this doc's numbers).
- Site artifacts (fetched 2026-08-02, saved in scratchpad): `main.js` (268 lines),
  `pyodide-worker.js` (71), `problem.py` (19,826 bytes, == tests/frozen_problem.py).
- `problem.py:65-74` SLOT_LIMITS {alu 12, valu 6, load 2, store 2, flow 1}, VLEN 8 => 60 lane-ops/cyc.
- `problem.py:415-437` instance law; `tests/submission_tests.py:33-59` reference validation (8 unseeded instances).
- `rust_harness/src/bin/global_mitm.rs:45` PROBE_COUNT=32, `:465-487` find accounting, `:511+` 10M verify.
