# Strain P5-J — close the 12 OPEN hash11->9 CEGIS deletion templates

status: PARTIAL (2026-08-02; session budget hit). 1 CLOSED analytically,
1 substantially narrowed by shift-split grind, 10 OPEN with calibrated
method + exact resume commands. Zero SAT/FOUND anywhere.

Mission: decide P5-D's 12 TIMEOUT nine-op deletion shapes of REAL_11
(sandwich9 excluded — P5-I owns it).
Tool: `tools/p5j_close.py` (imports tools/p5d_cegis.py machinery unmodified).

## Template ids (stable; from `python3 tools/p5j_close.py list`)

t0=[0,7] t1=[2,3] t2=[2,4] t3=[2,5] t4=[2,7] t5=[2,9]
t6=[4,6] t7=[4,7] t8=[4,9] t9=[5,7] t10=[5,9] t11=[7,9]
(REAL_11 op indices: 0=madd0,1=shr19,2=xorC1,3=join,4=maddP,5=maddQ,
6=join,7=madd4,8=shr16,9=xorC5,10=out-join never deleted. Enumeration
reproduces P5-D's 28 templates exactly — 16 UNSAT pairs + these 12; t6
dedups pair [5,6] branch=0, explaining why [5,6] is absent from P5-D's
verdict lists. All 12 retain BOTH shr ops.)

## Soundness additions (proofs in p5j_close.py docstring)

1. **CUT-VERTEX LEMMA** (generalizes P5-H's odd-K): myhash is bijective
   (P5-H) and dependency paths have strictly increasing slot ids, so the
   DAG factors into a chain of segments at every cut slot (a slot on ALL
   input->output paths); on a finite set a bijective composition forces
   every segment bijective and each segment's LAST op injective on the
   full 2^32 domain. Hence:
   - cut madd => K odd (K&1==1 is a sound pre-constraint: every
     full-function solution satisfies it, so sample-UNSAT under it is
     still a sound closure);
   - cut shr => template ANALYTICALLY UNSAT (image <= 2^31 < 2^32) — a
     full-function refutation, STRONGER than sample-UNSAT.
2. **SHIFT SPLIT**: fixing shr unknowns to concrete 1..31 values
   partitions the space exactly; UNSAT over all combos = sound closure.

## LEDGER (final for this session)

| id | pair | madds | cut-madds(oddK) | method | verdict |
|----|------|-------|------------------|--------|---------|
| t0 | [0,7] | 2 (p/q pair, no cuts) | none | 60s z3 | OPEN (TIMEOUT iter=0) |
| t1 | [2,3] | 4 | - | **cut-shr lemma** | **UNSAT-ANALYTIC, CLOSED** (deletion forwards shr onto main path: x->madd->shr->{madd,madd}^->madd->sigmaC; shr slot 2 is a cut) |
| t2 | [2,4] | 3 | 0,5 | 60s+oddK | OPEN |
| t3 | [2,5] | 3 | 0,5 | 60s+oddK | OPEN |
| t4 | [2,7] | 3 | 0 | 60s+oddK | OPEN |
| t5 | [2,9] | 4 | 0,6 | 60s+oddK | OPEN |
| t6 | [4,6] | 3 | 0,4,5 | 60s+oddK | OPEN |
| t7 | [4,7] | 2 | 0 | **shift-split grind** | **NARROWED: 853/961 combos decided — 806 UNSAT, 47 hard-TIMEOUT, 108 untried, 0 SAT** |
| t8 | [4,9] | 3 | 0,6 | 60s+oddK | OPEN |
| t9 | [5,7] | 2 | 0 | 60s+oddK | OPEN |
| t10 | [5,9] | 3 | 0,6 | 60s+oddK | OPEN |
| t11 | [7,9] | 3 | 0 | 60s+oddK | OPEN |

## Empirical findings (transferable to the remaining grind)

- **Monolithic solves are hopeless even with odd-K**: all 11 z3 templates
  TIMEOUT at 60s at iter=0; P5-D already showed 120s fails; sandwich9
  survived 10,800s. Splitting is the only viable path.
- **Split calibration**: a typical concrete-(s1,s2) combo refutes UNSAT in
  1-5s (t7) / 3-5s (t2, 3 madds). ~5% are stragglers (>25s).
- **Straggler geography (t7)**: (a) the s2=16 COLUMN (the real form's
  second shift) times out for s1=18..25 — near-real structure is hardest
  to refute; (b) the weak-first-shift corner s1>=23 with small s2 is a
  dense hard region (large s1 => first sigma nearly degenerate).
- t7 fully-closed rows: s1 in 1..17 ALL UNSAT (527 combos); rows 18..28
  UNSAT except the 47 stragglers below; rows 28(s2>=17)..31 untried.

## t7 remaining work (exact)

47 hard-TIMEOUT combos (25s cap, oddK=[0]):
(18,16)(19,16)(20,16)(21,16)(21,18)(22,16)(23,9)(23,13)(23,16)(24,7)
(24,9)(24,15)(24,16)(25,6)(25,7)(25,8)(25,16)(25,18)(26,5)(26,7)(26,8)
(26,9)(26,11)(26,14)(26,18)(26,20)(26,24)(26,26)(27,4)(27,5)(27,6)(27,7)
(27,8)(27,9)(27,14)(27,21)(27,22)(27,26)(28,3)(28,4)(28,5)(28,7)(28,8)
(28,9)(28,10)(28,14)(28,16)
Untried: s1=28 s2 in 17..31, and all of s1=29,30,31 (108 combos; the
grinder was killed at (28,16) at session end — no orphan processes left).

## Resume protocol

  # finish t7's untried tail (row 28 partially redone, cheap):
  python3 tools/p5j_close.py split --ids 7 --timeout 25 --max-iters 4 --s1-lo 28 --s1-hi 32
  # escalate a single straggler combo (A,B) at long budget:
  python3 tools/p5j_close.py split --ids 7 --timeout 900 --s1-lo A --s1-hi $((A+1)) --s2-lo B --s2-hi $((B+1))
  # grind any other template (band with --s1-lo/--s1-hi for 3-proc parallel):
  python3 tools/p5j_close.py split --ids N --timeout 25 --max-iters 4 --s1-lo 1 --s1-hi 32
  # cost estimate per template: ~35 min of 3-proc grind for the easy 95%
  # + straggler escalation (47 x 900s ~ 12 box-hours single-proc for t7 —
  # consider extra analytic constraints for the weak-shift corner first).
  # Priority: t9 (2 madds, mirror of t7), then t2/t3/t4, t11, t5/t8/t10, t6, t0
  # (t0 last: parallel p/q madds get no odd-K help).

Session logs (scratchpad, ephemeral): p5j_quick{A,B,C}.log, p5j_cal{2,7}.log,
p5j_t7_band{1,2,3}.log. All FOUND counts zero everywhere.
