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
CHECKPOINT pair=(28,20) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,13) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,19) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,14) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,18) verdict=REFUTED rung=k8 iter=0 solve=15.2s total=15.2s rt=25s
CHECKPOINT pair=(31,15) verdict=REFUTED rung=k8 iter=0 solve=8.8s total=8.8s rt=25s
CHECKPOINT pair=(31,17) verdict=REFUTED rung=k8 iter=0 solve=7.6s total=7.6s rt=25s
CHECKPOINT pair=(9,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(10,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(11,26) verdict=REFUTED rung=k8 iter=0 solve=10.6s total=10.6s rt=25s
CHECKPOINT pair=(12,27) verdict=REFUTED rung=k8 iter=0 solve=9.4s total=9.4s rt=25s
CHECKPOINT pair=(13,28) verdict=REFUTED rung=k8 iter=0 solve=5.0s total=5.1s rt=25s
CHECKPOINT pair=(14,29) verdict=REFUTED rung=k8 iter=0 solve=4.5s total=4.5s rt=25s
CHECKPOINT pair=(15,30) verdict=REFUTED rung=k8 iter=0 solve=4.1s total=4.2s rt=25s
CHECKPOINT pair=(16,31) verdict=REFUTED rung=k8 iter=0 solve=4.2s total=4.2s rt=25s
CHECKPOINT pair=(17,30) verdict=REFUTED rung=k8 iter=0 solve=4.3s total=4.4s rt=25s
CHECKPOINT pair=(18,29) verdict=REFUTED rung=k8 iter=0 solve=4.2s total=4.2s rt=25s
CHECKPOINT pair=(19,28) verdict=REFUTED rung=k8 iter=0 solve=4.6s total=4.6s rt=25s
CHECKPOINT pair=(20,27) verdict=REFUTED rung=k8 iter=0 solve=7.4s total=7.4s rt=25s
CHECKPOINT pair=(21,26) verdict=REFUTED rung=k8 iter=0 solve=10.7s total=10.8s rt=25s
CHECKPOINT pair=(22,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(23,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(24,9) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(24,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,12) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,20) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,13) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,19) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(29,14) verdict=REFUTED rung=k8 iter=0 solve=7.1s total=7.1s rt=25s
CHECKPOINT pair=(29,18) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,15) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(30,17) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(31,16) verdict=REFUTED rung=k8 iter=0 solve=2.7s total=2.7s rt=25s
CHECKPOINT pair=(9,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(10,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(11,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(12,26) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(13,27) verdict=REFUTED rung=k8 iter=0 solve=6.6s total=6.7s rt=25s
CHECKPOINT pair=(14,28) verdict=REFUTED rung=k8 iter=0 solve=4.6s total=4.6s rt=25s
CHECKPOINT pair=(15,29) verdict=REFUTED rung=k8 iter=0 solve=3.9s total=3.9s rt=25s
CHECKPOINT pair=(16,30) verdict=REFUTED rung=k8 iter=0 solve=3.7s total=3.7s rt=25s
CHECKPOINT pair=(17,29) verdict=REFUTED rung=k8 iter=0 solve=3.8s total=3.8s rt=25s
CHECKPOINT pair=(18,28) verdict=REFUTED rung=k8 iter=0 solve=6.8s total=6.9s rt=25s
CHECKPOINT pair=(19,27) verdict=REFUTED rung=k8 iter=0 solve=6.3s total=6.4s rt=25s
CHECKPOINT pair=(20,26) verdict=REFUTED rung=k8 iter=0 solve=8.3s total=8.3s rt=25s
CHECKPOINT pair=(21,25) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(22,24) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(23,23) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(24,10) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(24,22) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,11) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(25,21) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,12) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(26,20) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,13) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(27,19) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s
CHECKPOINT pair=(28,14) verdict=OPEN rung=k8 iter=0 timeout=25s reason=timeout rt=25s

## 8. P5-I2 continuation — width-TRUNCATED encoder (tools/p5i_z3pair2.py)

Inherited state at handoff: 482 pairs in z3 scope; 172 REFUTED, 126 OPEN
(rt=25s), 184 never attempted (all in the hard middle shells 18..30).

NEW ENCODER. Rung k is encoded at the exact minimal widths implied by the
cone of `out mod 2^k`, instead of 32 bits everywhere:
    Wb = min(32, s1+s2+k)  for b, K1, C1
    We = min(32, s2+k)     for c, e, M1, K2, C2
    Ww = k                 for w, out, M2, K3, C3
Exactness: when Wb < 32, Wb - s1 == We exactly, so LShR at the truncated
width zero-fills only positions >= We, which are discarded. The encoded
formula is satisfiable iff the 32-bit formula restricted to `out mod 2^k`
on those samples is => UNSAT is still an EXACT refutation.
Unknown bits drop from 256 to 2*Wb + 3*We + 3*k (e.g. 130 at (30,6) k=8).

GUARDS (both passed, tools/p5i_z3pair2.py --selftest):
  SELFTEST-TRUNC   planted constants must be SAT at every rung k=8,16,32
                   (a truncation bug that lost information would show up
                   as UNSAT here, i.e. as a fabricated refutation).
  SELFTEST-PLANTED a random planted sandwich9 target must never come back
                   REFUTED. Verified at (16,16) and (30,6): both OPEN.

SPEEDUP (myhash target, same 34-sample battery, same rungs):
  (30,6)   v1 19.0s  -> v2  2.2s   (8.6x)
  (23,26)  v1 16.4s  -> v2  5.8s   (2.8x)
  (28,14)  v1 OPEN@25s -> v2 REFUTED 11.9s   (new kill)
  (16,16)  v1 OPEN@25s -> v2 OPEN@60s
  (25,25)  v1 OPEN@25s -> v2 OPEN@60s
MORE SAMPLES DO NOT HELP the stubborn band: (16,16) and (25,25) stay OPEN
at n=82 and n=178 with a 90s budget. "Cheap-or-never" survives the
re-encoding; the encoder just moves the cheap/never boundary outward.

Sweep driver: tools/p5i_sweep2.py (todo = scope minus every REFUTED/FOUND
in EITHER ledger; v1-OPEN pairs are retried). Lines below are CHECKPOINT2.
CHECKPOINT2 pair=(30,29) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,29) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,5) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.7s total=3.7s rt=25s
CHECKPOINT2 pair=(30,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(28,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,5) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=9.7s total=9.8s rt=25s
CHECKPOINT2 pair=(27,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(28,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,6) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,7) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=23.1s total=23.1s rt=25s
CHECKPOINT2 pair=(27,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(28,6) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(28,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(29,7) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(30,8) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(26,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s
CHECKPOINT2 pair=(27,6) verdict=OPEN rung=k8 iter=0 n=34 timeout=25s reason=timeout rt=25s

## 9. TOP-BIT DIFFERENTIAL-COUNT THEOREM — kills every pair with s2 <= 14

THEOREM (forward). Let out_0 be bit 0 of sandwich9 and
    N := #{ x in Z_2^32 : out_0(x ^ 2^31) != out_0(x) }.
For 1 <= s1 <= 30, 1 <= s2 <= 30, s1+s2 >= 32 (so u := 31-s1 >= 1 and
t := s1+s2-31 >= 1), for EVERY choice of the 8 constants:
        N == 0   (mod 2^(33-s2)).
Proof. b* = b ^ 2^31 exactly (K1 odd); c* = c ^ 2^31 ^ 2^u exactly;
e* = e + 2^31 + sg*K2*2^u with sg = +-1 from c_u. out_0 = e_0 ^ e_{s2} ^
const and e*_0 = e_0 (u>=1), so with A := bits u..u+t-1 of e, q := K2 mod
2^t (odd), the differential is exactly
    D(x) = K2_t ^ [A + q >= 2^t]   (sg=+1) ,   K2_t ^ [A < q]   (sg=-1).
Split c = c_hi*2^(u+1) + c_u*2^u + c_lo. For fixed (c_u, c_lo), bits
u+1..u+t-1 of e are EXACTLY uniform over c_hi (K2 odd) while bit u of e is
pinned to g ^ c_u, g := bit_u(K2*c_lo + C2). Counting both sg-classes and
using that q is odd (alpha(p) = beta(p^1)) gives
    M = 2^(32-t)*(q-1) + 2^(33-s2)*n_1,   n_1 := #{c_lo<2^u : g=1},
and N = M or 2^32 - M according to K2_t. s1 <= 30 makes 32-t >= 33-s2, so
2^(33-s2) divides both. QED

NUMERIC GUARD (tools/p5i_diffcount.py, scaled word width): w=14, 528
(pair,constants) trials over every legal (s1,s2), VIOLATIONS = 0, and the
observed common 2-adic valuation EQUALS the predicted w+1-s2 for every s2
-- the modulus is SHARP, not conservative. Control at t=0 (s1+s2=w-1)
reproduces sec. 2's N == 2^w exactly, 11/11.

MYHASH SIDE (tools/p5i_myhash_diffcount.py, full 2^32 numpy sweep, numpy
myhash cross-checked against the scalar reference):
        N_myhash = 2172911616 = 2^18 * 8289,   v2 = 18.
=> 33-s2 > 18, i.e. s2 <= 14, is REFUTED EXACTLY for every s1 in 1..30
with s1+s2 >= 32. 78 pairs in the z3 scope, 68 of them previously
undecided. (Consistent with, and strictly containing, the z3 refutations
already on record at s2 <= 14.)

COSET REFINEMENT — TESTED AND DEAD. The natural strengthening ("the
differential density is the same in every coset x mod 2^m") is FALSE for
s2 > s1 (scaled-model counterexamples at (3,12),(5,11),(7,8),(8,9),...;
it holds empirically iff s2 <= s1 or t=1). And it buys nothing anyway:
myhash's coset counts N_m(rho) are EXACTLY constant for all m = 1..8
(m=8: 8487936 in every one of the 256 cosets). No kills.

## 10. MIRROR THEOREM (sandwich9^{-1}) — VALID BUT VACUOUS

sandwich^{-1} = A1' o T1 o A2' o T2 o A3' with A' madds (odd K^{-1}) and
T_i = sigma_i^{-1} = multi-term xorshift. For s1,s2 >= 16 each T has
exactly two terms on 32 bits and the sec. 9 argument transfers verbatim
with (observed bit, low shift) = (s1, u2 := 31-s2), same t = s1+s2-31:
        N' == 0 (mod 2^(33-s1)),  N' := #{y : g_0(y) != g_0(y^2^31)}.
NUMERIC GUARD (tools/p5i_mirror.py): w=14 288 trials and w=16 196 trials
in the two-term regime, VIOLATIONS = 0, observed valuation == predicted
for every s1 -- sharp.
MYHASH SIDE (tools/p5i_myhash_invdiff.py; myhash^{-1} built stage-by-stage
in numpy, round-trip verified on 2^20 randoms + edge cases):
        N'_myhash = 2011299840 = 2^17 * 15345,  v2 = 17.
=> refutes s1 <= 32-17 = 15. But the theorem's validity regime is
s1 >= 16. The kill range and the validity range are DISJOINT (by one
notch), so the mirror closes ZERO pairs. Recorded so nobody re-derives it.
CHECKPOINT2 pair=(27,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(7,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=10.4s total=10.4s rt=15s
CHECKPOINT2 pair=(25,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(8,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(9,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=5.5s total=5.5s rt=15s
CHECKPOINT2 pair=(24,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(8,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(9,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=6.0s total=6.0s rt=15s
CHECKPOINT2 pair=(23,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(9,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(10,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=12.0s total=12.0s rt=15s
CHECKPOINT2 pair=(23,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,18) verdict=REFUTED rung=k8 iter=0 n=34 solve=7.4s total=7.5s rt=15s
CHECKPOINT2 pair=(30,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(9,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(10,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(11,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.4s total=3.4s rt=15s
CHECKPOINT2 pair=(21,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=6.5s total=6.5s rt=15s
CHECKPOINT2 pair=(22,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,17) verdict=REFUTED rung=k8 iter=0 n=34 solve=7.7s total=7.8s rt=15s
CHECKPOINT2 pair=(30,16) verdict=REFUTED rung=k8 iter=0 n=34 solve=11.6s total=11.7s rt=15s
CHECKPOINT2 pair=(10,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(11,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.8s total=3.8s rt=15s
CHECKPOINT2 pair=(14,27) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.0s total=3.0s rt=15s
CHECKPOINT2 pair=(15,28) verdict=REFUTED rung=k8 iter=0 n=34 solve=1.8s total=1.8s rt=15s
CHECKPOINT2 pair=(16,29) verdict=REFUTED rung=k8 iter=0 n=34 solve=1.6s total=1.6s rt=15s
CHECKPOINT2 pair=(17,28) verdict=REFUTED rung=k8 iter=0 n=34 solve=2.8s total=2.8s rt=15s
CHECKPOINT2 pair=(18,27) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.0s total=3.1s rt=15s
CHECKPOINT2 pair=(19,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.7s total=3.7s rt=15s
CHECKPOINT2 pair=(20,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(29,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(10,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(11,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.7s total=3.7s rt=15s
CHECKPOINT2 pair=(15,27) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.1s total=3.1s rt=15s
CHECKPOINT2 pair=(16,28) verdict=REFUTED rung=k8 iter=0 n=34 solve=1.6s total=1.7s rt=15s
CHECKPOINT2 pair=(17,27) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.0s total=3.0s rt=15s
CHECKPOINT2 pair=(18,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.9s total=3.9s rt=15s
CHECKPOINT2 pair=(19,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=7.4s total=7.4s rt=15s
CHECKPOINT2 pair=(20,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(28,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(11,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=6.2s total=6.2s rt=15s
CHECKPOINT2 pair=(15,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.7s total=3.7s rt=15s
CHECKPOINT2 pair=(16,27) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.0s total=3.0s rt=15s
CHECKPOINT2 pair=(17,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.6s total=3.6s rt=15s
CHECKPOINT2 pair=(18,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=6.9s total=6.9s rt=15s
CHECKPOINT2 pair=(19,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(27,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(11,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,26) verdict=REFUTED rung=k8 iter=0 n=34 solve=3.6s total=3.6s rt=15s
CHECKPOINT2 pair=(17,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=6.2s total=6.3s rt=15s
CHECKPOINT2 pair=(18,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(26,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(25,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(12,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(24,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(23,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(13,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(22,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,21) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(21,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(14,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,20) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(20,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,19) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(19,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(15,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,18) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,15) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(18,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,17) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(17,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(16,16) verdict=OPEN rung=k8 iter=0 n=34 timeout=15s reason=timeout rt=15s
CHECKPOINT2 pair=(30,29) verdict=REFUTED rung=k8 iter=0 n=34 solve=53.0s total=53.0s rt=150s
CHECKPOINT2 pair=(29,29) verdict=REFUTED rung=k8 iter=0 n=34 solve=69.9s total=70.0s rt=150s
CHECKPOINT2 pair=(30,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(29,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(30,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(30,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(29,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(30,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(28,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(29,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(27,28) verdict=OPEN rung=k8 iter=0 n=34 timeout=150s reason=timeout rt=150s
CHECKPOINT2 pair=(28,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(29,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(27,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(28,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(26,27) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(27,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(28,25) verdict=REFUTED rung=k8 iter=0 n=34 solve=63.5s total=63.5s rt=90s
CHECKPOINT2 pair=(30,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(26,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(27,25) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(28,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(29,23) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(30,22) verdict=OPEN rung=k8 iter=0 n=34 timeout=90s reason=timeout rt=90s
CHECKPOINT2 pair=(24,24) verdict=OPEN rung=k8 iter=0 n=34 timeout=560s reason=timeout rt=560s
CHECKPOINT2 pair=(28,26) verdict=OPEN rung=k8 iter=0 n=34 timeout=560s reason=timeout rt=560s

## 11. P5-I2 CLOSING LEDGER — 754/961 refuted, 207 open, 0 found

    theory secs. 1-3 (window / row-31 / row-32 / (31,1) / (18,14))   479
    z3 per-pair UNSAT (v1 encoder 172 + v2 encoder 35)               207
    sec. 9 differential-count theorem, s2 <= 14 (new-only)             68
    STILL OPEN                                                       207
                                                                    ----
                                                                     961
NOT A SINGLE `FOUND` ANYWHERE. Every pair that has been decided at all
was decided REFUTED. The whole s1=31 row and the whole s2=31 column are
closed. The 207 survivors form one contiguous block:

  s1= 8: 24,25              s1=17..19: 15..24
  s1= 9: 23..25             s1=20: 15..25      s1=21,22: 15..24
  s1=10: 22..25             s1=23,24: 15..25   s1=25: 15..26
  s1=11: 21..25             s1=26: 15..27      s1=27: 15..28
  s1=12: 20..25             s1=28: 15..24,26,27,28
  s1=13: 19..25             s1=29: 15,16,19..23,26,27,28
  s1=14: 18..24             s1=30: 15,17,19..23,27,28
  s1=15: 17..25             s1=16: 16..25
EVERY survivor has s2 >= 15 -- i.e. the open set is exactly what the
sec. 9 theorem could not reach (it needs 33-s2 > v2(N_myhash) = 18).

Z3 WALL, MEASURED (v2 encoder, k=8 rung, 34-sample battery):
    rt=15s  over 226 pairs -> 32 closed (14%)
    rt=90s  over  13 pairs ->  1 closed ( 8%)
    rt=150s over  11 pairs ->  2 closed (18%, at 53.0s and 69.9s)
    rt=560s on (24,24) and (28,26) -> both still OPEN
So the tail is real but thin: escalation converts a few percent per decade
of budget and does NOT collapse the block. Things that were tried and did
NOT move the wall: 82- and 178-sample batteries; rungs k=1,2,4 with
200-1200 samples; a battery made purely of top-bit differential pairs
(x, x^2^31) x 24 -- all still `unknown` at 60-100s on (16,16)/(20,20)/
(24,24)/(25,25)/(28,26).

RESUME PROTOCOL
  python3 tools/p5i_sweep2.py --rung-timeout T --wall-budget W \
                              [--redo-v2-open]
  Re-reads this file. Skips (a) anything REFUTED/FOUND in either ledger,
  (b) anything killed by sec. 9 (tools/p5i_sweep2.py:theorem_killed), and
  (c) any pair that already survived a rung timeout >= T. Order is
  `shell` = min(s1,32-s1)+min(s2,32-s2) ascending (easiest first).
  One CHECKPOINT2 line appended per attempt; crash-safe.

WHAT WOULD ACTUALLY CLOSE THE BLOCK (in order of expected value)
  1. A second differential-count statistic whose modulus is keyed to
     something other than the observed output bit's shift. Everything
     derived here keys on the LAST sigma's shift (forward: s2; inverse:
     s1), and both are exhausted: forward reaches s2 <= 14, inverse would
     reach s1 <= 15 but is only VALID for s1 >= 16 (sec. 10).
  2. Note the reachable-value refinement of sec. 9 that was NOT pushed:
     N determines (q, n_1) almost uniquely (n_1 = N/2^(33-s2) mod 2^u,
     q-1 = (Ntilde-n_1)/2^(u-1)), and n_1 must be realizable as
     #{c_lo<2^u : bit_u(K2*c_lo+C2)=1} by a K2 with K2 mod 2^t = q. Spot
     checks at (16,16) found it realizable (K2=1, C2=16578), but the
     realizability question was not settled in general -- if some pair's
     required n_1 is unreachable, that pair dies with no solver at all.
  3. Brute compute: ~207 pairs x >=10 min each with the v2 encoder.
CHECKPOINT pair=(28,18) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(29,15) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(29,17) verdict=REFUTED rung=k8 iter=0 solve=7.4s total=7.4s rt=600s
CHECKPOINT pair=(30,16) verdict=REFUTED rung=k8 iter=0 solve=3.0s total=3.0s rt=600s


## 12. [P5-I3] REALIZABILITY FILTER — 136 of the 207 survivors die, no solver

(P5-I3 own section; appended after the driver's CHECKPOINT lines.
Tools: `tools/p5i3_arith.py` (filter + 3 guards), `tools/p5i3_planted.py`
(SELFTEST-PLANTED).  This is item 2 of sec. 11's "what would close the block".)

### 12.1 The arithmetic is CLOSED FORM: (q, n_1) depend only on t

Sec. 9 gives, with u = 31-s1, t = s1+s2-31, s2 = u+t:
    M = 2^(32-t)(q-1) + 2^(33-s2) n_1,  N = M or 2^32 - M,
    q = K2 mod 2^t (odd),  n_1 = #{c_lo<2^u : bit_u(K2 c_lo + C2)=1} in [0,2^u].
Put Ntilde := M / 2^(33-s2) = 2^u Q + n_1 with q = 2Q+1, Q in [0,2^(t-1)-1].
For N = N_myhash = 2^18*8289 (branch A=8289) and 2^32-N = 2^18*8095
(branch A=8095), Ntilde = A*2^(s2-15) EXACTLY, so for t <= 15
    Q = A >> (15-t),   q = 2Q+1,   n_1 = (A mod 2^(15-t)) << (s2-15),
and for t > 15, Q = A*2^(t-15), n_1 = 0 (plus the boundary alternative
n_1 = 2^u with q = 2Q-1).  **q and n_1/2^u depend on t ONLY** -- not on u,
not on s1, not on s2 separately.  Range checks (Ntilde <= 2^(s2-1),
Q <= 2^(t-1)-1) are automatic because A < 2^14.

### 12.2 REALIZABILITY THEOREM (what n_1 a given K2 can produce)

Only k := K2 mod 2^(u+1) and C := C2 mod 2^(u+1) matter.  With
n1(C) = #{c<2^u : bit_u(kc+C)=1}:
  (a) n1(C+1)-n1(C) in {-1,0,+1}   (the count is a sliding half-circle window
      over S = {kc mod 2^(u+1) : c<2^u}, and S is a TRANSVERSAL of the pairs
      {v, v+2^u} because k is odd);
  (b) n1(C) + n1(C+2^u) = 2^u.
=> the achievable set is EXACTLY the contiguous, centred range
        [ m(k,u), 2^u - m(k,u) ],    m(k,u) := min_C n1(C).
Brute force (all odd k, u <= 8) confirms the set is exactly that range
(GUARD-RANGE, 0 violations) and that m(k,u) = 0 **iff k = +-1 mod 2^(u+1)**
(S is then an interval).  m(k,u) = m(k^{-1},u) = m(-k,u).

DESCENT LEMMA (proved).   m(u,k) >= 2 * m(u-1, k mod 2^u).
  Split c = 2c' and c = 2c'+1.  With C = 2C'+C_0 and k+C = 2E+f:
  bit_u(k(2c')+C) = bit_{u-1}(kc'+C') and bit_u(k(2c'+1)+C) = bit_{u-1}(kc'+E),
  so n1(C) is a SUM of two level-(u-1) counts at modulus k mod 2^u.
  Iterating: m(u,k) >= 2^(u-j) * m(j, k mod 2^(j+1)) for every j <= u.
GUARD-DESCENT: 7,172 (u<=9, all odd k, all j) instances, 0 violations.
Typical size: min{m(j,k) : k != +-1} / 2^j -> 1/3 (5/16, 10/32, 21/64,
42/128, ...), i.e. a NON-+-1 multiplier can only reach n_1 in ~[1/3,2/3]*2^u.

### 12.3 THE FILTER (sound; EXACT for u <= 10, i.e. s1 >= 21)

Branch dies if  n_1 < LB  or  n_1 > 2^u - LB,  where LB = 2^(u-j)*min{m(j,r)}
over the r reachable at level j = min(u,10) (r == q mod 2^t if t <= j+1, else
the single r = q mod 2^(j+1)).  Pair dies iff BOTH N-branches die.
For u <= 10 the level IS u, so LB = the true min and the verdict is EXACT.
For u > 10 the only ALIVE pairs have t <= 2 or n_1 = 2^(u-1), both of which
are realizable unconditionally -- so the verdict is exact on the whole
survivor set as well.

SELFTEST-PLANTED (tools/p5i3_planted.py): random constants at scaled width w,
TRUE N by 2^w brute force, then the width-w filter must return ALIVE (a
solution exists by construction).  w=14: 660 trials, 0 violations.
w=16: 182 trials, 0 violations.  TEETH (non-vacuity): at w=14, over every
legal N (all multiples of 2^(w+1-s2) in [0,2^w]) for every legal (s1,s2), the
filter returns DEAD for 13,424 / 41,028 = 32.7%.  It kills a third of the
possible N values and never the achievable ones.
GUARD-FORMULA (the sec. 9 identity itself, not just its modulus):
N in {M, 2^w - M} verified over 180 random-constant trials at w=12,
0 violations.

### 12.4 VERDICT on sec. 11's 207 survivors:  136 DEAD, 71 remain

DEAD (136) -- every pair with t = s1+s2-31 in 3..13 except (24,16),(25,15),
(28,16),(29,15); plus 23 pairs with t >= 15:
(9,25)(10,24)(10,25)(11,23..25)(12,22..25)(13,21..25)(14,20..24)(15,19..25)
(16,18..25)(17,17..24)(18,16..24)(19,15..24)(20,15..24)(21,15..23)
(22,15..22)(22,24)(23,15..21)(23,23..25)(24,15)(24,17..20)(24,22..25)
(25,16..19)(25,21..26)(26,15..18)(26,21..24)(27,15..17)(27,20..22)
(28,15)(28,19)(28,20)
ALIVE (71), with the reason -- and every reason is UNCONDITIONAL, so these
71 cannot be touched by any sharpening of this filter:
  t=1  (10 pairs)  q = 1  => K2 = 1 is admissible, m = 0, any n_1 works.
  t=2  (11 pairs)  the A=8095 branch has Q=0 => q=1, same escape.
  t=14 (11 pairs)  n_1 = 2^(u-1) EXACTLY (the centre of the window), and
                   m(k,u) <= 2^(u-1) always => realizable for every k.
  t>=13 with q == +-1 mod 2^(u+1)  (39 pairs, all s1 >= 24, u <= 7).
Full ALIVE list:
(8,24)(8,25)(9,23)(9,24)(10,22)(10,23)(11,21)(11,22)(12,20)(12,21)(13,19)
(13,20)(14,18)(14,19)(15,17)(15,18)(16,16)(16,17)(17,15)(17,16)(18,15)
(20,25)(21,24)(22,23)(23,22)(24,16)(24,21)(25,15)(25,20)(26,19)(26,20)
(26,25)(26,26)(26,27)(27,18)(27,19)(27,23..28)(28,16)(28,17)(28,18)
(28,21..24)(28,26)(28,27)(28,28)(29,15)(29,16)(29,19..23)(29,26)(29,27)
(29,28)(30,15)(30,17)(30,19..23)(30,27)(30,28)
LEDGER NOW: 961 = 479 (secs 1-3) + 207 (z3) + 68 (sec 9) + 136 (sec 12)
+ 71 OPEN.  Still 0 FOUND.

FULL-GRID form (needed by sec. 13): over all 435 pairs with s1,s2 <= 30 and
t >= 1, sec. 9 + sec. 12 kill 322 (91 by s2 <= 14, 231 NEW) and leave 113.
With the window theorem (435 pairs, s1+s2 <= 30) and row-31 (30 pairs), the
open shift space of a sandwich-structured shape is 113 + 61 (the s1 = 31 row
and s2 = 31 column, where sec. 9 is not valid: it needs u >= 1 and s2 <= 30)
= 174 of 961.

## 13. [P5-I3] TIER TRANSFER — sec. 9/12 reach 30 of the 3,005 p5k shapes

Tools: `tools/p5i3_transfer.py` (abstract differential interpreter over a
shape DAG + the transfer test), `tools/p5i3_guard_shape.py` (numeric guard).

TRANSFER CONDITIONS (a shape must satisfy ALL; each is checked syntactically):
 T1  exactly 2 shr ops (a 3rd breaks every step);
 T2  x reaches shr A's input carrying the EXACT single-bit flip 2^31 (only
     madd/xorc/xor2-with-exact-branches upstream);
 T3  the value c feeding the middle madd carries an EXACT flip set that is
     {31, u} or {u} alone, u = 31-s1 >= 1.  ({u} alone is enough: the 2^31
     term is invisible at every bit < 31, so both give the same differential
     at bit 0 and bit s2.)
 T4  exactly ONE madd between c and shr B's input (xorc and xor2 with
     exact-flip branches are transparent), so e* - e = [2^31 +] sg*K2*2^u;
 T5  bit 0 of out = bit 0 of shr B's output xored with CONSTANT-differential
     terms only (bit-0 differentials tracked in GF(2) over {1, D} so that
     re-joining bypass branches cancel correctly);
 T6a x -> c must be a BIJECTION *syntactically* (cone of c = madd/xorc/
     xorshift-motif only);
 T6b shr B's input slot is a DAG cut => out = G(F(x)) with F bijective
     (P5-K filter K2) => K2 is ODD.
Even-K case split: every parity assignment of the other madds must yield
either the same D or a CONSTANT bit-0 differential (then N in {0, 2^32},
which is divisible by everything and != N_myhash).

T6a IS NOT OPTIONAL — the guard caught it.  Queue rank 2953
[madd,madd,madd,shr,xor2(2,3),xor2(4,5),madd,shr,xor2(7,8)] passes T1-T5 and
T6b but its c = (x>>s1) ^ (two different madds of the same slot) is not a
bijection; at w=14 it produced 104/198 DIVISIBILITY violations and 135/198
FORM violations.  The sec. 9 count is a count OVER c; without bijectivity it
is re-weighted and the theorem is false.  (Recorded so nobody re-derives it.)

NUMERIC GUARD (tools/p5i3_guard_shape.py, w=14, all 66 legal (s1,s2) x 3
random odd-K constant sets = 198 trials per shape), on 5 accepted shapes
including two with a re-joining bypass xor2 and two with no leading madd:
  rank 200, 328 (=sandwich9), 634, 905, 1097
  -> DIV-VIOLATIONS 0/198 and FORM-VIOLATIONS 0/198 for every one.
(Being accepted, sandwich9 itself is a positive control on the analyser.)

MASS-FILTER RESULT.  Over tools/p5k_queue.json (3,005 entries):
  TRANSFER                                       30   (29 QUEUED + sandwich9)
  no sandwich pattern                         2,242
  no pattern + x->c not syntactically bijective  408
  no pattern + shr-B input not a cut             251
  no pattern + an even-K branch is not constant   73
  #shr != 2                                        1
Transferred ranks: 200 213 323 328 410 416 442 454 476 481 504 634 644 754
797 798 802 803 805 806 904 905 909 957 1000 1045 1046 1048 1051 1097.
Each of those 30 shapes has its shift space cut from 961 to **174** open
(s1,s2) assignments (sec. 12.4): 787 assignments refuted with no solver.
Before P5-I3 the same shapes stood at 405 open (window + row-31 + s2<=14).

MIRROR (sec. 10) CONTRIBUTES ZERO, for every shape.  Its kill range
(s1 <= 32 - v2(N'_myhash) = 15) and its validity range (s1 >= 16, needed for
sigma^{-1} to be a TWO-term xorshift on 32 bits) are disjoint by one notch.
That gap depends only on N'_myhash = 2^17*15345, not on the shape, so the
mirror is vacuous tier-wide.  Do not re-derive it.

QUEUE STATUSES: **DELIBERATELY NOT EDITED.**  No shape is CLOSED by this
filter -- 174 shift assignments survive on every transferred shape -- so
flipping any entry off QUEUED would silently retire a shape that is still
open (p5k's resume protocol consumes status=QUEUED in rank order).  Queue
size before = after = 3,005 (QUEUED 2,956).  The correct record of the
narrowing is this section.

WHAT WOULD CLOSE THE 30 (and, by the same argument, sandwich9's 71):
the surviving region is exactly {t <= 2} U {t = 14} U {q == +-1 mod 2^(u+1)}
U {s1 = 31 or s2 = 31}.  Nothing keyed on s2 can touch it (sec. 11 item 1
still stands).  A statistic keyed on a SECOND output bit (out_1, whose
differential brings in the carry structure of K3 as well) is the obvious
next axis, and it is untried.

### 13.1 [P5-I3] correction to 12.4's reason tally (append-only; supersedes)

The 71 ALIVE break down as: t=1 -> 10, t=2 -> 11, t=14 -> 11,
**q == +-1 mod 2^(u+1) -> 37** (t in 13,15..27, all s1 >= 26 except
(28,16)), and **2 by "n_1 lands inside the narrow window"**: (24,16) and
(25,15), both t=9, where the exact m(k,u) happens to be small enough.
10+11+11+37+2 = 71.  (Sec. 12.4's one-line summary said "39 pairs with
q == +-1"; the correct split is 37 + 2.)  The DEAD/ALIVE lists themselves
were re-verified against the code: both match exactly, 136 + 71 = 207.
CHECKPOINT pair=(10,23) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(11,24) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(12,25) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(13,26) verdict=REFUTED rung=k8 iter=0 solve=4.2s total=4.2s rt=600s
CHECKPOINT pair=(14,27) verdict=REFUTED rung=k8 iter=0 solve=3.2s total=3.2s rt=600s
CHECKPOINT pair=(15,28) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=600s
CHECKPOINT pair=(16,29) verdict=REFUTED rung=k8 iter=0 solve=1.9s total=1.9s rt=600s
CHECKPOINT pair=(17,28) verdict=REFUTED rung=k8 iter=0 solve=3.2s total=3.2s rt=600s
CHECKPOINT pair=(18,27) verdict=REFUTED rung=k8 iter=0 solve=3.4s total=3.4s rt=600s
CHECKPOINT pair=(19,26) verdict=REFUTED rung=k8 iter=0 solve=8.6s total=8.6s rt=600s
CHECKPOINT pair=(20,25) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(21,24) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(22,23) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(23,10) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(23,22) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(24,11) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(24,21) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(25,12) verdict=REFUTED rung=k8 iter=0 solve=284.9s total=284.9s rt=600s
CHECKPOINT pair=(25,20) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(26,13) verdict=REFUTED rung=k8 iter=0 solve=87.8s total=87.8s rt=600s
CHECKPOINT pair=(26,19) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(27,14) verdict=REFUTED rung=k8 iter=0 solve=72.2s total=72.2s rt=600s
CHECKPOINT pair=(27,18) verdict=REFUTED rung=k8 iter=0 solve=40.4s total=40.4s rt=600s
CHECKPOINT pair=(28,15) verdict=REFUTED rung=k8 iter=0 solve=3.7s total=3.7s rt=600s
CHECKPOINT pair=(28,17) verdict=REFUTED rung=k8 iter=0 solve=26.4s total=26.4s rt=600s
CHECKPOINT pair=(29,16) verdict=REFUTED rung=k8 iter=0 solve=27.4s total=27.4s rt=600s
CHECKPOINT pair=(10,22) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(11,23) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(12,24) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(13,25) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(14,26) verdict=REFUTED rung=k8 iter=0 solve=4.1s total=4.1s rt=600s
CHECKPOINT pair=(15,27) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=600s
CHECKPOINT pair=(16,28) verdict=REFUTED rung=k8 iter=0 solve=3.3s total=3.3s rt=600s
CHECKPOINT pair=(17,27) verdict=REFUTED rung=k8 iter=0 solve=3.8s total=3.8s rt=600s
CHECKPOINT pair=(18,26) verdict=REFUTED rung=k8 iter=0 solve=13.8s total=13.8s rt=600s
CHECKPOINT pair=(19,25) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(20,24) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
CHECKPOINT pair=(21,23) verdict=OPEN rung=k8 iter=0 timeout=600s reason=timeout rt=600s
