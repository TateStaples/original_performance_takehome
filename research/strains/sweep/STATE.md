# Strain: sweep (pure compute, no LLM)

## Charter
Exhaustive/priority grid search over build_kernel_scheduled tunables via
tools/sweep.py; results land in research/strains/sweep/results/*.json.
Grid grows to include every flag other strains land (free cross-pollination).
Driver harvests results each iteration; winners go through the same accept
gate as agent patches.

## Frontier
mainline 1140 @ b68a302 = tournament_levels=(1,2,3), alu_offload=True,
l4_gmin=(22,28), pool_sizes=(17,4), skew=(4,3).

## Grid state
Phase 1 (launched iter 1): l4_gmin in {14..30 step 2}^2 x pool_sizes
{(15,4),(16,4),(17,4),(18,4),(17,3),(17,5),(16,5)} x skew {(2,k),(4,k),(8,k)
k=1..5} + curated asymmetric lag lists. Done-set dedupe by config hash.

## Iteration log
(append-only)
- iter 1 / phase 1: 150 configs, 22s. NO config beats 1140; ties only re-express
  the baseline (pool_sizes=(17,3) ties). Defaults are locally optimal on every
  swept axis. Phase 2 (dense: exhaustive 4-block lag lists, l4_gmin incl.
  full-serve 0, dense pools, cross products) launched.
- iter 1 / phase 2 (a): 828 more configs (978 total), 122s. STILL zero below 1140;
  ties are aliases of the baseline ((4,3) == [0,3,6,9]). Parameter space of the
  CURRENT structure is exhausted -> H-005 closed until a structural flag lands
  (grid re-opens over new flags per charter). Next sweep waits on iter-1 agents.

- iter 2 / re-sweep under 1130 mainline (parity_conds): 981 configs, ZERO
  below 1130 — the (4,3)/(22,28)/(17,4) optimum is invariant under H-001's
  structural change; (17,3) still ties (32 words still free). sweep.py
  baseline now read from progress_log.json instead of hardcoded.
- iter 3 / phase 3 under 1088: 530 flag-combo configs; ONE winner:
  vsel_auto=(1,3) = 1087 (-1), accepted via full gate. Everything else at or
  above mainline -- the composed optimum is sharp.
- iter 4 / phase 4 under 1070: 493 configs (race-flag subsets, gmin dense,
  va x gmin, pools, skews incl. exhaustive short lag-lists): ZERO below 1070.
  The composed optimum is sharp after every accept. H-020/H-022 done.
- iter 6 / phase 5 under 1053: flag-combo grid (mem_prime x store_pair x
  b3 flags x dense epoch-1 gmin x pools x l4_race): 0 below 1053. The
  cross-pollination optimum is sharp on every tunable axis. Results
  archived to results-archive/base-1053/.
