#!/usr/bin/env python3
"""H-044: ideal-machine cost model + per-level serving-strategy solver.

The loop switched to ALGO-FIRST mode: assume an IDEALIZED machine (infinite
scratch, perfect slot allocation, zero scheduling friction) and ask which
ALGORITHMIC choices move the cycle floor. This tool answers four questions:

1. What is the ideal cycle floor of the CURRENT build's op multiset
   (validates against the known 1038 build: rigid per-engine floor 1021,
   fungible combined floor ~1015)?
2. Under infinite scratch, what is the min-cost per-tree-level serving
   strategy (gather vs flow-vselect tournament vs valu-madd tournament vs
   masked chains vs primed tables), and what ideal floor does the optimal
   global mix reach with the CURRENT hash+idx algorithm?
3. Sensitivity: d(ideal floor)/d(op removal) per purpose bucket.
4. Reconciliation: what op-mix deltas are SUFFICIENT to explain the 940
   with-indices frontier?

Fungibility model (explicit):
  - A vectorizable "lane-op" can run as 1 lane of a valu slot (6 slots x 8
    lanes = 48 lane-ops/cyc) or as 1 alu slot (12/cyc): combined capacity
    60 lane-ops/cyc for PLAIN ops (+ - ^ & | << >> ...), which have 1:1
    scalar spellings.
  - multiply_add lane-ops scalarize at 2 alu slots per lane (mul+add):
    fused only on valu.
  - Scalar-only work (setup consts etc.) can NOT vectorize: alu only.
  - Select-shaped work is additionally flow-eligible: 1 flow vselect = 8
    lane-ops of selection.  A select with a PRECOMPUTED diff vector (infinite
    scratch) also has a 1-valu-slot spelling b + cond*(a-b) (multiply_add);
    a select between runtime intermediates costs 2 valu slots (v- then madd),
    or 3 lane-ops of masked &|^ chain (dominated; reported for completeness).
  - load/store/flow slots are not fungible with compute.

Usage (repo root; plain python3 preferred -- uses scipy when available):
    python3 tools/ideal_floor.py            # full report
    python3 tools/ideal_floor.py --target 940
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

try:
    from scipy.optimize import linprog  # type: ignore
    HAVE_SCIPY = True
except Exception:  # pragma: no cover
    HAVE_SCIPY = False

VLEN = 8
CAPS = {"alu": 12.0, "valu": 6.0, "load": 2.0, "store": 2.0, "flow": 1.0}

# ---------------------------------------------------------------------------
# Census fixture: measured on the 1038 mainline (commit e0d35a6 lineage),
# tools/diagnose_kernel.py cross census (purpose x engine x opcode).
# ---------------------------------------------------------------------------
CENSUS_1038 = {
    "cycles": 1038,
    "span": 439,          # dependency-only span, no slot limits
    # slots per engine
    "engine_slots": {"alu": 11841, "valu": 6125, "load": 1900, "store": 38,
                     "flow": 788},
    # purpose x class (slots). plain = 1:1 alu spelling; madd = 2:1.
    "hash_alu_plain": 10584,   # ^ >>
    "hash_valu_madd": 2048,
    "hash_valu_plain": 2461,   # v^ v>>
    "idx_alu_plain": 408,
    "idx_valu_madd": 371,
    "idx_valu_plain": 509,     # v& v-
    "rout_alu_plain": 833,     # cond extraction, pool combines
    "rout_valu_madd": 531,     # raced first-fold selects
    "rout_valu_plain": 146,    # v& v-
    "rout_flow_vselect": 774,
    "rout_loads": 1848,        # gathers: 231 group-rounds x 8
    "setup_alu": 16,           # scalar-only
    "setup_vbroadcast": 59,
    "setup_loads": 52,         # 40 vload + 9 const + 3 load
    "setup_flow": 14,          # 12 add_imm + 2 pause
    "stores": 38,
}

# Problem shape: 256 walkers = 32 groups, 16 rounds -> 512 group-rounds.
# Lockstep descent: round r visits level r mod 11; levels 0-4 are visited in
# both epochs (rounds d and d+11) -> 64 group-rounds; levels 5-10 once -> 32.
N_GROUPS = 32
ROUNDS = 16
GD = {d: (64 if d <= 4 else 32) for d in range(11)}
ASBUILT_SERVE = {0: 64, 1: 64, 2: 64, 3: 64, 4: 25,
                 5: 0, 6: 0, 7: 0, 8: 0, 9: 0, 10: 0}
ASBUILT_PRIME = {5}  # H-026 mem_prime L5


# ---------------------------------------------------------------------------
# Layer 1: ideal floor of a given (plain, madd, scalar-only, flow-eligible)
# op multiset. Exact closed-form / tiny LP.
# ---------------------------------------------------------------------------
@dataclass
class ComputeSet:
    plain_lanes: float        # 1:1 alu-fungible lane-ops
    madd_lanes: float         # 2:1 alu-fungible lane-ops (fused on valu)
    scalar_only: float        # alu-only slots
    valu_only_slots: float    # valu slots with no alternative spelling (rare)
    sel_first: float          # selects w/ precomputed-diff arms: 1 flow | 1 valu | 8 plain-ish lanes... (alu 3/lane masked; tracked separately)
    sel_inner: float          # selects between runtime values: 1 flow | 2 valu
    loads: float
    stores: float
    flow_misc: float
    span: float

    def floor(self) -> tuple[float, dict[str, float]]:
        """Min cycles C such that a feasible engine assignment exists.

        Greedy-exchange-optimal assignment, verified against scipy LP:
        - flow takes selects first (each flow slot displaces 1-2 valu slots),
          inner selects before first (higher valu cost);
        - alu slack takes plain lane-ops 1:1, then madds 2:1.
        Solved by bisection on C (all constraints monotone in C).
        """
        lo, hi = max(self.span, 1.0), 5000.0

        def feasible(C: float) -> bool:
            if self.loads > CAPS["load"] * C:
                return False
            if self.stores > CAPS["store"] * C:
                return False
            flow_cap = CAPS["flow"] * C - self.flow_misc
            if flow_cap < 0:
                return False
            # selects: flow first (inner selects preferentially: save 2 valu)
            inner_f = min(self.sel_inner, flow_cap)
            first_f = min(self.sel_first, flow_cap - inner_f)
            valu_sel = 2.0 * (self.sel_inner - inner_f) + (self.sel_first - first_f)
            alu_cap = CAPS["alu"] * C - self.scalar_only
            if alu_cap < 0:
                return False
            # alu absorbs plain 1:1 then madd 2:1
            a_plain = min(self.plain_lanes, alu_cap)
            a_madd = min(self.madd_lanes, (alu_cap - a_plain) / 2.0)
            valu_lanes = (self.plain_lanes - a_plain) + (self.madd_lanes - a_madd)
            valu_slots = valu_lanes / VLEN + self.valu_only_slots + valu_sel
            return valu_slots <= CAPS["valu"] * C

        for _ in range(64):
            mid = (lo + hi) / 2.0
            if feasible(mid):
                hi = mid
            else:
                lo = mid
        C = hi
        detail = {
            "load_floor": self.loads / CAPS["load"],
            "store_floor": self.stores / CAPS["store"],
            "span": self.span,
            "compute_lanes": self.plain_lanes + self.madd_lanes,
        }
        return C, detail


def asbuilt_compute_sets(c: dict) -> dict[str, ComputeSet]:
    """Two views of the 1038 census.

    rigid: every op stays on the engine the build chose (per-engine floors).
    fungible: perfect allocation over the fungibility model above.
    """
    plain = (c["hash_alu_plain"] + c["idx_alu_plain"] + c["rout_alu_plain"]
             + VLEN * (c["hash_valu_plain"] + c["idx_valu_plain"]
                       + c["rout_valu_plain"])
             + VLEN * c["setup_vbroadcast"])
    madd = VLEN * (c["hash_valu_madd"] + c["idx_valu_madd"]
                   + c["rout_valu_madd"])
    fungible = ComputeSet(
        plain_lanes=plain, madd_lanes=madd, scalar_only=c["setup_alu"],
        valu_only_slots=0.0,
        # as-built flow vselects: treat as inner (conservative 2-valu
        # fallback); raced madd first-folds counted in madd above.
        sel_first=0.0, sel_inner=c["rout_flow_vselect"],
        loads=c["rout_loads"] + c["setup_loads"], stores=c["stores"],
        flow_misc=c["setup_flow"], span=c["span"])
    return {"fungible": fungible}


def rigid_floors(c: dict) -> dict[str, float]:
    e = c["engine_slots"]
    return {eng: e[eng] / CAPS[eng] for eng in e}


# ---------------------------------------------------------------------------
# Layer 2: algebraic serving model under infinite scratch.
# ---------------------------------------------------------------------------
# Fixed algorithm core (from census, serving-mix-independent):
#   hash with prexor'd nv everywhere: 46,656 - 8 * (unprimed gathered
#   group-rounds as-built = 39 L4 + 160 L6-L10 = 199) = 45,064 lane-ops.
#   idx minus gather-address combines (231 x 8): 7,448 - 1,848 = 5,600.
HASH_MADD_LANES = VLEN * 2048          # 16,384
HASH_PLAIN_LANES = 45064 - HASH_MADD_LANES  # 28,680 (prexor'd form)
IDX_MADD_LANES = VLEN * 371            # 2,968
IDX_PLAIN_LANES = 5600 - IDX_MADD_LANES     # 2,632
SETUP_SCALAR = 16
SETUP_FLOW = 14
BASE_SETUP_LOADS = 46   # input vloads + pointers; excludes remodeled tables
BASE_STORES = 38
SPAN = 439

STRATEGIES = ("gather", "gather_primed", "flow_tournament", "valu_tournament",
              "masked_alu", "hybrid")


def level_cost_table() -> list[dict]:
    """Per-group-round cost of each serving strategy at each level d.

    Costs per GROUP-ROUND (8 walkers, one round). Conditions are free under
    infinite scratch: the d path bits at level d are exactly the last d
    parity vectors, which the idx chain already materializes as 0/1 vectors.
    Amortized table setup (once, tree is static): 2^d broadcasts +
    2^(d-1) diff vectors + ceil(2^d/8) vloads (+ prexor vxors folded in).
    """
    rows = []
    for d in range(11):
        n_sel = 2**d - 1
        first = 2 ** (d - 1) if d >= 1 else 0
        inner = n_sel - first
        table_vloads = -(-(2**d) // VLEN)
        rows.append({
            "level": d,
            "grp_rounds": GD[d],
            "gather": {"load": 8, "valu_slots": 1, "note": "8 gathers + addr combine; +1 vxor hash penalty if unprimed"},
            "gather_primed": {"load": 8, "valu_slots": 1,
                              "prime_cost_once": {"load": table_vloads, "store": table_vloads, "valu": table_vloads}},
            "flow_tournament": {"flow": n_sel},
            "valu_tournament": {"valu_slots": first * 1 + inner * 2},
            "masked_alu_lanes": VLEN * (2 * first + 3 * inner),  # dominated
            "sel_first": first, "sel_inner": inner,
            "table_once": {"valu_slots": 2**d + first, "load": table_vloads},
        })
    return rows


@dataclass
class ServingSolution:
    C: float
    serve: dict[int, float]
    prime: dict[int, float]
    sel_flow: float
    sel_valu_first: float
    sel_valu_inner: float
    engine_use: dict[str, float] = field(default_factory=dict)


def solve_serving(
    hash_plain: float = HASH_PLAIN_LANES,
    hash_madd: float = HASH_MADD_LANES,
    idx_plain: float = IDX_PLAIN_LANES,
    idx_madd: float = IDX_MADD_LANES,
    extra_plain: float = 0.0,
    pin_serve: dict[int, float] | None = None,
    pin_prime: set[int] | None = None,
    flow_cap_mult: float = 1.0,
    load_delta: float = 0.0,
) -> ServingSolution:
    """LP over serving mix + engine assignment; minimize C.

    Variables: C; s_d (served group-rounds, level 1..10; L0 always served,
    zero marginal cost); p_d (primed fraction of level's gathered rounds);
    u_d (unprimed gathered group-rounds, linearization); t_d (table built
    fraction); f1,f2 (selects on flow); v1,v2 (selects on valu);
    xp,xm (plain/madd lane-ops assigned to alu).
    """
    if not HAVE_SCIPY:
        raise RuntimeError("scipy required for the serving LP")
    lv = level_cost_table()
    D = list(range(1, 11))
    # variable layout
    idx_of = {}
    n = 0
    for name in ("C",):
        idx_of[name] = n; n += 1
    for d in D:
        idx_of[f"s{d}"] = n; n += 1
    for d in D:
        idx_of[f"p{d}"] = n; n += 1
    for d in D:
        idx_of[f"u{d}"] = n; n += 1
    for d in D:
        idx_of[f"t{d}"] = n; n += 1
    for name in ("f1", "f2", "v1", "v2", "xp", "xm"):
        idx_of[name] = n; n += 1

    A_ub, b_ub, A_eq, b_eq = [], [], [], []

    def row() -> list[float]:
        return [0.0] * n

    # --- select totals: f1+v1 = sum s_d*first_d ; f2+v2 = sum s_d*inner_d
    r = row(); r[idx_of["f1"]] = 1; r[idx_of["v1"]] = 1
    for d in D:
        r[idx_of[f"s{d}"]] -= lv[d]["sel_first"]
    A_eq.append(r); b_eq.append(0.0)
    r = row(); r[idx_of["f2"]] = 1; r[idx_of["v2"]] = 1
    for d in D:
        r[idx_of[f"s{d}"]] -= lv[d]["sel_inner"]
    A_eq.append(r); b_eq.append(0.0)

    # --- linearization: u_d >= (G_d - s_d) - G_d * p_d
    for d in D:
        r = row()
        r[idx_of[f"u{d}"]] = -1; r[idx_of[f"s{d}"]] = -1
        r[idx_of[f"p{d}"]] = -GD[d]
        A_ub.append(r); b_ub.append(-GD[d])
    # --- table fraction: t_d >= s_d / G_d
    for d in D:
        r = row()
        r[idx_of[f"t{d}"]] = -1; r[idx_of[f"s{d}"]] = 1.0 / GD[d]
        A_ub.append(r); b_ub.append(0.0)

    # --- flow: f1 + f2 + setup_flow <= C * flow_cap_mult
    # (setup add_imms have 1:1 alu spellings; drop them when flow disabled)
    setup_flow = SETUP_FLOW if flow_cap_mult >= 0.5 else 0.0
    r = row(); r[idx_of["f1"]] = 1; r[idx_of["f2"]] = 1
    r[idx_of["C"]] = -CAPS["flow"] * flow_cap_mult
    A_ub.append(r); b_ub.append(-setup_flow)

    # --- load: BASE + 8*sum(G_d - s_d) + prime vloads + table vloads <= 2C
    r = row(); r[idx_of["C"]] = -CAPS["load"]
    const = BASE_SETUP_LOADS + load_delta + 1  # +1: L0 table row vload
    for d in D:
        const += 8 * GD[d]
        r[idx_of[f"s{d}"]] = -8
        tv = lv[d]["table_once"]["load"]
        r[idx_of[f"p{d}"]] += tv          # priming reads the level row
        r[idx_of[f"t{d}"]] += tv          # table build reads the level row
    A_ub.append(r); b_ub.append(-const)

    # --- store: BASE + prime stores <= 2C
    r = row(); r[idx_of["C"]] = -CAPS["store"]
    for d in D:
        r[idx_of[f"p{d}"]] = lv[d]["table_once"]["load"]
    A_ub.append(r); b_ub.append(-BASE_STORES)

    # --- alu: SETUP_SCALAR + xp + 2*xm <= 12C
    r = row(); r[idx_of["xp"]] = 1; r[idx_of["xm"]] = 2
    r[idx_of["C"]] = -CAPS["alu"]
    A_ub.append(r); b_ub.append(-SETUP_SCALAR)

    # --- xp <= P_total, xm <= M_total (P_total varies with mix)
    # P_total = hash_plain + idx_plain + extra + 8*combines + 8*u_d (extra
    #           xor) + prime vxors*8 + table lanes (broadcast 8/slot + diffs)
    # combines = sum (G_d - s_d)
    P_const = hash_plain + idx_plain + extra_plain
    r = row(); r[idx_of["xp"]] = 1
    for d in D:
        P_const += 8 * GD[d]                      # combines for all gathered
        r[idx_of[f"s{d}"]] += 8                   # served rounds drop combine
        r[idx_of[f"u{d}"]] -= 8                   # unprimed extra hash xor
        r[idx_of[f"p{d}"]] -= 8 * lv[d]["table_once"]["load"]  # prime vxors
        r[idx_of[f"t{d}"]] -= 8 * lv[d]["table_once"]["valu_slots"]
    A_ub.append(r); b_ub.append(P_const)
    r = row(); r[idx_of["xm"]] = 1
    A_ub.append(r); b_ub.append(hash_madd + idx_madd)

    # --- valu: (P_total - xp)/8 + (M_total - xm)/8 + v1 + 2*v2 <= 6C
    r = row()
    r[idx_of["xp"]] = -1.0 / VLEN
    r[idx_of["xm"]] = -1.0 / VLEN
    r[idx_of["v1"]] = 1; r[idx_of["v2"]] = 2
    r[idx_of["C"]] = -CAPS["valu"]
    M_total = hash_madd + idx_madd
    rhs = -(P_const + M_total) / VLEN
    for d in D:
        r[idx_of[f"s{d}"]] += -8.0 / VLEN
        r[idx_of[f"u{d}"]] += 8.0 / VLEN
        r[idx_of[f"p{d}"]] += 8.0 * lv[d]["table_once"]["load"] / VLEN
        r[idx_of[f"t{d}"]] += 8.0 * lv[d]["table_once"]["valu_slots"] / VLEN
    A_ub.append(r); b_ub.append(rhs)

    bounds: list[tuple[float, float | None]] = [(SPAN, None)]
    for d in D:
        pin = None if pin_serve is None else pin_serve.get(d, 0.0)
        bounds.append((pin if pin is not None else 0.0,
                       pin if pin is not None else GD[d]))
    for d in D:
        if pin_prime is not None:
            v = 1.0 if d in pin_prime else 0.0
            bounds.append((v, v))
        else:
            bounds.append((0.0, 1.0))
    for d in D:
        bounds.append((0.0, None))   # u_d
    for d in D:
        bounds.append((0.0, 1.0))    # t_d
    for _ in ("f1", "f2", "v1", "v2", "xp", "xm"):
        bounds.append((0.0, None))

    cvec = row(); cvec[idx_of["C"]] = 1.0
    res = linprog(cvec, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                  bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")
    x = res.x
    sol = ServingSolution(
        C=float(x[idx_of["C"]]),
        serve={d: float(x[idx_of[f"s{d}"]]) for d in D},
        prime={d: float(x[idx_of[f"p{d}"]]) for d in D},
        sel_flow=x[idx_of["f1"]] + x[idx_of["f2"]],
        sel_valu_first=x[idx_of["v1"]],
        sel_valu_inner=x[idx_of["v2"]],
    )
    # engine use at optimum
    C = sol.C
    gathered = sum(GD[d] - sol.serve[d] for d in D)
    loads = BASE_SETUP_LOADS + load_delta + 1 + 8 * gathered
    for d in D:
        loads += lv[d]["table_once"]["load"] * (x[idx_of[f"p{d}"]] + x[idx_of[f"t{d}"]])
    P_tot = P_const
    for d in D:
        P_tot += (-8 * sol.serve[d] + 8 * x[idx_of[f"u{d}"]]
                  + 8 * lv[d]["table_once"]["load"] * x[idx_of[f"p{d}"]]
                  + 8 * lv[d]["table_once"]["valu_slots"] * x[idx_of[f"t{d}"]])
    xp, xm = x[idx_of["xp"]], x[idx_of["xm"]]
    sol.engine_use = {
        "alu_slots": SETUP_SCALAR + xp + 2 * xm,
        "valu_slots": (P_tot - xp) / VLEN + (M_total - xm) / VLEN
                      + x[idx_of["v1"]] + 2 * x[idx_of["v2"]],
        "flow_slots": setup_flow + sol.sel_flow,
        "load_slots": loads,
        "alu_floor": (SETUP_SCALAR + xp + 2 * xm) / CAPS["alu"],
        "valu_floor": ((P_tot - xp) / VLEN + (M_total - xm) / VLEN
                       + x[idx_of["v1"]] + 2 * x[idx_of["v2"]]) / CAPS["valu"],
        "flow_floor": (setup_flow + sol.sel_flow) / max(flow_cap_mult, 1e-9),
        "load_floor": loads / CAPS["load"],
        "compute_lanes_total": P_tot + M_total,
    }
    return sol


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def fmt_sol(sol: ServingSolution, label: str) -> str:
    served = {d: round(v, 1) for d, v in sol.serve.items() if v > 0.05}
    primed = {d: round(v, 2) for d, v in sol.prime.items() if v > 0.01}
    e = sol.engine_use
    return (f"{label}: C = {sol.C:.1f}\n"
            f"  serve (grp-rounds/level, L0 always): {served}\n"
            f"  prime fraction: {primed}\n"
            f"  selects: flow {sol.sel_flow:.0f}, valu first {sol.sel_valu_first:.0f}, valu inner {sol.sel_valu_inner:.0f}\n"
            f"  floors: valu {e['valu_floor']:.1f}  alu {e['alu_floor']:.1f}  "
            f"load {e['load_floor']:.1f}  flow {e['flow_floor']:.1f}\n"
            f"  slots: valu {e['valu_slots']:.0f} alu {e['alu_slots']:.0f} "
            f"load {e['load_slots']:.0f} flow {e['flow_slots']:.0f}  "
            f"compute lane-ops {e['compute_lanes_total']:.0f}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=float, default=940.0)
    args = ap.parse_args()
    c = CENSUS_1038

    print("=" * 78)
    print("[1] AS-BUILT census floors (validation)")
    print("=" * 78)
    rf = rigid_floors(c)
    print("rigid per-engine floors (no fungibility):",
          {k: round(v, 1) for k, v in rf.items()})
    fung = asbuilt_compute_sets(c)["fungible"]
    C, detail = fung.floor()
    print(f"fungible ideal floor of the as-built multiset: {C:.1f}"
          f"  (target ~1014-1021; span {detail['span']},"
          f" load {detail['load_floor']:.0f})")
    print(f"  total compute lane-ops {detail['compute_lanes']:.0f}"
          f" (+ {c['rout_flow_vselect']} flow selects kept on flow)")

    print()
    print("=" * 78)
    print("[2] Per-level serving cost table (per group-round; infinite scratch)")
    print("=" * 78)
    print(f"{'d':>2} {'grp':>4} {'gather':>22} {'flow-tourn':>11} "
          f"{'valu-tourn':>11} {'masked-alu':>11} {'table-once':>18}")
    for r in level_cost_table():
        d = r["level"]
        print(f"{d:>2} {r['grp_rounds']:>4} "
              f"{'8 ld + 1 valu (+1 vxor unpr.)':>22} "
              f"{r['flow_tournament']['flow']:>8} fl "
              f"{r['valu_tournament']['valu_slots']:>8} vs "
              f"{r['masked_alu_lanes']:>7} ln "
              f"{r['table_once']['valu_slots']:>7} vs+{r['table_once']['load']:>2} ld")

    if not HAVE_SCIPY:
        print("\nscipy unavailable: serving LP skipped")
        return

    print()
    print("=" * 78)
    print("[3] Serving-mix LP solutions")
    print("=" * 78)
    pin = {d: float(ASBUILT_SERVE[d]) for d in range(1, 11)}
    sol_pin = solve_serving(pin_serve=pin, pin_prime=ASBUILT_PRIME)
    print(fmt_sol(sol_pin, "as-built mix, ideal allocation (layer-2 model)"))
    print()
    sol_free = solve_serving()
    print(fmt_sol(sol_free, "FREE serving mix (ideal floor, current hash+idx)"))
    print()
    sol_noflow = solve_serving(flow_cap_mult=1e-9)
    print(fmt_sol(sol_noflow, "free mix, flow engine DISABLED (control)"))

    print()
    print("=" * 78)
    print("[4] Sensitivity: d(ideal floor)/d(removal), at the free-mix optimum")
    print("=" * 78)
    base = sol_free.C
    probes = [
        ("hash plain  -1000 lanes", dict(hash_plain=HASH_PLAIN_LANES - 1000)),
        ("hash madd   -1000 lanes", dict(hash_madd=HASH_MADD_LANES - 1000)),
        ("hash plain  -4096 lanes (-1 op/hash)",
         dict(hash_plain=HASH_PLAIN_LANES - 4096)),
        ("idx         -1000 lanes", dict(idx_plain=IDX_PLAIN_LANES - 1000)),
        ("idx         -2632 lanes (all plain idx)", dict(idx_plain=0.0)),
        ("+1000 plain lanes (overhead re-added)", dict(extra_plain=1000.0)),
        ("+2280 lanes (cond-materialization pessimism)",
         dict(extra_plain=2280.0)),
        ("idx maintenance FREE (bound on idx prize)",
         dict(idx_plain=0.0, idx_madd=0.0)),
        ("hash -8192 lanes (-2 ops/hash)",
         dict(hash_plain=HASH_PLAIN_LANES - 8192)),
        ("loads       -100 (setup/side channel)", dict(load_delta=-100.0)),
        ("loads       +200", dict(load_delta=200.0)),
        ("flow x2 (hypothetical 2 slots/cyc)", dict(flow_cap_mult=2.0)),
        ("flow x0 (disabled)", dict(flow_cap_mult=1e-9)),
    ]
    for label, kw in probes:
        s = solve_serving(**kw)  # type: ignore[arg-type]
        print(f"  {label:<42} C = {s.C:8.1f}   dC = {s.C - base:+7.1f}")

    print()
    print("=" * 78)
    print(f"[5] Reconciliation vs target {args.target:.0f}")
    print("=" * 78)
    def min_removal(tgt: float, **fixed) -> float | None:
        """Min fungible lane-op removal (hash bucket) for C<=tgt.

        None = unreachable by compute removal (a non-compute floor binds).
        """
        if solve_serving(**fixed).C <= tgt:
            return 0.0
        if solve_serving(hash_plain=HASH_PLAIN_LANES - 40000.0, **fixed).C > tgt:
            return None
        lo_r, hi_r = 0.0, 40000.0
        for _ in range(40):
            mid = (lo_r + hi_r) / 2
            s = solve_serving(hash_plain=HASH_PLAIN_LANES - mid, **fixed)
            if s.C <= tgt:
                hi_r = mid
            else:
                lo_r = mid
        return hi_r

    def fmt_removal(r: float | None) -> str:
        if r is None:
            return "UNREACHABLE (non-compute floor binds)"
        return f"{r:7.0f} lane-ops ({r/4096:.2f} ops/hash)"

    pin_kw = dict(pin_serve=pin, pin_prime=ASBUILT_PRIME)
    for tgt in sorted({args.target, 940.0, 892.0}, reverse=True):
        r_free = min_removal(tgt)
        r_pin = min_removal(tgt, **pin_kw)
        print(f"target {tgt:6.0f}: removal needed (free mix) "
              f"{fmt_removal(r_free)} | (as-built mix pinned) "
              f"{fmt_removal(r_pin)}")
    print()
    print(f"free-mix ideal floor {base:.1f} vs 940 frontier -> "
          f"{'FLOOR IS BELOW the frontier: no op-mix delta needed; the gap is allocation+overhead' if base <= 940 else f'needs {(base-940)*60:.0f} lane-ops removed'}")
    # decomposition of the 1038 -> ideal gap
    C_asbuilt, _ = fung.floor()
    sol_pin2 = solve_serving(**pin_kw)
    print("gap decomposition (cycles):")
    print(f"  1038 actual -> {C_asbuilt:.0f} as-built-census fungible floor  "
          f"(scheduling friction + engine rigidity): {1038 - C_asbuilt:.0f}")
    print(f"  {C_asbuilt:.0f} -> {sol_pin2.C:.0f} same serving mix, ideal overhead "
          f"(free conds, diff tables, flow-saturated selects, prexor'd tables):"
          f" {C_asbuilt - sol_pin2.C:.0f}")
    print(f"  {sol_pin2.C:.0f} -> {base:.0f} optimal serving mix "
          f"(serve more L4, prime L4-L6): {sol_pin2.C - base:.0f}")


if __name__ == "__main__":
    main()
