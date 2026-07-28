"""P3-A: parametric census model for SERVING formulations.

Scores a serving design by its three simultaneous engine floors, using only
quantities that were measured on the shipped kernel (tools/p3a_mech.py) plus
the structural cost law for tournaments.

Units: a "vec-op" is one 8-lane elementwise operation = 8 alu+valu lane-ops.
Combined alu+valu capacity is 60 lane-ops/cycle = 7.5 vec-ops/cycle, which is
achievable iff madd vec-ops <= 6*C (madd is valu-only; 2 alu slots/lane).

Structural cost law (G-23 / H-058: no permute, no scratch-indexed read, so
per-lane routing is exactly 1 load or 2^d-1 selects):
  serving one group-round at level d = 2^d - 1 two-way selects, of which
  2^(d-1) are LEAF selects (both arms compile-time broadcast tables ->
  1 valu madd via a precomputed diff, or 1 flow vselect) and 2^(d-1)-1 are
  INTERIOR selects (arms are runtime vectors -> 2 valu ops (sub+madd) or
  1 flow vselect).

Usage: python3 tools/p3a_model.py
"""

from __future__ import annotations

from dataclasses import dataclass

# ---- measured constants from the shipped 1006 kernel (tools/p3a_mech.py) ----
HASH_CORE_VEC = 5280        # 42,240 lane-ops, incl. 352 elided ^C5
FOLDIN_VEC = 512            # 4,096 lane-ops (val ^= node_val, 1/group-round)
PARITY_VEC = 448            # 3,584 lane-ops (val & 1 where a successor needs it)
SETUP_VEC = 83              # 665 lane-ops (broadcast tables + consts)
SETUP_FLOW = 22
SETUP_LOAD = 60
SETUP_STORE = 46

N_GROUPS = 32
ROUNDS = 16
PERIOD = 11
# group-rounds per level
GR = {d: (64 if d <= 4 else 32) for d in range(PERIOD)}
VALUE_GR = sum(GR[d] for d in range(1, PERIOD))   # 448 need a value; L0 free


@dataclass
class Design:
    name: str
    served: dict[int, int]        # level -> served group-rounds
    exits: int                    # gathered group-rounds preceded by a served one
    exit_extra_valu: int = 2      # extra valu ops per exit vs a steady recurrence
    upkeep_vec: int = 0           # position-accumulator upkeep + cond masks
    setup_vec: int = SETUP_VEC
    setup_load: int = SETUP_LOAD
    setup_store: int = SETUP_STORE
    leaf_valu_cost: int = 1       # valu ops for a leaf select
    inter_valu_cost: int = 2      # valu ops for an interior select
    note: str = ""


def census(d: Design, C: int) -> dict:
    s = sum(d.served.values())
    g = VALUE_GR - s
    leaves = sum(n * 2 ** (L - 1) for L, n in d.served.items() if n)
    inter = sum(n * (2 ** (L - 1) - 1) for L, n in d.served.items() if n)
    folds = leaves + inter

    # index: one address per gathered group-round (1 madd + 1 constant-select);
    # exits pay exit_extra_valu more.
    idx_valu = g + d.exit_extra_valu * d.exits
    idx_selects = g            # flow-eligible (else +1 valu each)

    base_valu = (HASH_CORE_VEC + FOLDIN_VEC + PARITY_VEC + idx_valu
                 + d.upkeep_vec + d.setup_vec)

    # allocate flow greedily: interiors (save 2) before leaves/omf (save 1)
    flow_avail = max(0, C - SETUP_FLOW)
    x_i = min(inter, flow_avail)
    rem = flow_avail - x_i
    x_rest = min(leaves + idx_selects, rem)
    fold_valu = (d.inter_valu_cost * (inter - x_i)
                 + 1 * (leaves + idx_selects - x_rest))

    valu_vec = base_valu + fold_valu
    madd_vec = 2048 + idx_valu + (leaves - min(leaves, x_rest))  # lower bound-ish
    loads = 8 * g + d.setup_load
    flow_used = SETUP_FLOW + x_i + x_rest

    return dict(
        s=s, g=g, folds=folds, leaves=leaves, inter=inter,
        lane_ops=8 * valu_vec, vec=valu_vec, madd=madd_vec,
        loads=loads, flow=flow_used, store=d.setup_store,
        f_av=8 * valu_vec / 60.0, f_ld=loads / 2.0, f_fl=flow_used,
    )


def report(d: Design, C: int = 940) -> None:
    c = census(d, C)
    ok_av = c["lane_ops"] <= 60 * C
    ok_ld = c["loads"] <= 2 * C
    ok_fl = c["flow"] <= C
    print(f"\n--- {d.name} ---   {d.note}")
    print(f"  served {c['s']} / gathered {c['g']}   folds {c['folds']}"
          f" (leaf {c['leaves']} / interior {c['inter']})")
    print(f"  alu+valu lane-ops {c['lane_ops']:>7} | load slots {c['loads']:>5}"
          f" | flow slots {c['flow']:>5}")
    print(f"  implied floors    /60 = {c['f_av']:7.1f} | /2 = {c['f_ld']:7.1f}"
          f" | /1 = {c['f_fl']:7.1f}")
    print(f"  VERDICT @ {C}: alu+valu {'OK' if ok_av else 'FAIL by %d lane-ops' % (c['lane_ops']-60*C)}"
          f" | load {'OK' if ok_ld else 'FAIL by %d' % (c['loads']-2*C)}"
          f" | flow {'OK' if ok_fl else 'FAIL by %d' % (c['flow']-C)}")


def min_cycles(d: Design) -> int:
    for C in range(700, 1300):
        c = census(d, C)
        if c["lane_ops"] <= 60 * C and c["loads"] <= 2 * C and c["flow"] <= C:
            return C
    return -1


def profile(s_target: int) -> dict[int, int]:
    """Cheapest serving profile reaching s_target group-rounds: shallowest first."""
    out: dict[int, int] = {}
    left = s_target
    for L in range(1, PERIOD):
        take = min(GR[L], left)
        if take:
            out[L] = take
            left -= take
        if not left:
            break
    return out


def main() -> None:
    print("capacity per cycle: alu+valu 60 lane-ops | load 2 | flow 1 | store 2")

    # --- calibration: reproduce the shipped design's census -----------------
    shipped = Design(
        name="S0 shipped (measured, for calibration)",
        served={1: 64, 2: 64, 3: 64, 4: 27}, exits=37 + 32,
        exit_extra_valu=1, upkeep_vec=259,
        note="packed position accumulator; upkeep = pos.fold+pos.seed+cond.mask",
    )
    report(shipped, 1006)
    print("   (measured shipped: 59,489 lane-ops / 1,892 loads / 797 flow)")

    cands = []

    # (i) direct per-lane conditions, no position accumulator at all
    for s in (219, 221, 240, 283, 448):
        cands.append(Design(
            name=f"C1 ring/no-accumulator, s={s}",
            served=profile(s), exits=35 if s >= 221 else 37,
            exit_extra_valu=2, upkeep_vec=0,
            note="conditions = retained raw parities; exits Horner from parities",
        ))

    # (ii) sum-of-products / multilinear madd serving (no vselect at all)
    cands.append(Design(
        name="C2 sum-of-products (multilinear madd, no vselect)",
        served=profile(221), exits=35, exit_extra_valu=2, upkeep_vec=0,
        leaf_valu_cost=1, inter_valu_cost=1,
        note="multilinear poly in the d parity bits = 2^d-1 madds, ALL valu-only",
    ))

    # (iii) store-engine broadcast construction (removes 59 valu vbroadcasts)
    cands.append(Design(
        name="C3 ring + store-engine table broadcast",
        served=profile(221), exits=35, exit_extra_valu=2, upkeep_vec=0,
        setup_vec=SETUP_VEC - 59, setup_load=SETUP_LOAD + 59,
        setup_store=SETUP_STORE + 472,
        note="8 scalar stores + 1 vload per table vector instead of vbroadcast",
    ))

    # (iv) ring + deeper serving to buy load slack
    for s in (250, 260, 275):
        cands.append(Design(
            name=f"C4 ring, s={s} (buy load slack with folds)",
            served=profile(s), exits=32, exit_extra_valu=2, upkeep_vec=0,
            note="more served group-rounds -> fewer loads, more flow pressure",
        ))

    for d in cands:
        report(d, 940)
        print(f"  min feasible C = {min_cycles(d)}")


if __name__ == "__main__":
    main()
