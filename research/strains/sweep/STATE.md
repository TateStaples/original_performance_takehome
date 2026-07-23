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
