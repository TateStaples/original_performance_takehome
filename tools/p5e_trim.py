#!/usr/bin/env python3
"""P5-E: the k=10 rescue hedge — full trim ledger + honest censuses for
D1' (with-idx, C=904) and D2' (no-idx, C=889) at k=10, plus k=9 stacking.

Baseline law and decomposition are P5-C's (tools/p5c_frames.py):
  POOL0 = 53,286 lane-ops at k=11  (hash 46,464 + index 5,960 + setup ~580
          + round-15 fold penalty ~382; T1/T2@100%/T3 already applied,
          serving support = 0, folds/omf counted separately via overflow)
  F0    = 1,366 flow-eligible (1,139 folds + 227 omf)
  LOAD0 = 1,890 ; STORE0 = 96
  feasible at C iff POOL + 8*max(0, F - C) <= 60C, load <= 2C, store <= 2C
  serve-more-L4: per served gr load -8, folds +15

TRIM/ADD lines priced by this scout (see research/strains/p5e/STATE.md):
  T-omf   : each serve-more gr deletes its gather's omf select (P3-B:
            idx_selects = g exactly). P5-C omitted this. F += 14n not 15n.
  T-c5    : each ROUND-4 serve turns its group's round-3 trailing ^C5 into
            a c5_prexor elision (prexored L4 table): -1 vec-op = -8 lanes.
  T-idx15 : the 3 remaining round-15 L4 serves earn -3 madds each
            (P3-D measured -632/26gr => -24.3 lanes/gr): -72 lanes.
  T-dual  : w_fold re-tune recovers part of the round-15 fold penalty
            already inside POOL0 (P3-D: dual_fold rows +296 of +488;
            "recovering ALL still gives 942" from 945.5 => -210..-296).
            SPECULATIVE: never re-tuned/measured.
  A-ring  : POOL0 assumes T2 ring at 100%. Measured ceiling 62.5% =>
            +97 vec = +776 lanes (P3-E). Optimistic re-mine (st-deletion
            returns ~11 rings, 79%) => +432. k=10 scratch delta frees at
            most ~1 temp vector x <=32 in-flight groups = <=32 words =
            1.3 rings => coverage <=64.5%, residual -5 vec: NEGLIGIBLE.
  A-pen15 : +2.35 vec/gr round-15 penalty on the 3 added r15 serves: +56.
  A-slider: hash census 46,464 = 12 ops x 512 gr - ~336 c5 elisions (all
            x8); the per-removed-op unit is 512 vec (4,096 lanes), not the
            charter's 528 (4,224): +128 lanes per removed op ADVERSE.
  A-setup : POOL0 carries setup ~580; h058 measured 616 (shipped 664
            with-idx-free): +16..+104; mid +60.
  with-idx tail: 192 vec + 32 alu + 32 vst + 1 ld = +1,568 lanes (P5-C row
            CONFIRMED for T2 designs: all 32 r15 groups are served, pos4
            must be packed from raw parities P0..P3 = 3 madds + extract +
            sub + final madd = 6 vec/group; P5-A's 808 assumed the packed
            accumulator T2 deletes -> rejected for these designs).
"""

POOL0, F0, LOAD0, STORE0 = 53_286, 1_366, 1_890, 96
HASH_OP_CHARTER = 4_224   # 528-vec convention (P5-A/P5-C)
SLIDER_ADVERSE = 128      # +lanes per removed op if true unit is 512 vec
TAIL_POOL, TAIL_LOAD, TAIL_STORE = 1_568, 1, 32
R15_AVAIL = 3             # unserved round-15 L4 group-rounds in base design


def floor_c(pool, F, load, store):
    for C in range(600, 1400):
        if pool + 8 * max(0, F - C) <= 60 * C and load <= 2 * C and store <= 2 * C:
            return C
    return None


def joint_floor(pool0, load0, store, ring_add, setup_add, slider_tot,
                dual_trim):
    """Min feasible C with the serve-more count n chosen per C (n is forced
    by the load cap only; extra serves never help the pool: +14 F each)."""
    for C in range(600, 1400):
        n = max(0, -(-(load0 - 2 * C) // 8))          # ceil
        if n > 32 + R15_AVAIL:
            continue
        r15, r4 = min(n, R15_AVAIL), n - min(n, R15_AVAIL)
        F = F0 + 14 * n
        pool_h = (pool0 - 8 * r4 - 24 * r15 - dual_trim
                  + ring_add + 19 * r15 + slider_tot + setup_add)
        if pool_h + 8 * max(0, F - C) <= 60 * C and store <= 2 * C:
            return C
    return None


def scenario(name, board, target, k, *, tail, ring_add, setup_add,
             slider, dual_trim, regret=(11, 15)):
    kdrop = 11 - k
    pool = POOL0 - kdrop * HASH_OP_CHARTER + (TAIL_POOL if tail else 0)
    load = LOAD0 + (TAIL_LOAD if tail else 0)
    store = STORE0 + (TAIL_STORE if tail else 0)
    # serve-more count fixed by the load cap at the TARGET cycle count
    cap = 2 * target
    n = 0
    while load - 8 * n > cap:
        n += 1
    r15 = min(n, R15_AVAIL)
    r4 = n - r15
    F = F0 + 15 * n - n                       # T-omf: -1 omf per served gr
    load -= 8 * n
    trims = {"T-omf(in F)": 8 * n, "T-c5": 8 * r4, "T-idx15": 24 * r15,
             "T-dual(SPEC)": dual_trim}
    adds = {"A-ring": ring_add, "A-pen15": 19 * r15,
            "A-slider": slider * kdrop, "A-setup": setup_add}
    pool_h = pool - trims["T-c5"] - trims["T-idx15"] - trims["T-dual(SPEC)"] \
        + sum(adds.values())
    fl = joint_floor(pool, LOAD0 + (TAIL_LOAD if tail else 0), store,
                     ring_add, setup_add, slider * kdrop, dual_trim)
    lane_use = pool_h + 8 * max(0, F - target)
    lane_cap = 60 * target
    print(f"{name:34s} k={k} n={n:2d}(r4={r4},r15={r15}) "
          f"pool={pool_h:6d} F={F} ld={load} st={store} | "
          f"floor={fl} vs {target} ({target - fl:+d}) | "
          f"@{target}: lanes {lane_use}/{lane_cap} ({lane_cap - lane_use:+d} "
          f"= {(lane_cap - lane_use)/60:+.1f}cyc) | "
          f"realized {fl + regret[0]}..{fl + regret[1]}")
    return fl, lane_cap - lane_use


print("=" * 100)
print("A. Reproduce P5-C (their law, no omf credit, no honest adds) -- calibration")
print("=" * 100)
for nm, tgt, tail_p, k in (("no-idx", 889, 0, 10), ("with-idx", 904, 1536 + 32, 10),
                           ("no-idx", 889, 0, 9), ("with-idx", 904, 1536 + 32, 9)):
    pool = POOL0 - (11 - k) * HASH_OP_CHARTER + tail_p
    st = STORE0 + (32 if tail_p else 0)
    best = min(((floor_c(pool, F0 + 15 * n, LOAD0 - 8 * n, st), n)
                for n in range(30)), key=lambda t: t[0])
    print(f"  {nm:9s} k={k}: P5-C floor = {best[0]} (serve-more x{best[1]})")

print()
print("=" * 100)
print("B. D2' no-idx @889 and D1' with-idx @904, k=10 -- trim scenarios")
print("=" * 100)
for board, tgt, tail in (("no-idx", 889, False), ("with-idx", 904, True)):
    print(f"--- {board} target {tgt} ---")
    scenario("BEST (all trims, ring 79%, chtr)", board, tgt, 10, tail=tail,
             ring_add=432, setup_add=16, slider=0, dual_trim=296)
    scenario("EXPECTED (meas ring, mid setup)", board, tgt, 10, tail=tail,
             ring_add=776, setup_add=60, slider=128, dual_trim=210)
    scenario("WORST (no spec trims)", board, tgt, 10, tail=tail,
             ring_add=776, setup_add=104, slider=128, dual_trim=0)
    print()

print("=" * 100)
print("C. k=9 stacking (same trims/adds on D1/D2)")
print("=" * 100)
for board, tgt, tail in (("no-idx", 889, False), ("with-idx", 904, True)):
    print(f"--- {board} target {tgt} ---")
    scenario("BEST", board, tgt, 9, tail=tail,
             ring_add=432, setup_add=16, slider=0, dual_trim=296)
    scenario("EXPECTED", board, tgt, 9, tail=tail,
             ring_add=776, setup_add=60, slider=128, dual_trim=210)
    scenario("WORST", board, tgt, 9, tail=tail,
             ring_add=776, setup_add=104, slider=128, dual_trim=0)
    print()
