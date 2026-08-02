#!/usr/bin/env python3
"""P5-I2: exact N_myhash = #{x in Z_2^32 : myhash_0(x) != myhash_0(x^2^31)}
by full-domain numpy sweep, plus the pairs it refutes via the top-bit
differential count theorem (tools/p5i_diffcount.py).
"""
import numpy as np

M32 = np.uint32(0xFFFFFFFF)


def myhash_np(v):
    v = v.astype(np.uint32)
    v = (v + np.uint32(0x7ED55D16)) + (v << np.uint32(12))
    v = (v ^ np.uint32(0xC761C23C)) ^ (v >> np.uint32(19))
    v = (v + np.uint32(0x165667B1)) + (v << np.uint32(5))
    v = (v + np.uint32(0xD3A2646C)) ^ (v << np.uint32(9))
    v = (v + np.uint32(0xFD7046C5)) + (v << np.uint32(3))
    v = (v ^ np.uint32(0xB55A4F09)) ^ (v >> np.uint32(16))
    return v


def main():
    # cross-check against the scalar reference used by the z3 tools
    from p5i_z3pair import myhash
    probe = np.array([0, 1, 0x4E005510, 0xCE005510, 0x4679814A, 0xFFFFFFFF,
                      0x12345678], dtype=np.uint32)
    ref = np.array([myhash(int(p)) for p in probe], dtype=np.uint32)
    assert np.array_equal(myhash_np(probe), ref), "numpy myhash mismatch"
    print("myhash numpy/scalar cross-check: OK")

    CH = 1 << 24
    n = 0
    for base in range(0, 1 << 31, CH):
        x = (np.arange(CH, dtype=np.uint32) + np.uint32(base))
        d = (myhash_np(x) ^ myhash_np(x ^ np.uint32(1 << 31))) & np.uint32(1)
        n += int(d.sum())
    N = 2 * n  # x and x^2^31 both counted over the full domain
    v2 = (N & -N).bit_length() - 1
    print(f"N_myhash = {N} = 2^{v2} * {N >> v2}   (2^32 = {1<<32})")
    print(f"2-adic valuation v2(N_myhash) = {v2}")
    print(f"=> pair (s1,s2) with 1<=s1<=30, 1<=s2<=30, s1+s2>=32 is REFUTED "
          f"iff 33-s2 > {v2}, i.e. s2 <= {32 - v2}")


if __name__ == "__main__":
    main()
