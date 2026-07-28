"""P3-C: abstract-design census calculator + design-space enumeration.

Phase 3 asks a census question, not a scheduling question: for an abstract
DESIGN (which tree levels are served vs gathered, by which mechanism, at
which index cost), what are the exact per-engine slot counts and the
implied floors, and does any point in the space clear 940 on all three
engines simultaneously?

MODEL (every coefficient below is either an ISA identity or is calibrated
against a measured dev/perf build -- see `validate()` and the CALIBRATION
notes on each constant).

  Per group-round (there are 512 = 32 groups x 16 rounds; level(r)=r%11 so
  levels 0-4 carry 64 group-rounds each and levels 5-10 carry 32):

    * GATHERED  -> 8 load slots            (ISA: no permute / no vector
                                            gather / 0% lane contiguity,
                                            G-16; one load per lane)
                 + `gather_ovh` vec-ops    (address/boundary fixup)
    * SERVED at level d
                 -> folds(d) = 2^d - 1     (ISA: routing is exactly "1 load
                                            or 2^d-1 selects"; verified in
                                            dev.py's L1/L2/L3 emitters and
                                            b3l_fold_diffs for L4)
                    of which leaf(d) = 2^(d-1) fold a pair of BROADCAST
                    constants and therefore cost 1 valu madd (precomputed
                    diff) or 1 flow vselect; the interior 2^(d-1)-1 folds
                    have runtime arms and cost 1 flow vselect or 2 valu ops
                    (sub + madd) -- see dev.py:848.
                 + `mask_rate * (d-1)` vec-ops of condition extraction
                    (0 when the parity ring retains the raw parity vectors)
    * level 0 is free (root broadcast, 2^0-1 = 0 folds)

  Fixed:
    * HASH_VEC   = 5808 vec-ops (46,464 lane-ops), closed by four tool
                   classes over ~4e12 candidates. Constant.
    * index maintenance = c_idx vec-ops x 480 updated group-rounds
                   (15 of 16 rounds need a successor address; measured
                   950 vec-ops => c_idx = 1.98).
    * setup      = SETUP_VEC vec-ops + SETUP_LOAD load slots + SETUP_FLOW
                   flow slots, growing with the number of broadcast table
                   entries.

  Capacity: alu 12 slots/cyc scalar + valu 6 slots/cyc x 8 lanes = 60
  lane-ops/cyc = 7.5 vec-ops/cyc; load 2/cyc; flow 1/cyc; store 2/cyc.

Read-only.  Usage (repo root):
    python3 tools/p3c_design_cost.py            # validate + enumerate
    python3 tools/p3c_design_cost.py --cidx 1.5
"""

from __future__ import annotations

import argparse
import itertools
from dataclasses import dataclass, field

VLEN = 8
PERIOD = 11
ROUNDS = 16
N_GROUPS = 32
GROUP_ROUNDS = ROUNDS * N_GROUPS            # 512
# group-rounds per level: levels 0-4 occur in rounds d and d+11.
GD = {d: (64 if d <= 4 else 32) for d in range(PERIOD)}
UPDATED_GR = (ROUNDS - 1) * N_GROUPS        # 480 successor-address updates

# --- capacities (problem.py) -------------------------------------------
LANE_PER_CYC = 60          # 12 alu + 6*8 valu
VEC_PER_CYC = LANE_PER_CYC / VLEN   # 7.5
LOAD_PER_CYC = 2
FLOW_PER_CYC = 1
STORE_PER_CYC = 2

# --- fixed / calibrated constants --------------------------------------
HASH_VEC = 46464 / VLEN    # 5808 vec-ops, constant (G-10/G-20/G-24/G-38)
STORE_SLOTS = 46           # 32 result vstores + spill; never binds
SCRATCH_SIZE = 1536

# setup, measured @1006: 616 lane-ops = 77 vec-ops, 60 load slots,
# 22 flow slots, with 30 level-table entries live (2+4+8+16).
SETUP_VEC_BASE = 77.0
SETUP_LOAD_BASE = 60
SETUP_FLOW_BASE = 22
SETUP_TABLE_ENTRIES_BASE = 30
SETUP_VEC_PER_TABLE = 2.0     # vbroadcast + diff per extra table entry
SETUP_LOAD_PER_TABLE = 1.0    # vload per extra table entry

# scratch: 3 live vectors per live group (st/val/nv = 768 words at K=32),
# 2 broadcast vectors (evens + diffs) x 8 words per table entry, plus a
# measured ~285 words of pools/constants.
SCRATCH_PER_LIVE_GROUP = 3 * VLEN
SCRATCH_PER_TABLE_ENTRY = 2 * VLEN
SCRATCH_MISC = 285


def folds(d: int) -> int:
    return (1 << d) - 1


def leaf_folds(d: int) -> int:
    return (1 << (d - 1)) if d >= 1 else 0


def interior_folds(d: int) -> int:
    return folds(d) - leaf_folds(d)


@dataclass
class Design:
    """served[d] = number of the GD[d] group-rounds at level d that are
    served by selection instead of gathered."""
    served: dict[int, int] = field(default_factory=dict)
    K: int = N_GROUPS            # simultaneously live groups
    c_idx: float = 2.0           # vec-ops / group-round of index maintenance
    mask_rate: float = 0.0       # vec-ops per (served gr, older bit)
    gather_ovh: float = 0.0      # vec-ops per gathered group-round
    label: str = ""

    def table_entries(self) -> int:
        return sum(1 << d for d, n in self.served.items() if n > 0 and d >= 1)


@dataclass
class Census:
    lane: float
    load: float
    flow: float
    store: float
    vec: float
    served_gr: int
    gathered_gr: int
    folds_on_flow: float
    folds_on_valu: float
    scratch: float
    f_compute: float
    f_load: float
    f_flow: float
    f_store: float
    binder: str
    maxfloor: float


def census(d: Design, x_leaf_to_valu: float | None = None) -> Census:
    """Census of a design.  `x_leaf_to_valu` = how many LEAF folds are spelled
    on valu instead of flow; None => choose the split that minimises the
    max floor (the only free variable in the model)."""
    served_gr = sum(d.served.get(k, 0) for k in range(1, PERIOD))
    gathered_gr = (GROUP_ROUNDS - GD[0]) - served_gr

    F_tot = sum(d.served.get(k, 0) * folds(k) for k in range(1, PERIOD))
    L_tot = sum(d.served.get(k, 0) * leaf_folds(k) for k in range(1, PERIOD))
    I_tot = F_tot - L_tot
    masks = sum(d.served.get(k, 0) * d.mask_rate * max(0, k - 1)
                for k in range(1, PERIOD))

    te = d.table_entries()
    setup_vec = SETUP_VEC_BASE + SETUP_VEC_PER_TABLE * max(0, te - SETUP_TABLE_ENTRIES_BASE)
    setup_load = SETUP_LOAD_BASE + SETUP_LOAD_PER_TABLE * max(0, te - SETUP_TABLE_ENTRIES_BASE)

    fixed_vec = HASH_VEC + d.c_idx * UPDATED_GR + setup_vec + masks \
        + d.gather_ovh * gathered_gr
    load = setup_load + VLEN * gathered_gr
    f_load = load / LOAD_PER_CYC

    def eval_split(x: float, y: float) -> tuple[float, float, float]:
        vec = fixed_vec + x + 2 * y
        flow = SETUP_FLOW_BASE + (F_tot - x - y)
        return vec, flow, max(vec / VEC_PER_CYC, flow / FLOW_PER_CYC,
                              f_load, STORE_SLOTS / STORE_PER_CYC)

    if x_leaf_to_valu is None:
        # leaves cost 1 vec-op on valu, interiors 2 -> always move leaves
        # first.  The objective is piecewise-linear/convex in x, so the
        # balance point (or an endpoint) is optimal.
        lo, hi = 0.0, L_tot
        for _ in range(200):
            m1 = lo + (hi - lo) / 3
            m2 = hi - (hi - lo) / 3
            if eval_split(m1, 0.0)[2] <= eval_split(m2, 0.0)[2]:
                hi = m2
            else:
                lo = m1
        x = (lo + hi) / 2
        best = (eval_split(x, 0.0)[2], x, 0.0)
        if x >= L_tot - 1e-9 and I_tot > 0:      # leaves exhausted, spend interiors
            lo, hi = 0.0, float(I_tot)
            for _ in range(200):
                m1 = lo + (hi - lo) / 3
                m2 = hi - (hi - lo) / 3
                if eval_split(L_tot, m1)[2] <= eval_split(L_tot, m2)[2]:
                    hi = m2
                else:
                    lo = m1
            y = (lo + hi) / 2
            if eval_split(L_tot, y)[2] < best[0]:
                best = (eval_split(L_tot, y)[2], float(L_tot), y)
        _, x, y = best
    else:
        x, y = x_leaf_to_valu, 0.0

    vec, flow, mx = eval_split(x, y)
    scratch = (SCRATCH_PER_LIVE_GROUP * d.K
               + SCRATCH_PER_TABLE_ENTRY * te + SCRATCH_MISC)
    f_c, f_f, f_s = vec / VEC_PER_CYC, flow / FLOW_PER_CYC, STORE_SLOTS / STORE_PER_CYC
    binder = max(((f_c, "compute"), (f_load, "load"), (f_f, "flow"),
                  (f_s, "store")))[1]
    return Census(lane=vec * VLEN, load=load, flow=flow, store=STORE_SLOTS,
                  vec=vec, served_gr=served_gr, gathered_gr=gathered_gr,
                  folds_on_flow=F_tot - x - y, folds_on_valu=x + 2 * y,
                  scratch=scratch, f_compute=f_c, f_load=f_load, f_flow=f_f,
                  f_store=f_s, binder=binder, maxfloor=mx)


# ------------------------------------------------------------------ validation
MEASURED = dict(lane=59489, load=1892, flow=797, store=46)


def shipped_design(**kw) -> Design:
    """The 1006 kernel: L0-L3 fully served, L4 served at 27/64, rest gathered."""
    base = dict(served={1: 64, 2: 64, 3: 64, 4: 27}, K=32, c_idx=950 / UPDATED_GR,
                mask_rate=0.617, gather_ovh=0.43, label="SHIPPED @1006")
    base.update(kw)
    return Design(**base)


def validate(verbose: bool = True) -> Census:
    d = shipped_design()
    # the shipped kernel's actual flow/valu split is measured, not chosen:
    # 775 flow vselects of which 229 are gather boundary-selects -> 546 folds
    # on flow.  Feed that split in so the split is not a free parameter.
    F_tot = sum(d.served.get(k, 0) * folds(k) for k in range(1, PERIOD))
    c = census(d, x_leaf_to_valu=F_tot - (775 - 229 - 0))
    if verbose:
        print("== VALIDATION: model vs measured census of the shipped 1006 kernel ==")
        print(f"{'bucket':<10}{'model':>10}{'measured':>10}{'err':>9}")
        for k, m in MEASURED.items():
            mod = getattr(c, k)
            print(f"{k:<10}{mod:>10.0f}{m:>10}{(mod - m) / m * 100:>8.2f}%")
        print(f"\nmodel floors: compute {c.f_compute:.1f}  load {c.f_load:.1f} "
              f" flow {c.f_flow:.1f}  store {c.f_store:.1f}  -> binder {c.binder}"
              f"  max {c.maxfloor:.1f}")
        print(f"measured floors: compute {59489/60:.1f}  load {1892/2:.1f} "
              f" flow {797:.0f}   (h058_census.py)")
        print(f"scratch: model {c.scratch:.0f} vs measured 1533 "
              f"({(c.scratch-1533)/1533*100:+.1f}%)")
    return c


# ------------------------------------------------------------------ enumeration
def enumerate_space(c_idx: float, mask_rate: float, gather_ovh: float,
                    K: int = N_GROUPS, kmax_level: int = 10):
    """Exhaustive over served-level SETS x partial counts.

    Cost per served group-round is strictly increasing in d and every served
    group-round buys exactly the same 8 load slots, so for a fixed total
    served count the optimum is always 'fill the cheapest levels first'.
    We still enumerate every subset x partial level to prove that.
    """
    designs = []
    levels = list(range(1, kmax_level + 1))
    for r in range(len(levels) + 1):
        for full in itertools.combinations(levels, r):
            rest = [d for d in levels if d not in full]
            partial_opts: list[tuple[int, int]] = [(-1, 0)]
            for p in rest:
                partial_opts += [(p, n) for n in range(1, GD[p] + 1)]
            for p, n in partial_opts:
                served = {d: GD[d] for d in full}
                if p > 0:
                    served[p] = n
                designs.append(Design(served=served, K=K, c_idx=c_idx,
                                      mask_rate=mask_rate,
                                      gather_ovh=gather_ovh,
                                      label=f"full={full} partial=L{p}x{n}"))
    scored = [(census(d), d) for d in designs]
    scored.sort(key=lambda t: t[0].maxfloor)
    return scored


def report(c_idx: float, mask_rate: float, gather_ovh: float, tag: str,
           topn: int = 10):
    scored = enumerate_space(c_idx, mask_rate, gather_ovh)
    print(f"\n== FRONTIER ({tag}: c_idx={c_idx}, mask_rate={mask_rate}, "
          f"gather_ovh={gather_ovh}) ==")
    print(f"{'maxfloor':>9}{'lane-ops':>10}{'load':>7}{'flow':>7}{'store':>6}"
          f"{'f_cmp':>7}{'f_ld':>7}{'f_flw':>7}{'binder':>8}{'srv':>5}"
          f"{'gath':>6}{'scratch':>8}  design")
    seen = set()
    shown = 0
    for c, d in scored:
        key = tuple(sorted(d.served.items()))
        if key in seen:
            continue
        seen.add(key)
        flag = "!" if c.scratch > SCRATCH_SIZE else " "
        print(f"{c.maxfloor:>9.1f}{c.lane:>10.0f}{c.load:>7.0f}{c.flow:>7.0f}"
              f"{c.store:>6.0f}{c.f_compute:>7.1f}{c.f_load:>7.1f}"
              f"{c.f_flow:>7.1f}{c.binder:>8}{c.served_gr:>5}{c.gathered_gr:>6}"
              f"{c.scratch:>7.0f}{flag} {d.label}")
        shown += 1
        if shown >= topn:
            break
    best = scored[0]
    print(f"  -> MIN MAX-FLOOR = {best[0].maxfloor:.1f}  "
          f"({'940 REACHABLE' if best[0].maxfloor <= 940 else '940 NOT reachable'})")
    return scored[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cidx", type=float, default=None)
    ap.add_argument("--topn", type=int, default=10)
    a = ap.parse_args()

    validate()

    cidxs = [a.cidx] if a.cidx else [2.0, 1.5, 1.0]
    for ci in cidxs:
        report(ci, 0.617, 0.43, "CALIBRATED (measured support overheads)", a.topn)
        report(ci, 0.0, 0.0, "OPTIMISTIC (all support arithmetic free)", a.topn)

    print("\n== K sensitivity (simultaneously live groups) ==")
    for K in (32, 24, 16, 11, 8):
        d = shipped_design(K=K)
        c = census(d)
        print(f"  K={K:<3} census IDENTICAL (lane {c.lane:.0f} load {c.load:.0f} "
              f"flow {c.flow:.0f})   scratch {c.scratch:.0f}"
              f"{'  [< 1536]' if c.scratch <= SCRATCH_SIZE else ''}")
    print("  K is CENSUS-NEUTRAL: it changes scratch and latency slack only.")
    print("  (H-058: K>=11 covers the 314-cycle everything-free span at 940.)")


if __name__ == "__main__":
    main()
