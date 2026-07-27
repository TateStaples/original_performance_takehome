# Driver Loop Body (execute each iteration; this file is the compaction-proof source of truth)

The driver is the main assistant session. Agent completions re-invoke it (primary
wake signal); a ScheduleWakeup heartbeat (+1s) is the fallback. If resuming
from a compacted/fresh context: read this file + RESEARCH.md + backlog.md, then
continue from whatever step the state implies.

0. **RESEARCH MODE (user directive 2026-07-27): ALGO-FIRST under an
   idealized machine.** Evaluate hypotheses assuming INFINITE SCRATCH and
   PERFECT SLOT ALLOCATION: what matters is the op multiset (per-engine
   slot counts), the dependency span, and the resulting ideal floor
   (see H-044 tool) — NOT whether a change fits the current 1038 schedule,
   scratch budget, or greedy packer. Fitting/allocation work (beam packing,
   scratch juggling, schedule tie-breaks) is PARKED until the algo side is
   resolved; a hypothesis that loses on the real machine but wins on the
   ideal one is a KEEP (flag-gated), not a reject — record its ideal-floor
   delta. Rationale: G-23 showed we already run the frontier's slot
   balance; the 98-cyc gap to 940 is algorithmic.
1. **Re-arm heartbeat**: ScheduleWakeup +1s ("research-loop heartbeat").
2. **Sync & orient**: `git pull`; read `research/RESEARCH.md`, `research/backlog.md`.
3. **Harvest sweep**: check `research/strains/sweep/results/*.json` for configs
   beating mainline; verify winners per step 6; restart sweep (`tools/sweep.py`,
   background) on the next grid region if it exited.
4. **Select hypotheses**: 3 `open` hypotheses from 3 different strains, ranked by
   predicted_gain x plausibility / cost; mark `testing` in backlog.md; assign
   DISJOINT code regions (hash block / tournament block / idx-state block /
   scheduler+params) to minimize patch conflicts.
5. **Spawn agents**: 3 parallel worktree agents (prompt template in RESEARCH
   plan; hard rules: no tests/ edits, no build_kernel() dispatch change, new
   kwarg default-off bit-exact, keep debug_compares working, patch to scratchpad,
   agent writes only its own strains/<name>/STATE.md). Commit ledger; push.
6. **Verify each returned patch** (driver, serially, clean tree):
   `git am --3way` -> fast gate `python perf_takehome.py Tests.test_kernel_cycles`
   -> full gate `python tests/submission_tests.py` (all 9 green, note CYCLES)
   -> `python tools/diagnose_kernel.py` (delta for the ledger).
   On failure: `git am --abort`, record rejection + evidence.
7. **Accept rules**:

   - ANY commit: full grader green (dormant flags must not change build_kernel()).
   - Mainline default-flip: additionally strictly fewer cycles than current best.
   - Strain-frontier-only win: commit flag-gated OFF; record in strain STATE.md.
8. **Record**: every mainline accept -> `python tools/plot_progress.py --record

   <step> "<label>" "<note>"`. Update backlog (accepted/rejected), move
   rejections to graveyard.md with `evidence:` + `reopen-if:`; promote agents'
   proposed follow-ups into backlog.md (new H-ids); append iteration-log line
   in RESEARCH.md; refresh "Current best" table.
9. **Commit + push** (trailers: Co-Authored-By: Claude Fable 5

   <noreply@anthropic.com> + Claude-Session line). Unpushed work dies with the
   ephemeral container.
10. **Stall rotation**: strain dry 3 iters -> retire + promote replacement;
    6 global dry iters -> one cross-pollination iteration (single agent reads
    all /STATEs + graveyard). NO auto-stop. User status report every ~5 iters.
11. **Stop only when**: grader CYCLES < 1000 all-green (final --record, push,
    milestone report, disarm heartbeat) or the user says stop.