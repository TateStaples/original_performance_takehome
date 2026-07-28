"""P3-D: JOINT serving/index model.  Index cost is DERIVED, never swept.

Adjudicates P3-A (937.9 floor at s=221) against P3-C (964.8 as-built /
937.4 only at index=5,888 AND support-free), where P3-C reached its 937.4
by adding a NEGATIVE constant `idx_slack` to every design in its
enumeration (tools/p3c_design_cost.py, `report(...)` / the sensitivity grid)
-- i.e. it swept the index axis independently of the serving decision that
produces it.

THE MODEL.  A design is a per-GROUP schedule over the 16 rounds.
level(r) = r mod 11, so rounds are
    r : 0  1  2  3  4  5  6  7  8  9 10 | 11 12 13 14 15
    L : 0  1  2  3  4  5  6  7  8  9 10 |  0  1  2  3  4
Level 0 is the root: a compile-time constant, 0 folds and 0 loads.
Every other round is independently SERVED (2^L - 1 fold nodes, each 1 flow
vselect OR 1 valu madd -- P3-A T1) or GATHERED (8 load slots).

Index (P3-B's transition rule, applied per ROUND rather than per LEVEL):
  * 1 parity extract per paying transition; transitions are r -> r+1 for
    r = 0..14 excluding r = 10 (successor is level 0, discarded) and there
    is no transition out of round 15.  => exactly 14 per group = 448.
  * a GATHERED round needs an explicit address.  Walking the epoch and
    counting loose parity bits since the last materialised address:
    madds = (#loose bits) - 1 if the base is the level-0 root constant,
    else (#loose bits).  A served round emits no madd; its bit stays loose.
  * 1 flow-eligible two-way constant choice (`omf +/- par`) per GATHERED
    group-round (P3-A's idx_sel = g; P3-B section 9 confirms it is exact).

>>> THE COUPLING, EXACTLY.  Inside epoch 1 (rounds 0-10) serving level 4
does NOT reduce index cost: the address that round 4 would have packed
(4 loose bits, 3 madds) is simply packed one round later at round 5
(5 loose bits, 4 madds).  It cancels.  At round 15 it does NOT cancel,
because round 15 is the LAST round and has no successor -- a served round
15 never needs an address at all.  So P3-B's 5,888 index floor is bought
by serving the 32 EPOCH-2 (round-15) L4 group-rounds, and that purchase
costs 32 x 15 = 480 fold nodes and saves 32 x 8 = 256 load slots.  Both
legs are priced here in one model.

Read-only.  Usage:  python3 tools/p3d_joint.py
"""

from __future__ import annotations

import itertools

VLEN = 8
ROUNDS = 16
PERIOD = 11
NGROUPS = 32
LEVEL = [r % PERIOD for r in range(ROUNDS)]

# --- design-independent vec-op constants, from tools/p3a_mech.py @1006 ------
HASH_CORE = 5280          # 42,240 lane-ops
FOLDIN = 512              # 4,096 lane-ops, 1 per group-round
PARITY = 448              # 3,584 lane-ops, 14 extracts x 32 groups
SETUP_VEC_MIN = 70
SETUP_VEC_SHIPPED = 83
SETUP_LOAD = 60
SETUP_FLOW_MIN = 2        # 20 setup add_imm moved to alu (P3-A T3)
SETUP_FLOW_SHIPPED = 22
ADDIMM_ALU_VEC = 3
STORE_BASE = 78
MAX_STORE_BCAST = 48


def group_cost(sched: tuple[bool, ...]) -> tuple[int, int, int]:
    """sched[r] = True if round r is SERVED.  Rounds at level 0 are ignored.

    returns (madds, fold_nodes, gathered_rounds) for ONE group.
    """
    madds = folds = gath = 0
    loose = 0
    at_root = True            # base address is the level-0 constant
    for r in range(ROUNDS):
        L = LEVEL[r]
        if L == 0:            # root: constant value, no load, no fold
            loose = 0
            at_root = True
            continue
        loose += 1            # the parity bit produced by round r-1
        if sched[r]:
            folds += (1 << L) - 1
        else:
            gath += 1
            madds += loose - 1 if at_root else loose
            loose = 0
            at_root = False
    return madds, folds, gath


def all_schedules():
    """every per-group schedule; level-0 rounds forced served (free)."""
    free = [r for r in range(ROUNDS) if LEVEL[r] != 0]
    for bits in itertools.product((False, True), repeat=len(free)):
        s = [True] * ROUNDS
        for r, b in zip(free, bits):
            s[r] = b
        yield tuple(s)


# ---------------------------------------------------------------- feasibility
def feasible(C: int, M: int, F: int, G: int, setup_vec: int,
             setup_flow: int, fold_ovh: float = 1.0,
             mask: float = 0.0, store_bcast: bool = True):
    """M madds, F fold nodes, G gathered group-rounds (aggregate over 32
    groups).  Returns a census dict if the design fits in C cycles."""
    F = F * fold_ovh
    load0 = 8 * G + SETUP_LOAD
    if load0 > 2 * C:
        return None
    k = min(MAX_STORE_BCAST, 2 * C - load0) if store_bcast else 0
    base = (HASH_CORE + FOLDIN + PARITY + setup_vec + ADDIMM_ALU_VEC
            - k + M + mask)
    items = F + G                     # flow-eligible: fold nodes + omf selects
    flow_avail = C - setup_flow
    on_flow = min(items, flow_avail)
    vec = base + (items - on_flow)
    flow = setup_flow + on_flow
    load = load0 + k
    store = STORE_BASE + 8 * k
    ok = vec <= 7.5 * C and load <= 2 * C and flow <= C and store <= 2 * C
    return dict(C=C, vec=vec, lane=vec * VLEN, load=load, flow=flow,
                store=store, M=M, F=F, G=G, k=k,
                f_av=vec * VLEN / 60.0, f_ld=load / 2.0, f_fl=float(flow),
                ok=ok)


def solve(C: int, cands, **kw):
    """min over mixtures of <=3 group-schedules (32 groups) feasible at C."""
    best = None
    n = len(cands)
    for i in range(n):
        mi, fi, gi = cands[i]
        for j in range(i, n):
            mj, fj, gj = cands[j]
            for a in range(NGROUPS + 1):
                b = NGROUPS - a
                M = a * mi + b * mj
                F = a * fi + b * fj
                G = a * gi + b * gj
                r = feasible(C, M, F, G, **kw)
                if r and r["ok"]:
                    if best is None or r["lane"] < best[0]["lane"]:
                        best = (r, (cands[i], a), (cands[j], b))
    return best


def pareto(points):
    """keep (madds, folds, gathers) triples not dominated in all 3 coords."""
    pts = sorted(set(points))
    out = []
    for p in pts:
        if not any(q != p and q[0] <= p[0] and q[1] <= p[1] and q[2] <= p[2]
                   for q in pts):
            out.append(p)
    return out


def describe(sched):
    return "".join("S" if sched[r] else ("." if LEVEL[r] == 0 else "G")
                   for r in range(ROUNDS))


def main():
    scheds = list(all_schedules())
    costs = {s: group_cost(s) for s in scheds}
    print(f"schedules enumerated: {len(scheds)}")

    # ---------------- reproduce the known reference points -----------------
    def uniform(served_rounds):
        s = [True] * ROUNDS
        for r in range(ROUNDS):
            if LEVEL[r] != 0:
                s[r] = r in served_rounds
        return tuple(s)

    print("\n== index model check against P3-B's measured floor ==")
    # shipped policy: L1,L2,L3 served both epochs; L4 served for 23 groups in
    # epoch 1 (round 4) and 2 groups in epoch 2 (round 15)  [l4_gmin (9,30)]
    a = uniform({1, 2, 3, 4, 12, 13, 14, 15})     # L4 served both epochs
    b = uniform({1, 2, 3, 12, 13, 14})            # L4 gathered both epochs
    c = uniform({1, 2, 3, 4, 12, 13, 14})         # L4 served ep1 only
    d = uniform({1, 2, 3, 12, 13, 14, 15})        # L4 served ep2 only
    for nm, sc in (("ep1+ep2 served", a), ("neither", b),
                   ("ep1 only", c), ("ep2 only", d)):
        m, f, g = costs[sc]
        print(f"  {nm:<16} {describe(sc)}  madds/grp {m:>2}  folds/grp {f:>3}"
              f"  gath/grp {g:>2}")
    m_ship = 23 * costs[c][0] + 9 * costs[b][0] + 0  # epoch1 split
    # shipped = 23 groups served at r4, 9 gathered at r4; 2 served at r15
    ship_mix = [(costs[uniform({1, 2, 3, 4, 12, 13, 14})], 21),
                (costs[uniform({1, 2, 3, 4, 12, 13, 14, 15})], 2),
                (costs[uniform({1, 2, 3, 12, 13, 14})], 9)]
    M = sum(cst[0] * n for cst, n in ship_mix)
    F = sum(cst[1] * n for cst, n in ship_mix)
    G = sum(cst[2] * n for cst, n in ship_mix)
    print(f"  SHIPPED policy (23 ep1 + 2 ep2 served at L4): index ="
          f" {PARITY + M} vec = {(PARITY + M) * 8} lane-ops"
          f"   [P3-B floor 826 vec / 6,608 lane-ops]")
    print(f"      folds {F} (P3-C/P3-A: 1,109 at s=219)  gathered {G}"
          f"  loads {8*G+60} (measured 1,892)")
    e = uniform({1, 2, 3, 12, 13, 14, 15})
    Mb = 32 * costs[e][0]
    print(f"  b=0 POLICY (all 32 round-15 L4 served, none at round 4):"
          f" index = {PARITY + Mb} vec = {(PARITY + Mb) * 8} lane-ops"
          f"   [P3-B b=0 floor 736 vec / 5,888 lane-ops]")
    print(f"      folds {32*costs[e][1]}  gathered {32*costs[e][2]}"
          f"  loads {8*32*costs[e][2]+60}")

    # ---------------- the joint optimum ------------------------------------
    pts = pareto(costs.values())
    print(f"\npareto-minimal (madds, folds, gathers) triples: {len(pts)}")

    print("\n== JOINT OPTIMUM: min C feasible on all three engines ==")
    for tag, kw in (
        ("T1+T2+T3 (P3-A's assumptions, index DERIVED)",
         dict(setup_vec=SETUP_VEC_MIN, setup_flow=SETUP_FLOW_MIN)),
        ("+ shipped setup 83",
         dict(setup_vec=SETUP_VEC_SHIPPED, setup_flow=SETUP_FLOW_MIN)),
        ("+ add_imm stays on flow",
         dict(setup_vec=SETUP_VEC_MIN, setup_flow=SETUP_FLOW_SHIPPED)),
        ("+ 4% fold spelling overhead (shipped race_sel)",
         dict(setup_vec=SETUP_VEC_MIN, setup_flow=SETUP_FLOW_MIN,
              fold_ovh=1.04)),
        ("+ P3-C as-built support (mask 0.222/served-bit)",
         dict(setup_vec=SETUP_VEC_MIN, setup_flow=SETUP_FLOW_MIN,
              mask=0.0)),          # filled in below
    ):
        if "as-built support" in tag:
            continue
        lo = None
        for C in range(880, 1010):
            r = solve(C, pts, **kw)
            if r:
                lo = (C, r)
                break
        if lo is None:
            print(f"  {tag:<48} infeasible <= 1010")
            continue
        C, (r, (p1, n1), (p2, n2)) = lo
        mix = [(p, n) for p, n in ((p1, n1), (p2, n2)) if n]
        print(f"  {tag:<48} C={C}")
        print(f"      alu+valu {r['lane']:>6} load {r['load']:>5} flow"
              f" {r['flow']:>4} store {r['store']:>4}"
              f" | floors {r['f_av']:.1f}/{r['f_ld']:.1f}/{r['f_fl']:.1f}")
        print(f"      madds {r['M']} (index {(PARITY+r['M'])*8} lane-ops)"
              f"  folds {r['F']:.0f}  gathered {r['G']}  store-bcast k={r['k']}")
        for p, n in mix:
            s = next(s for s in scheds if costs[s] == p)
            print(f"      {n:>2} groups: {describe(s)}   "
                  f"(madds {p[0]}, folds {p[1]}, gath {p[2]})")

    # ------------- how much support arithmetic can the design afford? -------
    print("\n== SUPPORT-ARITHMETIC HEADROOM (T2 coverage) ==")
    print("   extra vec-ops of condition-prep/gather-support the design can")
    print("   absorb and still be feasible at a given C:")
    for C in (940, 946, 950, 960, 965):
        lo, hi = 0, 600
        while lo < hi:
            mid = (lo + hi + 1) // 2
            r = solve(C, pts, setup_vec=SETUP_VEC_MIN,
                      setup_flow=SETUP_FLOW_MIN, mask=mid)
            if r:
                lo = mid
            else:
                hi = mid - 1
        print(f"   C={C}: {lo} vec-ops ({lo*8} lane-ops) of support headroom")
    print("   [P3-A T2 removes 259 vec-ops (cond.mask 78 + pos.fold 141 +")
    print("    pos.seed 40) at the shipped design; P3-C's as-built calibration")
    print("    prices support at ~160 vec-ops at this design.]")

    # ---------------- P3-C's independent sweep, reproduced ------------------
    print("\n== WHAT P3-C's INDEPENDENT SWEEP DOES ==")
    print("   p3c sets idx_slack = target_index_vec - index_cost(shipped) and")
    print("   ADDS it to every design.  At target 5,888 lane-ops (736 vec) the")
    print("   constant is negative and is granted to designs that serve NO L4")
    print("   at all -- designs that cannot produce that index cost.")
    for name, sc in (("serve L1-L3 only, gather all L4", b),
                     ("serve L4 in epoch 1 only", c),
                     ("serve L4 in epoch 2 only (round 15)", d),
                     ("serve L4 both epochs", a)):
        m, f, g = costs[sc]
        print(f"   {name:<38} index {(PARITY//32 + m)*32*8:>6} lane-ops"
              f"  folds/grp {f:>3}  loads {32*g*8+60:>5}")


if __name__ == "__main__":
    main()
