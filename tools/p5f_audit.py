"""P5-F: non-hash capacity audit — reproducible arithmetic.

Three results, all derived from the frozen h058 census constants:
 1. Fold-in elision settlement: census Hash bucket nets c5_prexor elisions;
    elision = 336 vec-ops EXACTLY (two independent decompositions agree).
    Exact hash law: hash(k) = 512k + 176 vec-ops (fold-in residual is
    k-invariant) => per-op removal unit is 4,096 lane-ops, not 4,224.
    Adverse correction vs P5-A model: +2.1 cyc at k=10, +4.3 cyc at k=9.
 2. Budget inversion re-derivation at C=904/889 with measured setup 616:
    k=11 over by 4.3 / 5.8 cycles with serving priced at literal ZERO.
 3. Flow-escape closure: in any load-feasible shape (g <= 214), served
    group-rounds >= 298 => min folds >= 1,334 > flow capacity C at both
    targets, so flow has NO idle slots for add_imm/mux compute in any
    feasible world — the 60 lane-ops/cycle alu+valu ceiling (+F-model flow
    credit) is airtight.

Run: python3 tools/p5f_audit.py
"""

# --- census constants (tools/h058_census.py @ 1006, Hash bucket, lane-ops) ---
HASH_ALU_SHR = 4160
HASH_ALU_XOR = 6504
HASH_MADD = 16384
HASH_VSHR = 4032
HASH_VXOR = 15384
IDX_FLOOR = 6608        # P3-B enumeration
SETUP = 616             # h058 measured (P5-A used ~600)
TAIL_WITH_IDX = 808     # P5-A minimal tail (P5-E: 192-vec form for T2 designs)
GR = 512                # group-rounds
SETUP_LOADS = 60
TAIL_LOADS = 33         # 32 vstores ride store engine; ~1 const; conservative load debit


def main() -> None:
    hash_lane = HASH_ALU_SHR + HASH_ALU_XOR + HASH_MADD + HASH_VSHR + HASH_VXOR
    hash_vec = hash_lane // 8
    assert hash_lane == 46464

    # 1. fold-in decomposition: pure 11-op form = 4 madd + 2 shift + 5 xor / gr
    madd_vec = HASH_MADD // 8
    shift_vec = (HASH_VSHR + HASH_ALU_SHR) // 8
    xor_vec = (HASH_VXOR + HASH_ALU_XOR) // 8
    assert madd_vec == 4 * GR and shift_vec == 2 * GR
    resid = xor_vec - 5 * GR                     # unelided fold-in xors
    elided = GR - resid
    assert elided == 336 == 12 * GR - hash_vec   # decompositions agree
    print(f"fold-in: residual {resid} vec-ops, elided {elided} (settles 336-vs-251: it is 336)")
    print("exact hash law: hash(k) = 512k + 176 vec-ops (removal unit 4,096 lane-ops)")
    for k in (11, 10, 9):
        exact = (512 * k + 176) * 8
        model = 4224 * k
        print(f"  k={k}: exact {exact}  P5-A model {model}  adverse {(exact - model) / 60:+.1f} cyc")

    # 2. inversion re-derivation (serving at literal zero)
    for C, tail, tail_ld, name in ((904, TAIL_WITH_IDX, TAIL_LOADS, "with-idx"),
                                   (889, 0, 0, "no-idx")):
        cap = 60 * C
        demand = hash_lane + IDX_FLOOR + SETUP + tail
        print(f"{name} C={C}: demand(k=11, FREE serving) {demand} vs cap {cap} "
              f"=> over {(demand - cap) / 60:+.1f} cyc")

        # 3. flow-escape closure
        g_max = (2 * C - SETUP_LOADS - tail_ld) // 8
        served = GR - g_max
        folds, rem = 0, served
        for per in (0, 1, 3, 7):          # L0..L3, 64 group-rounds each
            take = min(rem, 64)
            folds += take * per
            rem -= take
        folds += rem * 15                 # remainder at L4
        assert folds > C
        print(f"  flow escape closed: g<={g_max} => served>={served} => "
              f"min folds {folds} > flow cap {C}")


if __name__ == "__main__":
    main()
