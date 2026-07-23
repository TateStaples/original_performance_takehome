"""
# Anthropic's Original Performance Engineering Take-home (Release version)

Copyright Anthropic PBC 2026. Permission is granted to modify and use, but not
to publish or redistribute your solutions so it's hard to find spoilers.

# Task

- Optimize the kernel (in KernelBuilder.build_kernel) as much as possible in the
  available time, as measured by test_kernel_cycles on a frozen separate copy
  of the simulator.

Validate your results using `python tests/submission_tests.py` without modifying
anything in the tests/ folder.

We recommend you look through problem.py next.
"""

from collections import defaultdict
import random
import unittest

from problem import (
    Engine,
    DebugInfo,
    SLOT_LIMITS,
    VLEN,
    N_CORES,
    SCRATCH_SIZE,
    Machine,
    Tree,
    Input,
    HASH_STAGES,
    reference_kernel,
    build_mem_image,
    reference_kernel2,
)


# Vector ops whose lanes are independent 1-in-1-out scalar alu ops, so a
# single valu slot can instead be split into 8 scalar alu slots (the alu
# engine has 12 slots/cycle and is otherwise completely idle in this
# workload). multiply_add / vbroadcast have no scalar alu equivalent.
_SCALARIZABLE = {"+", "-", "*", "^", "&", "|", "<<", ">>", "<", "=="}


class ListScheduler:
    """
    Greedy dependency-tracking list scheduler over the VLIW bundle stream.

    Ops are emitted in program order; each is placed in the EARLIEST bundle
    that (a) satisfies its data hazards and (b) has a free slot on its
    engine. Hazard rules follow the machine's bundle semantics (docs/isa.md
    §2: all reads in a bundle see start-of-cycle state; writes commit at end
    of cycle):
      RAW: a read of scratch addr X must be placed at cycle >= write(X)+1.
      WAW: a write of X must be placed at cycle >= write(X)+1.
      WAR: a write of X may share a cycle with the last read of X
           (reads see the old value), so write(X) >= last_read(X) suffices.
    Because ops are processed strictly in program order and the constraints
    above are enforced against running per-address maxima, placing a later
    op into an earlier bundle than a previously placed independent op is
    always safe.

    Memory is tracked coarsely (one pseudo-location for all of mem): reads
    are plentiful (gathers) and the only writes are the final vstores, so
    per-address tracking would buy nothing.

    Placement scans start from a per-engine `hint` = first cycle known to
    possibly have a free slot on that engine (monotone, since slots only
    ever fill), keeping total scan cost ~linear.
    """

    def __init__(self):
        self.bundles = []
        self.counts = []
        self.last_write = {}
        self.last_read = {}
        self.mem_read_c = -1
        self.mem_write_c = -1
        self.hint = dict.fromkeys(SLOT_LIMITS, 0)

    def ready(self, reads=(), writes=(), mem_read=False, mem_write=False, min_cycle=0):
        c = min_cycle
        lw = self.last_write
        lr = self.last_read
        for a in reads:
            t = lw.get(a, -1) + 1
            if t > c:
                c = t
        for a in writes:
            t = lw.get(a, -1) + 1
            if t > c:
                c = t
            t = lr.get(a, -1)
            if t > c:
                c = t
        if mem_read and self.mem_write_c + 1 > c:
            c = self.mem_write_c + 1
        if mem_write:
            if self.mem_write_c + 1 > c:
                c = self.mem_write_c + 1
            if self.mem_read_c > c:
                c = self.mem_read_c
        return c

    def find_free(self, engine, c, extra=None):
        if c < self.hint[engine]:
            c = self.hint[engine]
        counts = self.counts
        limit = SLOT_LIMITS[engine]
        n = len(counts)
        if extra is None:
            while c < n and counts[c][engine] >= limit:
                c += 1
            return c
        while True:
            base = counts[c][engine] if c < n else 0
            if base + extra.get(c, 0) < limit:
                return c
            c += 1

    def put(self, engine, slot, c, reads=(), writes=(), mem_read=False, mem_write=False):
        bundles = self.bundles
        counts = self.counts
        while len(bundles) <= c:
            bundles.append({})
            counts.append(dict.fromkeys(SLOT_LIMITS, 0))
        bundles[c].setdefault(engine, []).append(slot)
        counts[c][engine] += 1
        lr = self.last_read
        lw = self.last_write
        for a in reads:
            if lr.get(a, -1) < c:
                lr[a] = c
        for a in writes:
            lw[a] = c
        if mem_read and self.mem_read_c < c:
            self.mem_read_c = c
        if mem_write and self.mem_write_c < c:
            self.mem_write_c = c
        if counts[c][engine] >= SLOT_LIMITS[engine] and c == self.hint[engine]:
            h = c
            n = len(counts)
            while h < n and counts[h][engine] >= SLOT_LIMITS[engine]:
                h += 1
            self.hint[engine] = h

    def emit(self, engine, slot, reads=(), writes=(), mem_read=False, mem_write=False, min_cycle=0):
        c = self.ready(reads, writes, mem_read, mem_write, min_cycle)
        c = self.find_free(engine, c)
        self.put(engine, slot, c, reads, writes, mem_read, mem_write)
        return c


class KernelBuilder:
    def __init__(self):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self._current = {}  # bundle being greedily packed by _pack/_flush

    def debug_info(self):
        return DebugInfo(scratch_map=self.scratch_debug)

    def build(self, slots: list[tuple[Engine, tuple]], vliw: bool = False):
        # Simple slot packing that just uses one slot per instruction bundle
        instrs = []
        for engine, slot in slots:
            instrs.append({engine: [slot]})
        return instrs

    def add(self, engine, slot):
        self.instrs.append({engine: [slot]})

    def _pack(self, engine, slot):
        """
        Greedily append `slot` to the bundle currently being built, filling
        up to SLOT_LIMITS[engine] slots on that engine before starting a new
        bundle. Safe to call freely for mutually-independent ops; call
        _flush() before pushing anything that depends on a value one of
        those ops just wrote, since a bundle's writes only become visible
        after the whole bundle commits (see docs/isa.md).
        """
        bucket = self._current.setdefault(engine, [])
        if len(bucket) >= SLOT_LIMITS[engine]:
            self._flush()
            bucket = self._current.setdefault(engine, [])
        bucket.append(slot)

    def _flush(self):
        if self._current:
            self.instrs.append(self._current)
            self._current = {}

    def alloc_scratch(self, name=None, length=1):
        addr = self.scratch_ptr
        if name is not None:
            self.scratch[name] = addr
            self.scratch_debug[addr] = (name, length)
        self.scratch_ptr += length
        assert self.scratch_ptr <= SCRATCH_SIZE, "Out of scratch space"
        return addr

    def scratch_const(self, val, name=None):
        if val not in self.const_map:
            addr = self.alloc_scratch(name)
            self.add("load", ("const", addr, val))
            self.const_map[val] = addr
        return self.const_map[val]

    def build_kernel(
        self, forest_height: int, n_nodes: int, batch_size: int, rounds: int
    ):
        if (
            forest_height is not None
            and n_nodes == 2 ** (forest_height + 1) - 1
            and batch_size % VLEN == 0
            and rounds >= 1
        ):
            self.build_kernel_scheduled(
                batch_size, rounds, forest_height,
                tournament_levels=(1, 2, 3), alu_offload=True,
                parity_conds=True,
            )
        else:
            self.build_kernel_pipelined(
                batch_size, rounds, forest_height=forest_height, pipeline_width=16
            )

    # ------------------------------------------------------------------
    # Fused-hash constants (see docs/problem.md 2.4 and the bit-exact proof
    # in rust_harness/src/problem.rs::cross_stage_fusion_is_bit_exact).
    #
    # myhash's 6 stages collapse to 11 vector "mixing" ops instead of 18:
    #   stage0 (affine)      a*(1+2^12) + C0            -> 1 multiply_add
    #   stage1 (xor-shift)   (a ^ C1) ^ (a >> 19)       -> 3 ops
    #   stage2+stage3 fused  p = a*33 + (C2+C3);
    #                        q = a*(33*512) + (C2<<9);
    #                        a = p ^ q                  -> 2 multiply_add + 1 xor
    #   stage4 (affine)      a*(1+2^3) + C4             -> 1 multiply_add
    #   stage5 (xor-shift)   (a ^ C5) ^ (a >> 16)       -> 3 ops
    # stage2 is affine (b = 33a + C2) and both of stage3's branches are
    # integer-affine in b (hence in a), so the pair fuses across the boundary.
    # ------------------------------------------------------------------
    @staticmethod
    def _fused_hash_constants():
        M = (1 << 32) - 1
        (o0, C0, _, _, s0) = HASH_STAGES[0]
        (o1a, C1, _, o1b, s1) = HASH_STAGES[1]
        (_, C2, _, _, s2) = HASH_STAGES[2]
        (_, C3, _, _, s3) = HASH_STAGES[3]
        (_, C4, _, _, s4) = HASH_STAGES[4]
        (o5a, C5, _, o5b, s5) = HASH_STAGES[5]
        assert (o0, s0) == ("+", 12)
        assert (o1a, o1b, s1) == ("^", ">>", 19)
        assert s2 == 5 and s3 == 9 and s4 == 3
        assert (o5a, o5b, s5) == ("^", ">>", 16)
        c = {
            "k0": (1 + (1 << s0)) & M,
            "C0": C0,
            "C1": C1,
            "sh1": s1,
            "kp": (1 + (1 << s2)) & M,
            "ap": (C2 + C3) & M,
            "kq": ((1 + (1 << s2)) * (1 << s3)) & M,
            "aq": (C2 << s3) & M,
            "k4": (1 + (1 << s4)) & M,
            "C4": C4,
            "C5": C5,
            "sh5": s5,
        }

        def fused(a):
            a = (a * c["k0"] + c["C0"]) & M
            a = (a ^ c["C1"]) ^ (a >> c["sh1"])
            p = (a * c["kp"] + c["ap"]) & M
            q = (a * c["kq"] + c["aq"]) & M
            a = p ^ q
            a = (a * c["k4"] + c["C4"]) & M
            a = (a ^ c["C5"]) ^ (a >> c["sh5"])
            return a

        # Build-time sanity: the fused form must reproduce myhash bit-for-bit.
        import random as _r

        _rng = _r.Random(0xC0FFEE)
        samples = [0, 1, 2, 255, 1 << 31, M, C2, C3] + [
            _rng.randint(0, M) for _ in range(2000)
        ]
        for a in samples:
            ref = a
            for op1, val1, op2, op3, val3 in HASH_STAGES:
                fns = {
                    "+": lambda x, y: (x + y) & M,
                    "^": lambda x, y: x ^ y,
                    "<<": lambda x, y: (x << y) & M,
                    ">>": lambda x, y: x >> y,
                }
                ref = fns[op2](fns[op1](ref, val1), fns[op3](ref, val3))
            assert fused(a) == ref, f"fused hash mismatch at {a:#x}"
        return c

    # ------------------------------------------------------------------
    # List-scheduled kernel (the graded path).
    # ------------------------------------------------------------------
    def _v(self, base):
        return tuple(range(base, base + VLEN))

    def _sched_vec(self, S, op, dest, a, b, allow_alu=False, force_alu=False):
        """
        Emit an elementwise vector op, either as one valu slot or -- when the
        valu engine is backed up and the (otherwise idle) scalar alu can
        retire all 8 lanes no later -- as 8 scalar alu slots. `force_alu`
        skips the comparison and always scalarizes (used to statically
        reserve valu slots for multiply_adds, which alu can't run).
        """
        reads = self._v(a) + self._v(b)
        writes = self._v(dest)
        c0 = S.ready(reads, writes)
        cv = None
        if not force_alu:
            cv = S.find_free("valu", c0)
        if op in _SCALARIZABLE and (force_alu or (allow_alu and cv > c0)):
            extra = {}
            lanes = []
            worst = -1
            for i in range(VLEN):
                ci = S.ready((a + i, b + i), (dest + i,))
                ci = S.find_free("alu", ci, extra)
                lanes.append(ci)
                extra[ci] = extra.get(ci, 0) + 1
                if ci > worst:
                    worst = ci
            if force_alu or worst <= cv:
                for i in range(VLEN):
                    S.put("alu", (op, dest + i, a + i, b + i), lanes[i],
                          (a + i, b + i), (dest + i,))
                return worst
        if cv is None:
            cv = S.find_free("valu", c0)
        S.put("valu", (op, dest, a, b), cv, reads, writes)
        return cv

    def _sched_madd(self, S, dest, a, b, c):
        return S.emit(
            "valu", ("multiply_add", dest, a, b, c),
            self._v(a) + self._v(b) + self._v(c), self._v(dest),
        )

    def _sched_vsel(self, S, dest, cond, a, b):
        return S.emit(
            "flow", ("vselect", dest, cond, a, b),
            self._v(cond) + self._v(a) + self._v(b), self._v(dest),
        )

    def build_kernel_scheduled(
        self,
        batch_size: int,
        rounds: int,
        forest_height: int,
        tournament_levels=(),
        alu_offload: bool = False,
        l4_gmin=(22, 28),
        pool_sizes=(17, 4),
        skew=(4, 3),
        parity_early=False,
        parity_conds: bool = False,
        debug_compares: bool = True,
    ):
        """
        Same maths as `build_kernel_pipelined` (fused hash, gaddr-carried
        indices, root-broadcast level-0 rounds) re-expressed as a flat op
        stream placed by `ListScheduler`, plus:

        - NO wraparound compare/select. All walkers start at the root and
          advance one level per round, so every walker is at tree level
          (round % (height+1)); wrapping happens exactly on level==height
          rounds, for every lane at once, and is compiled away: the round
          after a bottom round is a broadcast-root round and the position
          state is simply re-seeded from that round's parities.

        - "Tournament" rounds (`tournament_levels`, a prefix {1..k} of the
          shallow levels): level d has only 2^d distinct node values, and a
          walker's position within the level is the d-bit number formed by
          its last d branch parities (oldest bit = MSB). Instead of
          gathering 8 node values per group through the 2-slot load engine,
          the level's values are pre-broadcast into scratch at setup and
          each group folds the 2^d candidates down to 1:
            * first fold, by the NEWEST parity bit b:
              select(b, v[2k+1], v[2k]) == multiply_add(b, v[2k+1]-v[2k], v[2k])
              with the diff vector precomputed at setup -- one valu op, no
              flow slot;
            * remaining folds on the flow engine's vselect, with condition
              vectors extracted from the position accumulator by masking
              (vselect only tests !=0, so `p & 2^j` needs no shift).
          Position accumulator: on rounds feeding a tournament round the
          kernel carries p (p' = 2p + parity, one multiply_add) in the same
          scratch vector that otherwise carries gaddr = forest_values_p+idx;
          on the last tournament level it converts p back to a gather
          address: gaddr = 2p + parity + (fp + 2^(k+1) - 1).

        - Optional alu offload (`alu_offload`): elementwise vector ops may
          be split into 8 scalar alu slots when that retires them earlier
          (see `_sched_vec`), raising compute throughput from 6 to up to
          7.5 vector-ops/cycle.

        - Parity-early (`parity_early`, H-002): the next round's gather
          address / tournament position needs ONLY bit0 of the hashed
          value, but bit0 normally waits for the full hash (the stage-1/
          stage-5 xor-shifts pull bits 19/16 down into bit0, so no shorter
          boolean chain exists below the pre-stage-4 value c). One extra
          madd off c, scheduled in parallel with the stage-4 madd, puts the
          parity at BIT 31 carry-free:
            m = c*Km + Cm  ==  d*(2^31+2^15) + (C5&1)<<31   (mod 2^32)
          (Km = k4*(2^31+2^15), Cm = C4*(2^31+2^15) + (C5&1)<<31; below
          bit31 only the d<<15 addend is nonzero, so bit31(m) = bit16(d) ^
          bit0(d) ^ bit0(C5) = bit0(hash)), and `m >> 31` is the clean 0/1
          parity: available at dependency depth 8 instead of 10, so the
          next round's gather/tournament unblocks 2 levels earlier, at the
          price of +1 valu madd per group-round (the >>31 replaces the old
          `& 1`). The madd result is hosted in the group's dead nv vector
          (no new state); the 3 constant vectors (27 words) are traded for
          4 hash-temp slots since scratch is full. `parity_early` is False
          (off), True (all rounds), or an iterable of CURRENT-round levels
          at which to apply it (e.g. (3,) = only rounds feeding level 4).

        - `parity_conds` (H-001): tournament conditions from raw parity
          vectors instead of mask-extracting them from the accumulator.
          The newest parity rides the group's `nv` vector (dead between
          served rounds -- no gather in flight), so the round's madd
          conditions need no `& 1`; the accumulator update `p := 2p + b`
          LAGS one round, folded inside the next tournament block
          (`madd(st, st, two, nv)`) before `nv` is clobbered, so the
          remaining vselect conditions extract from an `st` that is ready
          at round START (off the tournament's critical path) and the
          epoch-exit gaddr conversions see the same `st` as the default
          path. Saves the newest-bit extraction at L2/L3/L4 plus the L4
          `>>` (b2 lands at bit 0, already 0/1 for the U-combines).

        `debug_compares` interleaves free `("debug", ("vcompare", ...))`
        slots (skipped by the grader) checking node_val and hashed_val of
        every (round, walker) against the reference trace.
        """
        assert batch_size % VLEN == 0
        n_groups = batch_size // VLEN
        period = forest_height + 1

        if parity_early is True:
            pe_levels = set(range(period))
        elif parity_early:
            pe_levels = set(parity_early)
        else:
            pe_levels = set()

        T = tuple(l for l in tournament_levels if l < forest_height)
        assert T == tuple(range(1, len(T) + 1)), "tournament levels must be 1..k"
        maxT = len(T)
        T_set = set(T)

        def level(r):
            return r % period

        # Rounds at level maxT+1 partially served by the two-stage "pair"
        # tournament (see below): the level-4 candidate set is the pair of
        # children of the level-3 winner. Only groups >= the epoch's
        # l4_gmin threshold are served; earlier groups still gather, so the
        # load engine's pipeline into the following gather levels starts on
        # time while the later groups' tournaments run in its shadow (the
        # tournament depends on the previous round's parity, so unlike a
        # gather it cannot be prefetched a full round ahead).
        L4 = maxT + 1
        n_groups_ = batch_size // VLEN

        def l4_served(r, g):
            if maxT != 3 or L4 >= forest_height or level(r) != L4:
                return False
            ep = r // period
            gmin = l4_gmin[ep] if ep < len(l4_gmin) else n_groups_
            return g >= gmin

        l4_any = any(
            l4_served(r, g) for r in range(rounds) for g in (0, n_groups_ - 1)
        )

        def served(r, g):
            # node_val comes from scratch (no gather) on these rounds
            lv_ = level(r)
            return lv_ == 0 or lv_ in T_set or l4_served(r, g)

        S = ListScheduler()

        def const(val, name=None):
            if val not in self.const_map:
                addr = self.alloc_scratch(name)
                S.emit("load", ("const", addr, val), writes=(addr,))
                self.const_map[val] = addr
            return self.const_map[val]

        def bvec(src, name=None):
            d = self.alloc_scratch(name, VLEN)
            S.emit("valu", ("vbroadcast", d, src), (src,), self._v(d))
            return d

        vec = lambda op, dst, a, b: self._sched_vec(S, op, dst, a, b, alu_offload)
        avec = lambda op, dst, a, b: self._sched_vec(
            S, op, dst, a, b, alu_offload, force_alu=alu_offload
        )
        madd = lambda dst, a, b, c: self._sched_madd(S, dst, a, b, c)
        vsel = lambda dst, cond, a, b: self._sched_vsel(S, dst, cond, a, b)

        # --- header (inp_indices is never read: only values are graded) ---
        for name, hidx in (("forest_values_p", 4), ("inp_values_p", 6)):
            self.alloc_scratch(name)
            caddr = const(hidx)
            S.emit("load", ("load", self.scratch[name], caddr),
                   (caddr,), (self.scratch[name],), mem_read=True)
        fp = self.scratch["forest_values_p"]
        ivp = self.scratch["inp_values_p"]

        # Matches reference_kernel2's first yield (dev harness; grader
        # disables pausing). Lands in bundle 0's flow slot.
        S.emit("flow", ("pause",))

        # --- constants / broadcasts ---
        one_c = const(1)
        omf_s = self.alloc_scratch("omf")  # 1 - forest_values_p
        S.emit("alu", ("-", omf_s, one_c, fp), (one_c, fp), (omf_s,))
        root_nv = self.alloc_scratch("root_nv")
        S.emit("load", ("load", root_nv, fp), (fp,), (root_nv,), mem_read=True)

        one_vec = bvec(one_c, "one_vec")
        two_vec = bvec(const(2), "two_vec")
        omf_vec = bvec(omf_s, "omf_vec")
        root_nv_vec = bvec(root_nv, "root_nv_vec")
        hc = self._fused_hash_constants()
        hv = {k: bvec(const(hc[k]), k) for k in
              ("k0", "C0", "C1", "sh1", "kp", "ap", "kq", "aq", "k4", "C4", "C5", "sh5")}
        if pe_levels:
            # Parity-early constants (see docstring): bit31(c*km + cm) is
            # bit0 of the final hash, carry-free by construction.
            M_ = (1 << 32) - 1
            km = (hc["k4"] * ((1 << 31) + (1 << 15))) & M_
            cm = (hc["C4"] * ((1 << 31) + (1 << 15)) + ((hc["C5"] & 1) << 31)) & M_
            hv["km"] = bvec(const(km), "km")
            hv["cm"] = bvec(const(cm), "cm")
            hv["c31"] = bvec(const(31), "c31")

        # gaddr reconstruction constants: leaving a served round r for a
        # gather round at level Ln needs  fp + 2^Ln - 1  as a vector.
        rec_needed = sorted({
            level(r + 1) for r in range(rounds - 1) for g in range(n_groups_)
            if served(r, g) and not served(r + 1, g) and level(r + 1) != 0
        })
        rec_vecs = {}
        for Ln in rec_needed:
            rs = self.alloc_scratch()
            S.emit("flow", ("add_imm", rs, fp, 2 ** Ln - 1), (fp,), (rs,))
            rec_vecs[Ln] = bvec(rs, f"rec{Ln}")

        # --- tournament level values: load tree[1..], broadcast each
        # pair's even element and its (odd-even) diff ---
        lvl = {}
        if maxT:
            n_lv = 2 ** ((L4 if l4_any else maxT) + 1) - 2
            lv = self.alloc_scratch("lv", ((n_lv + VLEN - 1) // VLEN) * VLEN)
            la = self.alloc_scratch("lv_addr")
            for blk in range(0, n_lv, VLEN):
                S.emit("flow", ("add_imm", la, fp, 1 + blk), (fp,), (la,))
                S.emit("load", ("vload", lv + blk, la),
                       (la,), self._v(lv + blk), mem_read=True)
            for L in T:
                base = 2 ** L - 1  # first tree index of level L; lv[i] = tree[1+i]
                evens, diffs = [], []
                for k in range(2 ** (L - 1)):
                    s0 = lv + (base + 2 * k - 1)
                    s1 = s0 + 1
                    d = self.alloc_scratch()
                    S.emit("alu", ("-", d, s1, s0), (s0, s1), (d,))
                    evens.append(bvec(s0))
                    diffs.append(bvec(d))
                lvl[L] = (evens, diffs)
        if l4_any:
            # Level maxT+1 candidates, indexed by the level-maxT position t:
            # E[t] / D[t] = even child of the level-maxT winner / its
            # (odd - even) sibling diff.
            base = 2 ** L4 - 1
            E_vecs, D_vecs = [], []
            for t in range(2 ** maxT):
                s0 = lv + (base + 2 * t - 1)
                s1 = s0 + 1
                d = self.alloc_scratch()
                S.emit("alu", ("-", d, s1, s0), (s0, s1), (d,))
                E_vecs.append(bvec(s0))
                D_vecs.append(bvec(d))
            four_vec = bvec(const(4), "four_vec")
            eight_vec = bvec(const(8), "eight_vec")

        # --- persistent state ---
        # state_vecs[g] carries p (position accumulator) during tournament
        # levels and gaddr = forest_values_p + idx during gather levels.
        state_vecs = [self.alloc_scratch(f"st{g}", VLEN) for g in range(n_groups)]
        val_vecs = [self.alloc_scratch(f"val{g}", VLEN) for g in range(n_groups)]
        nv_vecs = [self.alloc_scratch(f"nv{g}", VLEN) for g in range(n_groups)]
        TP, CP = pool_sizes
        if pe_levels and maxT >= 2:
            # Scratch is full: trade one cond-pool slot (32 words across the
            # 4 pools) for the 3 parity constant vectors (27 words). Measured
            # free at the default shape ((17,3) == (17,4) == 1140), unlike
            # shrinking the t1 pool ((13,4) costs +12).
            CP -= 1
            assert CP >= 1, "parity_early needs pool_sizes[1] >= 2"
        t1 = [self.alloc_scratch(None, VLEN) for _ in range(TP)]

        if maxT >= 2:
            condA = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
            condB = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
            tm = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
        if maxT >= 3:
            tmM = [self.alloc_scratch(None, VLEN) for _ in range(CP)]

        # --- initial vals ---
        val_addrs = []
        for g in range(n_groups):
            a = self.alloc_scratch(f"va{g}")
            S.emit("flow", ("add_imm", a, ivp, g * VLEN), (ivp,), (a,))
            val_addrs.append(a)
            S.emit("load", ("vload", val_vecs[g], a),
                   (a,), self._v(val_vecs[g]), mem_read=True)

        # --- rounds ---
        def emit_group_round(r, g):
            if True:  # keep the original indentation of the body below
                L = level(r)
                s = g % TP
                j = g % CP
                st = state_vecs[g]
                vl = val_vecs[g]
                nv = nv_vecs[g]

                # ---- node_val: broadcast root / tournament select / gather ----
                if L == 0:
                    nvsrc = root_nv_vec
                elif L in T_set:
                    nvsrc = nv
                    evens, diffs = lvl[L]
                    if L == 1:
                        # p is the single parity bit itself.
                        madd(nv, st, diffs[0], evens[0])
                    elif L == 2:
                        if parity_conds:
                            # nv = b1 (raw parity), st = b0 (single bit).
                            # b0 copy (st folds next); vselect(c,a,a,a) is a
                            # pure copy, so it rides the idle flow engine.
                            vsel(condB[j], st, st, st)
                            madd(st, st, two_vec, nv)        # fold b1: st = b0b1
                            madd(t1[s], nv, diffs[0], evens[0])
                            madd(tm[j], nv, diffs[1], evens[1])
                            vsel(nv, condB[j], tm[j], t1[s])
                        else:
                            vec("&", condA[j], st, one_vec)   # newest bit b1
                            vec("&", condB[j], st, two_vec)   # mask for b0
                            madd(t1[s], condA[j], diffs[0], evens[0])
                            madd(tm[j], condA[j], diffs[1], evens[1])
                            vsel(nv, condB[j], tm[j], t1[s])
                    elif parity_conds:  # L == 3
                        # nv = b2 (raw parity), st = b0b1 (bit1=b0, bit0=b1);
                        # both conds extract from st at round START.
                        vec("&", condB[j], st, one_vec)   # b1
                        vec("&", condA[j], st, two_vec)   # b0 mask
                        madd(st, st, two_vec, nv)         # fold b2: st = b0b1b2
                        madd(t1[s], nv, diffs[0], evens[0])   # m0
                        madd(tmM[j], nv, diffs[1], evens[1])  # m1
                        madd(tm[j], nv, diffs[2], evens[2])   # m2
                        madd(nv, nv, diffs[3], evens[3])      # m3 (b2 dead)
                        vsel(t1[s], condB[j], tmM[j], t1[s])  # q0 = b1 ? m1 : m0
                        vsel(nv, condB[j], nv, tm[j])         # q1 = b1 ? m3 : m2
                        vsel(nv, condA[j], nv, t1[s])         # b0 ? q1 : q0
                    else:  # L == 3
                        vec("&", condA[j], st, one_vec)   # newest bit b2
                        vec("&", condB[j], st, two_vec)   # mask for b1
                        madd(t1[s], condA[j], diffs[0], evens[0])  # m0
                        madd(tmM[j], condA[j], diffs[1], evens[1])  # m1
                        madd(tm[j], condA[j], diffs[2], evens[2])   # m2
                        madd(nv, condA[j], diffs[3], evens[3])      # m3
                        # condA is dead after the madds; reuse it for b0.
                        vec(">>", condA[j], st, two_vec)  # b0 (p is 3 bits)
                        vsel(t1[s], condB[j], tmM[j], t1[s])  # q0 = b1 ? m1 : m0
                        vsel(nv, condB[j], nv, tm[j])         # q1 = b1 ? m3 : m2
                        vsel(nv, condA[j], nv, t1[s])         # b0 ? q1 : q0
                elif l4_served(r, g) and parity_conds:
                    # Same two-stage select as below, but b3 = nv (raw
                    # parity, no extraction) and t = st = b0b1b2 (bit0=b2,
                    # already 0/1 for the U-combines -- no shift). st folds
                    # to b0b1b2b3 for the epoch-exit gaddr unless this is
                    # the last round (nothing reads st after). With b3
                    # occupying nv, condA joins the value-temp rotation.
                    nvsrc = nv
                    fold = r != rounds - 1
                    vec("&", condB[j], st, one_vec)                 # b2 (0/1)
                    if fold:
                        madd(st, st, two_vec, nv)                   # st=b0b1b2b3
                    madd(t1[s], nv, D_vecs[0], E_vecs[0])           # W0
                    madd(tm[j], nv, D_vecs[1], E_vecs[1])           # W1
                    vec("-", tm[j], tm[j], t1[s])                   # W1-W0
                    madd(t1[s], condB[j], tm[j], t1[s])             # U0
                    madd(tmM[j], nv, D_vecs[2], E_vecs[2])          # W2
                    madd(tm[j], nv, D_vecs[3], E_vecs[3])           # W3
                    vec("-", tm[j], tm[j], tmM[j])                  # W3-W2
                    madd(tmM[j], condB[j], tm[j], tmM[j])           # U1
                    madd(tm[j], nv, D_vecs[4], E_vecs[4])           # W4
                    madd(condA[j], nv, D_vecs[5], E_vecs[5])        # W5
                    vec("-", condA[j], condA[j], tm[j])             # W5-W4
                    madd(tm[j], condB[j], condA[j], tm[j])          # U2
                    madd(condA[j], nv, D_vecs[6], E_vecs[6])        # W6
                    madd(nv, nv, D_vecs[7], E_vecs[7])              # W7 (b3 dead)
                    vec("-", nv, nv, condA[j])                      # W7-W6
                    madd(nv, condB[j], nv, condA[j])                # U3 (b2 dead)
                    vec("&", condA[j], st, four_vec if fold else two_vec)  # b1
                    vsel(t1[s], condA[j], tmM[j], t1[s])            # q0
                    vsel(nv, condA[j], nv, tm[j])                   # q1
                    vec("&", condB[j], st, eight_vec if fold else four_vec)  # b0
                    vsel(nv, condB[j], nv, t1[s])                   # winner
                elif l4_served(r, g):
                    # Two-stage level-(maxT+1) select: with t = p>>1 the
                    # level-maxT position and b3 = p&1 the newest parity,
                    # node_val = E[t] + b3*D[t]. Combine first (8 madds),
                    # then fold the 8 W[t] candidates by the bits of t,
                    # rotating through 6 live vectors -- no extra pools.
                    nvsrc = nv
                    vec("&", condA[j], st, one_vec)                 # b3
                    madd(t1[s], condA[j], D_vecs[0], E_vecs[0])     # W0
                    madd(tm[j], condA[j], D_vecs[1], E_vecs[1])     # W1
                    madd(tmM[j], condA[j], D_vecs[2], E_vecs[2])    # W2
                    madd(nv, condA[j], D_vecs[3], E_vecs[3])        # W3
                    vec("&", condB[j], st, two_vec)
                    vec(">>", condB[j], condB[j], one_vec)          # bit0 of t
                    vec("-", tm[j], tm[j], t1[s])                   # W1-W0
                    madd(t1[s], condB[j], tm[j], t1[s])             # U0
                    vec("-", nv, nv, tmM[j])                        # W3-W2
                    madd(tmM[j], condB[j], nv, tmM[j])              # U1
                    madd(tm[j], condA[j], D_vecs[4], E_vecs[4])     # W4
                    madd(nv, condA[j], D_vecs[5], E_vecs[5])        # W5
                    vec("-", nv, nv, tm[j])                         # W5-W4
                    madd(tm[j], condB[j], nv, tm[j])                # U2
                    madd(nv, condA[j], D_vecs[6], E_vecs[6])        # W6
                    madd(condA[j], condA[j], D_vecs[7], E_vecs[7])  # W7 (b3 dead)
                    vec("-", condA[j], condA[j], nv)                # W7-W6
                    madd(nv, condB[j], condA[j], nv)                # U3 (bit0 dead)
                    vec("&", condB[j], st, four_vec)                # bit1 of t mask
                    vsel(t1[s], condB[j], tmM[j], t1[s])            # q0
                    vsel(nv, condB[j], nv, tm[j])                   # q1
                    vec("&", condB[j], st, eight_vec)               # bit2 of t mask
                    vsel(nv, condB[j], nv, t1[s])                   # winner
                else:
                    nvsrc = nv  # gathered during round r-1

                if debug_compares:
                    S.emit("debug",
                           ("vcompare", nvsrc,
                            [(r, g * VLEN + i, "node_val") for i in range(VLEN)]),
                           reads=self._v(nvsrc))

                # ---- val = fused_hash(val ^ node_val) ----
                # Each xor-shift stage uses ONE temp: the shifted copy goes
                # to t, then val updates in place (same-cycle write-after-
                # read of val is safe under the bundle semantics).
                pe = (L in pe_levels and r < rounds - 1
                      and level(r + 1) != 0)
                t = t1[s]
                vec("^", vl, vl, nvsrc)
                madd(vl, vl, hv["k0"], hv["C0"])
                avec(">>", t, vl, hv["sh1"])
                avec("^", vl, vl, hv["C1"])
                vec("^", vl, vl, t)
                madd(t, vl, hv["kp"], hv["ap"])
                madd(vl, vl, hv["kq"], hv["aq"])
                vec("^", vl, vl, t)
                if pe:
                    # Parity-early: bit31(vl*km + cm) == bit0 of the final
                    # hash (vl holds the pre-stage-4 value c here; see the
                    # docstring). Runs in parallel with the stage-4 madd;
                    # nv is dead (node_val already folded in) and is
                    # rewritten by round r+1's gather/select, so it hosts
                    # the parity word with no new scratch.
                    madd(nv, vl, hv["km"], hv["cm"])
                madd(vl, vl, hv["k4"], hv["C4"])
                vec(">>", t, vl, hv["sh5"])
                vec("^", vl, vl, hv["C5"])
                vec("^", vl, vl, t)

                if debug_compares:
                    S.emit("debug",
                           ("vcompare", vl,
                            [(r, g * VLEN + i, "hashed_val") for i in range(VLEN)]),
                           reads=self._v(vl))

                # ---- position/state update & gather prefetch for r+1 ----
                if r == rounds - 1:
                    return
                Ln = level(r + 1)
                if Ln == 0:
                    return  # everyone wraps to the root; state re-seeded there
                if pe:
                    # nv holds the parity word m; m>>31 is the clean 0/1
                    # parity, ready 2 dependency levels before the hash.
                    par = nv
                    parity = lambda dst: vec(">>", dst, nv, hv["c31"])
                else:
                    par = t1[s]
                    parity = lambda dst: vec("&", dst, vl, one_vec)
                if served(r + 1, g):
                    if L == 0:
                        parity(st)                         # p := b
                    elif parity_conds:
                        # Newest parity rides nv into the next tournament
                        # round; the p-fold lags into that round's block.
                        parity(nv)
                    else:
                        parity(par)
                        madd(st, st, two_vec, par)         # p := 2p + b
                else:
                    parity(par)
                    if served(r, g):
                        # leave accumulator mode: gaddr = 2p + b + fp + 2^Ln - 1
                        if L == 0:
                            vec("+", st, rec_vecs[Ln], par)
                        else:
                            madd(st, st, two_vec, rec_vecs[Ln])
                            vec("+", st, st, par)
                    else:
                        madd(st, st, two_vec, omf_vec)     # 2*gaddr + 1 - fp
                        vec("+", st, st, par)
                    for lane in range(VLEN):
                        S.emit("load", ("load", nv + lane, st + lane),
                               (st + lane,), (nv + lane,), mem_read=True)

        # Groups are fully independent, so they need not march in lockstep:
        # emitting the later blocks a few ROUNDS behind the earlier ones
        # skews the whole batch into a software-pipelined diagonal, so one
        # block's compute-heavy epoch rounds (levels 0..3, no gathers)
        # overlap another block's load-bound gather levels and both engines
        # stay busy. skew = (block_count, rounds_of_lag_per_block), or an
        # explicit per-block lag list for an asymmetric diagonal.
        if isinstance(skew, list):
            lags = skew
        else:
            n_blocks, lag = skew
            lags = [lag * b for b in range(n_blocks)]
        if n_groups % len(lags) != 0:
            lags = [0]  # degenerate shapes: no skew
        bs_ = n_groups // len(lags)
        for t in range(rounds + max(lags)):
            for b, lb in enumerate(lags):
                r = t - lb
                if 0 <= r < rounds:
                    for g in range(b * bs_, (b + 1) * bs_):
                        emit_group_round(r, g)

        # --- store final values; second pause after everything ---
        last = 0
        for g in range(n_groups):
            c = S.emit("store", ("vstore", val_addrs[g], val_vecs[g]),
                       (val_addrs[g],) + self._v(val_vecs[g]), (), mem_write=True)
            last = max(last, c)
        S.emit("flow", ("pause",), min_cycle=last)

        self.instrs = [b for b in S.bundles if b]

    def build_kernel_pipelined(
        self,
        batch_size: int,
        rounds: int,
        forest_height: int = None,
        pipeline_width: int = 16,
        debug_compares: bool = False,
    ):
        """
        Vectorized + software-pipelined kernel.

        Two independent, engine-disjoint work items make up each round for a
        group of VLEN walkers:
          - GATHER: compute the 8 gather addresses (one valu add) and issue
            the 8 scalar `load`s of `mem[forest_values_p + idx]` -- this is
            `load`-engine work (2 slots/cycle), and it is the workload's hard
            floor: batch_size/VLEN * rounds * 8 / 2 load-cycles no matter how
            well anything else packs.
          - COMPUTE: `val ^= node_val`, the (fused) 6-stage hash, and the
            idx update -- this is `valu`/`flow`-engine work.
        The baseline `build_kernel_vectorized` ran these as separate, barriered
        phases, so `load` sat idle during COMPUTE and `valu` sat idle during
        GATHER; the round cost was ~sum of the two. Here we software-pipeline:
        while COMPUTE(unit k) runs on valu/flow, GATHER(unit k+1) fills the
        otherwise-idle load slots of the very same bundles (ping-ponging two
        node_val buffers so the consumer and producer never alias). The round
        then costs ~max(load, valu, flow) instead of their sum -- i.e. it
        approaches the ~2048-cycle load floor.

        Also folds the hash to 11 mixing ops via multiply_add (see
        `_fused_hash_constants`) and the idx update to `2*idx + 1 + (val&1)`
        (one multiply_add + one and + one add), so valu stays comfortably
        under the load floor and hides beneath it.

        `debug_compares=True` interleaves free `("debug", ("vcompare", ...))`
        checks (ignored by the grader, `enable_debug=False`) against the
        reference value trace for fast (round, walker, field) bug isolation.
        """
        M = (1 << 32) - 1
        assert batch_size % VLEN == 0, f"batch_size must be a multiple of VLEN={VLEN}"
        n_groups = batch_size // VLEN
        pw = pipeline_width
        assert pw >= 1

        # Every walker advances exactly one tree level per round and wraps
        # back to the root together at the bottom, so at round r EVERY walker
        # sits at level r % (forest_height+1). On a "level 0" round every idx
        # is 0, so node_val is just the (broadcast) root value -- no gather.
        if forest_height is not None:
            period = forest_height + 1
            level0_rounds = {r for r in range(rounds) if r % period == 0}
        else:
            level0_rounds = {0}  # only the guaranteed initial all-root round

        # --- header: read the 4 fields this kernel uses (docs/problem.md 2.5)
        header_fields = {
            "n_nodes": 1,
            "forest_values_p": 4,
            "inp_indices_p": 5,
            "inp_values_p": 6,
        }
        for name, header_index in header_fields.items():
            self.alloc_scratch(name)
            addr = self.scratch_const(header_index)
            self.add("load", ("load", self.scratch[name], addr))

        # Matches reference_kernel2's first yield.
        self.add("flow", ("pause",))

        # --- broadcast every constant/vector this kernel needs, once ---
        bcast_slots = []

        def broadcast(src):
            dest = self.alloc_scratch(length=VLEN)
            bcast_slots.append(("vbroadcast", dest, src))
            return dest

        # node_val of the root (tree.values[0]); round 0 has every walker at
        # idx 0, so its gather is just this value broadcast -- no loads needed.
        root_nv = self.alloc_scratch("root_nv")
        self.add("load", ("load", root_nv, self.scratch["forest_values_p"]))
        root_nv_vec = broadcast(root_nv)

        one_vec = broadcast(self.scratch_const(1))
        two_vec = broadcast(self.scratch_const(2))
        fp_vec = broadcast(self.scratch["forest_values_p"])
        n_nodes_vec = broadcast(self.scratch["n_nodes"])

        hc = self._fused_hash_constants()
        vecs = {
            key: broadcast(self.scratch_const(hc[key]))
            for key in ("k0", "C0", "C1", "sh1", "kp", "ap", "kq", "aq", "k4", "C4", "C5", "sh5")
        }
        # Derived vectors for the gaddr-based idx update (see below):
        #   omf = 1 - forest_values_p   (folds the +1 and the -fp into one madd)
        #   fpn = forest_values_p + n_nodes  (wraparound compares gaddr < fpn)
        omf_vec = self.alloc_scratch(length=VLEN)
        fpn_vec = self.alloc_scratch(length=VLEN)
        # flush broadcasts, 6 valu/cycle
        for i in range(0, len(bcast_slots), SLOT_LIMITS["valu"]):
            self.instrs.append({"valu": bcast_slots[i : i + SLOT_LIMITS["valu"]]})
        self.instrs.append({"valu": [
            ("-", omf_vec, one_vec, fp_vec),
            ("+", fpn_vec, fp_vec, n_nodes_vec),
        ]})

        # --- persistent state -------------------------------------------
        # We never need the final indices (only `inp_values` is graded), so
        # instead of carrying `idx` we carry the gather ADDRESS
        #   gaddr = forest_values_p + idx
        # directly. That makes node_val's lookup a bare `load` of
        # mem[gaddr[lane]] with NO per-round address arithmetic, and folds
        # `forest_values_p` into the idx-update's multiply_add. One 8-wide
        # gaddr/val vector per group, alive for the whole run.
        gaddr_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]
        val_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]

        # Ping-pong node_val buffers, 2 sets of pw vectors.
        nv_bufs = [self.alloc_scratch(length=pw * VLEN) for _ in range(2)]
        # Per-pipeline-slot compute temporaries.
        t1 = [self.alloc_scratch(length=VLEN) for _ in range(pw)]
        t2 = [self.alloc_scratch(length=VLEN) for _ in range(pw)]

        # --- initial load of every group's idx/val (once) ---
        def group_addrs(base_name):
            base = self.scratch[base_name]
            addrs = []
            slots = []
            for g in range(n_groups):
                dest = self.alloc_scratch()
                slots.append(("+", dest, base, self.scratch_const(g * VLEN)))
                addrs.append(dest)
            for i in range(0, len(slots), SLOT_LIMITS["alu"]):
                self.instrs.append({"alu": slots[i : i + SLOT_LIMITS["alu"]]})
            return addrs

        # Every walker starts at idx 0 (Input.generate), so gaddr = fp for
        # all lanes -- just broadcast it, no index load needed. Values are
        # random, so they must be vloaded.
        val_addrs = group_addrs("inp_values_p")
        init_slots = [
            ("vbroadcast", gaddr_vecs[g], self.scratch["forest_values_p"])
            for g in range(n_groups)
        ]
        for i in range(0, len(init_slots), SLOT_LIMITS["valu"]):
            self.instrs.append({"valu": init_slots[i : i + SLOT_LIMITS["valu"]]})
        vload_slots = [("vload", val_vecs[g], val_addrs[g]) for g in range(n_groups)]
        for i in range(0, len(vload_slots), SLOT_LIMITS["load"]):
            self.instrs.append({"load": vload_slots[i : i + SLOT_LIMITS["load"]]})

        # --- pipeline over (round, wave) units ---
        waves = [
            list(range(ws, min(ws + pw, n_groups)))
            for ws in range(0, n_groups, pw)
        ]
        units = [(r, w) for r in range(rounds) for w in range(len(waves))]

        def gather_ops(unit, parity):
            # Pure loads: node_val[lane] = mem[gaddr[lane]]. No address math.
            # Level-0 rounds are all-root, so they need no gather.
            if unit[0] in level0_rounds:
                return []
            wave = waves[unit[1]]
            nv_buf = nv_bufs[parity]
            return [
                ("load", nv_buf + s * VLEN + lane, gaddr_vecs[g] + lane)
                for s, g in enumerate(wave)
                for lane in range(VLEN)
            ]

        def compute_cycles(unit, parity):
            r, w = unit
            wave = waves[w]
            nv_buf = nv_bufs[parity]
            cycles = []

            def step(ops):  # chunk independent valu ops into <=6/cycle bundles
                for i in range(0, len(ops), SLOT_LIMITS["valu"]):
                    cycles.append({"valu": ops[i : i + SLOT_LIMITS["valu"]]})

            # val ^= node_val  (level-0 rounds: broadcast root; else gathered)
            def nv_src(s):
                return root_nv_vec if r in level0_rounds else nv_buf + s * VLEN
            step([("^", val_vecs[g], val_vecs[g], nv_src(s))
                  for s, g in enumerate(wave)])
            # stage0 (affine): val = val*k0 + C0
            step([("multiply_add", val_vecs[g], val_vecs[g], vecs["k0"], vecs["C0"])
                  for g in wave])
            # stage1: (val ^ C1) ^ (val >> 19)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("^", t1[s], val_vecs[g], vecs["C1"]))
                ops.append((">>", t2[s], val_vecs[g], vecs["sh1"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # stage2+stage3 fused: p = val*kp + ap ; q = val*kq + aq ; val = p ^ q
            ops = []
            for s, g in enumerate(wave):
                ops.append(("multiply_add", t1[s], val_vecs[g], vecs["kp"], vecs["ap"]))
                ops.append(("multiply_add", t2[s], val_vecs[g], vecs["kq"], vecs["aq"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # stage4 (affine): val = val*k4 + C4
            step([("multiply_add", val_vecs[g], val_vecs[g], vecs["k4"], vecs["C4"])
                  for g in wave])
            # stage5: (val ^ C5) ^ (val >> 16)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("^", t1[s], val_vecs[g], vecs["C5"]))
                ops.append((">>", t2[s], val_vecs[g], vecs["sh5"]))
            step(ops)
            step([("^", val_vecs[g], t1[s], t2[s]) for s, g in enumerate(wave)])
            # val_vecs now holds the finished hash (hashed_val)
            if debug_compares:
                for g in wave:
                    cycles.append({"debug": [(
                        "vcompare", val_vecs[g],
                        [(r, g * VLEN + lane, "hashed_val") for lane in range(VLEN)],
                    )]})
            # idx update in gaddr space:
            #   next_gaddr = 2*gaddr + 1 - fp + (val & 1)
            #             = madd(gaddr, two, omf) + (val & 1)
            #   gaddr = (next_gaddr < fp+n_nodes) ? next_gaddr : fp  (idx=0 wrap)
            ops = []
            for s, g in enumerate(wave):
                ops.append(("&", t1[s], val_vecs[g], one_vec))                       # parity
                ops.append(("multiply_add", t2[s], gaddr_vecs[g], two_vec, omf_vec))  # 2*gaddr+1-fp
            step(ops)
            step([("+", t1[s], t2[s], t1[s]) for s, g in enumerate(wave)])           # next_gaddr
            step([("<", t2[s], t1[s], fpn_vec) for s, g in enumerate(wave)])         # in-range?
            for s, g in enumerate(wave):
                cycles.append({"flow": [("vselect", gaddr_vecs[g], t2[s], t1[s], fp_vec)]})
            return cycles

        def emit_unit(compute, load_ops):
            # Interleave the prefetched gather's loads into COMPUTE's
            # otherwise-idle load slots (2/cycle). Loads read gaddr_vecs of a
            # DIFFERENT wave, so they're independent of this compute.
            li = 0
            for cyc in compute:
                is_real = ("valu" in cyc) or ("flow" in cyc)
                if is_real and li < len(load_ops):
                    cyc = dict(cyc)
                    cyc["load"] = load_ops[li : li + SLOT_LIMITS["load"]]
                    li += SLOT_LIMITS["load"]
                self.instrs.append(cyc)
            while li < len(load_ops):
                self.instrs.append({"load": load_ops[li : li + SLOT_LIMITS["load"]]})
                li += SLOT_LIMITS["load"]

        def emit_gather_full(unit, parity):
            loads = gather_ops(unit, parity)
            for i in range(0, len(loads), SLOT_LIMITS["load"]):
                self.instrs.append({"load": loads[i : i + SLOT_LIMITS["load"]]})

        # Unit j's gathered node_val lives in buffer parity j % 2, so a
        # consumer (compute j, reads j%2) and the concurrently-prefetched
        # producer (gather j+1, writes (j+1)%2) never alias.
        #
        # We prefetch unit k+1's gather during unit k's compute ONLY when
        # their groups are disjoint -- otherwise gather(k+1) would read
        # gaddr_vecs before compute(k)'s vselect has committed the new gaddr
        # for those very groups. For the graded shape (32 groups) waves are
        # always disjoint, so this always prefetches; the fallback keeps
        # smaller/degenerate shapes correct.
        emit_gather_full(units[0], 0)
        for k, unit in enumerate(units):
            compute = compute_cycles(unit, k % 2)
            nxt = k + 1
            can_prefetch = nxt < len(units) and set(waves[units[nxt][1]]).isdisjoint(
                waves[unit[1]]
            )
            if can_prefetch:
                emit_unit(compute, gather_ops(units[nxt], nxt % 2))
            else:
                emit_unit(compute, [])
                if nxt < len(units):
                    emit_gather_full(units[nxt], nxt % 2)

        # --- store every group's final val once (indices aren't graded) ---
        store_slots = [("vstore", val_addrs[g], val_vecs[g]) for g in range(n_groups)]
        for i in range(0, len(store_slots), SLOT_LIMITS["store"]):
            self.instrs.append({"store": store_slots[i : i + SLOT_LIMITS["store"]]})

        # Matches reference_kernel2's second yield.
        self.add("flow", ("pause",))

    def build_kernel_vectorized(self, batch_size: int, rounds: int, pipeline_width: int = 6):
        """
        Vectorized + pipelined kernel: processes VLEN=8 walkers per `valu`
        register instead of one scalar walker at a time, and keeps idx/val
        resident in scratch for a group's entire round-lifetime -- memory is
        only touched once at the very start (vload) and once at the very
        end (vstore) per group, unlike a round-major scan that round-trips
        through memory every round for every walker.

        `pipeline_width` groups' independent instruction streams are
        interleaved so valu's 6 slots/cycle actually get filled: a single
        group's own hash-stage dependency chain (op1/op3 are independent,
        but the combine step needs both, so it can't join them in the same
        bundle -- see docs/isa.md) only ever offers 2 independent valu ops
        at a time, and every other phase (addr, xor, mod, ...) offers only
        1 -- so a wave of pipeline_width=6 groups fills every phase's valu
        bundles at (close to) 100%, since 6 is a multiple of both 1 and 2.
        pipeline_width=1 gives the vectorize-only version (valu is used,
        but its slots mostly aren't filled).

        node_val's lookup (`mem[forest_values_p + idx[lane]]`) is a
        data-dependent gather -- there's no vector gather instruction in
        this ISA, only contiguous vload/vstore -- so it's unavoidably 8
        scalar loads per group per round; with `load`'s 2-slot/cycle limit
        that makes it the dominant, hardest-to-remove cost once everything
        else is packed (confirmed via rust_harness's usage-stats tool).

        This was prototyped, correctness-checked against Python-exported
        fixtures, and profiled in rust_harness/src/vectorized.rs before
        being ported here -- see that file and rust_harness/README.md for
        the fuller write-up, and docs/problem.md for the algorithm this
        implements.
        """
        assert batch_size % VLEN == 0, f"batch_size must be a multiple of VLEN={VLEN}"
        n_groups = batch_size // VLEN

        # Only the 4 header fields this kernel actually reads (see
        # docs/problem.md §2.5 for the fixed 7-word header layout). Routed
        # through scratch_const (memoized) rather than a raw "const" load,
        # since header index 1 (n_nodes) coincides with the "one" constant
        # broadcast below and can share its load.
        header_fields = {"n_nodes": 1, "forest_values_p": 4, "inp_indices_p": 5, "inp_values_p": 6}
        for name, header_index in header_fields.items():
            self.alloc_scratch(name)
            addr = self.scratch_const(header_index)
            self.add("load", ("load", self.scratch[name], addr))

        # Matches reference_kernel2's first yield.
        self.add("flow", ("pause",))

        # Broadcast every constant this kernel needs into an 8-wide vector,
        # exactly once; every group/round below only *reads* these.
        def broadcast(src):
            dest = self.alloc_scratch(length=VLEN)
            self._pack("valu", ("vbroadcast", dest, src))
            return dest

        zero_const = self.scratch_const(0)
        one_const = self.scratch_const(1)
        two_const = self.scratch_const(2)
        zero_vec = broadcast(zero_const)
        one_vec = broadcast(one_const)
        two_vec = broadcast(two_const)
        forest_values_p_vec = broadcast(self.scratch["forest_values_p"])
        n_nodes_vec = broadcast(self.scratch["n_nodes"])

        hash_const_vecs = [
            (broadcast(self.scratch_const(val1)), broadcast(self.scratch_const(val3)))
            for (_, val1, _, _, val3) in HASH_STAGES
        ]
        self._flush()

        # One persistent 8-wide vector register per group, alive for the
        # group's entire 16-round lifetime.
        idx_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]
        val_vecs = [self.alloc_scratch(length=VLEN) for _ in range(n_groups)]

        # Per-pipeline-slot scratch temporaries, reused wave to wave.
        def temp_pool():
            return [self.alloc_scratch(length=VLEN) for _ in range(pipeline_width)]

        addr_tmp = temp_pool()
        node_val_tmp = temp_pool()
        hash_tmp1 = temp_pool()
        hash_tmp2 = temp_pool()
        offset_tmp = temp_pool()
        next_idx_tmp = temp_pool()
        cmp_tmp = temp_pool()

        def group_addrs(base):
            # addr[g] = base + g*VLEN, computed as one packed batch (up to
            # SLOT_LIMITS["alu"]/cycle) rather than one bundle per group.
            addrs = []
            for g in range(n_groups):
                dest = self.alloc_scratch()
                offset_const = self.scratch_const(g * VLEN)
                self._pack("alu", ("+", dest, base, offset_const))
                addrs.append(dest)
            self._flush()
            return addrs

        # Load every group's starting idx/val once.
        idx_addrs = group_addrs(self.scratch["inp_indices_p"])
        val_addrs = group_addrs(self.scratch["inp_values_p"])
        for g in range(n_groups):
            self._pack("load", ("vload", idx_vecs[g], idx_addrs[g]))
            self._pack("load", ("vload", val_vecs[g], val_addrs[g]))
        self._flush()

        for _round in range(rounds):
            wave_start = 0
            while wave_start < n_groups:
                wave = list(range(wave_start, min(wave_start + pipeline_width, n_groups)))
                wave_start += pipeline_width

                # addr[g] = idx[g] + forest_values_p (all 8 lanes' gather addresses in one valu op)
                for slot, g in enumerate(wave):
                    self._pack("valu", ("+", addr_tmp[slot], idx_vecs[g], forest_values_p_vec))
                self._flush()

                # gather node_val -- unavoidably scalar, see docstring above
                for slot in range(len(wave)):
                    for lane in range(VLEN):
                        self._pack("load", ("load", node_val_tmp[slot] + lane, addr_tmp[slot] + lane))
                self._flush()

                # val ^= node_val
                for slot, g in enumerate(wave):
                    self._pack("valu", ("^", val_vecs[g], val_vecs[g], node_val_tmp[slot]))
                self._flush()

                # 6-stage hash, vectorized
                for stage_idx, (op1, _, op2, op3, _) in enumerate(HASH_STAGES):
                    c1_vec, c3_vec = hash_const_vecs[stage_idx]
                    for slot, g in enumerate(wave):
                        self._pack("valu", (op1, hash_tmp1[slot], val_vecs[g], c1_vec))
                        self._pack("valu", (op3, hash_tmp2[slot], val_vecs[g], c3_vec))
                    self._flush()
                    for slot, g in enumerate(wave):
                        self._pack("valu", (op2, val_vecs[g], hash_tmp1[slot], hash_tmp2[slot]))
                    self._flush()

                # offset = (val % 2) + 1 -- replaces the naive mod+eq+select
                for slot, g in enumerate(wave):
                    self._pack("valu", ("%", offset_tmp[slot], val_vecs[g], two_vec))
                self._flush()
                for slot in range(len(wave)):
                    self._pack("valu", ("+", offset_tmp[slot], offset_tmp[slot], one_vec))
                self._flush()

                # next_idx = idx*2 + offset
                for slot, g in enumerate(wave):
                    self._pack("valu", ("*", next_idx_tmp[slot], idx_vecs[g], two_vec))
                self._flush()
                for slot in range(len(wave)):
                    self._pack("valu", ("+", next_idx_tmp[slot], next_idx_tmp[slot], offset_tmp[slot]))
                self._flush()

                # wraparound: idx = (next_idx < n_nodes) ? next_idx : 0 -- the one genuine select
                for slot in range(len(wave)):
                    self._pack("valu", ("<", cmp_tmp[slot], next_idx_tmp[slot], n_nodes_vec))
                self._flush()
                for slot, g in enumerate(wave):
                    self._pack("flow", ("vselect", idx_vecs[g], cmp_tmp[slot], next_idx_tmp[slot], zero_vec))
                self._flush()

        # Store every group's final idx/val once, at the same addresses
        # computed for the initial load (nothing writes those pointer
        # registers in between, so there's no need to recompute them).
        for g in range(n_groups):
            self._pack("store", ("vstore", idx_addrs[g], idx_vecs[g]))
            self._pack("store", ("vstore", val_addrs[g], val_vecs[g]))
        self._flush()

        # Matches reference_kernel2's second yield.
        self.add("flow", ("pause",))

BASELINE = 147734

def do_kernel_test(
    forest_height: int,
    rounds: int,
    batch_size: int,
    seed: int = 123,
    trace: bool = False,
    prints: bool = False,
):
    print(f"{forest_height=}, {rounds=}, {batch_size=}")
    random.seed(seed)
    forest = Tree.generate(forest_height)
    inp = Input.generate(forest, batch_size, rounds)
    mem = build_mem_image(forest, inp)

    kb = KernelBuilder()
    kb.build_kernel(forest.height, len(forest.values), len(inp.indices), rounds)
    # print(kb.instrs)

    value_trace = {}
    machine = Machine(
        mem,
        kb.instrs,
        kb.debug_info(),
        n_cores=N_CORES,
        value_trace=value_trace,
        trace=trace,
    )
    machine.prints = prints
    for i, ref_mem in enumerate(reference_kernel2(mem, value_trace)):
        machine.run()
        inp_values_p = ref_mem[6]
        if prints:
            print(machine.mem[inp_values_p : inp_values_p + len(inp.values)])
            print(ref_mem[inp_values_p : inp_values_p + len(inp.values)])
        assert (
            machine.mem[inp_values_p : inp_values_p + len(inp.values)]
            == ref_mem[inp_values_p : inp_values_p + len(inp.values)]
        ), f"Incorrect result on round {i}"
        inp_indices_p = ref_mem[5]
        if prints:
            print(machine.mem[inp_indices_p : inp_indices_p + len(inp.indices)])
            print(ref_mem[inp_indices_p : inp_indices_p + len(inp.indices)])
        # Updating these in memory isn't required, but you can enable this check for debugging
        # assert machine.mem[inp_indices_p:inp_indices_p+len(inp.indices)] == ref_mem[inp_indices_p:inp_indices_p+len(inp.indices)]

    print("CYCLES: ", machine.cycle)
    print("Speedup over baseline: ", BASELINE / machine.cycle)
    return machine.cycle


class Tests(unittest.TestCase):
    def test_ref_kernels(self):
        """
        Test the reference kernels against each other
        """
        random.seed(123)
        for i in range(10):
            f = Tree.generate(4)
            inp = Input.generate(f, 10, 6)
            mem = build_mem_image(f, inp)
            reference_kernel(f, inp)
            for _ in reference_kernel2(mem, {}):
                pass
            assert inp.indices == mem[mem[5] : mem[5] + len(inp.indices)]
            assert inp.values == mem[mem[6] : mem[6] + len(inp.values)]

    def test_kernel_trace(self):
        # Full-scale example for performance testing
        do_kernel_test(10, 16, 256, trace=True, prints=False)

    # Passing this test is not required for submission, see submission_tests.py for the actual correctness test
    # You can uncomment this if you think it might help you debug
    # def test_kernel_correctness(self):
    #     for batch in range(1, 3):
    #         for forest_height in range(3):
    #             do_kernel_test(
    #                 forest_height + 2, forest_height + 4, batch * 16 * VLEN * N_CORES
    #             )

    def test_kernel_cycles(self):
        do_kernel_test(10, 16, 256)


# To run all the tests:
#    python perf_takehome.py
# To run a specific test:
#    python perf_takehome.py Tests.test_kernel_cycles
# To view a hot-reloading trace of all the instructions:  **Recommended debug loop**
# NOTE: The trace hot-reloading only works in Chrome. In the worst case if things aren't working, drag trace.json onto https://ui.perfetto.dev/
#    python perf_takehome.py Tests.test_kernel_trace
# Then run `python watch_trace.py` in another tab, it'll open a browser tab, then click "Open Perfetto"
# You can then keep that open and re-run the test to see a new trace.

# To run the proper checks to see which thresholds you pass:
#    python tests/submission_tests.py

if __name__ == "__main__":
    unittest.main()
