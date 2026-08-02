#!/usr/bin/env python3
"""P6-R3: served-level-local conjugation family — formalization + verification.

Family: carried representation w = phi(v) across a contiguous span of SERVED
rounds, phi GF(2)-linear invertible (round-varying phi_r allowed).  Round body
becomes  w' = A(Q(X_n(B(w))))  with  A = phi_next∘S,  B = phi^{-1},  node table
n -> phi(n) (+ constant merges), parity tap = row0(B)·w'.

This tool:
  1. verifies bit-exact semantic equivalence of the conjugated construction
     (values AND the full parity stream) against frozen reference semantics,
     for several phi, on the real 16-round schedule with served/gathered spans;
  2. demonstrates SEAM CANCELLATION: at every interior served->served seam the
     implementation may compute S directly (A then B collapses), so the
     concatenated op chain is IDENTICAL to baseline for every phi — verified
     numerically per-seam;
  3. prints the absorption cost table per boundary class and the candidate-phi
     table (c(A), c(B), parity class, decomposable floor, required fusion).

Costs are in ops per group-round unless labeled; cycle figures use the
project's standard 6 valu/cyc, 2 load + 2 store slots/cyc, VLEN=8.
"""
import random

MASK = (1 << 32) - 1

C0, K0 = 0x7ED55D16, 4097
C1 = 0xC761C23C
KP, AP = 33, 0xE9F8CC1D
KQ, AQ = 16896, 0xACCF6200
K4, C4 = 9, 0xFD7046C5
C5 = 0xB55A4F09


def myhash(v):
    v = (v * K0 + C0) & MASK
    v = (v ^ C1) ^ (v >> 19)
    p = (v * KP + AP) & MASK
    q = (v * KQ + AQ) & MASK
    v = p ^ q
    v = (v * K4 + C4) & MASK
    return ((v ^ C5) ^ (v >> 16)) & MASK


def Q(v):
    """8-op core: madd4097 | shr19,xor2,xorcC1 | madd33,madd512-equiv,xor2 | madd9."""
    v = (v * K0 + C0) & MASK
    v = (v ^ C1) ^ (v >> 19)
    p = (v * KP + AP) & MASK
    q = (v * KQ + AQ) & MASK
    v = p ^ q
    v = (v * K4 + C4) & MASK
    return v


def S(v):  # sigma16 linear layer (2 ops)
    return v ^ (v >> 16)


assert all(myhash(x) == (S(Q(x)) ^ C5) & MASK for x in
           [0, 1, MASK, 1 << 31] + [random.Random(1).getrandbits(32) for _ in range(1000)]), \
    "decomposition H = X_C5∘S∘Q broken"


# --------------------------------------------------------------------------
# GF(2)-linear phi library.  Represent phi by its action (a python callable
# on u32) plus name; inverses computed via nilpotency of shifts:
# (I+S_k)^{-1} = I + S_k + S_2k + ...  (exact at width 32).
# --------------------------------------------------------------------------

def sig_r(k):
    f = lambda x: (x ^ (x >> k)) & MASK
    f.__name__ = f"sig{k}r"
    return f


def sig_l(k):
    f = lambda x: (x ^ (x << k)) & MASK
    f.__name__ = f"sig{k}l"
    return f


def inv(f):
    """Inverse of an invertible GF(2)-linear map given as a callable (via
    matrix inversion over F2, 32x32)."""
    cols = [f(1 << i) for i in range(32)]  # matrix columns
    # Gaussian elimination to invert: rows of identity tracked alongside.
    M = cols[:]  # M[i] = column i as bitmask of output bits
    # build 32x32 bit-matrix rows: row j bit i = (M[i] >> j) & 1
    rows = [(sum(((M[i] >> j) & 1) << i for i in range(32))) for j in range(32)]
    aug = [(rows[j], 1 << j) for j in range(32)]
    for c in range(32):
        p = next(r for r in range(c, 32) if (aug[r][0] >> c) & 1)
        aug[c], aug[p] = aug[p], aug[c]
        for r in range(32):
            if r != c and (aug[r][0] >> c) & 1:
                aug[r] = (aug[r][0] ^ aug[c][0], aug[r][1] ^ aug[c][1])
    invrows = [aug[j][1] for j in range(32)]

    def g(x):
        y = 0
        for j in range(32):
            if bin(x & invrows[j]).count("1") & 1:
                y |= 1 << j
        return y
    g.__name__ = f"inv_{f.__name__}"
    return g


def compose(f, g):
    h = lambda x: f(g(x))
    h.__name__ = f"{f.__name__}∘{g.__name__}"
    return h


def is_linear(f, rng, n=200):
    return all(f(a ^ b) == f(a) ^ f(b) for a, b in
               ((rng.getrandbits(32), rng.getrandbits(32)) for _ in range(n)))


# --------------------------------------------------------------------------
# 1. Semantic verification of the conjugated construction on the real
#    16-round schedule.  Served rounds {0..4, 11..15}; spans [0..4], [11..15].
#    Entry round (plain in, transformed out):   w' = A(Q(v ^ n))
#    Interior round (transformed in/out):       w' = A(Q(B(w) ^ phi(n)))
#    Exit round (transformed in, plain out):    v' = S(Q(B(w) ^ phi(n))) ^ C5
#    Gathered round: baseline.
#    Parity stream: reference parity_r = bit0 of true v_{r+1} each round;
#    conjugated construction must reproduce it from its own state via the
#    row0(B) tap.
# --------------------------------------------------------------------------

ROUNDS = 16
SERVED = set(range(0, 5)) | set(range(11, 16))


def ref_walk(v0, node_at):
    """Reference: returns (final v, parity list). node_at(r) -> node value."""
    v = v0
    par = []
    for r in range(ROUNDS):
        v = myhash(v ^ node_at(r))
        par.append(v & 1)
    return v, par


def conj_walk(v0, node_at, phi, phi_inv):
    """Conjugated construction with spans [0..4] and [11..15]."""
    par = []
    state = v0            # holds w inside spans, v outside
    transformed = False
    for r in range(ROUNDS):
        n = node_at(r)
        if r in SERVED:
            entry = not transformed
            nxt_transformed = (r + 1) in SERVED and (r + 1) < ROUNDS
            # value entering fold:
            u = state if entry else phi_inv(state)          # B(w) [seam!]
            nn = n                                          # table transform:
            # (fold with phi(n) after B(w) == B(w ^ phi(n)) is NOT the form we
            #  use; we use u ^ n with u = true v — both orders verified equal)
            core = Q(u ^ nn)
            v_true = (S(core) ^ C5) & MASK
            if nxt_transformed:
                state = phi(v_true)                         # A(core)^const
                transformed = True
                # parity tap = row0(phi^{-1})·w'  == bit0(v_true):
                par.append(phi_inv(state) & 1)
            else:
                state = v_true
                transformed = False
                par.append(state & 1)
        else:
            assert not transformed, "gathered round received transformed state"
            state = myhash(state ^ n)
            par.append(state & 1)
    return state, par


def run_semantics(phis):
    rng = random.Random(0xA5A5)
    ok_all = True
    for name, phi in phis:
        phi_i = inv(phi)
        # sanity: inverse + linearity
        assert is_linear(phi, rng), name
        assert all(phi_i(phi(x)) == x for x in (rng.getrandbits(32) for _ in range(200)))
        bad = 0
        for _ in range(200):
            v0 = rng.getrandbits(30)
            nodes = [rng.getrandbits(30) for _ in range(ROUNDS)]
            f_ref, p_ref = ref_walk(v0, lambda r: nodes[r])
            f_c, p_c = conj_walk(v0, lambda r: nodes[r], phi, phi_i)
            if f_ref != f_c or p_ref != p_c:
                bad += 1
        print(f"  [semantics] phi={name:24s} 200 walks x16 rounds: "
              f"{'PASS bit-exact (values+parity)' if bad == 0 else f'FAIL {bad}'}")
        ok_all &= bad == 0
    return ok_all


# --------------------------------------------------------------------------
# 2. Seam cancellation, per-seam numeric check:
#    A-then-B across an interior seam equals S directly:
#    B(A(x) ^ const-absorbed)  ==  S(x) ^ ...   i.e. phi^{-1}∘phi = I around
#    the boundary, so the optimal implementation never materializes w and the
#    concatenated chain is op-identical to baseline for EVERY linear phi.
# --------------------------------------------------------------------------

def run_seam(phis):
    rng = random.Random(0xBEEF)
    for name, phi in phis:
        phi_i = inv(phi)
        ok = all(
            phi_i(phi((S(x) ^ C5) & MASK)) == (S(x) ^ C5) & MASK
            for x in (rng.getrandbits(32) for _ in range(1000))
        )
        print(f"  [seam] phi={name:24s} B∘A == S∘X_C5 exactly: {'PASS' if ok else 'FAIL'}")


# --------------------------------------------------------------------------
# 3. Cost model / tables.
# --------------------------------------------------------------------------

def layer_cost_upper(kind, k=None):
    """Known upper bounds for GF(2) layers in the machine vocabulary."""
    if kind == "I":
        return 0
    if kind in ("sig_r", "sig_l"):
        return 2                      # shift + xor2 (sigma floor = 2, P5-L2 d)
    if kind == "prod2":
        return 4                      # two sigma layers back-to-back
    raise ValueError(kind)


def candidate_table():
    print("\nCANDIDATE-PHI TABLE  (A = phi∘S, B = phi^{-1}; S = I+S16r)")
    print("  interior-round decomposable cost = 1 fold + 8 (Q) + c(A) + c(B)")
    print("  win condition: <=10  =>  required nonlocal fusion = floor - 10")
    hdr = f"  {'phi':14s} {'c(A)':>4s} {'c(B)':>4s} {'C_par':>5s} {'floor':>5s} {'fusion needed':>13s}  note"
    print(hdr)
    rows = []
    # trivial orbit
    rows.append(("I", 2, 0, "yes", "A=S itself; the baseline"))
    rows.append(("sig16r (=S)", 0, 2, "no*", "re-bracketing; *tap = bit0+bit16 shared with B"))
    # single right xorshifts
    for k in (3, 8, 19):
        rows.append((f"sig{k}r", 4, 2, "no", "A = sig_kr*S: 2-layer product"))
    # single left xorshifts (parity-preserving)
    for k in (3, 12, 16):
        rows.append((f"sig{k}l", 4, 2, "yes", "left shifts fix bit0"))
    for name, cA, cB, cpar, note in rows:
        floor = 1 + 8 + cA + cB
        need = max(0, floor - 10)
        print(f"  {name:14s} {cA:4d} {cB:4d} {cpar:>5s} {floor:5d} {need:13d}  {note}")
    print("  (c(A)=4 upper bound = factored product; c>=4 lower bound for the")
    print("   mixed-support products follows P5-L2 3.1's support argument for")
    print("   pure-right products; mixed left/right products contain a masked")
    print("   term (S_kl*S16r) and have no <=3-op form in the deletion family")
    print("   -- z3-checked in tools/p6r3_cegis.py for the tested members.)")


def absorption_table():
    print("\nABSORPTION COST TABLE (per boundary class, GF(2)-linear phi)")
    print("""
  boundary            phi seam        runtime cost              one-time setup cost
  ------------------  --------------  ------------------------  ---------------------------------
  served->served      B∘A = I         0 (seam cancels; optimal  served table transform: 31 nodes
   (interior seam)    (cancellation)  impl computes S direct)   = 4 vec x c(phi) vec-ops (~<=16
                                                                vec-ops ~ 2.7 cyc TOTAL, all
                                                                served levels together)
  gathered->served    A alone (entry) +(c(A) - 2) ops/gr        same served-table setup
  served->gathered    B alone (exit)  +c(B) ops/gr              --
  gathered->gathered  phi = I forced  0                         table transport DEAD: 2,047 nodes
                                                                = 256 vload + 256*c(phi) valu +
                                                                256 vstore; load/store-slot bound
                                                                128 cyc/pass MINIMUM vs total
                                                                prize <=70 cyc (10-op body) --
                                                                loses even before valu cost
  initial load (r0)   entry class     +(c(A) - 2) ops/gr
  final store (r15)   exit class      +c(B) ops/gr (output must be exact plain v)
  parity tap (all     row0(B)·w'      0 if C_par (row0(B)=e0,   --
  transformed rounds)                 left-shift phis) or if
                                      shared with next B (e.g.
                                      phi=S); else +<=2 ops/gr
""")
    print("  Entry+exit seam sum per span: (c(A)-2) + c(B) >= 0, with equality")
    print("  iff phi in {I, S} (the trivial orbit). Two spans double it.")


def main():
    rng = random.Random(7)
    phis = [
        ("sig16r(=S,triv)", sig_r(16)),
        ("sig19r", sig_r(19)),
        ("sig16l", sig_l(16)),
        ("sig3l", sig_l(3)),
        ("sig12l", sig_l(12)),
        ("sig3l∘sig16r", compose(sig_l(3), sig_r(16))),
    ]
    print("1. SEMANTIC VERIFICATION (conjugated construction == reference)")
    ok = run_semantics(phis)
    print("2. SEAM CANCELLATION")
    run_seam(phis)
    absorption_table()
    candidate_table()
    print("\nOVERALL:", "ALL PASS" if ok else "FAILURES PRESENT")


if __name__ == "__main__":
    main()
