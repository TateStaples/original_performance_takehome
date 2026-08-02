#!/usr/bin/env python3
"""P5-I2: exact N'_myhash = #{y : myhash^{-1}(y)_0 != myhash^{-1}(y^2^31)_0}
by full-domain numpy sweep, for the MIRROR differential-count theorem
(tools/p5i_mirror.py):  N' == 0 mod 2^(33-s1) for 16<=s1,s2<=30, s1+s2>=32.
"""
import numpy as np

from p5i_myhash_diffcount import myhash_np

INV9 = np.uint32(pow(9, -1, 1 << 32))
INV33 = np.uint32(pow(33, -1, 1 << 32))
INV4097 = np.uint32(pow(4097, -1, 1 << 32))


def myhash_inv_np(y):
    v = y.astype(np.uint32)
    # S6^{-1}:  out = v ^ C ^ (v>>16)
    z = v ^ np.uint32(0xB55A4F09)
    v = z ^ (z >> np.uint32(16))
    # S5^{-1}:  out = v*9 + A
    v = (v - np.uint32(0xFD7046C5)) * INV9
    # S4^{-1}:  out = (v + A) ^ (v<<9)   -- 9-bit-block fixed point, 4 rounds
    A4 = np.uint32(0xD3A2646C)
    u = np.zeros_like(v)
    for _ in range(4):
        u = (v ^ (u << np.uint32(9))) - A4
    v = u
    # S3^{-1}:  out = v*33 + A
    v = (v - np.uint32(0x165667B1)) * INV33
    # S2^{-1}:  out = v ^ C ^ (v>>19)
    z = v ^ np.uint32(0xC761C23C)
    v = z ^ (z >> np.uint32(19))
    # S1^{-1}:  out = v*4097 + A
    v = (v - np.uint32(0x7ED55D16)) * INV4097
    return v


def main():
    probe = np.array([0, 1, 7, 0x4E005510, 0xCE005510, 0x4679814A,
                      0xFFFFFFFF, 0x12345678, 0xDEADBEEF], dtype=np.uint32)
    assert np.array_equal(myhash_inv_np(myhash_np(probe)), probe)
    rng = np.random.default_rng(5)
    r = rng.integers(0, 1 << 32, size=1 << 20, dtype=np.uint64).astype(np.uint32)
    assert np.array_equal(myhash_inv_np(myhash_np(r)), r)
    assert np.array_equal(myhash_np(myhash_inv_np(r)), r)
    print("myhash_inv round-trip on 2^20 randoms + edges: OK")

    CH = 1 << 24
    n = 0
    for base in range(0, 1 << 31, CH):
        y = (np.arange(CH, dtype=np.uint32) + np.uint32(base))
        d = (myhash_inv_np(y) ^ myhash_inv_np(y ^ np.uint32(1 << 31))) \
            & np.uint32(1)
        n += int(d.sum())
    N = 2 * n
    v2 = (N & -N).bit_length() - 1
    print(f"N'_myhash = {N} = 2^{v2} * {N >> v2}")
    print(f"v2(N'_myhash) = {v2}")
    print(f"=> pair with 16<=s1,s2<=30, s1+s2>=32 REFUTED iff 33-s1 > {v2}, "
          f"i.e. s1 <= {32 - v2}")


if __name__ == "__main__":
    main()
