# P5-G — Web-intelligence sweep (2026-08-01)

Brief: mine every public artifact about the challenge for techniques absent from our
ledger; corroborate/contradict the k<=9.5 effective-hash requirement; any intel on how
904/889 (saifalharthi), 892 (wouterkool), 923/940 (josusanmartin), 941/958 (jamespayor),
950/1002 (dougall) were achieved.

Status: FINAL (~48 tool calls).

## VERDICT

1. **Zero NEW kernel mechanisms found anywhere public.** No artifact describes a hash
   below 11 ops/round, cross-round fusion, or anything absent from our ledger. Best
   documented public tier is still Wallace 1,137/1,152 (unchanged since 2026-01-24).
2. **The k<=9.5 requirement is neither corroborated nor contradicted** — the frontier's
   mechanism is completely undisclosed. Explanation found: Nareg's writeup states
   "**Anthropic has asked for solutions to remain private**" — the strong players are
   deliberately not publishing mechanisms.
3. **The frontier method (not mechanism) IS documented: large agent-research harnesses.**
   josusanmartin (923/940, 138+41 subs) runs Codex workers + his public "Scorebench"
   middleware + a "problem-agnostic-optimization" skill; stool233 (926) reached top-5
   with a Codex harness + scheduler-aware profiler; saifalharthi ground 71 subs to 889
   then ported to 904 in 3 subs. The named human kernel experts (payor, corsix, dougall)
   sit BELOW the agent-driven accounts. Implication: the sub-911 design was likely FOUND
   by machine-scale search, consistent with our position that only a k<=9 form (or an
   unknown frame-break) can get there — and nobody is going to hand it to us.

## Source table (filled as mined)

| # | url | author | best cycles | reachable? | yield |
|---|---|---|---|---|---|
| 1 | arxiv.org/abs/2604.01658 + /html (CORAL) | MIT/NUS group | 1103 | yes | techniques all subsumed (see ledger) |
| 2 | vliw-challenge.fly.dev/api/scoreboard (both) | — | — | yes | refresh 2026-08-01: no-idx top10 = 889 saif(71), 892 wouterkool(5), 908 ogotaiking(18), 922 adrianleb(3), 923 josu(138), 924 alan_wang(5), 926 stool233(4), 927 ligeng_zhu(8), 941 jamespayor(18), 950 dougall(9); anboto1 955 with 696 subs. with-idx: 904 saif(3), 940 josu(41), 958 payor(5), 981 glentaggart(1), 994 corsix(2), 995 paul1365972(1), 996 tmalesinski(1), 1002 dougall(2)+thejden(1) |
| 3 | mastodon.social API lookups (10 accounts) | — | — | yes | ALL frontier accounts have 0 posts. dougall = Dougall Johnson CONFIRMED (verified fields: dougallj.wordpress.com, github.com/dougallj, twitter dougallj). dougall is leaderboard user_id=1 (first account on the site). saifalharthi acct created 2026-02-01, josusanmartin 2026-02-02, wouterkool 2026-03-13, ogotaiking+alan_wang 2026-07-06, anboto1 2026-07-07, stool233 2026-07-09 (= Weng Jialin, github.com/Stool233, wengjialin.com, x.com/wengjialin37). adrianleb = Adrian le Bas (2016 acct) |
| 4 | dougall mastodon statuses (last 40, back to 2026-03-29) | dougall | 950/1002 | yes | zero takehome/vliw content in window |
| 5 | github.com/Stool233 repos | stool233 (926) | 926 | yes | NO takehome/vliw repo public |
| 6 | github.com/wouterkool repos | wouterkool (892) | 892 | yes | NO takehome repo (re-confirmed); all combinatorial-opt research (beam search, VRP, Gumbel-top-k) |
| 7 | github.com/EnvCommons/AnthropicTakehome | GeneralReasoning | n/a | yes | OpenReward RL ENVIRONMENT (reward interpolates 2164->1363 "Claude baselines"); no techniques |
| 8 | dougallj.wordpress.com + gist.github.com/dougallj | dougall | 950/1002 | yes | ZERO takehome content (blog last post 2022, gists 2023) |
| 9 | HN 46700594 (639 pts, full Algolia tree) | many | best mentioned: abra0 1112, eisbaw 1121 | yes | nothing sub-1100; all agent-orchestration tier |
| 10 | HN 48911420 (fiigii/ai-comp) | fiigii | n/a | yes | "general-purpose compiler optimizations" only (DCE, CSE, SLP vectorization; HIR->LIR->MIR->VLIW); docs: mad_optimization, slsr, load_store, hir_load_elimination |
| 11 | kerneloptimization.fun | — | — | partial | static shell; /api/leaderboard = {"error":"Failed to fetch leaderboard"}; thresholds 1487/1363 only |

## Notable leaderboard-shape intel

- saifalharthi: 71 subs to reach 889 no-idx, then only 3 subs to port to 904 with-idx.
  Port delta 15 cycles == our modeled k-design writeback delta (16). Consistent with a
  single parameterized generator, not hand-schedule.
- anboto1: 696 submissions, best 955 — looks like automated search from a weak design
  (grinding submissions does NOT reach the frontier: evidence the frontier is a design
  insight, not schedule-search luck).
- josusanmartin: 138 subs no-idx / 41 with-idx (923/940). Heavy iteration.
- dougall (Dougall Johnson) only made 9/2 submissions, stalled at 950/1002 in early Feb;
  user_id=1 => likely the first user (possibly connected to site creation).

## Technique ledger

(technique | source+quote | our status | if NEW: census sketch)

- CORAL idx pre-computation | "Pre-compute idx=2*idx+1 before hash, index update just adds
  direction. Same VALU count but multiply_add decoupled from hash critical path" | ALREADY-DONE
  (our idx representation/pointer-form work; latency-only trick, no op-count change)
- CORAL depth-0 XOR -> ALU | "Converting depth-0 XOR (rounds 0,11) from 1 VALU to 8 per-lane
  ALU per chunk. Saves 64 VALU, costs 512 ALU" | ALREADY-DONE (ALU offload is in our
  flow-balance mechanism; Wallace-tier)
- CORAL engine floors | "VALU (binding constraint at 1158) and ALU (1046)" | ALREADY-DONE
  (our census/floor machinery is far finer); their tier 1103 >> our 1006
- CORAL failed-conversion note | "Depth-1 XOR follows vselect (FLOW). Converting it creates
  8 ALU deps on the vselect output" | ALREADY-DONE (dependency-aware offload)

| 12 | Stool233/website blog: agent-harness-performance-takehome.md (2026-07-12) | stool233 = Weng Jialin | 951 then, 926 now (no-idx) | yes (raw via GitHub) | METHODOLOGY ONLY, zero kernel mechanisms: Codex + agent harness (529-line prompt contract, frozen tests, sole-integrator + read-only subagents, experiment registry w/ negative results, Perfetto trace-processor CLI + scheduler-aware profiler exporting ready/issue times + temp-storage lifetimes). Explicitly BANNED searching public solutions. Plateaued ~1000 until profiler built |
| 13 | THINNGO2511/AMD-GPU-MODE discord logs (GPU MODE Discord, 2026-03-17) | josusanmartin | 923/940 | yes | josu is active in GPU MODE Discord; quotes below; has X acct x.com/josusanmartin |
| 14 | paradigm.xyz/optimization-arena | Paradigm | — | partial (JS shell) | THIRD leaderboard exists: "Hand-optimize a kernel for a simulated VLIW machine — Anthropic's original performance take-home." 617 players, 8,720 runs; no visible board data |
| 15 | Medium indosambhav (7a5dc46dd6e0) | indosambhav | 1338 | yes | all subsumed (madd fusion "eighteen VALU ops per round to just six" = the 3 madd-able stages only; preload L0-L14 + vselect "eliminating roughly 400 memory loads"; N=24 batches; round fusion) |
| 16 | Medium adityarawat | adityarawat | 1487 | yes | all subsumed (vectorize, x&1, madd fusion, preload nodes 0-14, dep-aware scheduler, phase overlap) |

| 17 | NaregAmirianMegan.github.io/anthropic_takehome.html | Nareg Amirian Megan (naregmegan@gmail.com) | **966 no-idx** (1089 board entry is stale/with-idx) | yes (master branch raw) | Writeup "Kernel Development with LLMs - Breaking 970 Cycles". Explicitly withholds mechanisms ("Anthropic has asked for solutions to remain private"). Pillars named: reduce instructions / vector-scalar combo efficiency / DAG greedy scheduler improved via LLVM-SSA analogy. KEY QUOTE (Claude, at his 1078 plateau): "since the critical path (459) is far below the floor (~1000), a perfect schedule should hit ~floor with near-zero gap. My drain is a schedule artifact of sequential group emission, not fundamental." 1357 -> 1078 -> 966 via "algorithmic restructures" + scheduler rework |
| 18 | payor.io | jamespayor | 941/958 | yes | AI-alignment person; site has ZERO takehome content |
| 19 | wouterkool.github.io | wouterkool | 892 | yes | zero takehome mentions (grep empty) |

## Frontier intel

- **josusanmartin speaks (GPU MODE Discord, 2026-03-17, quotes verbatim):**
  - "I don't even know what the kernel does, and here I am. This is absurd."
  - "I'm having a lot of fun though, and learning a lot."
  - re rate-limiting complaints: "It's annoying for non-humans too." (implies he runs
    AGENT-driven submission loops)
  - "Here is another fun challenge. The top positions, at least James and Corsix are
    top-notch kernel engineers. https://vliw-challenge.fly.dev/"
  - (context: msgs are about the AMD GPU MODE challenge, but the self-description +
    138/41 submission counts support an LLM-agent-driven approach to OUR board too)
- **stool233 (926) reached top-5 with a Codex agent harness and NO named kernel
  mechanism beyond ours** — the writeup's pivot question at the ~1000 plateau was
  "Should we keep improving the schedule, or must we reduce the amount of work?"
  (consistent with our census law; no answer disclosed).
- **All frontier accounts (saifalharthi, josusanmartin, wouterkool, ogotaiking, alan_wang,
  anboto1, stool233) have ZERO Mastodon posts** — accounts created solely for leaderboard
  login. No writeups linked from any profile (stool233 links github.com/Stool233 +
  wengjialin.com but has no takehome repo).
- dougall = Dougall Johnson (dougallj), CONFIRMED via verified profile fields
  (dougallj.wordpress.com, github.com/dougallj). He has published NOTHING on the takehome
  (blog last post 2022, gists last 2023, recent 40 toots to 2026-03 checked). 950 no-idx
  with only 9 subs, then stopped. He is leaderboard user_id=1 (first account on the site).
- ogotaiking (908 no-idx) display_name = "zartbot" — matches the Chinese networking/AI-infra
  blogger handle (search pending).
- Possible link: "Anboto" is a Basque mountain; josusanmartin is a Basque name; anboto1
  (696 subs, best 955) may be a related/alt grinding automated search — unverified.
- saifalharthi: 71 subs to 889 no-idx, then 3 subs to 904 with-idx. Port delta 15 ==
  our modeled writeback delta for k-designs (16). Consistent with parameterized generator.

## Additional sources (final)

| # | url | author | best | yield |
|---|---|---|---|---|
| 20 | github.com/josusanmartin/problem-agnostic-optimization-{skill,adapters} + scorebench{,-skill} (pushed through 2026-07-31) | josusanmartin | 923/940 | HIS FULL METHOD, no mechanisms. PAO skill: "contract -> baseline -> bottleneck model -> candidate -> validate/measure -> decide -> iterate or escape"; references/fixed-resource-scheduling.md is his VLIW module: per-engine floors, "Use contract-aware omission only when output semantics prove state is unobserved" (=no-idx relief), "Schedule-only search cannot beat a proven lower bound above the target". resource-models.md: "If the target lies below one or more credible floors, stop schedule-only work and **delete work, fuse stages, specialize a contract-valid route, transfer work to measured slack, or change representation/primitive**"; "Invert A Toxic Primitive" (replace gather-family when microcoded/narrow). frontier-introspection.md: full protocol for mining faster artifacts + relabeling closures (algorithm-/mapping-/integration-negative etc). Scorebench = middleware over venues incl "Paradigm Puzzles", GPU Mode, HighLoad.fun; dashboards, per-submission records, token accounting |
| 21 | austinwallace.ca/kernel (re-check) | Austin Wallace | 1137/1152 | UNCHANGED since 2026-01-24; depth-3 balanced vselect tree, stage-major interleaving, ALU constant offload — all in ledger |
| 22 | obviy.us/blog/vliw-optimization | obviy.us | 1524 | all subsumed (madd fusion 3->1, preload L0-2, global list scheduler; load 100% util at their org) |
| 23 | trirpi.github.io | Tristan Trouwen | (analysis only) | educational; nothing new |
| 24 | EpicVogel X thread (via search snippets; page walled) | Daniel Vogel | 1105 | "hash algebraic merges, L4 tree caching, DAG-based list schedulers, 250K+ parameter configurations, emission order sweeps, store engine exploitation, loop-based kernels"; Lean "lower bound" 1,081 from load capacity "2,089 ops at 2/cycle" — org-specific load count, falsified by 889 frontier; all subsumed |
| 25 | josusanmartin blog (Highload.fun #1 vibecoding parts I-II, Jan 2026) | josusanmartin | — | exists on josusanmartin.com; exact post URLs 404 via guess; methodology tier (skipped, budget) |

## Technique ledger — final tally

NEW techniques: **ZERO**. Every named public technique maps to ALREADY-DONE
(madd fusion, preload/vselect trees incl depth-3 balanced tree, ALU offload,
stage-major interleaving, wavefront/list/beam scheduling, scratch residency, round
fusion, pointer idx, contract-aware idx omission) or CLOSED-DEAD in our graveyard
(schedule-only search past floor; load-bound claims at other orgs' op mixes).
Generic-but-aligned frontier advice worth noting: josu's escape list explicitly
includes "fuse stages" and "change representation/primitive" — i.e., the frontier's
own playbook, facing a floor, prescribes exactly the space P5-D is searching.

## Top-3 new research directions (plausibility x cycles)

1. **Fund P5-D/CEGIS harder (indirect corroboration).** The 889/904 accounts are
   agent-harness operations making 70-140 submissions; the humans who publish stall at
   941-1002. Machine-scale search finding a fan-out k<=9 form nobody published is the
   single hypothesis consistent with ALL web evidence + our inversion. (No public
   counter-evidence to k<=9.5 exists.)
2. **Paradigm optimization-arena** (paradigm.xyz/optimization-arena): 617 players, 8,720
   runs, JS-walled board, listed as a Scorebench venue. Unmined channel — Paradigm
   puzzles historically get post-mortems. Next: browser-capable fetch of its board/API,
   search "paradigm optimization arena writeup vliw".
3. **GPU MODE Discord full-text** (searchable dumps exist in stray repos, e.g.
   THINNGO2511/AMD-GPU-MODE): josusanmartin chats there; a VLIW-challenge thread with
   technique talk may exist. Next: github code search "vliw-challenge" in more dumps,
   or join-and-read (out of scope for this scout).

## Dead ends / unreachable

- kerneloptimization.fun /api/leaderboard: `{"error":"Failed to fetch leaderboard"}` on
  two attempts (server-side breakage); static page shows only 1487/1363 thresholds.
- EpicVogel X thread: walled; mined via search snippets only.
- saifalharthi: no writeups, no takehome repos (GitHub = 27 repos, ALL forks of
  databases/infra; bio "Software Engineer and Researcher", Jeddah); Mastodon 0 posts;
  web search for identity + techniques: nothing.
- wouterkool, jamespayor, adrianleb, glentaggart: no takehome artifacts anywhere found.
- Discord logs other than 16th-17th CSV: no vliw/takehome mentions.
- NaregAmirianMegan.github.io main branch 404 (master branch works).
- mintlify.wiki auto-docs: skipped (generated from repo, no new content).
