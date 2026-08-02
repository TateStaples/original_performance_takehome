# Strain P5-I — sandwich9 EXACT decision (bit-serial windows + differentials + fixed-shift z3)

status: IN PROGRESS (theory kills complete; z3 pair sweep running below)
tools: `tools/p5i_proto.py` (window/differential theorems + certificates),
`tools/p5i_z3pair.py` (fixed-shift per-pair z3 CEGIS with UNSAT ladder),
`tools/p5i_sweep.py` (checkpointed sweep driver),
`rust_harness/src/bin/s9_exact.rs` (row-32 recursion validation + full-domain
parity sweep; Cargo.toml untouched, auto-discovered)

## 0. Shape spec (matched to P5-D / P5-H exactly)

    b   = x*K1 + C1          (madd, mod 2^32)
    c   = b ^ M1 ^ (b >> s1) (sigma1 = shr + xorc + xor2, 3 ops)
    e   = c*K2 + C2          (madd)
    w   = e ^ M2 ^ (e >> s2) (sigma2)
    out = w*K3 + C3          (madd)      -- 9 ops total (1+3+1+3+1)

Identical to tools/p5d_sandwich9.py SANDWICH_9 (slot program) and
stoke.rs s9 (b/c/e/w naming taken from there). K1,K2,K3 odd by the
bijectivity lemma (myhash bijective; a finite-set composition is bijective
only if every factor is; even-K madd is non-injective: x vs x+2^31
collide). s1,s2 in 1..31 (s=0 makes sigma constant, non-bijective).
961 (s1,s2) pairs. The question: does ANY parameter assignment make this
equal myhash (problem.py:482-502) on all 2^32 inputs?

## 1. WINDOW THEOREM — kills all 435 pairs with s1+s2 <= 30

THEOREM. For any constants (K's odd), out_0 is a function of
x mod 2^(min(s1+s2,31)+1).
Proof: madd is bit-triangular (bits 0..m of out need bits 0..m of in);
c_i = b_i ^ M1_i ^ b_{i+s1} so c mod 2^(s2+1) reads b only up to bit
min(s1+s2,31); w_0 = e_0 ^ M2_0 ^ e_{s2} reads e mod 2^(s2+1);
out_0 = w_0 ^ C3_0 because K3 is odd (bit 0 has no carry).

COROLLARY (exact refutation certificate). If s1+s2 <= 30 and
x == x' (mod 2^(s1+s2+1)) with myhash(x)_0 != myhash(x')_0, then NO
constants exist for (s1,s2). A witness with x' = x + 2^31 refutes ALL
435 pairs with s1+s2 <= 30 simultaneously.

UNIVERSAL WITNESS (verified): x = 0x4E005510, x' = 0xCE005510
(myhash bits 0: 0 vs 1). Independent per-L witnesses for every
L = s1+s2 in 2..30 printed by tools/p5i_proto.py (all found, <=512 tries
each). Numeric guard: theorem validated on 4,918 random-constant trials
(incl. edge pairs); sharpness confirmed — survivor pairs (L>=31) DO
depend on x_31 at out_0 for generic constants, so the classification is
exact, not conservative.

## 2. ROW-31 DIFFERENTIAL THEOREM — kills all 30 pairs with s1+s2 = 31

THEOREM. For s1+s2 = 31 (s1,s2 <= 30) and any constants:
sandwich(x ^ 2^31)_0 ^ sandwich(x)_0 = 1 for ALL x.
Proof: b* = b ^ 2^31 exactly (K1 odd: K1*2^31 = 2^31 mod 2^32);
c* = c ^ 2^31 ^ 2^u exactly, u = 31-s1 = s2; e* = e + sg1*2^31 +
sg2*K2*2^u (sg in {+-1} from c's bits 31 and u); e_0 unchanged (u>=1);
at bit s2 <= 30 the 2^31 term is invisible and K2*2^u mod 2^(s2+1) =
2^s2 (K2 odd, u = s2), so e_s2 always flips; w_0 flips; out_0 flips
(K3 odd).
myhash witness (verified): x = 0x4679814A has myhash(x)_0 ==
myhash(x^2^31)_0 — the required forced flip fails => the whole row is
refuted. Numeric guard: 3,000 random-constant trials, delta out_0 == 1
always.

## 3. ROW-32 RECURSION — kills (19,13)..(30,2), (31,1), (18,14)

Setup: u = 31-s1 = s2-1 (W := s2-u+1 = 2 is what makes this row special).
Step 1 (direction 2^31): as in sec. 2, e* = e + sg1*2^31 + sg2*K2*2^u.
With W=2, bit s2 of the update collapses and the odd-K2 low bit cancels
the per-sample c_u nuisance:
   H(x) := D_{2^31} out_0 (x) = bit_u(K2*(c mod 2^u) + C2) ^ kappa.
The peeled constraint reads only b mod 2^31, on which the next
differential 2^30 acts as an EXACT flip of bit 30 (K1*2^30 == 2^30 mod
2^31), flipping c bit u-1 only; the same odd-K2 cancellation peels
again. After u+1 peels (directions 2^31, 2^30, ..., 2^s1) the RHS is
bit_0(C2) = CONSTANT.

CONSEQUENCE. For pair (s1, 32-s1): the parity of myhash_0 over the
cosets of span{2^s1, ..., 2^31} (an order-(32-s1) iterated
XOR-derivative, table P_{s1}[x mod 2^s1]) must be CONSTANT.

FULL-DOMAIN SWEEP (s9_exact sweep; one 2^32 myhash pass + XOR folds,
0.7 s): P_m NONCONSTANT for m = 19..30, CONSTANT (0) for m = 1..18.
   => (19,13), (20,12), ..., (30,2): REFUTED EXACTLY (12 pairs).
      Witness cosets printed by the sweep (e.g. m=30: P[0]=0, P[1]=1).
Numeric guard: end-to-end theorem (derivative constant on random-constant
row-32 sandwiches) validated at s1 = 30,29,24,20,16 x 4 param sets x 25
points; negative control (row-33 shapes) shows generic NONconstant
derivatives — the test has teeth.

EDGE (31,1) (u=0, but same W=2 collapse with the K2-odd cancellation at
bit 0): H(x) = D_{2^31} out_0 must be CONSTANT for any constants
(validated: 200 random-constant trials x 31 points). myhash's H is
nonconstant (x=0x4E005510 gives 1, x=0x4679814A gives 0) => REFUTED.

LEVEL-ABOVE DICHOTOMY, pair (18,14): the order-13 derivative table
(directions 2^19..2^31, = P_19[x mod 2^19]) must equal
bit_1(K2*c_0(x) + C2) ^ kappa where c_0(x) = x_0 ^ C1_0 ^ M1_0 ^
bit_18(K1x+C1). Hence it is either CONSTANT (iff bit1(K2+C2) == C2_1)
or exactly kappa ^ c_0(x), which is ANTI-symmetric under x -> x^2^18
(bit_18(K1x+C1) always flips: K1*2^18 == 2^18 mod 2^19).
Validated 12/12 random trials incl. branch selector; anti branch
exercised deliberately (8 cases, exact c_0 match).
myhash data: P_19 NONCONSTANT (kills const branch) and P_18 == 0, i.e.
P_19[r] == P_19[r ^ 2^18] for ALL r — perfect SYMMETRY (kills anti
branch). => (18,14) REFUTED EXACTLY.
(The same dichotomy at pairs s1 <= 17 is vacuous: P_{s1+1} is constant
there, so the const branch is consistent — no kill.)

## 4. Why the briefed lift-and-prune cannot touch the remaining pairs

For s1+s2 >= 32 the first output-bit constraint (bit 0) already has a
cone containing ALL 64 bits of (K1,C1) (c's window reads b bits s1..31,
b bit 31 depends on every bit of K1,C1 via carries; verified numerically:
flipping K1 bit 31 changes out_0), plus M1,K2,C2 mod 2^(s2+1) and 3 more
bits. An explicit-set lift therefore has its FIRST prune only after
~2^(66+3*s2) states — the explosion is at depth 0, not at depth 8; an
affine-class representation does not help because the constraint is
carry-nonlinear in the constant bits. This is exactly why survivors were
attacked with differentials (secs. 2-3, which sidestep the cone by
making the unknown dependence cancel) and per-pair z3 (sec. 5). Local
differential relaxations for rows >= 33 were checked and are VACUOUS
(per-sample nuisance bits absorb any 1-bit constraint), so rows >= 33
genuinely require whole-circuit reasoning.

## 5. Fixed-shift z3 (tools/p5i_z3pair.py) — the remaining 482 pairs

Encoding: 8 free 32-bit constants, K's odd, shifts CONCRETE; battery =
edges + universal-witness pair + 16 randoms + 4 structured triples
(x, x^2^31, x^2^30) = 34 samples; UNSAT ladder over masked low-k bits
k = 8, 16, 32; SAT at k=32 => constants verified outside z3 (2^20 sweep
+ 10^7 randoms) with CEGIS iteration. Soundness: UNSAT of necessary
conditions = exact refutation; encoding guarded by SELFTEST-ENCODING
(pinned-constant disagreement UNSAT) — passed. Planted-recovery
selftest note: z3 cannot even solve the SAT side (find planted constants)
at rung k=1 in 60s, so FOUND results are not expected from z3 even where
solutions exist — but UNSAT results are sound and that is what the sweep
harvests. OPEN is never counted as closed.

Measurements: (16,16) OPEN at rung k=8/120s. (30,3) REFUTED in 2.1 s at
rung k=8. Difficulty is highly pair-dependent => sweep everything cheap
first, escalate leftovers.

## 6. Classification ledger (961 pairs)

| class | pairs | verdict | certificate |
|---|---|---|---|
| s1+s2 <= 30 | 435 | REFUTED EXACTLY | universal witness 0x4E005510/0xCE005510 (+ per-L witnesses) |
| s1+s2 = 31 | 30 | REFUTED EXACTLY | forced-flip witness 0x4679814A |
| s1+s2 = 32, s1 in 19..30 | 12 | REFUTED EXACTLY | P_{s1} nonconstant (sweep witnesses) |
| (31,1) | 1 | REFUTED EXACTLY | H nonconstant (two witnesses above) |
| (18,14) | 1 | REFUTED EXACTLY | P_19 nonconstant + P_18 == 0 |
| s1+s2 = 32, s1 in 1..17 | 17 | z3 sweep below | — |
| s1+s2 >= 33 | 465 | z3 sweep below | — |

Running totals: 479 REFUTED EXACTLY by theory; 482 to the z3 sweep.

## 7. z3 sweep ledger (append CHECKPOINT lines; tools/p5i_sweep.py)

Resume protocol: `python3 tools/p5i_sweep.py --rung-timeout T --wall-budget W`
re-reads this file, skips pairs already checkpointed, appends one line per
pair. Escalation pass: rerun with bigger --rung-timeout; only OPEN pairs
are retried (a REFUTED/FOUND line is final). Order: s2 ascending, s1
ascending (small-s2 pairs measured cheap).

CHECKPOINT pair=(16,16) verdict=OPEN rung=k8 iter=0 timeout=120s reason=timeout
CHECKPOINT pair=(30,3) verdict=REFUTED rung=k8 iter=0 solve=2.1s total=2.1s
CHECKPOINT pair=(31,2) verdict=REFUTED rung=k8 iter=0 solve=1.1s total=1.1s rt=25s
CHECKPOINT pair=(31,3) verdict=REFUTED rung=k8 iter=0 solve=1.7s total=1.7s rt=25s
CHECKPOINT pair=(29,4) verdict=REFUTED rung=k8 iter=0 solve=2.5s total=2.6s rt=25s
CHECKPOINT pair=(30,4) verdict=REFUTED rung=k8 iter=0 solve=8.4s total=8.4s rt=25s
CHECKPOINT pair=(31,4) verdict=REFUTED rung=k8 iter=0 solve=2.0s total=2.0s rt=25s
CHECKPOINT pair=(28,5) verdict=REFUTED rung=k8 iter=0 solve=4.0s total=4.0s rt=25s
CHECKPOINT pair=(29,5) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,5) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,5) verdict=REFUTED rung=k8 iter=0 solve=2.4s total=2.4s rt=25s
CHECKPOINT pair=(27,6) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,6) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,6) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,6) verdict=REFUTED rung=k8 iter=0 solve=19.0s total=19.1s rt=25s
CHECKPOINT pair=(31,6) verdict=REFUTED rung=k8 iter=0 solve=6.5s total=6.5s rt=25s
CHECKPOINT pair=(26,7) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,7) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,7) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,7) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,7) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,7) verdict=REFUTED rung=k8 iter=0 solve=2.0s total=2.1s rt=25s
CHECKPOINT pair=(25,8) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,8) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,8) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,8) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,31) verdict=REFUTED rung=k8 iter=0 solve=2.3s total=2.3s rt=25s
CHECKPOINT pair=(2,31) verdict=REFUTED rung=k8 iter=0 solve=2.6s total=2.6s rt=25s
CHECKPOINT pair=(2,30) verdict=REFUTED rung=k8 iter=0 solve=2.5s total=2.5s rt=25s
CHECKPOINT pair=(17,16) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(16,17) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(19,16) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(1,31) verdict=REFUTED rung=k8 iter=0 solve=2.3s total=2.4s rt=25s
CHECKPOINT pair=(30,31) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(31,30) verdict=REFUTED rung=k8 iter=0 solve=5.0s total=5.0s rt=25s
CHECKPOINT pair=(3,31) verdict=REFUTED rung=k8 iter=0 solve=2.6s total=2.6s rt=25s
CHECKPOINT pair=(29,31) verdict=REFUTED rung=k8 iter=0 solve=2.6s total=2.6s rt=25s
CHECKPOINT pair=(30,30) verdict=REFUTED rung=k8 iter=0 solve=8.7s total=8.7s rt=25s
CHECKPOINT pair=(31,29) verdict=REFUTED rung=k8 iter=0 solve=12.9s total=12.9s rt=25s
CHECKPOINT pair=(3,30) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.8s rt=25s
CHECKPOINT pair=(4,31) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(28,31) verdict=REFUTED rung=k8 iter=0 solve=2.6s total=2.6s rt=25s
CHECKPOINT pair=(29,30) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(30,29) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,28) verdict=REFUTED rung=k8 iter=0 solve=16.5s total=16.5s rt=25s
CHECKPOINT pair=(3,29) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(4,30) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.8s rt=25s
CHECKPOINT pair=(5,31) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(27,31) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(28,30) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(29,29) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,28) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,27) verdict=REFUTED rung=k8 iter=0 solve=11.8s total=11.8s rt=25s
CHECKPOINT pair=(4,29) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.9s rt=25s
CHECKPOINT pair=(5,30) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(6,31) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(26,31) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(27,30) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(28,29) verdict=REFUTED rung=k8 iter=0 solve=13.0s total=13.0s rt=25s
CHECKPOINT pair=(29,28) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,27) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,26) verdict=REFUTED rung=k8 iter=0 solve=8.8s total=8.8s rt=25s
CHECKPOINT pair=(4,28) verdict=REFUTED rung=k8 iter=0 solve=4.6s total=4.7s rt=25s
CHECKPOINT pair=(5,29) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=3.0s rt=25s
CHECKPOINT pair=(6,30) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(7,31) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(25,31) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(26,30) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(27,29) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(28,28) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,27) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,25) verdict=REFUTED rung=k8 iter=0 solve=5.0s total=5.0s rt=25s
CHECKPOINT pair=(5,28) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(6,29) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(7,30) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(8,31) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(24,31) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(25,30) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(26,29) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(27,28) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,27) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,8) verdict=REFUTED rung=k8 iter=0 solve=2.5s total=2.5s rt=25s
CHECKPOINT pair=(31,24) verdict=REFUTED rung=k8 iter=0 solve=14.2s total=14.2s rt=25s
CHECKPOINT pair=(5,27) verdict=REFUTED rung=k8 iter=0 solve=5.4s total=5.4s rt=25s
CHECKPOINT pair=(6,28) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(7,29) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(8,30) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(9,31) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.8s rt=25s
CHECKPOINT pair=(23,31) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.8s rt=25s
CHECKPOINT pair=(24,30) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(25,29) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(26,28) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(27,27) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,25) verdict=REFUTED rung=k8 iter=0 solve=7.0s total=7.1s rt=25s
CHECKPOINT pair=(30,8) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,24) verdict=REFUTED rung=k8 iter=0 solve=10.8s total=10.8s rt=25s
CHECKPOINT pair=(31,9) verdict=REFUTED rung=k8 iter=0 solve=2.8s total=2.9s rt=25s
CHECKPOINT pair=(31,23) verdict=REFUTED rung=k8 iter=0 solve=10.4s total=10.4s rt=25s
CHECKPOINT pair=(6,27) verdict=REFUTED rung=k8 iter=0 solve=5.6s total=5.6s rt=25s
CHECKPOINT pair=(7,28) verdict=REFUTED rung=k8 iter=0 solve=5.2s total=5.2s rt=25s
CHECKPOINT pair=(8,29) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(9,30) verdict=REFUTED rung=k8 iter=0 solve=3.2s total=3.2s rt=25s
CHECKPOINT pair=(10,31) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(22,31) verdict=REFUTED rung=k8 iter=0 solve=3.2s total=3.2s rt=25s
CHECKPOINT pair=(23,30) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(24,29) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(25,28) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=25s
CHECKPOINT pair=(26,27) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,8) verdict=REFUTED rung=k8 iter=0 solve=6.0s total=6.0s rt=25s
CHECKPOINT pair=(29,24) verdict=REFUTED rung=k8 iter=0 solve=15.5s total=15.5s rt=25s
CHECKPOINT pair=(30,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,10) verdict=REFUTED rung=k8 iter=0 solve=1.8s total=1.8s rt=25s
CHECKPOINT pair=(31,22) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(6,26) verdict=REFUTED rung=k8 iter=0 solve=3.2s total=3.2s rt=25s
CHECKPOINT pair=(7,27) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(8,28) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=25s
CHECKPOINT pair=(9,29) verdict=REFUTED rung=k8 iter=0 solve=1.6s total=1.6s rt=25s
CHECKPOINT pair=(10,30) verdict=REFUTED rung=k8 iter=0 solve=1.7s total=1.7s rt=25s
CHECKPOINT pair=(11,31) verdict=REFUTED rung=k8 iter=0 solve=1.7s total=1.7s rt=25s
CHECKPOINT pair=(21,31) verdict=REFUTED rung=k8 iter=0 solve=1.6s total=1.6s rt=25s
CHECKPOINT pair=(22,30) verdict=REFUTED rung=k8 iter=0 solve=1.6s total=1.6s rt=25s
CHECKPOINT pair=(23,29) verdict=REFUTED rung=k8 iter=0 solve=1.6s total=1.6s rt=25s
CHECKPOINT pair=(24,28) verdict=REFUTED rung=k8 iter=0 solve=1.9s total=1.9s rt=25s
CHECKPOINT pair=(25,27) verdict=REFUTED rung=k8 iter=0 solve=12.6s total=12.6s rt=25s
CHECKPOINT pair=(26,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,11) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.8s rt=25s
CHECKPOINT pair=(31,21) verdict=REFUTED rung=k8 iter=0 solve=7.2s total=7.2s rt=25s
CHECKPOINT pair=(7,26) verdict=REFUTED rung=k8 iter=0 solve=6.7s total=6.7s rt=25s
CHECKPOINT pair=(8,27) verdict=REFUTED rung=k8 iter=0 solve=6.0s total=6.0s rt=25s
CHECKPOINT pair=(9,28) verdict=REFUTED rung=k8 iter=0 solve=5.3s total=5.3s rt=25s
CHECKPOINT pair=(10,29) verdict=REFUTED rung=k8 iter=0 solve=3.5s total=3.5s rt=25s
CHECKPOINT pair=(11,30) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.7s rt=25s
CHECKPOINT pair=(12,31) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.6s rt=25s
CHECKPOINT pair=(20,31) verdict=REFUTED rung=k8 iter=0 solve=3.7s total=3.7s rt=25s
CHECKPOINT pair=(21,30) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.6s rt=25s
CHECKPOINT pair=(22,29) verdict=REFUTED rung=k8 iter=0 solve=3.7s total=3.7s rt=25s
CHECKPOINT pair=(23,28) verdict=REFUTED rung=k8 iter=0 solve=3.7s total=3.7s rt=25s
CHECKPOINT pair=(24,27) verdict=REFUTED rung=k8 iter=0 solve=7.1s total=7.1s rt=25s
CHECKPOINT pair=(25,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,9) verdict=REFUTED rung=k8 iter=0 solve=11.8s total=11.8s rt=25s
CHECKPOINT pair=(28,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,12) verdict=REFUTED rung=k8 iter=0 solve=3.8s total=3.8s rt=25s
CHECKPOINT pair=(31,20) verdict=REFUTED rung=k8 iter=0 solve=8.9s total=8.9s rt=25s
CHECKPOINT pair=(7,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(8,26) verdict=REFUTED rung=k8 iter=0 solve=9.5s total=9.5s rt=25s
CHECKPOINT pair=(9,27) verdict=REFUTED rung=k8 iter=0 solve=6.4s total=6.4s rt=25s
CHECKPOINT pair=(10,28) verdict=REFUTED rung=k8 iter=0 solve=6.2s total=6.2s rt=25s
CHECKPOINT pair=(11,29) verdict=REFUTED rung=k8 iter=0 solve=3.8s total=3.8s rt=25s
CHECKPOINT pair=(12,30) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.6s rt=25s
CHECKPOINT pair=(13,31) verdict=REFUTED rung=k8 iter=0 solve=3.5s total=3.5s rt=25s
CHECKPOINT pair=(19,31) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.6s rt=25s
CHECKPOINT pair=(20,30) verdict=REFUTED rung=k8 iter=0 solve=5.8s total=5.8s rt=25s
CHECKPOINT pair=(21,29) verdict=REFUTED rung=k8 iter=0 solve=3.8s total=3.9s rt=25s
CHECKPOINT pair=(22,28) verdict=REFUTED rung=k8 iter=0 solve=3.6s total=3.6s rt=25s
CHECKPOINT pair=(23,27) verdict=REFUTED rung=k8 iter=0 solve=6.2s total=6.3s rt=25s
CHECKPOINT pair=(24,26) verdict=REFUTED rung=k8 iter=0 solve=9.3s total=9.3s rt=25s
CHECKPOINT pair=(25,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,12) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,20) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,13) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(31,19) verdict=REFUTED rung=k8 iter=0 solve=5.3s total=5.3s rt=25s
CHECKPOINT pair=(8,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(9,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(10,27) verdict=REFUTED rung=k8 iter=0 solve=4.6s total=4.6s rt=25s
CHECKPOINT pair=(11,28) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(12,29) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(13,30) verdict=REFUTED rung=k8 iter=0 solve=3.1s total=3.1s rt=25s
CHECKPOINT pair=(14,31) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(18,31) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(19,30) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(20,29) verdict=REFUTED rung=k8 iter=0 solve=2.9s total=2.9s rt=25s
CHECKPOINT pair=(21,28) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.4s rt=25s
CHECKPOINT pair=(22,27) verdict=REFUTED rung=k8 iter=0 solve=5.7s total=5.7s rt=25s
CHECKPOINT pair=(23,26) verdict=REFUTED rung=k8 iter=0 solve=16.4s total=16.4s rt=25s
CHECKPOINT pair=(24,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,12) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,20) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,13) verdict=REFUTED rung=k8 iter=0 solve=12.4s total=12.4s rt=25s
CHECKPOINT pair=(30,19) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,14) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=25s
CHECKPOINT pair=(31,18) verdict=REFUTED rung=k8 iter=0 solve=6.8s total=6.8s rt=25s
CHECKPOINT pair=(8,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(9,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(10,26) verdict=REFUTED rung=k8 iter=0 solve=7.9s total=7.9s rt=25s
CHECKPOINT pair=(11,27) verdict=REFUTED rung=k8 iter=0 solve=6.2s total=6.2s rt=25s
CHECKPOINT pair=(12,28) verdict=REFUTED rung=k8 iter=0 solve=5.7s total=5.7s rt=25s
CHECKPOINT pair=(13,29) verdict=REFUTED rung=k8 iter=0 solve=3.4s total=3.4s rt=25s
CHECKPOINT pair=(14,30) verdict=REFUTED rung=k8 iter=0 solve=3.4s total=3.4s rt=25s
CHECKPOINT pair=(15,31) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.4s rt=25s
CHECKPOINT pair=(17,31) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=25s
CHECKPOINT pair=(18,30) verdict=REFUTED rung=k8 iter=0 solve=3.5s total=3.5s rt=25s
CHECKPOINT pair=(19,29) verdict=REFUTED rung=k8 iter=0 solve=3.4s total=3.4s rt=25s
CHECKPOINT pair=(20,28) verdict=REFUTED rung=k8 iter=0 solve=5.7s total=5.7s rt=25s
CHECKPOINT pair=(21,27) verdict=REFUTED rung=k8 iter=0 solve=6.1s total=6.1s rt=25s
CHECKPOINT pair=(22,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(23,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(24,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,12) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
