"""H-058: the feasible-census envelope for a target cycle count.

Phase-2 asks the BACKWARD question: what must a 940-cycle kernel's op census
and dependency structure BE?  This solves the constraint system rather than
searching for it.

Everything is anchored on the MEASURED 1006 census (tools/h058_census.py,
`python3 tools/diagnose_kernel.py`), never on a re-derived one -- H-044's
`tools/ideal_floor.py` re-derived its buckets from the 1038 report and
double-subtracted the 1,848 gather-address combines (they live in the
Routing bucket, not the Idx bucket), which is why its layer-2 optimum reads
~932 instead of ~960.  This tool works in DELTAS off a census that is
reproduced exactly, so that class of error cannot recur.

Unit of account: the VEC-OP (one 8-lane vector operation, or its 8-slot
scalar spelling).  The machine retires
    6 valu slots + 12 alu slots per cycle
  = 6 vec-ops + 12/8 vec-ops = 7.5 vec-ops/cycle for plain ops,
and a multiply_add costs 1 valu slot but 16 alu slots (mul+add per lane),
so madds are only worth putting on alu after valu is full.

Usage (repo root):
    python3 tools/h058_envelope.py                 # validation + envelope
    python3 tools/h058_envelope.py --target 940
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, replace

VLEN = 8
CAP = {"alu": 12, "valu": 6, "load": 2, "store": 2, "flow": 1}

# ---------------------------------------------------------------------------
# MEASURED anchors -- all from tools/h058_census.py on the shipped 1006 kernel
# ---------------------------------------------------------------------------
M_ALU_SLOTS = 11761
M_VALU_SLOTS = 5966
M_LOAD = 1892
M_STORE = 46
M_FLOW = 797          # 775 vselect + 20 add_imm + 2 pause
M_LANES = 59489       # alu + valu lane-ops
M_VECOPS = M_LANES / VLEN          # 7436.125
M_MADD_SLOTS = 2911   # 2048 hash + 343 idx + 504 routing + 16 setup
M_CYCLES = 1006

# Serving census (measured): L0 64 free, L1/L2/L3 64 each, L4 27 of 64
# served, 229 group-rounds gathered (1,832 scalar loads / 8).
M_S4 = 27
M_GATHERED = 229
M_SETUP_LOADS = 60    # 48 vload + 9 const + 3 load
M_FLOW_MISC = 22      # 20 add_imm + 2 pause

# Structural decomposition of the 59,489 lane-ops, in vec-ops.
# Each line is measured or exactly derived from a measured line; the
# reconstruction is checked in validate().
HASH_MADD = 2048                 # 4 fused madds x 512 group-rounds (exact)
HASH_PLAIN_BASE = 7 * 512        # 3,584: 2 shifts + 5 xors x 512 (exact)
HASH_NV_PENALTY = 176            # measured excess: rounds that cannot elide ^C5
IDX = 950                        # measured 7,600 lane-ops (parity + recurrence)
IDX_MADD = 343                   # measured
COMBINE = 229                    # 1 addr combine per gathered group-round
SEL_VALU = 275                   # routing madds that are folds (504 - 229)
COND = 777 / VLEN                # 97.125: cond re-extraction + pool combines
SETUP = 616 / VLEN               # 77.0: 59 vbroadcast + 16 madd + 16 alu
# selects actually spelled at 1006: 775 on flow + 275 on valu = 1,050.
# The nominal tree cost of the measured serving mix is
#   64*1 + 64*3 + 64*7 + 27*15 = 1,109, so 59 folds are elided/absorbed.
SEL_ELISION = 1109 - (775 + SEL_VALU)     # 59

# group-rounds per tree level (levels 0-4 are visited in rounds d and d+11)
GD = {d: (64 if d <= 4 else 32) for d in range(11)}
TREE_SEL = {d: 2 ** d - 1 for d in range(11)}        # selects per group-round
FIRST_LAYER = {d: 2 ** (d - 1) if d else 0 for d in range(11)}


# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Design:
    s4: int = M_S4              # level-4 group-rounds served (of 64)
    s5: int = 0                 # level-5 group-rounds served (of 32)
    prime: frozenset = frozenset({4, 5})   # mem levels C5-pre-xored
    relocate: bool = False      # forest re-based so fp == 1 (kills combines)
    cond_keep: float = 1.0      # surviving fraction of the 97 cond vec-ops
    setup_keep: float = 1.0     # surviving fraction of the 77 setup vec-ops
    flow_misc: int = M_FLOW_MISC
    groups_live: int = 32
    extra_vec: float = 0.0      # additive vec-op delta (for shadow prices)
    extra_load: float = 0.0     # additive load-slot delta


def prime_cost(levels: frozenset, relocate: bool) -> tuple[int, int, int]:
    """(vec-ops, load slots, store slots) to C5-pre-xor the named levels.

    Level d holds 2^d nodes -> ceil(2^d/8) each of vload / vxor / vstore.
    Levels 4 and 5 are already vloaded into the `lv` staging block for the
    pair tournament, so their read is free (measured: 48 setup vloads carry
    them).  `relocate` rewrites the WHOLE forest (2,047 words) to base 1, and
    is fused with the pre-xor: one pass, so the xor rides along free.
    """
    if relocate:
        return 256, 256, 256          # 2,047 words / 8, read+xor+write
    v = ld = st = 0
    for d in sorted(levels):
        blocks = -(-(2 ** d) // VLEN)
        v += blocks
        st += blocks
        if d not in (4, 5):
            ld += blocks
    return v, ld, st


def census(d: Design) -> dict:
    """Full engine census of a design, in vec-ops / slots."""
    served = {1: 64, 2: 64, 3: 64, 4: d.s4, 5: d.s5}
    gathered = sum(GD[k] - served.get(k, 0) for k in range(1, 11))

    pv, pl, ps = prime_cost(d.prime, d.relocate)
    primed = set(range(11)) if d.relocate else set(d.prime)

    # hash: 11 fused ops/group-round, +1 where ^C5 cannot fold into the next
    # round's ^nv (i.e. the next round's node value arrives unprimed).
    if d.relocate:
        nv_pen = 32                        # final round only (values must be true)
    else:
        unprimed_gathered = sum(GD[k] - served.get(k, 0)
                                for k in range(1, 11) if k not in primed)
        # measured baseline: 160 unprimed gathered group-rounds -> 176 penalty
        nv_pen = unprimed_gathered + (HASH_NV_PENALTY - 160)
    hash_plain = HASH_PLAIN_BASE + nv_pen

    # selects
    n_sel = sum(served[k] * TREE_SEL[k] for k in served) - SEL_ELISION
    first_cap = sum(served[k] * FIRST_LAYER[k] for k in served)

    combines = 0 if d.relocate else gathered
    loads = 8 * gathered + M_SETUP_LOADS + pl + d.extra_load
    stores = M_STORE + ps

    return dict(served=served, gathered=gathered, n_sel=n_sel,
                first_cap=first_cap, hash_plain=hash_plain,
                hash_madd=HASH_MADD, combines=combines, loads=loads,
                stores=stores, prime_vec=pv,
                cond=COND * d.cond_keep, setup=SETUP * d.setup_keep,
                flow_misc=d.flow_misc, extra_vec=d.extra_vec)


def floor_cycles(d: Design) -> dict:
    """Minimum C at which every engine budget is simultaneously satisfiable."""
    c = census(d)

    def feasible(C: float) -> bool:
        if c["loads"] > CAP["load"] * C:
            return False
        if c["stores"] > CAP["store"] * C:
            return False
        flow_sel = min(c["n_sel"], CAP["flow"] * C - c["flow_misc"])
        if flow_sel < 0:
            return False
        rest = c["n_sel"] - flow_sel
        # valu-spelled selects: 1 vec-op with a precomputed static diff
        # (first layer only), 2 vec-ops for a runtime-arm inner fold.
        first = min(rest, c["first_cap"])
        sel_vec = first + 2 * (rest - first)
        madd = c["hash_madd"] + IDX_MADD + c["combines"] + first
        plain = (c["hash_plain"] + (IDX - IDX_MADD) + c["cond"] + c["setup"]
                 + c["prime_vec"] + 2 * (rest - first) + c["extra_vec"])
        # assign madds to valu first (16 alu slots vs 8), then plain to valu,
        # then the remaining plain to alu at 8 slots/vec-op.
        vcap = CAP["valu"] * C
        m_valu = min(madd, vcap)
        p_valu = min(plain, vcap - m_valu)
        alu = 8 * (plain - p_valu) + 16 * (madd - m_valu)
        return alu <= CAP["alu"] * C and (sel_vec >= 0)

    lo, hi = 300.0, 4000.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if feasible(mid):
            hi = mid
        else:
            lo = mid
    C = hi
    # report the realised split at C
    flow_sel = min(c["n_sel"], C - c["flow_misc"])
    rest = c["n_sel"] - flow_sel
    first = min(rest, c["first_cap"])
    sel_vec = first + 2 * (rest - first)
    madd = c["hash_madd"] + IDX_MADD + c["combines"] + first
    plain = (c["hash_plain"] + (IDX - IDX_MADD) + c["cond"] + c["setup"]
             + c["prime_vec"] + 2 * (rest - first) + c["extra_vec"])
    return dict(C=C, vecops=madd + plain, madd=madd, plain=plain,
                loads=c["loads"], stores=c["stores"],
                flow=flow_sel + c["flow_misc"], sel_total=c["n_sel"],
                sel_flow=flow_sel, sel_valu_vec=sel_vec,
                gathered=c["gathered"], served=c["served"],
                compute_floor=(madd + plain) / 7.5,
                load_floor=c["loads"] / 2, flow_floor=flow_sel + c["flow_misc"])


# ---------------------------------------------------------------------------
# scratch model (words).  Validated against the shipped 1533/1536.
# ---------------------------------------------------------------------------
SCRATCH_TOTAL = 1536
SCRATCH_POOLS = 405      # temp/cond pools + constants + ring bookkeeping
                         # (1533 measured - 768 state - 360 L1-L4 tables)


def scratch(d: Design) -> dict:
    state = 24 * d.groups_live                       # st + val + nv per group
    tables = 0
    for k in (1, 2, 3, 4, 5):
        s = {1: 64, 2: 64, 3: 64, 4: d.s4, 5: d.s5}[k]
        if s:
            tables += VLEN * (2 ** k + FIRST_LAYER[k])   # values + static diffs
    total = state + tables + SCRATCH_POOLS
    return dict(state=state, tables=tables, pools=SCRATCH_POOLS, total=total,
                free=SCRATCH_TOTAL - total)


# ---------------------------------------------------------------------------
def validate() -> None:
    print("=" * 74)
    print("[0] VALIDATION against the measured 1006 census")
    print("=" * 74)
    base = Design()
    c = census(base)
    r = floor_cycles(base)
    # the model saturates flow; the shipped kernel does not, so validate the
    # census with flow PINNED at the 775 vselects it actually spells.
    cc = census(base)
    rest = cc["n_sel"] - 775
    first = min(rest, cc["first_cap"])
    pinned = (cc["hash_madd"] + IDX_MADD + cc["combines"] + first
              + cc["hash_plain"] + (IDX - IDX_MADD) + cc["cond"] + cc["setup"]
              + cc["prime_vec"] + 2 * (rest - first))
    print(f"model vec-ops (flow pinned at the measured 775) {pinned:.1f}"
          f"   measured {M_VECOPS:.1f}   delta {pinned - M_VECOPS:+.1f}")
    print(f"model vec-ops (flow saturated) {r['vecops']:.1f}"
          f"  -- the {M_VECOPS - r['vecops']:.0f} vec-op gap IS the unexploited"
          f" flow capacity")
    print(f"model loads   {c['loads']:.0f}      measured {M_LOAD}"
          f"       delta {c['loads'] - M_LOAD:+.0f}")
    print(f"model selects {c['n_sel']}      measured 1050 (775 flow + 275 valu)")
    print(f"model gathered grp-rounds {c['gathered']}   measured {M_GATHERED}")
    s = scratch(base)
    print(f"model scratch {s['total']} words (state {s['state']} + tables "
          f"{s['tables']} + pools {s['pools']})   measured 1533")
    print(f"model slot floor at the as-built mix: C = {r['C']:.1f}"
          f"   (measured realized 1006, engine LB 995, fungible 992)")


def scan(target: float) -> None:
    print()
    print("=" * 74)
    print("[1] THE ONE-DIMENSIONAL DESIGN SPACE: s4 (level-4 group-rounds served)")
    print("=" * 74)
    print("Levels 1-3 must be served (8 loads vs 1/3/7 selects per group-round);")
    print("levels 5-10 must be gathered (31+ selects vs 8 loads).  Everything")
    print("else is fixed by the algorithm, so the mix is one integer.\n")
    print(f"{'s4':>3}{'gath':>6}{'loads':>7}{'ldFl':>7}{'sel':>6}{'flow':>6}"
          f"{'selVal':>7}{'vecops':>8}{'cmpFl':>7}{'C':>7}")
    best = None
    for s4 in range(0, 65):
        d = Design(s4=s4)
        r = floor_cycles(d)
        if best is None or r["C"] < best[1]["C"]:
            best = (d, r)
        if s4 % 4 == 0 or 18 <= s4 <= 32:
            print(f"{s4:>3}{r['gathered']:>6}{r['loads']:>7}"
                  f"{r['load_floor']:>7.0f}{r['sel_total']:>6}{r['flow']:>6.0f}"
                  f"{r['sel_valu_vec']:>7.0f}{r['vecops']:>8.0f}"
                  f"{r['compute_floor']:>7.0f}{r['C']:>7.1f}")
    assert best is not None
    print(f"\nbest as-is: s4={best[0].s4}  C={best[1]['C']:.1f}"
          f"   (load {best[1]['load_floor']:.0f} / compute "
          f"{best[1]['compute_floor']:.0f} / flow {best[1]['flow_floor']:.0f})")

    print()
    print("=" * 74)
    print("[2] MECHANISM LEDGER (each applied at its own best s4)")
    print("=" * 74)
    print(f"{'mechanism':<46}{'C':>8}{'dC':>8}")
    base_C = best[1]["C"]

    def best_over_s4(**kw) -> tuple[int, dict]:
        b = None
        for s4 in range(0, 65):
            r = floor_cycles(Design(s4=s4, **kw))
            if b is None or r["C"] < b[1]["C"]:
                b = (s4, r)
        assert b is not None
        return b

    mechs = [
        ("baseline (prime L4/L5, all overhead)", {}),
        ("+ move 20 setup add_imm off flow", dict(flow_misc=2)),
        ("+ prime L6 as well", dict(prime=frozenset({4, 5, 6}), flow_misc=2)),
        ("+ prime L6,L7", dict(prime=frozenset({4, 5, 6, 7}), flow_misc=2)),
        ("+ delete HALF the cond overhead", dict(prime=frozenset({4, 5, 6}),
                                                 flow_misc=2, cond_keep=0.5)),
        ("+ delete ALL cond overhead", dict(prime=frozenset({4, 5, 6}),
                                            flow_misc=2, cond_keep=0.0)),
        ("+ delete ALL cond AND setup overhead",
         dict(prime=frozenset({4, 5, 6}), flow_misc=2, cond_keep=0.0,
              setup_keep=0.0)),
        ("relocate forest to fp=1 (kills combines)",
         dict(relocate=True, flow_misc=2)),
        ("relocate + no cond/setup overhead",
         dict(relocate=True, flow_misc=2, cond_keep=0.0, setup_keep=0.0)),
        ("serve 8 L5 group-rounds too", dict(s5=8, flow_misc=2)),
    ]
    for label, kw in mechs:
        s4, r = best_over_s4(**kw)
        print(f"{label:<46}{r['C']:>8.1f}{r['C'] - base_C:>8.1f}"
              f"   (s4={s4})")

    print()
    print("=" * 74)
    print(f"[3] SHADOW PRICES at the balanced optimum (target {target:.0f})")
    print("=" * 74)
    s4, r0 = best_over_s4(flow_misc=2, prime=frozenset({4, 5, 6}))
    print(f"reference point: s4={s4}  C={r0['C']:.2f}  "
          f"vecops {r0['vecops']:.0f}  loads {r0['loads']}  flow {r0['flow']:.0f}")

    def perturb(dvec: float = 0.0, dload: float = 0.0,
                dflow: float = 0.0) -> float:
        b = None
        for s in range(0, 65):
            d = Design(s4=s, flow_misc=2 - int(dflow),
                       prime=frozenset({4, 5, 6}),
                       extra_vec=-dvec, extra_load=dload)
            r = floor_cycles(d)
            if b is None or r["C"] < b["C"]:
                b = r
        assert b is not None
        return b["C"]

    for dv in (0, 50, 100, 200, 400):
        print(f"  remove {dv:>4.0f} vec-ops of overhead -> C = {perturb(dvec=dv):7.2f}")
    for dl in (0, -50, -100, -200):
        print(f"  {dl:>+5.0f} load slots               -> C = {perturb(dload=dl):7.2f}")

    print()
    print("=" * 74)
    print(f"[4] WHAT A {target:.0f} CENSUS MUST BE (solve the equalities)")
    print("=" * 74)
    C = target
    print(f"  load  budget  {CAP['load'] * C:>7.0f} slots -> gathered group-rounds"
          f" <= {(CAP['load'] * C - M_SETUP_LOADS) / 8:.1f}"
          f"  (levels 5-10 alone force 192 = 1,536 loads)")
    print(f"  flow  budget  {CAP['flow'] * C:>7.0f} slots -> selects on flow <= "
          f"{C - 2:.0f}")
    print(f"  alu+valu      {7.5 * C:>7.0f} vec-ops = {60 * C:.0f} lane-ops")
    print(f"  of which hash is {HASH_MADD + HASH_PLAIN_BASE + 32:>6.0f} vec-ops "
          f"({(HASH_MADD + HASH_PLAIN_BASE + 32) / (7.5 * C) * 100:.1f}% of budget) "
          f"- irreducible (G-10/G-20/G-24/H-043)")
    rest = 7.5 * C - (HASH_MADD + HASH_PLAIN_BASE + 32)
    print(f"  => non-hash budget {rest:.0f} vec-ops for idx + combines + "
          f"valu-selects + cond + setup + prime")
    print(f"     measured non-hash at 1006: "
          f"{M_VECOPS - (HASH_MADD + HASH_PLAIN_BASE + HASH_NV_PENALTY):.0f} vec-ops")


# ---------------------------------------------------------------------------
# [5] MEASURED-SLOPE envelope.  Independent of the structural cost model:
# every coefficient below is a regression slope measured by
# tools/h058_marginal.py (l4_gmin swept 1..33 served L4 group-rounds on the
# 1006 stream with the pinned ring plan dropped).
# ---------------------------------------------------------------------------
SLOPE = {"vecops": 11.66, "load": -8.00, "flow": 6.31, "madd": 7.50,
         "scratch": 0.28}
BASE_POINT = {"s4": 27, "vecops": 7436.125, "load": 1892, "flow": 797,
              "valu_folds": 338}   # valu_folds from the def-use pass


def measured_envelope(target: float) -> None:
    print()
    print("=" * 74)
    print("[5] MEASURED-SLOPE ENVELOPE (independent of the structural model)")
    print("=" * 74)
    print("slopes per served level-4 group-round, measured by h058_marginal.py:")
    for k, v in SLOPE.items():
        print(f"    d({k})/d(s4) = {v:+.2f}")

    def solve(removal: float = 0.0) -> tuple[float, float, float, dict]:
        best = None
        for i in range(-2700, 3800, 5):
            dl = i / 100.0
            V = BASE_POINT["vecops"] + SLOPE["vecops"] * dl - removal
            L = BASE_POINT["load"] + SLOPE["load"] * dl
            F = BASE_POINT["flow"] + SLOPE["flow"] * dl
            E = max(0.0, BASE_POINT["valu_folds"] + SLOPE["madd"] * dl)
            # export e selects valu -> flow; optimum equalises compute & flow
            lo, hi = 0.0, E
            for _ in range(50):
                m = (lo + hi) / 2
                if (V - m) / 7.5 > F + m:
                    lo = m
                else:
                    hi = m
            for e in (0.0, E, hi):
                e = min(max(e, 0.0), E)
                C = max((V - e) / 7.5, L / 2, F + e)
                if best is None or C < best[0]:
                    best = (C, dl, e, {"compute": (V - e) / 7.5, "load": L / 2,
                                       "flow": F + e, "vecops": V - e,
                                       "loads": L})
        assert best is not None
        return best[0], BASE_POINT["s4"] + best[1], best[2], best[3]

    C, s4, e, d = solve()
    print(f"\njoint floor: C = {C:.1f}  at s4 = {s4:.1f}, "
          f"{e:.0f} selects exported valu -> flow")
    print(f"  compute {d['compute']:.1f} | load {d['load']:.1f} | "
          f"flow {d['flow']:.1f}   -- all three bind simultaneously")
    print(f"  census at the floor: {d['vecops']:.0f} vec-ops "
          f"({d['vecops'] * 8:.0f} lane-ops), {d['loads']:.0f} loads, "
          f"{d['flow']:.0f} flow slots")

    print("\nremoval required from the alu+valu census, by target:")
    for tgt in (960, 950, target, 930, 920):
        lo, hi = 0.0, 4000.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if solve(mid)[0] <= tgt:
                hi = mid
            else:
                lo = mid
        print(f"  floor {tgt:4.0f}: {hi:6.0f} vec-ops ({hi * 8:6.0f} lane-ops)"
              f"   marginal rate {8 * hi / max(C - tgt, 1e-9):5.0f} lane-ops/cycle")
    print("\nrealized-vs-floor friction on this stream is 11 cycles "
          "(1006 realized vs LB 995, G-32),")
    print("so REALIZING 940 needs a census floor near 929, not 940.")


# ---------------------------------------------------------------------------
# [6] scratch / groups-live trade curve.
# MEASURED latency anchors (tools/h058_oracle.py on the 1006 artifact):
#   every slot free                     -> 314 cycles  (the dependency skeleton)
#   vec+madd+gather+sel free            -> 331
#   vec+madd+gather free                -> 650
#   vec+madd free (all compute free)    -> 977   (load floor 946 + 31 friction)
# A group's 16 rounds are strictly serial, so with K of the 32 groups live at
# once the schedule runs 32/K generations, each of length C*K/32, and each
# generation must be at least one group's serial span (314):
#     K >= 32 * 314 / C          (K >= 10.7 at C = 940)
# ---------------------------------------------------------------------------
DEP_SPAN = 314


def scratch_curve(target: float) -> None:
    print()
    print("=" * 74)
    print("[6] SCRATCH / GROUPS-LIVE TRADE (the axis Phase 1 never tested)")
    print("=" * 74)
    print(f"dependency skeleton (every slot free, measured) = {DEP_SPAN} cycles")
    print(f"latency-feasibility at C={target:.0f}: K >= 32*{DEP_SPAN}/C = "
          f"{32 * DEP_SPAN / target:.1f} live groups\n")
    print(f"{'K':>4}{'state':>7}{'tables':>8}{'pools':>7}{'used':>7}{'free':>7}"
          f"{'gen len':>9}{'slack':>7}  what the free words fund")
    for K in (32, 28, 24, 20, 16, 12, 11, 8):
        sc = scratch(replace(Design(), groups_live=K))
        gen = target * K / 32
        needs = []
        if sc["free"] >= 32 * K:
            needs.append(f"FULL cond retention ({32 * K}w)")
        if sc["free"] >= 384:
            needs.append("L5 select table (384w, arithmetically negative)")
        if sc["free"] >= 256:
            needs.append("pair-preload (256w, closed G-18/G-28)")
        print(f"{K:>4}{sc['state']:>7}{sc['tables']:>8}{sc['pools']:>7}"
              f"{sc['total']:>7}{sc['free']:>7}{gen:>9.0f}"
              f"{gen - DEP_SPAN:>7.0f}  {'; '.join(needs) or '-'}")
    print("\ncond retention needs 4 parity vectors x 8 words per live group at")
    print("level 4 = 32K words; today parity_ring BORROWS 480 dead-register")
    print("words and funds 20 of 32 groups, leaving the measured 97 vec-ops of")
    print("cond re-extraction.  K = 16 funds all of them out of real scratch.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=940.0)
    args = ap.parse_args()
    validate()
    scan(args.target)
    measured_envelope(args.target)
    scratch_curve(args.target)


if __name__ == "__main__":
    main()
