#!/usr/bin/env python3
"""P5-A: exhaustive budget inversion for the 904 (with-idx) / 889 (no-idx)
leaderboard frontier.

Question: which of our PROVED frames must break, and in what combination,
for a C-cycle kernel to exist? For each (k, g) cell — k = hash ops/round,
g = gathered group-rounds — solve whether the remaining system fits ALL
engine budgets simultaneously, under parameterized index law, serving law,
load-contiguity fraction, and with/without the index-writeback tail.

All coefficients cited from the ledger (see research/strains/p5a/STATE.md
section 0 for the citations):
  hash(k)   = 4224*k lane-ops               (528 vec-ops per hash-op unit)
  index     : 'p3b'   = 6608 fixed          (P3-B proved floor, today's policy)
              'b0'    = 5888 fixed          (b=0 policy; P3-D retraction caveat)
              'coupled(g)' = 8*(448 + 1.31*g)  (P3-D derived: 5,960 @ g=227)
  serving   : F(g) = min folds, 2^d-1 law, cheapest levels served first
              + omf selects = g (P3-B round 2), all flow-eligible
              scale=0 -> free-serving fantasy (folds AND omf cost nothing)
  setup     = 600 lane-ops + 22 flow + 60 load slots
  loads     = g*(8*(1-phi) + 1*phi) + 60        (phi = contiguity fraction)
  stores    = 46 (+32 with tail)
  tail      = +808 lane-ops, +1 load, +32 store (32x[parity,bias,madd] +
              1 vbroadcast + 32 alu addr adds; 2-op/group form proved
              impossible by P3-B Lemma 1)

Capacity at C: lane 60C, load 2C, flow C, store 2C.
Serving support arithmetic is 0 throughout (frontier-favorable; P3-E says
the realizable residual is ~97 vec-ops, which is the 944-952 vs ~939 gap).

Usage: python3 tools/p5a_budget.py
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------------------
# Machine / problem constants
VLEN = 8
LANES_PER_CYC = 60          # 12 alu + 6 valu x 8
SETUP_LANES = 600
SETUP_FLOW = 22
SETUP_LOAD = 60
BASE_STORES = 46

# tail (with-indices writeback), from STATE.md section 1
TAIL_LANES = 808            # 96 vec + 1 bcast + 32 alu
TAIL_LOAD = 1
TAIL_STORE = 32

# level inventory: (level d, group-rounds, folds per served group-round)
INVENTORY = [(d, 64 if d <= 4 else 32, 2 ** d - 1) for d in range(11)]
TOTAL_GR = sum(n for _, n, _ in INVENTORY)          # 512


def hash_lanes(k: int) -> int:
    return 4224 * k


def min_folds(g: int) -> int:
    """Min folds to serve 512-g group-rounds: serve cheapest levels first."""
    to_serve = TOTAL_GR - g
    folds = 0
    for _, n, f in INVENTORY:            # already sorted by f ascending
        take = min(n, to_serve)
        folds += take * f
        to_serve -= take
        if to_serve == 0:
            break
    return folds


def index_lanes(law: str, g: int) -> float:
    if law == "p3b":
        return 6608.0
    if law == "b0":
        return 5888.0
    if law == "coupled":
        return 8.0 * (448 + 1.31 * g)
    if law == "free":
        return 0.0
    raise ValueError(law)


def cell(C: int, k: int, g: int, *, idx_law: str = "p3b",
         serve_scale: float = 1.0, phi: float = 0.0,
         tail: bool = False) -> dict:
    """Return the engine ledger + binding engine for one design cell."""
    lane_cap = 60 * C
    flow_cap = C - SETUP_FLOW
    load_cap = 2 * C
    store_cap = 2 * C

    folds = min_folds(g) * serve_scale
    omf = g * serve_scale                       # P3-B: idx_selects = g
    flow_eligible = folds + omf
    spill_vec = max(0.0, flow_eligible - flow_cap)

    lanes = (hash_lanes(k) + index_lanes(idx_law, g) + SETUP_LANES
             + VLEN * spill_vec + (TAIL_LANES if tail else 0))
    loads = g * (8 * (1 - phi) + phi) + SETUP_LOAD + (TAIL_LOAD if tail else 0)
    stores = BASE_STORES + (TAIL_STORE if tail else 0)

    over = {
        "lane": lanes - lane_cap,
        "load": loads - load_cap,
        "store": stores - store_cap,
    }
    worst = max(over, key=lambda e: over[e] / {"lane": 60, "load": 2,
                                               "store": 2}[e])
    feas = all(v <= 1e-9 for v in over.values())
    return dict(lanes=lanes, loads=loads, stores=stores, spill=spill_vec,
                folds=folds, over=over, feasible=feas, binding=worst,
                # overrun in CYCLES on the worst engine (for tables)
                over_cyc=max(over["lane"] / 60, over["load"] / 2,
                             over["store"] / 2))


def min_phi(C: int, k: int, g: int, **kw) -> float | None:
    """Smallest contiguity fraction making the LOAD engine fit at (k,g),
    or None if even phi=1 fails."""
    tail = kw.get("tail", False)
    load_cap = 2 * C
    need = load_cap - SETUP_LOAD - (TAIL_LOAD if tail else 0)
    if g == 0:
        return 0.0
    per = need / g                      # allowed slots per gathered gr
    if per >= 8:
        return 0.0
    phi = (8 - per) / 7
    return phi if phi <= 1.0 else None


# ---------------------------------------------------------------------------
def grid(C: int, tail: bool, idx_law: str, serve_scale: float = 1.0):
    print(f"\n=== C={C}  tail={'YES' if tail else 'no'}  idx={idx_law}"
          f"  serve_scale={serve_scale}  phi=0 (our load law) ===")
    print("g:      " + "".join(f"{g:>7}" for g in GRID_G))
    for k in (11, 10, 9, 8):
        row = []
        for g in GRID_G:
            c = cell(C, k, g, idx_law=idx_law, serve_scale=serve_scale,
                     tail=tail)
            if c["feasible"]:
                row.append("     OK")
            else:
                b = c["binding"][0].upper()      # L=lane, O=load(lOad)... use letters
                b = {"lane": "V", "load": "L", "store": "S"}[c["binding"]]
                row.append(f"{b}{c['over_cyc']:+6.0f}")
        print(f"k={k}:   " + "".join(f"{x:>7}" for x in row))
    print("cells: OK = all engines fit; V/L/S+n = binding engine "
          "(Valu+alu / Load / Store) and overrun in cycles")


def best_over_g(C: int, k: int, tail: bool, idx_law: str,
                serve_scale: float = 1.0, phi: float = 0.0):
    """Scan every g in 0..512, return the min worst-engine overrun."""
    best = None
    for g in range(0, TOTAL_GR + 1):
        c = cell(C, k, g, idx_law=idx_law, serve_scale=serve_scale,
                 phi=phi, tail=tail)
        key = c["over_cyc"]
        if best is None or key < best[1]["over_cyc"]:
            best = (g, c)
    return best


GRID_G = [0, 64, 128, 192, 214, 218, 229, 256, 269, 288, 320, 384, 448, 512]


def main() -> None:
    # ---------------- headline grids -----------------------------------
    for C, tail in ((904, True), (889, False)):
        grid(C, tail, "p3b")

    # ---------------- per-question analysis ----------------------------
    print("\n\n=== Q1/Q2/Q5: minimum-k feasibility per target, by relaxation "
          "layer ===")
    print(f"{'target':<14}{'k':>3} {'idx law':<9}{'serving':<7} verdict")
    for label, C, tail in (("904 with-idx", 904, True),
                           ("889 no-idx", 889, False)):
        for idx_law in ("p3b", "b0", "coupled"):
            for scale, sname in ((1.0, "2^d-1"), (0.0, "FREE")):
                for k in (11, 10, 9, 8):
                    # (a) any g outright feasible at phi=0?
                    feas_g = [g for g in range(TOTAL_GR + 1)
                              if cell(C, k, g, idx_law=idx_law,
                                      serve_scale=scale, phi=0.0,
                                      tail=tail)["feasible"]]
                    if feas_g:
                        # slack at the best point
                        slk = max(-cell(C, k, g, idx_law=idx_law,
                                        serve_scale=scale,
                                        tail=tail)["over"]["lane"] / 60
                                  for g in feas_g)
                        v = (f"FEASIBLE in-regime, g in "
                             f"[{feas_g[0]},{feas_g[-1]}], "
                             f"lane slack up to {slk:.1f} cyc")
                    else:
                        # (b) min phi over lane-feasible g
                        lf = [(min_phi(C, k, g, tail=tail), g)
                              for g in range(TOTAL_GR + 1)
                              if cell(C, k, g, idx_law=idx_law,
                                      serve_scale=scale, phi=1.0,
                                      tail=tail)["over"]["lane"] <= 0]
                        lf = [(p, g) for p, g in lf if p is not None]
                        if lf:
                            p, g = min(lf)
                            v = f"needs phi>={p:.3f} (at g={g})"
                        else:
                            over = min(cell(C, k, g, idx_law=idx_law,
                                            serve_scale=scale, phi=1.0,
                                            tail=tail)["over"]["lane"]
                                       for g in range(TOTAL_GR + 1))
                            v = f"INFEASIBLE: lanes over by {over/60:+.1f} cyc"
                    print(f"{label:<14}{k:>3} {idx_law:<9}{sname:<7} {v}")

    # ---------------- Q1 detail: 904 at k=11 ---------------------------
    print("\n=== Q1 detail: 904 at k=11 (our hash), idx=p3b, support-free ===")
    for g in (218, 229, 256, 258, 269, 274, 280, 288):
        c = cell(904, 11, g, idx_law="p3b", tail=True)
        pn = min_phi(904, 11, g, tail=True)
        print(f"g={g:>3}: lanes={c['lanes']:>7.0f}/54240 "
              f"(over {c['over']['lane']:+7.0f} = {c['over']['lane']/60:+5.1f} cyc)"
              f"  loads={c['loads']:>6.0f}/1808 -> phi>= "
              f"{pn if pn is not None else float('nan'):.3f}"
              f"  spill={c['spill']:>5.0f} vec")
    print("\nsame, WITHOUT the tail (i.e. if their with-idx tail were free):")
    for g in (256, 258, 269, 288):
        c = cell(904, 11, g, idx_law="p3b", tail=False)
        pn = min_phi(904, 11, g, tail=False)
        print(f"g={g:>3}: lanes={c['lanes']:>7.0f}/54240 "
              f"(over {c['over']['lane']:+7.0f})  loads={c['loads']:>6.0f}"
              f" -> phi>={pn if pn is not None else float('nan'):.3f}")

    # ---------------- Q2 detail: what k=10 buys ------------------------
    print("\n=== Q2 detail: k=10 (-4,224 lane-ops) ===")
    for label, C, tail in (("904 with-idx", 904, True),
                           ("889 no-idx", 889, False)):
        # phi=0 scan: is any g feasible outright?
        feas = [g for g in range(TOTAL_GR + 1)
                if cell(C, 10, g, idx_law="p3b", tail=tail)["feasible"]]
        g0, c0 = best_over_g(C, 10, tail, "p3b")
        print(f"{label}: phi=0 feasible g-set = {feas or 'EMPTY'}; "
              f"best cell g={g0} worst-over={c0['over_cyc']:+.1f} cyc "
              f"(binding {c0['binding']})")
        # what is the cheapest single extra break?
        # (a) contiguity at the lane-feasible g
        lane_feas = [g for g in range(TOTAL_GR + 1)
                     if cell(C, 10, g, idx_law="p3b", phi=1.0,
                             tail=tail)["over"]["lane"] <= 0]
        if lane_feas:
            opts = [(min_phi(C, 10, g, tail=tail), g) for g in lane_feas]
            opts = [(p, g) for p, g in opts if p is not None]
            p, g = min(opts)
            print(f"   min contiguity miracle: phi={p:.3f} at g={g} "
                  f"(lane-feasible g-range {lane_feas[0]}..{lane_feas[-1]})")

    # ---------------- load-side sanity: what does phi mean -------------
    print("\n=== load-law note ===")
    print("phi = fraction of gathered group-rounds whose 8 lane addresses")
    print("are CONTIGUOUS (one vload) instead of 8 scalar loads. P4-B: the")
    print("depth-k descendants of one node are contiguous, but lanes are")
    print("i.i.d. walkers -- 0/256 group-rounds share an ancestor at any")
    print("level >=3 (measured). phi>0 therefore requires lane-regrouping")
    print("(dynamic lane<->walker binding), breaking the static-binding")
    print("frame, or serving from packed scratch copies (breaks the")
    print("memory-image frame for values: vstore-back is legal -- the")
    print("L4/L5 priming waves already do it, perf_takehome.py:1160-1229).")


if __name__ == "__main__":
    main()
