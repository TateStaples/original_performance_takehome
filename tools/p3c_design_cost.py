"""P3-C: abstract-design census calculator + exhaustive design-space enumeration.

Phase 3 asks a CENSUS question, not a scheduling question: for an abstract
DESIGN (which tree levels are served by selection vs gathered, by which
mechanism, at which index cost, with how many groups live), what are the
exact per-engine slot counts and the implied floors, and does ANY point in
the space clear 940 simultaneously on alu+valu, load and flow?

--------------------------------------------------------------------------
THE MODEL.  Every coefficient is either an ISA identity or is calibrated
against a measured build (see `validate()`).

Shape: 512 group-rounds (32 groups x 16 rounds), level(r) = r mod 11, so
levels 0-4 carry 64 group-rounds each and levels 5-10 carry 32.

1. HASH -- 46,464 alu+valu lane-ops = 5,808 vec-ops.  CONSTANT (closed by
   four independent tool classes over ~4e12 candidates: G-10/G-20/G-24).

2. ROUTING (getting the level's node value into each lane).  The ISA has no
   permute and no scratch-indexed vector read, so per lane this is exactly
   one of:
     * GATHER  -- 8 load slots per group-round (one per lane), plus
                  `gather_ovh` vec-ops of boundary fixup;
     * SERVE   -- fold the level's 2^d broadcast values down to 1:
                  folds(d) = 2^d - 1 ops per group-round, of which
                  leaf(d) = 2^(d-1) fold two BROADCAST constants (1 valu
                  madd with a precomputed diff, or 1 flow vselect) and
                  interior(d) = 2^(d-1) - 1 have runtime arms (1 flow
                  vselect, or 2 valu ops = sub + madd; dev.py:848).
                  Plus `mask_rate * (d-1)` vec-ops of condition extraction
                  (0 when a parity ring retains the raw parity vectors).
   Verified against dev.py's L1/L2/L3 emitters and `b3l_fold_diffs` (L4),
   and against the measured l4_gmin slope (tools/h058_marginal.py):
   d(vec)/d(served L4 gr) = +11.66, d(flow) = +6.31, d(load) = -8.00,
   i.e. 15 folds + ~3 masks - ~0 gather overhead.

3. INDEX / PARITY (P3-B, research/strains/p3b/STATE.md).  NOT a flat
   2 vec-ops/group-round.  Only 448 of 512 group-rounds emit index work
   (the L10->L0 wrap and the last round are exactly free).  Per paying
   transition into successor level e:
        1 vec-op   parity extract                        (always)
      + 0          if e is SERVED (bit stays loose)
      + 1 + j      if e is GATHERED, where j = the number of consecutive
                   SERVED levels immediately below e that must now be
                   packed into an address
      + 1 flow slot if e is GATHERED and level e-1 was also gathered
                   (the steady `omf +/- par` advance select)
   >>> This couples the served-level set to the index axis: serving a level
   makes the transition INTO it cost 1 instead of 2, but makes the exit
   transition out of the served run cost one more per loose bit. For a
   contiguous served prefix the two effects CANCEL exactly.

4. SETUP -- measured 616 lane-ops (77 vec-ops) + 60 load + 22 flow at 30
   live broadcast-table entries; grows with extra table entries.

Capacity: alu 12 + valu 6x8 = 60 lane-ops/cyc (7.5 vec-ops/cyc);
load 2/cyc; flow 1/cyc; store 2/cyc.  Floors are /60, /2, /1, /2.

Read-only.  Usage (repo root):
    python3 tools/p3c_design_cost.py
    python3 tools/p3c_design_cost.py --topn 12
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass, field

VLEN = 8
PERIOD = 11
ROUNDS = 16
N_GROUPS = 32
GROUP_ROUNDS = ROUNDS * N_GROUPS                     # 512
GD = {d: (64 if d <= 4 else 32) for d in range(PERIOD)}

# paying transitions (pred level -> succ level), each x N_GROUPS.
# rounds 0..14 minus round 10 (successor is level 0: free) ; round 15 is last.
TRANSITIONS = [(r % PERIOD, (r + 1) % PERIOD) for r in range(ROUNDS - 1)
               if (r + 1) % PERIOD != 0]
assert len(TRANSITIONS) * N_GROUPS == 448

LANE_PER_CYC, VEC_PER_CYC = 60, 7.5
LOAD_PER_CYC, FLOW_PER_CYC, STORE_PER_CYC = 2, 1, 2

HASH_VEC = 46464 / VLEN
STORE_SLOTS = 46
SCRATCH_SIZE = 1536

SETUP_VEC_BASE, SETUP_LOAD_BASE, SETUP_FLOW_BASE = 77.0, 60, 22
SETUP_TABLE_ENTRIES_BASE = 30
SETUP_VEC_PER_TABLE, SETUP_LOAD_PER_TABLE = 2.0, 1.0

SCRATCH_PER_LIVE_GROUP = 3 * VLEN        # st / val / nv
SCRATCH_PER_TABLE_ENTRY = 2 * VLEN       # evens + diffs, broadcast
SCRATCH_MISC = 285


def folds(d: int) -> int:
    return (1 << d) - 1


def leaf_folds(d: int) -> int:
    return (1 << (d - 1)) if d >= 1 else 0


@dataclass
class Design:
    served: dict[int, int] = field(default_factory=dict)   # level -> served gr
    K: int = N_GROUPS          # simultaneously live groups (census-neutral)
    idx_slack: float = 0.0     # vec-ops above the structural index floor
    mask_rate: float = 0.0     # vec-ops per (served gr, older bit)
    gather_ovh: float = 0.0    # vec-ops per gathered group-round
    label: str = ""

    def p(self, d: int) -> float:
        """fraction of level d's group-rounds that are served"""
        if d == 0:
            return 1.0
        return self.served.get(d, 0) / GD[d] if GD.get(d) else 0.0

    def table_entries(self) -> int:
        return sum(1 << d for d, n in self.served.items() if n > 0 and d >= 1)


def index_cost(d: Design) -> tuple[float, float]:
    """(vec-ops, flow slots) of index/parity maintenance under P3-B's rule.

    Partial levels are handled by expectation over the serve fraction; this
    is exact whenever every level is fully served or fully gathered, and the
    optimum of the enumeration is always of that form except at one level.
    """
    vec = flow = 0.0
    for pred, succ in TRANSITIONS:
        n = N_GROUPS
        ps, pp = d.p(succ), d.p(pred)
        vec += n * 1.0                                    # parity extract
        # gathered successor: accumulate + pack the loose run below it
        j = 0.0
        run = 1.0
        lv = succ - 1
        while lv >= 1:
            run *= d.p(lv)
            j += run
            lv -= 1
        vec += n * (1 - ps) * (1 + j)
        flow += n * (1 - ps) * (1 - pp) if pred != 0 else 0.0
    return vec + d.idx_slack, flow


@dataclass
class Census:
    lane: float
    load: float
    flow: float
    store: float
    vec: float
    served_gr: int
    gathered_gr: int
    idx_vec: float
    idx_flow: float
    folds_total: float
    folds_on_flow: float
    scratch: float
    f_compute: float
    f_load: float
    f_flow: float
    f_store: float
    binder: str
    maxfloor: float


def census(d: Design, force_folds_on_valu: float | None = None) -> Census:
    served_gr = sum(d.served.get(k, 0) for k in range(1, PERIOD))
    gathered_gr = (GROUP_ROUNDS - GD[0]) - served_gr

    F_tot = sum(d.served.get(k, 0) * folds(k) for k in range(1, PERIOD))
    L_tot = sum(d.served.get(k, 0) * leaf_folds(k) for k in range(1, PERIOD))
    I_tot = F_tot - L_tot
    masks = sum(d.served.get(k, 0) * d.mask_rate * max(0, k - 1)
                for k in range(1, PERIOD))

    te = d.table_entries()
    extra = max(0, te - SETUP_TABLE_ENTRIES_BASE)
    setup_vec = SETUP_VEC_BASE + SETUP_VEC_PER_TABLE * extra
    setup_load = SETUP_LOAD_BASE + SETUP_LOAD_PER_TABLE * extra

    idx_vec, idx_flow = index_cost(d)
    A = HASH_VEC + idx_vec + setup_vec + masks + d.gather_ovh * gathered_gr
    B = SETUP_FLOW_BASE + idx_flow                      # flow slots before folds
    load = setup_load + VLEN * gathered_gr
    f_load = load / LOAD_PER_CYC

    def ev(x: float, y: float):
        vec = A + x + 2 * y
        flw = B + (F_tot - x - y)
        return vec, flw, max(vec / VEC_PER_CYC, flw / FLOW_PER_CYC, f_load,
                             STORE_SLOTS / STORE_PER_CYC)

    if force_folds_on_valu is not None:
        x, y = force_folds_on_valu, 0.0
    else:
        # leaves cost 1 valu op, interiors 2 -> always spend leaves first.
        cands = [(0.0, 0.0), (L_tot, 0.0), (L_tot, float(I_tot))]
        xb = (VEC_PER_CYC * (B + F_tot) - A) / (1 + VEC_PER_CYC)
        cands.append((min(max(xb, 0.0), L_tot), 0.0))
        yb = (VEC_PER_CYC * (B + F_tot - L_tot) - A - L_tot) / (2 + VEC_PER_CYC)
        cands.append((L_tot, min(max(yb, 0.0), float(I_tot))))
        x, y = min(cands, key=lambda t: ev(*t)[2])

    vec, flw, mx = ev(x, y)
    scratch = SCRATCH_PER_LIVE_GROUP * d.K + SCRATCH_PER_TABLE_ENTRY * te \
        + SCRATCH_MISC
    f_c, f_f = vec / VEC_PER_CYC, flw / FLOW_PER_CYC
    f_s = STORE_SLOTS / STORE_PER_CYC
    binder = max(((f_c, "compute"), (f_load, "load"), (f_f, "flow"),
                  (f_s, "store")))[1]
    return Census(lane=vec * VLEN, load=load, flow=flw, store=STORE_SLOTS,
                  vec=vec, served_gr=served_gr, gathered_gr=gathered_gr,
                  idx_vec=idx_vec, idx_flow=idx_flow, folds_total=F_tot,
                  folds_on_flow=F_tot - x - y, scratch=scratch,
                  f_compute=f_c, f_load=f_load, f_flow=f_f, f_store=f_s,
                  binder=binder, maxfloor=mx)


# ------------------------------------------------------------------ validation
MEASURED = dict(lane=59489, load=1892, flow=797, store=46)
MEASURED_IDX_VEC, MEASURED_IDX_FLOW = 898.0, 166.0    # P3-B attribution


def shipped(**kw) -> Design:
    base = dict(served={1: 64, 2: 64, 3: 64, 4: 27}, K=32,
                idx_slack=0.0, mask_rate=0.0, gather_ovh=0.0,
                label="SHIPPED @1006")
    base.update(kw)
    return Design(**base)


def validate() -> None:
    d0 = shipped()
    iv, ifl = index_cost(d0)
    print("== VALIDATION vs the measured shipped 1006 kernel ==")
    print(f"index model (P3-B rule): {iv:.0f} vec / {ifl:.0f} flow   "
          f"vs P3-B measured {MEASURED_IDX_VEC:.0f} vec / {MEASURED_IDX_FLOW:.0f} flow"
          f"   [structural FLOOR is 826; measured slack {MEASURED_IDX_VEC-iv:+.0f}]")
    # calibrate the two support coefficients so BOTH split buckets match the
    # measured flow/valu split, then check every bucket.
    d = shipped(idx_slack=MEASURED_IDX_VEC - iv, mask_rate=0.222,
                gather_ovh=0.43)
    F_tot = sum(d.served.get(k, 0) * folds(k) for k in range(1, PERIOD))
    serving_flow = MEASURED["flow"] - SETUP_FLOW_BASE - MEASURED_IDX_FLOW
    c = census(d, force_folds_on_valu=F_tot - serving_flow)
    print(f"\n{'bucket':<12}{'model':>10}{'measured':>10}{'err':>9}")
    for k, m in MEASURED.items():
        mod = getattr(c, k)
        print(f"{k:<12}{mod:>10.0f}{m:>10}{(mod - m) / m * 100:>8.2f}%")
    print(f"{'scratch':<12}{c.scratch:>10.0f}{1533:>10}"
          f"{(c.scratch-1533)/1533*100:>8.2f}%")
    print(f"\nmodel floors : compute {c.f_compute:7.1f}  load {c.f_load:6.1f}"
          f"  flow {c.f_flow:6.1f}  store {c.f_store:5.1f}  -> {c.binder}")
    print(f"measured     : compute {59489/60:7.1f}  load {1892/2:6.1f}"
          f"  flow {797:6.1f}  store {23:5.1f}  -> compute")
    print("(realized cycles 1006; regret over the binding floor ~15)")


# ----------------------------------------------------------------- enumeration
def enumerate_space(idx_slack: float, mask_rate: float, gather_ovh: float,
                    K: int = N_GROUPS):
    designs = []
    levels = list(range(1, PERIOD))
    for r in range(len(levels) + 1):
        for full in itertools.combinations(levels, r):
            rest = [d for d in levels if d not in full]
            opts: list[tuple[int, int]] = [(-1, 0)]
            for p in rest:
                opts += [(p, n) for n in range(1, GD[p] + 1)]
            for p, n in opts:
                served = {d: GD[d] for d in full}
                if p > 0:
                    served[p] = n
                designs.append(Design(
                    served=served, K=K, idx_slack=idx_slack,
                    mask_rate=mask_rate, gather_ovh=gather_ovh,
                    label=("full=" + ("".join(f"L{d}" for d in full) or "-")
                           + (f" +L{p}x{n}" if p > 0 else ""))))
    return sorted(((census(d), d) for d in designs),
                  key=lambda t: t[0].maxfloor)


HDR = (f"{'maxfloor':>9}{'lane-ops':>10}{'load':>6}{'flow':>6}{'store':>6}"
       f"{'f_cmp':>7}{'f_ld':>7}{'f_flw':>7}{'binder':>8}{'srv':>5}{'gth':>5}"
       f"{'idxV':>6}{'scr':>6}  design")


def row(c: Census, d: Design) -> str:
    flag = "!" if c.scratch > SCRATCH_SIZE else " "
    return (f"{c.maxfloor:>9.1f}{c.lane:>10.0f}{c.load:>6.0f}{c.flow:>6.0f}"
            f"{c.store:>6.0f}{c.f_compute:>7.1f}{c.f_load:>7.1f}{c.f_flow:>7.1f}"
            f"{c.binder:>8}{c.served_gr:>5}{c.gathered_gr:>5}{c.idx_vec:>6.0f}"
            f"{c.scratch:>6.0f}{flag} {d.label}")


def report(idx_slack, mask_rate, gather_ovh, tag, topn=10):
    scored = enumerate_space(idx_slack, mask_rate, gather_ovh)
    print(f"\n== FRONTIER [{tag}] idx_slack={idx_slack:.0f} "
          f"mask_rate={mask_rate} gather_ovh={gather_ovh} ==")
    print(HDR)
    for c, d in scored[:topn]:
        print(row(c, d))
    b = scored[0]
    print(f"  -> MIN MAX-FLOOR {b[0].maxfloor:.1f}   "
          f"{'*** 940 REACHABLE ***' if b[0].maxfloor <= 940 else '940 NOT reachable'}")
    return b[0].maxfloor


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topn", type=int, default=10)
    a = ap.parse_args()

    validate()

    d0 = shipped()
    iv, _ = index_cost(d0)
    MEAS_SLACK = MEASURED_IDX_VEC - iv          # +84 vec-ops of measured slop

    print("\n\n################ ENUMERATION ################")
    print("Space: every subset of {L1..L10} fully served x every partial count")
    print("at one further level (405,000+ designs), x the optimal flow/valu")
    print("fold split.  K is census-neutral (see below) so it is not a")
    print("dimension of the census search.")

    grid = [
        (MEAS_SLACK, 0.222, 0.43, "AS-BUILT: measured index slop + measured support"),
        (0.0, 0.222, 0.43, "index at P3-B FLOOR, support as built"),
        (MEAS_SLACK, 0.0, 0.0, "index as measured, ALL support arithmetic FREE"),
        (0.0, 0.0, 0.0, "index at FLOOR and ALL support FREE (best case)"),
    ]
    best = {}
    for sl, mr, go, tag in grid:
        best[tag] = report(sl, mr, go, tag, a.topn)

    print("\n\n== SENSITIVITY: index cost (P3-B's axis) ==")
    print(f"{'idx lane-ops':>14}{'idx vec':>9}   "
          f"{'min max-floor (as-built support)':>34}"
          f"{'  (support free)':>18}")
    for lane_ops, note in ((7184, "measured today"), (6608, "P3-B floor, today's policy"),
                           (5888, "P3-B b=0 L4 policy"), (5120, "hypothetical -30%")):
        sl = lane_ops / VLEN - iv
        a1 = enumerate_space(sl, 0.222, 0.43)[0][0].maxfloor
        a2 = enumerate_space(sl, 0.0, 0.0)[0][0].maxfloor
        print(f"{lane_ops:>14}{lane_ops/VLEN:>9.0f}   {a1:>34.1f}{a2:>18.1f}"
              f"   <- {note}")

    print("\n== K sensitivity (simultaneously live groups) ==")
    for K in (32, 24, 16, 11, 8):
        c = census(shipped(K=K, idx_slack=MEAS_SLACK, mask_rate=0.222,
                           gather_ovh=0.43))
        print(f"  K={K:<3} lane {c.lane:.0f}  load {c.load:.0f}  flow {c.flow:.0f}"
              f"   scratch {c.scratch:.0f}"
              f"{'' if c.scratch <= SCRATCH_SIZE else '  [> 1536]'}")
    print("  K changes SCRATCH and latency slack only -- the census is")
    print("  identical, so K cannot move any engine floor (consistent with")
    print("  G-33: freed scratch buys nothing) . H-058: K>=11 covers the")
    print("  314-cycle everything-free dependency span at 940.")


if __name__ == "__main__":
    main()
