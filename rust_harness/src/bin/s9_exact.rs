// P5-I: exact decision machinery for sandwich9 -- row s1+s2=32 refutation
// engine + recursion validation.
//
// Shape (matches stoke.rs s9 / tools/p5d_sandwich9.py exactly):
//   b = x*K1+C1; c = b ^ M1 ^ (b>>s1); e = c*K2+C2;
//   w = e ^ M2 ^ (e>>s2); out = w*K3+C3.   K1,K2,K3 odd (bijectivity).
//
// ROW-32 THEOREM (derivation in research/strains/p5i/STATE.md): for
// s1+s2 = 32, 2 <= s1 <= 30, u = 31-s1 = s2-1, and ANY constants with odd
// K's, the iterated XOR-derivative of out_0 in directions
// 2^31, 2^30, ..., 2^(31-u) is CONSTANT over x, i.e. the parity of out_0
// over every coset of span{2^s1, ..., 2^31} is the same.  Sketch:
//   Delta_{2^31}: b* = b^2^31, c* = c^2^31^2^u exactly; K2*2^u mod
//   2^(s2+1) = 2^u*(K2 mod 4), and with W = 2 the top-window flip
//   collapses to  H(x) = bit_u(K2*(c mod 2^u) + C2) ^ kappa  (the c_u
//   term cancels because K2 is odd).  The peeled constraint reads only
//   b mod 2^31, where the next differential 2^30 acts as an exact bit
//   flip (K1*2^30 = 2^30 mod 2^31), flipping c bit u-1 only; the same
//   odd-K2 cancellation peels again.  After u+1 peels the right side is
//   bit_0(C2) = constant.
// myhash side: compute parity of myhash bit 0 over all cosets of
// span{2^m..2^31} for every m (one full 2^32 sweep + XOR folds).  If the
// parity table at m = s1 is nonconstant, pair (s1, 32-s1) admits NO
// constants: REFUTED EXACTLY.
//
// Modes:  validate  -- numeric check of the theorem on random constants,
//                      plus a negative control (row-33 pairs must show a
//                      NONconstant derivative for generic constants).
//         sweep     -- full-domain myhash sweep + folds; prints per-m
//                      constancy verdict + witness coset.

use std::env;
use std::thread;

#[inline(always)]
fn myhash(mut v: u32) -> u32 {
    v = v.wrapping_add(0x7ED55D16).wrapping_add(v << 12);
    v = (v ^ 0xC761C23C) ^ (v >> 19);
    v = v.wrapping_add(0x165667B1).wrapping_add(v << 5);
    v = v.wrapping_add(0xD3A2646C) ^ (v << 9);
    v = v.wrapping_add(0xFD7046C5).wrapping_add(v << 3);
    (v ^ 0xB55A4F09) ^ (v >> 16)
}

#[inline(always)]
fn sandwich(p: &[u32; 8], s1: u32, s2: u32, x: u32) -> u32 {
    let b = x.wrapping_mul(p[0]).wrapping_add(p[1]);
    let c = b ^ p[2] ^ (b >> s1);
    let e = c.wrapping_mul(p[3]).wrapping_add(p[4]);
    let w = e ^ p[5] ^ (e >> s2);
    w.wrapping_mul(p[6]).wrapping_add(p[7])
}

struct Rng(u64);
impl Rng {
    fn next(&mut self) -> u64 {
        self.0 ^= self.0 << 13;
        self.0 ^= self.0 >> 7;
        self.0 ^= self.0 << 17;
        self.0
    }
    fn u32(&mut self) -> u32 {
        (self.next() >> 16) as u32
    }
}

/// Iterated XOR-derivative of f's bit0 in directions 2^(31-u)..2^31 at x:
/// parity of f(x ^ (w << (31-u)))_0 over w in 0..2^(u+1).
fn iter_deriv<F: Fn(u32) -> u32>(f: &F, u: u32, x: u32) -> u32 {
    let sh = 31 - u;
    let mut p = 0u32;
    for w in 0..(1u64 << (u + 1)) {
        p ^= f(x ^ ((w as u32) << sh)) & 1;
    }
    p
}

fn validate() {
    println!("myhash spot: {:#010x} {:#010x} {:#010x}", myhash(0), myhash(1), myhash(0xDEADBEEF));
    let mut rng = Rng(0x9517_1CE5_D00D_F00D);
    // Row-32 pairs: derivative must be CONSTANT for any constants.
    for &s1 in &[30u32, 29, 24, 20, 16] {
        let s2 = 32 - s1;
        let u = 31 - s1;
        for trial in 0..4 {
            let p = [rng.u32() | 1, rng.u32(), rng.u32(), rng.u32() | 1,
                     rng.u32(), rng.u32(), rng.u32() | 1, rng.u32()];
            let f = |x: u32| sandwich(&p, s1, s2, x);
            let d0 = iter_deriv(&f, u, rng.u32());
            for _ in 0..24 {
                let d = iter_deriv(&f, u, rng.u32());
                assert_eq!(d, d0, "ROW-32 THEOREM VIOLATED s1={} trial={}", s1, trial);
            }
        }
        println!("row-32 validate s1={} s2={} u={}: derivative constant on 4 random-constant sandwiches x 25 points", s1, s2, u);
    }
    // Negative control: row-33 pairs should generically be NONconstant.
    let mut nonconst = 0;
    let mut total = 0;
    for &s1 in &[30u32, 24, 16] {
        let s2 = 33 - s1;
        let u = 31 - s1;
        for _ in 0..4 {
            let p = [rng.u32() | 1, rng.u32(), rng.u32(), rng.u32() | 1,
                     rng.u32(), rng.u32(), rng.u32() | 1, rng.u32()];
            let f = |x: u32| sandwich(&p, s1, s2, x);
            let d0 = iter_deriv(&f, u, rng.u32());
            let mut varied = false;
            for _ in 0..48 {
                if iter_deriv(&f, u, rng.u32()) != d0 {
                    varied = true;
                    break;
                }
            }
            total += 1;
            if varied {
                nonconst += 1;
            }
        }
    }
    println!("negative control (row-33): {}/{} random sandwiches show NONconstant derivative (test has teeth)", nonconst, total);
}

fn sweep() {
    // P30[r] = parity of myhash bit0 over {r, r+2^30, r+2^31, r+3*2^30}.
    const NBITS: usize = 1 << 30;
    const NBYTES: usize = NBITS / 8; // 128 MiB
    let nthreads = 8usize;
    let chunk_bytes = NBYTES / nthreads;
    let mut table = vec![0u8; NBYTES];
    thread::scope(|s| {
        for (t, chunk) in table.chunks_mut(chunk_bytes).enumerate() {
            s.spawn(move || {
                let base_bit = t * chunk_bytes * 8;
                for (i, byte) in chunk.iter_mut().enumerate() {
                    let mut b = 0u8;
                    for k in 0..8 {
                        let r = (base_bit + i * 8 + k) as u32;
                        let p = (myhash(r)
                            ^ myhash(r.wrapping_add(1 << 30))
                            ^ myhash(r.wrapping_add(1 << 31))
                            ^ myhash(r.wrapping_add(3 << 30)))
                            & 1;
                        b |= (p as u8) << k;
                    }
                    *byte = b;
                }
            });
        }
    });
    println!("P_30 built (parities over cosets of span{{2^30,2^31}}), spot P30[0..4] = {} {} {} {}",
             table[0] & 1, (table[0] >> 1) & 1, (table[0] >> 2) & 1, (table[0] >> 3) & 1);

    // fold down: P_{m-1}[r] = P_m[r] ^ P_m[r + 2^(m-1)]
    let mut m = 30usize;
    let mut cur = table;
    loop {
        // constancy check of cur (represents P_m over 2^m cosets)
        let nbytes = (1usize << m) / 8;
        let verdict = if m >= 3 {
            let first = cur[0];
            if (first == 0x00 || first == 0xFF) && cur[..nbytes].iter().all(|&b| b == first) {
                format!("CONSTANT ({})", first & 1)
            } else {
                // find witness bit differing from bit 0
                let b0 = cur[0] & 1;
                let mut wit = 0usize;
                'outer: for (i, &by) in cur[..nbytes].iter().enumerate() {
                    for k in 0..8 {
                        if (by >> k) & 1 != b0 {
                            wit = i * 8 + k;
                            break 'outer;
                        }
                    }
                }
                format!("NONCONSTANT (P[0]={} P[{}]={})", b0, wit, 1 - b0)
            }
        } else {
            let bits: Vec<u32> = (0..(1usize << m)).map(|r| ((cur[r / 8] >> (r % 8)) & 1) as u32).collect();
            if bits.iter().all(|&b| b == bits[0]) {
                format!("CONSTANT ({})", bits[0])
            } else {
                format!("NONCONSTANT ({:?})", bits)
            }
        };
        // m = s1 of the refuted pair (s1, 32-s1); m=1 -> pair (1,31)
        println!("m={:2}  pair=({},{})  parity table over cosets of span{{2^{}..2^31}}: {}", m, m, 32 - m, m, verdict);
        if m == 1 {
            break;
        }
        // fold
        let half_bits = 1usize << (m - 1);
        if half_bits >= 8 {
            let hb = half_bits / 8;
            for i in 0..hb {
                cur[i] ^= cur[i + hb];
            }
        } else {
            // sub-byte folds: operate on bits of byte 0
            let mut nb = 0u8;
            for r in 0..half_bits {
                let a = (cur[0] >> r) & 1;
                let b = (cur[0] >> (r + half_bits)) & 1;
                nb |= (a ^ b) << r;
            }
            cur[0] = nb;
        }
        m -= 1;
    }
}

fn main() {
    let mode = env::args().nth(1).unwrap_or_else(|| "validate".into());
    match mode.as_str() {
        "validate" => validate(),
        "sweep" => sweep(),
        "both" => {
            validate();
            sweep();
        }
        _ => eprintln!("usage: s9_exact [validate|sweep|both]"),
    }
}
