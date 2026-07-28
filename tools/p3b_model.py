"""P3-B: the index/parity recurrence cost model and its floor.

Encodes the per-group-round cost of index maintenance for the shipped 1006
kernel and for every candidate REPRESENTATION searched, and prints the
census delta of each against the measured baseline
(alu+valu 59,489 lane-ops | load 1,892 slots | flow 797 slots).

Measured inputs come from tools/p3b_attrib.py (per-(L -> nextL) tail
attribution) and tools/h058_census.py.  The one-op impossibility used by
the floor comes from tools/p3b_onestep.py.

Usage: python3 tools/p3b_model.py
"""

from __future__ import annotations

VLEN = 8
PERIOD = 11
ROUNDS = 16
NG = 32                     # groups of 8 walkers
CAP940 = (56_400, 1_880, 940)          # alu+valu lane-ops | load | flow @940
BASE = (59_489, 1_892, 797)            # measured @1006
HASH = 46_464

# --- serving policy of the shipped kernel (tools/h058_census.py) -----------
A_L4_GATHER_E1 = 9          # groups gathering at round 4  (l4_gmin[0] = 9)
B_L4_GATHER_E2 = 30         # groups gathering at round 15 (l4_gmin[1] = 30)

# --- MEASURED tail (tools/p3b_attrib.py), vec-op-equivalents --------------
# key: (L -> nextL) -> (total vec-op-equivalents, of which flow slots, gr count)
MEASURED = {
    (0, 1):  (64.0,   0, 64),
    (1, 2):  (64.0,   0, 64),
    (2, 3):  (90.0,   0, 64),
    (3, 4):  (230.0,  0, 64),
    (4, 5):  (136.0,  6, 32),
    (5, 6):  (96.0,  32, 32),
    (6, 7):  (96.0,  32, 32),
    (7, 8):  (96.0,  32, 32),
    (8, 9):  (96.0,  32, 32),
    (9, 10): (96.0,  32, 32),
}


def floor_model() -> dict[tuple[int, int], tuple[float, int]]:
    """Per-(L -> nextL) floor in alu+valu vec-ops, and flow slots.

    Rules (derived in research/strains/p3b/STATE.md):
      * every group-round whose successor level != 0 needs exactly ONE
        parity-materialising op (PROVED: tools/p3b_onestep.py part 1 --
        only `&1`, `%2`, `*2**31`, `<<31`, `|0xFFFFFFFE` read val and
        depend on it solely through bit0);
      * a group-round whose SUCCESSOR gathers needs the packed address;
        producing it from an already-packed predecessor costs exactly ONE
        madd and cannot cost zero (PROVED: p3b_onestep.py part 2, 1,548,224
        structural forms, 0 solutions).  The -6 address bias is absorbed by
        a flow vselect between two live constants -> 0 alu/valu lane-ops;
      * producing it from k loose parity bits costs k-1 madds;
      * a group-round whose successor level is 0 (the wrap) costs ZERO.
    """
    f: dict[tuple[int, int], tuple[float, int]] = {}
    f[(0, 1)] = (64.0, 0)                     # extract only (ring bit)
    f[(1, 2)] = (64.0, 0)
    f[(2, 3)] = (64.0, 0)
    # into L4: 64 extracts + 3 packing madds for every group that GATHERS at L4
    f[(3, 4)] = (64.0 + 3 * (A_L4_GATHER_E1 + B_L4_GATHER_E2), 0)
    # into L5: 32 extracts; groups served at L4 pack 5 loose bits (4 madds),
    # groups that gathered at L4 already hold a packed address (1 madd)
    served_l4_e1 = NG - A_L4_GATHER_E1
    f[(4, 5)] = (32.0 + 4 * served_l4_e1 + 1 * A_L4_GATHER_E1, 32)
    for d in range(5, 10):                    # steady gather: extract + madd
        f[(d, d + 1)] = (2.0 * NG, NG)
    return f


def show() -> None:
    fl = floor_model()
    print("== PER-GROUP-ROUND COST TABLE: index maintenance, shipped 1006 ==")
    print(f"{'transition':<14}{'gr':>5}{'meas vec':>10}{'meas flow':>11}"
          f"{'floor vec':>11}{'floor flow':>12}{'excess vec':>12}")
    mv = mf = fv = ff = 0.0
    for k in sorted(MEASURED):
        tot, flow, gr = MEASURED[k]
        alu_valu = tot - flow                 # my tail counts flow as 1 unit
        fvv, ffv = fl[k]
        mv += alu_valu; mf += flow; fv += fvv; ff += ffv
        print(f"L{k[0]:<2}-> L{k[1]:<8}{gr:>5}{alu_valu:>10.1f}{flow:>11}"
              f"{fvv:>11.1f}{ffv:>12}{alu_valu - fvv:>12.1f}")
    print(f"{'(L10 -> L0 wrap)':<14}{NG:>5}{0.0:>10.1f}{0:>11}{0.0:>11.1f}"
          f"{0:>12}{0.0:>12.1f}")
    print(f"{'(round 15)':<14}{NG:>5}{0.0:>10.1f}{0:>11}{0.0:>11.1f}"
          f"{0:>12}{0.0:>12.1f}")
    print(f"{'TOTAL':<14}{512:>5}{mv:>10.1f}{mf:>11.0f}{fv:>11.1f}"
          f"{ff:>12.0f}{mv - fv:>12.1f}")
    print(f"  measured alu+valu lane-ops {mv * VLEN:.0f}  "
          f"floor {fv * VLEN:.0f}  excess {(mv - fv) * VLEN:.0f}")
    print(f"  charter's ASSUMED floor 512 x 2 x 8 = 8192 lane-ops "
          f"-> overstates by {8192 - fv * VLEN:.0f}")

    print("\n== FLOOR SENSITIVITY to the L4 serving policy ==")
    for b in (30, 0):
        v = 64 * 3 + 64 + 3 * (A_L4_GATHER_E1 + b) + \
            32 + 4 * (NG - A_L4_GATHER_E1) + A_L4_GATHER_E1 + 2 * NG * 5
        print(f"  epoch-2 L4 gathers b={b:>2}: floor {v:.0f} vec-ops = "
              f"{v * VLEN:.0f} lane-ops -> design floor "
              f"{(HASH + v * VLEN) / 60:.1f} cycles")

    print("\n== CENSUS DELTA of each candidate representation ==")
    print(f"{'candidate':<44}{'alu+valu':>10}{'load':>7}{'flow':>7}")
    cands = [
        ("C0 shipped 1006 (baseline)", 0, 0, 0),
        ("C1 force all idx madds onto valu (undo alu race)", -352, 0, 0),
        ("C2 carry idx+1 (M'=2M+p, constant-free)", +160 * VLEN, 0, -166),
        ("C3 carry idx+3, parity = val|0xFFFFFFFE", +160 * VLEN, 0, -166),
        ("C4 level-offset split (idx = 2^d-1+off)", 0, 0, 0),
        ("C5 carry U=2A-6 redundantly (select advance)", +160 * VLEN, 0, -160),
        ("C6 advance via mem table in extra_room", -160 * VLEN, +1280, 0),
        # C7/C8 count the INDEX side only; the tournament work that must
        # replace those 30 gathers is P3-A/P3-C's axis and is NOT modelled
        # here, so both rows are optimistic upper bounds on the saving.
        ("C7 drop epoch-2 L4 gathers (idx side only)", -90 * VLEN, -240, 0),
        ("C8 C1 + C7 + close L2..L4 slop (idx side only)", -1088, -240, 0),
    ]
    for name, dv, dl, df in cands:
        a, l, fw = BASE[0] + dv, BASE[1] + dl, BASE[2] + df
        ok = "PASS" if (a <= CAP940[0] and l <= CAP940[1] and fw <= CAP940[2]) \
             else "fail"
        print(f"{name:<44}{dv:>+10}{dl:>+7}{df:>+7}   -> "
              f"{a}/{l}/{fw} vs 56400/1880/940 [{ok}]")

    print("\n== budget chain, corrected ==")
    for label, idxfloor in (("charter assumption", 8192),
                            ("P3-B floor, today's policy", int(fv * VLEN)),
                            ("P3-B floor, b=0 policy", 5888)):
        pool_cap = CAP940[0] - HASH - idxfloor
        pool_now = BASE[0] - HASH - idxfloor
        print(f"  {label:<28} idx floor {idxfloor:>5}  "
              f"non-hash-non-idx budget @940 {pool_cap:>5}  "
              f"current {pool_now:>5}  cut {pool_now - pool_cap:>5} "
              f"({100 * (pool_now - pool_cap) / pool_now:.0f}%)")


if __name__ == "__main__":
    show()
