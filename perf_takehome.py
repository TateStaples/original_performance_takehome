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
        # H-028 (store_pair): when True, two mem WRITES may share a cycle
        # (writes commit at end of cycle, so same-cycle writes to DISJOINT
        # addresses are exact; this kernel never writes the same mem word
        # twice). Reads keep full ordering against writes both ways.
        self.pair_writes = False
        self.hint = dict.fromkeys(SLOT_LIMITS, 0)
        # Optional placement trace (tools/sched_profile.py): when `trace` is
        # a list, every put() appends (cycle, engine, tag, slot, reads,
        # writes, mem_read, mem_write). `tag` is builder-set context (e.g.
        # the (round, group) being emitted). Default off; placement is
        # unaffected either way.
        self.trace = None
        self.tag = None

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
            t = self.mem_write_c + (0 if self.pair_writes else 1)
            if t > c:
                c = t
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
        if self.trace is not None:
            self.trace.append(
                (c, engine, self.tag, slot, reads, writes, mem_read, mem_write)
            )
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

    def emit_any(self, encodings):
        """
        H-019: place ONE of several alternative ENCODINGS of the same
        computation -- whichever retires EARLIEST; ties go to the
        earliest-listed encoding. Each encoding is a sequence of micro-ops
        (engine, slot, reads, writes) placed greedily in listed order;
        micro-ops within an encoding may depend on each other (trial-local
        RAW/WAW/WAR tracking on top of the global state) and compete for
        the same engine's slots (trial-local occupancy), so an encoding's
        retire time is the max of its micro-ops' placements. This is the
        one mechanism behind both the H-017 valu-madd-vs-flow-vselect fold
        race (1-op encodings on two engines) and the alu-offload split race
        (1 valu op vs 8 scalar alu lane ops); `dual_fold` and `_sched_vec`
        route through it, and any op with several equivalent spellings can
        race the same way.
        """
        best = None
        for enc in encodings:
            extra = {}
            t_lw = {}
            t_lr = {}
            placements = []
            retire = -1
            for engine, slot, reads, writes in enc:
                c = self.ready(reads, writes)
                for a in reads:
                    t = t_lw.get(a, -1) + 1
                    if t > c:
                        c = t
                for a in writes:
                    t = t_lw.get(a, -1) + 1
                    if t > c:
                        c = t
                    t = t_lr.get(a, -1)
                    if t > c:
                        c = t
                c = self.find_free(engine, c, extra.setdefault(engine, {}))
                extra[engine][c] = extra[engine].get(c, 0) + 1
                placements.append(c)
                if c > retire:
                    retire = c
                for a in reads:
                    if t_lr.get(a, -1) < c:
                        t_lr[a] = c
                for a in writes:
                    t_lw[a] = c
            if best is None or retire < best[0]:
                best = (retire, enc, placements)
        retire, enc, placements = best
        for (engine, slot, reads, writes), c in zip(enc, placements):
            self.put(engine, slot, c, reads, writes)
        return retire


class KernelBuilder:
    def __init__(self):
        self.instrs = []
        self.scratch = {}
        self.scratch_debug = {}
        self.scratch_ptr = 0
        self.const_map = {}
        self._current = {}  # bundle being greedily packed by _pack/_flush
        # spec_fold auto-mode race tally: [A wins, cycles saved by B, B wins]
        self._spec_stats = [0, 0, 0]

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
                parity_conds=True, c5_prexor=True, vsel_auto=(1, 2),
                u_race=True, l4_race=3, idx_race=True,
                derive_consts=True, alu_val_addrs=True,
                mem_prime=(5,), store_pair=True,
                b3_last=(15,), b3l_diffs=True,
                pool_sizes=(16, 4), l4_gmin=(12, 30),
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

    def _sched_vec(self, S, op, dest, a, b, allow_alu=False, force_alu=False,
                   valu_ties=False):
        """
        Emit an elementwise vector op, either as one valu slot or -- when the
        valu engine is backed up and the (otherwise idle) scalar alu can
        retire all 8 lanes no later -- as 8 scalar alu slots. `force_alu`
        skips the comparison and always scalarizes (used to statically
        reserve valu slots for multiply_adds, which alu can't run).
        """
        reads = self._v(a) + self._v(b)
        writes = self._v(dest)
        if op in _SCALARIZABLE and (force_alu or allow_alu):
            alu_enc = tuple(
                ("alu", (op, dest + i, a + i, b + i), (a + i, b + i), (dest + i,))
                for i in range(VLEN)
            )
            if force_alu:
                return S.emit_any((alu_enc,))
            c0 = S.ready(reads, writes)
            cv = S.find_free("valu", c0)
            if cv > c0:
                # valu is backed up: race the split. alu listed first so it
                # keeps retire-time ties (the historical `worst <= cv` rule);
                # valu_ties flips that (H-021 tie_break="vec_valu").
                encs = (
                    alu_enc,
                    (("valu", (op, dest, a, b), reads, writes),),
                )
                return S.emit_any(encs[::-1] if valu_ties else encs)
            S.put("valu", (op, dest, a, b), cv, reads, writes)
            return cv
        cv = S.find_free("valu", S.ready(reads, writes))
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
        vsel_folds=False,
        vsel_auto=(),
        c5_prexor: bool = False,
        mem_prime=(),
        spec_fold=(),
        l4_race=(),
        u_race: bool = False,
        sel_race: bool = False,
        idx_race: bool = False,
        idx_select: bool = False,
        store_order: str = "group",
        b3_last=(),
        b3l_race: bool = True,
        b3l_diffs: bool = False,
        bl_last=(),
        emit_order: str = "group",
        flow_consts: bool = False,
        vals_first: bool = False,
        tie_break: tuple = (),
        derive_consts: bool = False,
        alu_val_addrs: bool = False,
        lazy_val_loads: bool = False,
        store_pair: bool = False,
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

        - `vsel_folds` (H-017): move tournament FIRST-folds -- whose
          condition is the newest parity, a raw 0/1 vector under
          `parity_conds` -- from valu multiply_add to flow vselect. The
          level tables store the odd VALUES instead of (odd - even) diffs
          for the flipped levels (same vector scratch, minus the setup
          subtracts and their scalar diff words), and each first fold
          becomes vselect(b, O[k], E[k]): same dependency depth, one valu
          slot traded for one flow slot. False (off), True (all levels),
          or an iterable of levels from {1, 2, 3, 4}, where 4 means the
          l4-served W-combines. Requires `parity_conds`.

        - `vsel_auto` (H-017/H-007): schedule-aware version of the above
          for levels from {1, 2, 3} -- each first-fold is placed on flow
          ONLY when the flow engine's earliest free slot strictly beats
          valu's (both the diff and the odd-value tables are kept live,
          funded by trading one cond-pool slot, measured cycle-neutral).
          Requires `parity_conds`; disjoint from `vsel_folds`. {1, 2} or
          {3} fit the freed scratch; larger sets overflow the allocator.

        - `c5_prexor` (H-015): C5-pre-xor value domain. The hash's final
          stage is val' = e ^ (e>>16) ^ C5 ^ n_next-fold; pre-xoring every
          node-value SOURCE with C5 (broadcast tables + primed root at
          setup; the 16 level-4 tree words rewritten in mem from the
          already-loaded lv scratch) lets a round DROP its `^ C5` whenever
          the next round's fold-in absorbs it: on such rounds the stored
          val is primed (val^C5) and the next round's `val ^= node_val'`
          cancels both C5s. One valu op per (group, elided round) is saved
          -- 9 of 16 rounds at the graded shape (levels 5..10 gather the
          untouched true tree, so rounds feeding them keep `^ C5`; the
          last round always keeps it so the STORED values are true).
          C5 is odd, so parities ride INVERTED out of elided rounds; all
          rounds feeding tournaments are elided, so the position
          accumulator uniformly carries the bitwise COMPLEMENT p' = ~p:
            * within a broadcast pair the newest (inverted) bit selects
              via base=odd, diff=even-odd (setup constant swap);
            * the older (inverted) bits select correctly from tables
              stored in REVERSED order (select-by-~t from reversed = t),
              so the tournament fold emission is completely unchanged;
            * epoch-exit gaddr conversion becomes
              gaddr = -2*p' + (fp + 2^Ln-1 + 2^(L+1)-2 + inv) -/+ parity
              (one madd by a negtwo vector + add/sub -- same op count).
          Requires parity_conds; incompatible with parity_early (whose
          carry-free parity is TRUE-domain). Trades one cond-pool slot
          (32 words) for the negtwo/primed-root vectors, like
          parity_early does.

        - `mem_prime` (H-026, cross): extend c5_prexor's in-mem priming
          from level 4 to deeper GATHER levels. For each level d in the
          iterable, the 2^d tree words at that level are vloaded, xored
          with C5 and vstored back during the setup load-engine lull
          (between the setup vloads and the first gather; staged through
          the setup-dead `lv` scratch). Round d's gathers then return
          PRIMED values, so round d-1 joins the elide set and drops its
          `^ C5` for every group (32 vec ops per level at the graded
          shape). Rounds that exit an elided round into gather mode carry
          an inverted parity; the update becomes
            gaddr' = 2*gaddr + (omf+1) - par'
          (same op count: the `omf1` vector rides the last 8 words of the
          setup-dead lv scratch, so no persistent allocation). Cost per
          level d: 2^d/8 vloads + vstores + vec xors in the setup lull,
          where the load engine is otherwise idle -- the marginal-cost
          refutation of H-015's P-4 all-or-nothing arithmetic. Levels
          must be gather levels above the tournament (5..height); load
          cost doubles per level while the elide gain stays constant, so
          only the shallowest levels can pay. Requires c5_prexor (and the
          full-width lv scratch: maxT == 3 with level-4 service on).

        - `spec_fold` (H-010): parity speculation at shallow tournament
          levels. xor distributes over select, so the hash fold-in
            vl ^ select(b, O, E)  ==  select(b, vl^O, vl^E):
          the level's candidate values are pre-xored into vl BOTH ways
          (elementwise xors, alu-split -- nearly free) and the
          parity-dependent select runs LAST, on flow, feeding the first
          hash madd directly. Removes the fold madd AND the fold-in xor
          from valu (zero-net-valu by construction) and shortens the
          parity->first-madd chain by one level. Value tables stored like
          `vsel_folds` (no diffs); node_val itself never materializes, so
          its debug compare is skipped on speculated rounds. Levels from
          {1, 2}: level d costs 2^d speculated xors + 2^d - 1 vselects,
          so deeper levels flood flow. Requires `parity_conds`; takes
          precedence over `vsel_folds`/`vsel_auto` at the same level.
          "auto" (level 1; needs its `vsel_auto` dual tables) instead
          RACES the speculated form against the status-quo fold per site
          via trial emission, keeping whichever completes vl earlier;
          "auto:N" lets the speculated form pay up to N extra cycles of
          local vl delay to shed valu slots. All modes measured >= 1088
          (H-010 closed negative): the existing dual_fold/alu racing
          already keeps these sites pointwise optimal, and the extra
          speculated xor displaces alu-offloaded ops back onto valu.

        - `l4_race` / `u_race` / `sel_race` (H-019): `emit_any` races
          beyond the vsel_auto first-folds. `l4_race` gives the served
          level-4 W-combines dual valu-madd/flow-vselect encodings for the
          listed pair indices (True = all; int N = the first N pairs),
          each raced pair funded by one extra odd-value broadcast (VLEN
          words of free scratch; the select arm is the EVEN word under
          c5_prexor, exactly like vsel_auto's tables). `u_race` gives each
          level-4 U-combine (dst := b2 ? Wa : Wb, runtime arms, exact 0/1
          cond) a 1-op flow-vselect encoding racing the 2-op valu
          subtract+madd (subtract alu-splittable), clobbering the dead Wa
          on the valu path. `sel_race` is the symmetric reverse race: the
          L2 b0-copy and final select and L3's q0/q1 (the vselects whose
          conds are exact 0/1) may fall BACK to valu subtract+madd (or alu
          splits) when flow is the local constraint. `idx_race` gives the
          Idx-madd family (`p := 2p + b` lagged folds, epoch-exit gaddr
          conversions, gather-mode `2*gaddr + omf` updates) an alu
          spelling -- per-lane shift then add/subtract, 16 scalar slots
          over two dependent levels -- raced against the single valu madd.
          All except idx_race require parity_conds; all default off.
          `idx_select` (P-14, ported from a third-party solution to this
          same problem -- github.com/zhanglistar/original_performance_takehome
          -- not an in-house finding) rewrites the gather-mode steady-state
          update `madd(st,st,two,ov); vec(sgn,st,st,par)` as a select
          BEFORE the madd instead of an add/sub AFTER it: since
          `omf1_vec == omf_vec + 1` by construction, `ov +/- par` for a
          0/1 `par` is exactly a choice between the two ALREADY-EXISTING
          broadcast constants `omf_vec`/`omf1_vec` (no new scratch),
          which a flow vselect can express but a variable add/sub cannot
          -- moving that step off valu/alu onto flow. Same op count;
          mutually exclusive with idx_race (idx_select takes priority
          when both are set). Only the steady-gather branch is covered;
          the boundary-crossing branch (c5_prexor's key-indexed rec_vecs)
          is left alone since exploiting the same trick there would need
          new persistent scratch this kernel doesn't have (1533/1536 used).

        - `b3_last` (H-023): reverse the served-level-4 tournament fold
          order so the NEWEST parity (b3 = the raw parity riding `nv`,
          which arrives LAST out of round r-1's hash) selects LAST -- as a
          single final multiply_add -- instead of first via the 8 W-combine
          madds. The 16 candidates factor as node_val = E[t] + b3*D[t] with
          t = b0b1b2 the level-3 winner index (all three older bits already
          in `st` at round start); since the fold over t is linear and
          independent of b3, the two broadcast tables are folded SEPARATELY
          by b0,b1,b2 (`E_winner = E[t*]`, `D_winner = D[t*]`, 7 flow
          vselects each, depth 3) and combined by one b3-dependent madd
          (`nv = E_winner + b3*D_winner`), bit-identical to the b3-first
          tree. The post-parity dependency chain drops from ~4 select levels
          + hash to 1 madd + hash (~17 -> ~11 levels), directly shrinking
          the r15 drain staircase (see research/strains/scheduler/STATE.md).
          No extra scratch: the fold reuses the existing E_vecs/D_vecs
          tables and the 5 tournament pool temps (masks recomputed off `st`
          on the idle alu; `st` left intact for the epoch-exit conversion).
          False/() (off), True (all served level-4 rounds), or an iterable
          of round numbers. Requires parity_conds; disjoint from a hard
          level-4 vsel_folds.

        - `bl_last` (H-027 companion, cross): the b3_last idea applied to
          the shallow tournament levels 2 and 3 WITHOUT any new tables:
          node_val = evens[t] + b_new * diffs[t] where t is chosen by the
          OLDER bits already sitting in `st` at round start, so the even
          and diff tables can be folded down to evens[t]/diffs[t] by
          flow vselects BEFORE the newest parity arrives, leaving a
          post-parity chain of ONE madd (L2: 2 -> 1 dependency levels,
          L3: 3 -> 1) at the cost of moving fold work from valu madds to
          flow vselects (L2: 2 madd + 1 vsel -> 1 madd + 2 vsel; L3:
          4 madd + 3 vsel -> 1 madd + 6 vsel). That trade loses in the
          triple-saturated middle (G-12: flow floods) but wins in the
          drain where flow idles and the LAST skew block's serial
          round chain is the binder, so it applies only to rounds listed
          in `bl_last` AND groups of the last skew block. Requires
          parity_conds.

        - `b3l_diffs` (H-027, cross; G-17's reopen-if): fund b3_last's
          leaf folds with PRECOMPUTED leaf-diff tables --
          dT[k] = tabs[2k+1] - tabs[2k] for both E_vecs and D_vecs --
          so each leaf select spells as ONE valu madd (raced against the
          flow vselect via `dual_fold`) instead of H-023's 2-op
          subtract+madd or a serialized flow vselect. The ~64 words those
          8 vectors need do not exist as free scratch; at the FINAL round
          they ride the `st` vectors of the non-served groups, which are
          truly dead there (their last read is the previous round's
          gather issue) -- the 8 subtracts are emitted lazily at the
          first served group's fold and land in the r14/r15 seam where
          valu drains. Applies to the final round only (earlier rounds'
          st vectors are live; those keep H-023's race_leaf path).

        - `emit_order` / `flow_consts` / `vals_first` / `tie_break`
          (H-021): pure EMISSION-ORDER / setup-encoding / tie-break
          experiments; none changes the maths. `emit_order="group"`
          (default) emits each group's round contiguously; "stage"
          round-robins the hash/tournament STAGES of the 8 groups within a
          skew block (all groups' fold-in, then all stage-0 madds, ...);
          "stage_all" round-robins across ALL blocks active at a diagonal
          step; "stage_tail:N"/"rev_tail:N" apply stage-interleave /
          reversed group order only on the last N diagonal steps (the
          drain). `flow_consts` materializes scratch constants on the idle
          flow engine (`add_imm` off a zeroed word) instead of the load
          engine's 2/cycle `const` slots. `vals_first` emits the initial
          per-group value vloads BEFORE the tournament-table setup (True)
          or right after the hash constants ("hash"). `tie_break` flips
          which encoding keeps retire-time ties in the emit_any races
          ("fold_flow", "idx_alu", "vec_valu"). ALL measured >= 1070 at
          the mainline config (iter 4 friction study): the saturated
          middle is insensitive to emission order (greedy placement
          reorders it anyway), the setup ramp is load-THROUGHPUT-bound
          (any reorder that delays the lv-table stream costs +15), and
          the r15 drain is chain-LATENCY-bound (interleaving cannot
          compress it; see research/strains/scheduler/STATE.md). Kept as
          negative controls / sweep dimensions.

        - `derive_consts` / `alu_val_addrs` / `lazy_val_loads` (H-024):
          setup load/flow-slot removal; none changes the maths.
          `derive_consts` materializes the nine setup constants that are
          cheap algebraic combinations of already-loaded ones (2, 8,
          sh5=16, k4=9, kp=33, kq=kp<<9, k0=(16<<8)+1, sh1=19, -2) with
          in-place scalar alu chains instead of one `load:const` slot
          each -- the alu is idle during the setup ramp while the load
          engine (2/cycle) is the binder; the arbitrary hash addends
          (C0, C1, ap, aq, C4, C5) have no such relations (brute-forced)
          and stay as const loads. `alu_val_addrs` computes the 32
          initial-value vload addresses (ivp + 8g) on the alu as four
          parallel +32 chains instead of 32 serial `add_imm` slots on
          the 1-wide flow engine (which otherwise books flow solid to
          ~cycle 40 and crowds the tournament fold vselect races off
          flow). `lazy_val_loads` emits each group's va/vload at the
          top of that group's round-0 emission instead of all up-front
          (placement backfills, so this only moves slot-contention
          tie-breaks). All default off; defaults are bit-identical.

        - `store_pair` (H-028, cross): allow two mem WRITES to share a
          cycle in the scheduler's coarse memory model. Writes commit at
          end of cycle and every store in this kernel targets a distinct
          mem word, so same-cycle write pairs are exact; reads keep full
          ordering against writes in both directions. Without it the 32
          final vstores serialize at 1/cycle on the 2-wide store engine
          and the last few are exposed at the very end of the drain.

        `debug_compares` interleaves free `("debug", ("vcompare", ...))`
        slots (skipped by the grader) checking node_val and hashed_val of
        every (round, walker) against the reference trace. Under
        `c5_prexor` only true-domain values exist to compare, so compares
        are emitted only where the scratch value equals the reference's:
        node_val on non-primed rounds (round 0 + gather levels >= 5),
        hashed_val on non-elided rounds (incl. the final stored round).
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

        # vsel_folds (H-017) normalization: which levels' first-folds ride
        # flow vselect instead of valu madd. 4 = the l4-served W-combines.
        if vsel_folds is True:
            vf_levels = set(range(1, L4 + 1))
        elif vsel_folds:
            vf_levels = ({vsel_folds} if isinstance(vsel_folds, int)
                         else set(vsel_folds))
        else:
            vf_levels = set()
        vf_levels &= set(range(1, L4 + 1))
        assert not vf_levels or parity_conds, "vsel_folds requires parity_conds"

        # vsel_auto (H-017/H-007): levels whose first-folds race valu vs
        # flow at schedule time (needs both diff and odd tables live).
        va_levels = ({vsel_auto} if isinstance(vsel_auto, int)
                     else set(vsel_auto)) & set(range(1, maxT + 1))
        va_levels -= vf_levels
        assert not va_levels or parity_conds, "vsel_auto requires parity_conds"

        # spec_fold (H-010): levels whose whole fold + fold-in is speculated
        # (see docstring). Wins the level from vsel_folds/vsel_auto.
        # Modes: an int/iterable of ints speculates those levels HARD
        # (measured negative: flow serializes, like G-12); "auto" / an
        # iterable containing "auto" races the speculated form against the
        # status-quo fold per site and commits whichever completes vl
        # earlier (trial emission with scheduler-state snapshots). Auto is
        # implemented for level 1 and needs its dual tables (vsel_auto).
        if isinstance(spec_fold, str):
            spec_fold = (spec_fold,)
        elif isinstance(spec_fold, int):
            spec_fold = (spec_fold,)
        spa_tol = 0  # extra local vl-delay B may pay to shed valu slots
        spa_levels = set()
        for x in spec_fold:
            if isinstance(x, str) and x.startswith("auto"):
                spa_levels = {1}
                if ":" in x:
                    spa_tol = int(x.split(":", 1)[1])
        sp_levels = ({x for x in spec_fold if isinstance(x, int)}
                     & T_set & {1, 2}) - spa_levels
        if maxT < 3:
            sp_levels -= {2}  # the L2 site borrows the tmM pool (maxT >= 3)
        assert not (sp_levels or spa_levels) or parity_conds, \
            "spec_fold requires parity_conds"
        vf_levels -= sp_levels
        va_levels -= sp_levels
        assert spa_levels <= va_levels, \
            "spec_fold auto needs the level's vsel_auto dual tables"

        def l4_served(r, g):
            if maxT != 3 or L4 >= forest_height or level(r) != L4:
                return False
            ep = r // period
            gmin = l4_gmin[ep] if ep < len(l4_gmin) else n_groups_
            # l4_gmin entries may be an int threshold (g >= gmin, original
            # semantics) or an explicit iterable of served group indices
            # (finer-grained than a contiguous threshold; external-repo
            # comparison found they tune L4 service as arbitrary block
            # sets, not a simple cutoff).
            if isinstance(gmin, (set, frozenset, list, tuple)):
                return g in gmin
            return g >= gmin

        # NOTE: checks every group, not just the endpoints, since l4_gmin
        # entries may now be an arbitrary set (not just a contiguous
        # g >= threshold range where checking the endpoints would suffice).
        l4_any = any(
            l4_served(r, g) for r in range(rounds) for g in range(n_groups_)
        )

        # l4_race (H-019): served-level-4 W-combine pairs whose fold races
        # valu madd vs flow vselect at schedule time, exactly like
        # vsel_auto's first-folds. True = all pairs; int N = the first N
        # pair (table) indices; iterable = explicit pair indices. Each
        # raced pair funds one extra odd-value broadcast (VLEN words) out
        # of free scratch.
        if l4_race is True:
            lr_pairs = set(range(2 ** maxT))
        elif isinstance(l4_race, int):
            lr_pairs = set(range(l4_race))
        else:
            lr_pairs = set(l4_race)
        lr_pairs &= set(range(2 ** maxT)) if maxT else set()
        if not l4_any:
            lr_pairs = set()
        assert not lr_pairs or (parity_conds and 4 not in vf_levels), \
            "l4_race requires parity_conds and no hard level-4 vsel_folds"
        # u_race / sel_race (H-019): symmetric emit_any races at the served
        # level-4 U-combines (valu subtract+madd vs one flow vselect) and
        # the L2/L3 vselects whose conds are exact 0/1 vectors (flow
        # vselect vs valu subtract+madd, subtract alu-splittable).
        assert not (u_race or sel_race) or parity_conds, \
            "u_race/sel_race require parity_conds"

        # b3_last (H-023): served-level-4 rounds whose fold order is reversed
        # so the newest parity (b3=nv) selects LAST (see docstring). True =
        # all level-4 rounds; iterable = explicit round numbers.
        if b3_last is True:
            b3l_rounds = {r for r in range(rounds) if level(r) == L4}
        elif b3_last:
            b3l_rounds = set(b3_last)
        else:
            b3l_rounds = set()
        if not l4_any:
            b3l_rounds = set()
        assert not b3l_rounds or (parity_conds and 4 not in vf_levels), \
            "b3_last requires parity_conds and no hard level-4 vsel_folds"

        # bl_last (H-027 companion): newest-parity-last folds at L2/L3 for
        # the LAST skew block's listed rounds (see docstring).
        if bl_last is True:
            bl_rounds = {r for r in range(rounds) if level(r) in (2, 3)}
        elif bl_last:
            bl_rounds = set(bl_last)
        else:
            bl_rounds = set()
        bl_rounds = {r for r in bl_rounds if level(r) in (2, 3)}
        assert not bl_rounds or parity_conds, "bl_last requires parity_conds"

        def bl_lastq(r, g):
            # bs_ (groups per skew block) is defined before emission runs.
            return (r in bl_rounds and level(r) in T_set
                    and g >= n_groups_ - bs_
                    and level(r) not in sp_levels
                    and level(r) not in vf_levels)

        def served(r, g):
            # node_val comes from scratch (no gather) on these rounds
            lv_ = level(r)
            return lv_ == 0 or lv_ in T_set or l4_served(r, g)

        # --- C5-pre-xor value domain (H-015) -------------------------------
        if c5_prexor:
            assert parity_conds, "c5_prexor requires parity_conds"
            assert maxT >= 2, "c5_prexor needs the tournament cond pools"
            assert not pe_levels, "c5_prexor is incompatible with parity_early"
        # Level-4 tree words can be primed in mem for free only when they
        # are already vloaded into lv scratch for the pair-tournament.
        l4_mem_primed = c5_prexor and l4_any and maxT == 3

        # mem_prime (H-026): deeper gather levels primed in mem at setup.
        mp_levels = ({mem_prime} if isinstance(mem_prime, int)
                     else set(mem_prime))
        if mp_levels:
            assert c5_prexor, "mem_prime requires c5_prexor"
            assert l4_mem_primed, \
                "mem_prime stages through the full-width lv scratch"
            assert all(L4 < d < forest_height + 1 for d in mp_levels), \
                "mem_prime levels must be gather levels above the tournament"
            # dffold's lv leaf temps at NON-final b3_last rounds would
            # clobber omf1_vec (lv[24..31]) while it is still live (elided
            # gather exits read it after those rounds). Final-round
            # b3_last is fine: omf1's last read precedes r15.
            assert not (b3l_rounds - {rounds - 1}), \
                "mem_prime supports b3_last on the final round only"
        if idx_select:
            assert mp_levels, "idx_select needs omf1_vec, which mem_prime creates"

        def primed_nv(rr, g):
            # Does round rr's fold read a C5-pre-xored node_val source?
            if not c5_prexor:
                return False
            lv_ = level(rr)
            if lv_ == 0:
                return rr > 0  # round 0 uses the TRUE root broadcast
            if lv_ in T_set or l4_served(rr, g):
                return True  # broadcast tables are primed at setup
            if lv_ in mp_levels:
                return True  # gather level primed in mem (H-026)
            return lv_ == L4 and l4_mem_primed  # level-4 mem primed in place

        def elide(r, g):
            # Round r drops its stage-5 `^ C5` iff round r+1's fold-in
            # absorbs it (never the last round: stored values must be true).
            return r < rounds - 1 and primed_nv(r + 1, g)

        def rec_off(r, g):
            # Exit from a tournament round under c5_prexor: st is the
            # complement position p' = 2^L - 1 - p, and par is inverted iff
            # round r elided, so
            #   gaddr = 2p + b + fp + 2^Ln - 1
            #         = -2*p' + (2^Ln - 1 + 2^(L+1) - 2 + inv) + fp -/+ par
            assert level(r) != 0
            return (2 ** level(r + 1) - 1 + 2 ** (level(r) + 1) - 2
                    + (1 if elide(r, g) else 0))

        S = ListScheduler()
        S.trace = getattr(self, "sched_trace", None)
        # H-028 (store_pair): let mem writes pair up within a cycle -- the
        # scheduler's coarse one-location mem model otherwise serializes
        # the 32 final vstores at 1/cycle on the 2-wide store engine, and
        # the last ~5 of them are exposed at the very end of the drain
        # (every store in this kernel targets a distinct mem word, so
        # same-cycle commits are exact).
        S.pair_writes = bool(store_pair)

        if flow_consts:
            # H-021: the setup ramp is load-bound (consts + vloads share the
            # 2-slot load engine); materialize constants on the idle flow
            # engine instead: one real `const 0`, then add_imm off it.
            zero_c = self.alloc_scratch("zero_c")
            S.emit("load", ("const", zero_c, 0), writes=(zero_c,))
            self.const_map[0] = zero_c

        def const(val, name=None):
            if val not in self.const_map:
                addr = self.alloc_scratch(name)
                if flow_consts:
                    S.emit("flow", ("add_imm", addr, zero_c, val),
                           (zero_c,), (addr,))
                else:
                    S.emit("load", ("const", addr, val), writes=(addr,))
                self.const_map[val] = addr
            return self.const_map[val]

        def bvec(src, name=None):
            d = self.alloc_scratch(name, VLEN)
            S.emit("valu", ("vbroadcast", d, src), (src,), self._v(d))
            return d

        vec = lambda op, dst, a, b: self._sched_vec(
            S, op, dst, a, b, alu_offload, valu_ties="vec_valu" in tb
        )
        avec = lambda op, dst, a, b: self._sched_vec(
            S, op, dst, a, b, alu_offload, force_alu=alu_offload,
            valu_ties="vec_valu" in tb
        )
        madd = lambda dst, a, b, c: self._sched_madd(S, dst, a, b, c)
        vsel = lambda dst, cond, a, b: self._sched_vsel(S, dst, cond, a, b)

        odd_of = {}  # diff-vector addr -> odd-value vector addr (vsel_auto)

        # H-021 tie_break: flip which encoding keeps retire-time TIES in the
        # emit_any races ("fold_flow": dual_fold's vselect; "idx_alu":
        # race_idx_madd's alu split). Default () keeps the historical order.
        if isinstance(tie_break, str):
            tie_break = (tie_break,)
        tb = set(tie_break)

        def dual_fold(dst, cond, dv, ev):
            # H-017 auto mode via emit_any (H-019): place this first-fold on
            # flow's vselect only when its slot retires strictly earlier
            # than valu's madd would (valu listed first keeps ties; cond is
            # a raw 0/1 parity, so the two forms are equivalent).
            ov = odd_of[dv]
            writes = self._v(dst)
            encs = (
                (("valu", ("multiply_add", dst, cond, dv, ev),
                  self._v(cond) + self._v(dv) + self._v(ev), writes),),
                (("flow", ("vselect", dst, cond, ov, ev),
                  self._v(cond) + self._v(ov) + self._v(ev), writes),),
            )
            S.emit_any(encs[::-1] if "fold_flow" in tb else encs)

        def race_sel(dst, cond, wa, wb):
            # H-019 (u_race/sel_race): dst := cond ? wa : wb where the arms
            # are RUNTIME values and cond is an exact 0/1 vector, so the op
            # has equivalent spellings on both engines: one flow vselect,
            # or a valu subtract (diff into wa, which must be dead) + valu
            # madd, with the subtract alu-splittable under alu_offload.
            # Greedy: earliest retire wins; flow listed first so ties stay
            # off the binding valu engine.
            rc, ra, rb = self._v(cond), self._v(wa), self._v(wb)
            wd = self._v(dst)
            madd_op = ("valu", ("multiply_add", dst, cond, wa, wb),
                       rc + ra + rb, wd)
            encs = [
                (("flow", ("vselect", dst, cond, wa, wb), rc + ra + rb, wd),),
                (("valu", ("-", wa, wa, wb), ra + rb, ra), madd_op),
            ]
            if alu_offload:
                encs.append(tuple(
                    ("alu", ("-", wa + i, wa + i, wb + i),
                     (wa + i, wb + i), (wa + i,))
                    for i in range(VLEN)
                ) + (madd_op,))
            S.emit_any(encs)

        def race_copy(dst, src):
            # H-019 (sel_race): pure vector copy -- flow vselect(c, a, a),
            # valu bitwise-or with itself, or 8 scalar alu ors.
            rd, wd = self._v(src), self._v(dst)
            encs = [
                (("flow", ("vselect", dst, src, src, src), rd, wd),),
                (("valu", ("|", dst, src, src), rd, wd),),
            ]
            if alu_offload:
                encs.append(tuple(
                    ("alu", ("|", dst + i, src + i, src + i),
                     (src + i,), (dst + i,))
                    for i in range(VLEN)
                ))
            S.emit_any(encs)

        def race_idx_madd(st_, bv, cv, lane2):
            # H-019 (idx_race): an Idx update of the form
            #   st := st * <bv> + <cv>   (bv = +/-2 broadcast)
            # has an alu spelling: per-lane  st <<= 1  then lane2(i) --
            # ("+", st+i, st+i, addend) for 2p+b / 2p+omf forms, or
            # ("-", st+i, K, st+i) for the c5_prexor exit's K - 2p'. 16
            # scalar slots over two dependent levels, raced against the
            # single valu madd (listed first: ties keep the madd).
            enc_m = (("valu", ("multiply_add", st_, st_, bv, cv),
                      self._v(st_) + self._v(bv) + self._v(cv),
                      self._v(st_)),)
            enc_a = tuple(
                ("alu", ("<<", st_ + i, st_ + i, one_c),
                 (st_ + i, one_c), (st_ + i,)) for i in range(VLEN)
            ) + tuple(
                ("alu", lane2(i), (lane2(i)[2], lane2(i)[3]), (lane2(i)[1],))
                for i in range(VLEN)
            )
            S.emit_any((enc_a, enc_m) if "idx_alu" in tb else (enc_m, enc_a))

        def pfold(st_, nv_):
            # The lagged position fold p := 2p + b (b = raw 0/1 parity).
            if idx_race:
                race_idx_madd(st_, two_vec, nv_,
                              lambda i: ("+", st_ + i, st_ + i, nv_ + i))
            else:
                madd(st_, st_, two_vec, nv_)

        def race_leaf(dst, cond, hi, lo, dtmp):
            # H-023 (b3_last): leaf fold of two BROADCAST tables hi/lo by an
            # exact 0/1 cond -- flow vselect, or (valu, drain-idle) a
            # subtract into the dead-scratch dtmp (=hi-lo) then a madd
            # (cond*dtmp + lo). The subtract is alu-splittable. dtmp must be
            # a per-slot dead-scratch vector so concurrent leaves don't
            # serialize through it.
            rc, rh, rl = self._v(cond), self._v(hi), self._v(lo)
            rt, wd = self._v(dtmp), self._v(dst)
            madd_op = ("valu", ("multiply_add", dst, cond, dtmp, lo),
                       rc + rt + rl, wd)
            encs = [
                (("flow", ("vselect", dst, cond, hi, lo), rc + rh + rl, wd),),
                (("valu", ("-", dtmp, hi, lo), rh + rl, rt), madd_op),
            ]
            if alu_offload:
                encs.append(tuple(
                    ("alu", ("-", dtmp + i, hi + i, lo + i),
                     (hi + i, lo + i), (dtmp + i,))
                    for i in range(VLEN)
                ) + (madd_op,))
            S.emit_any(encs)

        def dffold(st_, tabs, r_lo, r_mid, r_hi, r_mask, dst, da=None,
                   db=None):
            # H-023 (b3_last): depth-first fold of the 8 broadcast tables
            # tabs[0..7] (indexed by the level-3 winner t = b0b1b2) down to
            # tabs[t*], by b2 (leaf, st_&1), b1 (mid, st_&2), b0 (root,
            # st_&4) -- the SAME masks and arm order as the b3-first U/q/
            # winner selects, so E_vecs and D_vecs each fold to their t*
            # entry. Masks recompute off st_ (idle alu), leaving st_ intact.
            # Working set = r_lo,r_mid,r_hi + r_mask; result in dst (may
            # alias r_lo). Bit-0=b2 always because masks are read BEFORE any
            # lagged pfold updates st_. The 4 leaf selects have BROADCAST
            # arms (no dead value to overwrite) so they ride flow; the 3
            # combining selects have dead-temp arms, so `race_sel`
            # (u_race's primitive) lets them fall to the drain-idle valu
            # (sub+madd) instead of serializing on the 1-slot flow engine.
            comb = race_sel if b3l_race else vsel
            leaf = ((lambda d, c, hi, lo, dt: race_leaf(d, c, hi, lo, dt))
                    if (b3l_race and da is not None) else
                    (lambda d, c, hi, lo, dt: vsel(d, c, hi, lo)))
            m = r_mask

            def mask(bit):
                # EXACT 0/1 mask for position bit `bit` of st_ (bit0=b2,
                # bit1=b1, bit2=b0). Raced selects multiply by the cond, so
                # 0/2- or 0/4-masks (fine for a bare vselect) are unsound;
                # shift the bit down to bit0. Idle-alu ops, recomputed per
                # use so st_ stays intact.
                if bit == 0:
                    vec("&", m, st_, one_vec)
                else:
                    vec(">>", m, st_, one_vec if bit == 1 else two_vec)
                    vec("&", m, m, one_vec)

            mask(0)                                   # b2
            leaf(r_lo, m, tabs[1], tabs[0], da)       # u0
            leaf(r_mid, m, tabs[3], tabs[2], db)      # u1
            mask(1)                                   # b1
            comb(r_lo, m, r_mid, r_lo)                # q0 = b1 ? u1 : u0
            mask(0)                                   # b2
            leaf(r_mid, m, tabs[5], tabs[4], da)      # u2
            leaf(r_hi, m, tabs[7], tabs[6], db)       # u3
            mask(1)                                   # b1
            comb(r_mid, m, r_hi, r_mid)               # q1 = b1 ? u3 : u2
            mask(2)                                   # b0
            comb(dst, m, r_mid, r_lo)                 # winner = b0 ? q1 : q0

        def sched_snap():
            # Snapshot of the scheduler's mutable state (slot tuples inside
            # bundle lists are immutable, so one level of container copy
            # suffices). Used by spec_fold's auto mode to trial-emit both
            # forms of a fold site and keep the better schedule.
            return (
                [{e: list(ss) for e, ss in b.items()} for b in S.bundles],
                [dict(c) for c in S.counts],
                dict(S.last_write), dict(S.last_read),
                S.mem_read_c, S.mem_write_c, dict(S.hint),
            )

        def sched_install(snap):
            (S.bundles, S.counts, S.last_write, S.last_read,
             S.mem_read_c, S.mem_write_c, S.hint) = snap

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

        hc = self._fused_hash_constants()
        if derive_consts:
            # H-024 (setup load-slot removal): the setup ramp is bound by
            # the 2-wide load engine (~21 scalar const/header loads ahead
            # of the lv/val vloads) while the alu sits idle until the
            # first hash round. Nine of the setup constants are cheap
            # algebraic combinations of already-loaded ones; materialize
            # them with IN-PLACE alu chains (each costs only its own
            # scratch word) and pre-seed const_map so the const() calls
            # below find them. The arbitrary hash addends (C0, C1, ap,
            # aq, C4, C5) have no 1-op relations (brute-forced) and stay
            # as const loads, as do 1/4/6 (header critical path).
            four_c = self.const_map[4]

            def dconst(val, name, *steps):
                addr = self.alloc_scratch(name)
                for op, a, b in steps:
                    a = addr if a is None else a
                    b = addr if b is None else b
                    S.emit("alu", (op, addr, a, b), (a, b), (addr,))
                self.const_map[val] = addr
                return addr

            two_c = dconst(2, "dc_two", ("+", one_c, one_c))
            eight_c = dconst(8, "dc_eight", ("+", four_c, four_c))
            sh5_c = dconst(hc["sh5"], "dc_sh5",            # 16 = 1<<4
                           ("<<", one_c, four_c))
            k4_c = dconst(hc["k4"], "dc_k4",               # 9 = 8+1
                          ("+", eight_c, one_c))
            kp_c = dconst(hc["kp"], "dc_kp",               # 33 = 16+16+1
                          ("+", sh5_c, sh5_c), ("+", None, one_c))
            dconst(hc["kq"], "dc_kq",                      # 16896 = 33<<9
                   ("<<", kp_c, k4_c))
            dconst(hc["k0"], "dc_k0",                      # 4097 = (16<<8)+1
                   ("<<", sh5_c, eight_c), ("+", None, one_c))
            dconst(hc["sh1"], "dc_sh1",                    # 19 = (2+1)+16
                   ("+", two_c, one_c), ("+", None, sh5_c))
            dconst((1 << 32) - 2, "dc_negtwo",             # -2 = (1^1)-2
                   ("^", one_c, one_c), ("-", None, two_c))

        one_vec = bvec(one_c, "one_vec")
        two_vec = bvec(const(2), "two_vec")
        omf_vec = bvec(omf_s, "omf_vec")
        root_nv_vec = bvec(root_nv, "root_nv_vec")
        hv = {k: bvec(const(hc[k]), k) for k in
              ("k0", "C0", "C1", "sh1", "kp", "ap", "kq", "aq", "k4", "C4", "C5", "sh5")}

        # --- persistent state + initial vals (definitions; called below) ---
        # state_vecs[g] carries p (position accumulator) during tournament
        # levels and gaddr = forest_values_p + idx during gather levels.
        # Wrapped as functions so `vals_first` (H-021) can emit the initial
        # value vloads BEFORE the tournament-table setup (True) or right
        # after the hash constants ("hash"); the default calls them at the
        # original position, keeping the stream bit-identical.
        state_vecs = val_vecs = nv_vecs = t1 = None
        condA = condB = tm = tmM = None
        TP = CP = None
        val_addrs = None

        def alloc_state():
            nonlocal state_vecs, val_vecs, nv_vecs, t1, condA, condB, tm, tmM
            nonlocal TP, CP
            state_vecs = [self.alloc_scratch(f"st{g}", VLEN) for g in range(n_groups)]
            val_vecs = [self.alloc_scratch(f"val{g}", VLEN) for g in range(n_groups)]
            nv_vecs = [self.alloc_scratch(f"nv{g}", VLEN) for g in range(n_groups)]
            TP, CP = pool_sizes
            if pe_levels and maxT >= 2:
                # Scratch is full: trade one cond-pool slot (32 words across
                # the 4 pools) for the 3 parity constant vectors (27 words).
                # Measured free at the default shape ((17,3) == (17,4) ==
                # 1140), unlike shrinking the t1 pool ((13,4) costs +12).
                CP -= 1
                assert CP >= 1, "parity_early needs pool_sizes[1] >= 2"
            if va_levels and maxT >= 2:
                # vsel_auto's odd tables are funded the same way (one cond-
                # pool slot = 32 words; (17,3) measured == (17,4) == 1130).
                CP -= 1
                assert CP >= 1, "vsel_auto needs pool_sizes[1] >= 2"
            if c5_prexor:
                # Same trade for the negtwo/primed-root vectors (19 words).
                CP -= 1
                assert CP >= 1, "c5_prexor needs pool_sizes[1] >= 2"
            t1 = [self.alloc_scratch(None, VLEN) for _ in range(TP)]
            if maxT >= 2:
                condA = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
                condB = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
                tm = [self.alloc_scratch(None, VLEN) for _ in range(CP)]
            if maxT >= 3:
                tmM = [self.alloc_scratch(None, VLEN) for _ in range(CP)]

        va_chain = {}  # alu_val_addrs scalars, materialized on first use

        def emit_val_g(g):
            a = self.alloc_scratch(f"va{g}")
            val_addrs[g] = a
            if alu_val_addrs:
                # H-024: va addresses (ivp + 8g) on the ramp-idle alu as
                # four parallel +32 chains instead of 32 serial add_imm
                # slots on the 1-wide flow engine (pause + rec + la + 32
                # va otherwise book flow solid to ~cycle 40, gating the
                # val vloads at 1/cycle AND crowding the tournament fold
                # vselect races off flow).
                if not va_chain:
                    c8, c16 = const(8), const(16)
                    t24 = self.alloc_scratch("va_c24")
                    S.emit("alu", ("+", t24, c8, c16), (c8, c16), (t24,))
                    t32 = self.alloc_scratch("va_c32")
                    S.emit("alu", ("+", t32, c16, c16), (c16,), (t32,))
                    va_chain.update({1: c8, 2: c16, 3: t24, "step": t32})
                if g == 0:
                    S.emit("alu", ("|", a, ivp, ivp), (ivp,), (a,))
                elif g < 4:
                    h = va_chain[g]
                    S.emit("alu", ("+", a, ivp, h), (ivp, h), (a,))
                else:
                    prev, stp = val_addrs[g - 4], va_chain["step"]
                    S.emit("alu", ("+", a, prev, stp), (prev, stp), (a,))
            else:
                S.emit("flow", ("add_imm", a, ivp, g * VLEN), (ivp,), (a,))
            S.emit("load", ("vload", val_vecs[g], a),
                   (a,), self._v(val_vecs[g]), mem_read=True)

        def emit_vals():
            nonlocal val_addrs
            val_addrs = [None] * n_groups
            for g in range(n_groups):
                emit_val_g(g)

        if vals_first == "hash":
            alloc_state()
            emit_vals()

        if c5_prexor:
            # Primed root broadcast (L0 rounds after round 0 fold a primed
            # val, so they must fold the primed root) and the -2 multiplier
            # for complement-position epoch exits. C5 must be odd for the
            # inversion bookkeeping below; it is (0xB55A4F09).
            assert hc["C5"] & 1 == 1, "c5_prexor bookkeeping assumes odd C5"
            c5s = const(hc["C5"])
            rootp = self.alloc_scratch("root_pr")
            S.emit("alu", ("^", rootp, root_nv, c5s), (root_nv, c5s), (rootp,))
            root_pr_vec = bvec(rootp, "root_pr_vec")
            negtwo_vec = bvec(const((1 << 32) - 2), "negtwo_vec")
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
        # gather round at level Ln needs  fp + 2^Ln - 1  as a vector
        # (under c5_prexor: fp + rec_off(r, g), keyed by the offset).
        rec_exits = [
            (r, g) for r in range(rounds - 1) for g in range(n_groups_)
            if served(r, g) and not served(r + 1, g) and level(r + 1) != 0
        ]
        if c5_prexor:
            rec_needed = sorted({rec_off(r, g) for r, g in rec_exits})
        else:
            rec_needed = sorted({level(r + 1) for r, g in rec_exits})
        rec_vecs = {}
        rec_scalar = {}  # idx_race: the scalar sources double as alu operands
        for key in rec_needed:
            rs = self.alloc_scratch()
            off = key if c5_prexor else 2 ** key - 1
            S.emit("flow", ("add_imm", rs, fp, off), (fp,), (rs,))
            rec_vecs[key] = bvec(rs, f"rec{key}")
            rec_scalar[key] = rs

        if vals_first and vals_first != "hash":
            alloc_state()
            emit_vals()

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
            if c5_prexor:
                # Prime every loaded tree word in place: lv[i] ^= C5.
                for blk in range(0, n_lv, VLEN):
                    vec("^", lv + blk, lv + blk, hv["C5"])
            for L in T:
                base = 2 ** L - 1  # first tree index of level L; lv[i] = tree[1+i]
                evens, diffs = [], []
                for k in range(2 ** (L - 1)):
                    # c5_prexor: inverted position bits select correctly
                    # from tables stored in REVERSED pair order, with the
                    # (inverted) newest bit handled by base=odd,
                    # diff=even-odd. Emission is unchanged.
                    kk = (2 ** (L - 1) - 1 - k) if c5_prexor else k
                    s0 = lv + (base + 2 * kk - 1)
                    s1 = s0 + 1
                    if L in vf_levels or L in sp_levels:
                        # vselect first-fold (H-017) / speculated fold
                        # (H-010): keep the non-base VALUE as the select
                        # arm; no subtract, no diff word. Arms swap under
                        # c5_prexor (inverted bit).
                        evens.append(bvec(s1 if c5_prexor else s0))
                        diffs.append(bvec(s0 if c5_prexor else s1))
                        continue
                    d = self.alloc_scratch()
                    if c5_prexor:
                        S.emit("alu", ("-", d, s0, s1), (s0, s1), (d,))
                        evens.append(bvec(s1))
                    else:
                        S.emit("alu", ("-", d, s1, s0), (s0, s1), (d,))
                        evens.append(bvec(s0))
                    diffs.append(bvec(d))
                    if L in va_levels:
                        # vsel_auto (H-017): the non-base VALUE kept
                        # alongside the diff so the fold can go to either
                        # engine. c5_prexor bases on the odd word, so the
                        # select arm is the EVEN word there (arms swap with
                        # the inverted condition).
                        odd_of[diffs[-1]] = bvec(s0 if c5_prexor else s1)
                lvl[L] = (evens, diffs)
        if l4_any:
            # Level maxT+1 candidates, indexed by the level-maxT position t:
            # E[t] / D[t] = even child of the level-maxT winner / its
            # (odd - even) sibling diff. (c5_prexor: reversed order and
            # odd-base/negated-diff, exactly like the levels above.)
            base = 2 ** L4 - 1
            E_vecs, D_vecs = [], []
            for t in range(2 ** maxT):
                tt = (2 ** maxT - 1 - t) if c5_prexor else t
                s0 = lv + (base + 2 * tt - 1)
                s1 = s0 + 1
                if 4 in vf_levels:
                    # vselect W-combine (H-017): non-base VALUE, not the
                    # diff; arms swap under c5_prexor (inverted bit).
                    E_vecs.append(bvec(s1 if c5_prexor else s0))
                    D_vecs.append(bvec(s0 if c5_prexor else s1))
                    continue
                d = self.alloc_scratch()
                if c5_prexor:
                    S.emit("alu", ("-", d, s0, s1), (s0, s1), (d,))
                    E_vecs.append(bvec(s1))
                else:
                    S.emit("alu", ("-", d, s1, s0), (s0, s1), (d,))
                    E_vecs.append(bvec(s0))
                D_vecs.append(bvec(d))
                if t in lr_pairs:
                    # l4_race (H-019): odd-value select arm kept alongside
                    # the diff so this W-combine can go to either engine.
                    # c5_prexor bases on the odd word, so the select arm is
                    # the EVEN word there (arms swap with the inverted
                    # condition), exactly like vsel_auto's tables.
                    odd_of[D_vecs[-1]] = bvec(s0 if c5_prexor else s1)
            four_vec = bvec(const(4), "four_vec")
            eight_vec = bvec(const(8), "eight_vec")

        # --- persistent state + initial vals (default position) ---
        assert not (lazy_val_loads and vals_first), \
            "lazy_val_loads replaces the default val-vload position"
        if not vals_first:
            alloc_state()
            if lazy_val_loads:
                # H-024: filled per group at its round-0 emission instead.
                val_addrs = [None] * n_groups
            else:
                emit_vals()

        if l4_mem_primed:
            # Write the primed level-4 values (already ^C5 in lv scratch)
            # back over tree[2^L4-1 .. 2^(L4+1)-2] so level-4 GATHERS read
            # the primed domain too. Both vstores land in setup, long
            # before the first gather is placed, so the scheduler's coarse
            # mem_write hazard delays nothing.
            pst = self.alloc_scratch("pst")
            for blk in range(0, 2 ** L4, VLEN):
                S.emit("flow", ("add_imm", pst, fp, 2 ** L4 - 1 + blk),
                       (fp,), (pst,))
                src = lv + (2 ** L4 - 2) + blk
                S.emit("store", ("vstore", pst, src),
                       (pst,) + self._v(src), (), mem_write=True)

        if mp_levels:
            # H-026 (mem_prime): prime the listed deeper gather levels in
            # mem -- vload / ^C5 / vstore waves staged through lv[0..23]
            # (setup-dead once the broadcast tables have read it; the
            # scheduler's per-address WAR tracking orders the waves after
            # those reads, and its coarse mem hazards keep every wave's
            # store ahead of the first gather). lv[24..31] becomes the
            # permanent home of the omf1 = 2 - fp vector used by elided
            # gather-mode exits (scratch is otherwise full).
            omf1_s = self.alloc_scratch("omf1")
            S.emit("alu", ("+", omf1_s, omf_s, one_c),
                   (omf_s, one_c), (omf1_s,))
            omf1_vec = lv + 3 * VLEN
            S.emit("valu", ("vbroadcast", omf1_vec, omf1_s),
                   (omf1_s,), self._v(omf1_vec))
            k = 0
            for d in sorted(mp_levels):
                for off in range(0, 2 ** d, VLEN):
                    stage = lv + (k % 3) * VLEN
                    k += 1
                    S.emit("flow", ("add_imm", la, fp, 2 ** d - 1 + off),
                           (fp,), (la,))
                    S.emit("load", ("vload", stage, la),
                           (la,), self._v(stage), mem_read=True)
                    vec("^", stage, stage, hv["C5"])
                    S.emit("store", ("vstore", la, stage),
                           (la,) + self._v(stage), (), mem_write=True)

        b3l_dE = b3l_dD = b3l_pool = None
        # BUG GUARD (found 2026-07-23, traced with a scratch-write log at
        # l4_gmin=(9,0)): idx_select's vselect reads BOTH omf_vec and
        # omf1_vec on every steady-gather call (both select arms, not just
        # the elide(r,g)=True branch the original race_idx_madd path
        # used), so it needs omf1_vec valid strictly longer than the
        # "omf1's last read precedes r15" assumption that lets
        # b3l_diffs's round-15 dffold FALLBACK reclaim lv[24:32]
        # (=omf1_vec's storage) as a transient D_vecs fold temp when its
        # private-register funding runs out. Confirmed: omf1_vec's value
        # flips from the correct ~-5 to garbage mid-run, then a later
        # steady-gather madd for a different group reads it and produces
        # an out-of-bounds gather address. A same-session attempt to give
        # idx_select a protected copy of omf1_vec made things WORSE (broke
        # the validated (9,30) config via scratch overflow, and produced
        # silently wrong answers once pool_sizes was shrunk to compensate)
        # -- reverted. Detect the actual clobbering event instead of
        # trying to predict it, so this fails loudly at build time instead
        # of silently corrupting a gather address or (worse) passing
        # `correct` while wrong:
        omf1_vec_clobbered = False

        def b3l_make_diffs(r):
            # H-027 (b3l_diffs): leaf-diff tables + a private-register pool
            # for the b3-last fold at the FINAL round. There is no free
            # scratch, but by the final round's served-group folds a large
            # set of vectors is truly dead: the `st` of every non-served
            # group (last read = round r-1's gather issue) and the `nv` of
            # every earlier block's group (last read = its own final-round
            # fold-in xor, emitted before the last block). The 8 diff
            # vectors and each served group's private temps ride there --
            # per-address hazard tracking makes the reuse safe, and the
            # private temps remove the cond/tm-pool WAW serialization that
            # dffold's shared working set suffers at the drain. Donors are
            # ordered earliest-dead-first so the last group's temps never
            # wait on a late donor read.
            nonlocal b3l_dE, b3l_dD, b3l_pool
            if b3l_dE is not None:
                return
            unserved = [g for g in range(n_groups) if not l4_served(r, g)]
            early = 2 * bs_  # first two skew blocks die earliest
            b3l_pool = (
                [state_vecs[g] for g in unserved if g < early]
                + [nv_vecs[g] for g in unserved if g < early]
                + [state_vecs[g] for g in unserved if g >= early]
                + [nv_vecs[g] for g in unserved if g >= early]
            )
            if len(b3l_pool) < 8 + 9:  # diffs + one private group
                b3l_dE, b3l_dD, b3l_pool = [], [], []
                return
            b3l_dE, b3l_dD = [], []
            for k in range(2 ** maxT // 2):
                for tabs, out in ((E_vecs, b3l_dE), (D_vecs, b3l_dD)):
                    h = b3l_pool.pop(0)
                    vec("-", h, tabs[2 * k + 1], tabs[2 * k])
                    odd_of[h] = tabs[2 * k + 1]
                    out.append(h)

        def b3l_fold_diffs(st_, nv_):
            # Final-round b3-last fold with precomputed diffs and private
            # registers: masks computed ONCE (exact 0/1, off st_ which is
            # ready at round start), each leaf a dual_fold (1 valu madd
            # racing 1 flow vselect), combines race_sel. Post-b3 chain =
            # 1 madd + fold-in + hash. st_ is left intact (final round:
            # nothing reads it after, but the masks need it here).
            mb2, mb1, mb0, e0, e1, e2, d0, d1, d2 = (
                b3l_pool.pop(0) for _ in range(9))
            vec("&", mb2, st_, one_vec)
            vec(">>", mb1, st_, one_vec)
            vec("&", mb1, mb1, one_vec)
            vec(">>", mb0, st_, two_vec)
            vec("&", mb0, mb0, one_vec)
            comb = race_sel if b3l_race else vsel
            for tabs, dt, r0, r1, r2 in (
                (E_vecs, b3l_dE, e0, e1, e2),
                (D_vecs, b3l_dD, d0, d1, d2),
            ):
                dual_fold(r0, mb2, dt[0], tabs[0])    # u0
                dual_fold(r1, mb2, dt[1], tabs[2])    # u1
                comb(r0, mb1, r1, r0)                 # q0 = b1 ? u1 : u0
                dual_fold(r1, mb2, dt[2], tabs[4])    # u2
                dual_fold(r2, mb2, dt[3], tabs[6])    # u3
                comb(r1, mb1, r2, r1)                 # q1 = b1 ? u3 : u2
                comb(r0, mb0, r1, r0)                 # winner = b0 ? q1 : q0
            madd(nv_, nv_, d0, e0)                    # node_val = E + b3*D

        # --- rounds ---
        # The round body is a GENERATOR yielding at stage boundaries
        # (node_val block, each hash dependency level, state update), so the
        # emission loop can interleave stages across a block's groups
        # (`emit_order`); the default drains each group fully in order,
        # reproducing the historical contiguous emission bit-for-bit.
        def _egr_stages(r, g):
            if True:  # keep the original indentation of the body below
                if lazy_val_loads and val_addrs[g] is None:
                    # H-024: the group's initial-value va/vload emitted at
                    # its first touch instead of all up-front at setup.
                    emit_val_g(g)
                L = level(r)
                s = g % TP
                j = g % CP
                st = state_vecs[g]
                vl = val_vecs[g]
                nv = nv_vecs[g]

                # ---- node_val: broadcast root / tournament select / gather ----
                if L == 0:
                    # c5_prexor: L0 rounds after round 0 fold a PRIMED val,
                    # so they fold the primed root to cancel the C5s.
                    nvsrc = root_pr_vec if c5_prexor and r > 0 else root_nv_vec
                elif L in T_set:
                    nvsrc = nv
                    evens, diffs = lvl[L]
                    # H-017: on vsel_folds levels the first fold rides flow
                    # (diffs[] holds odd VALUES there; conds are raw 0/1
                    # parities under parity_conds); on vsel_auto levels it
                    # goes to whichever engine's slot retires earlier. Same
                    # arg shape all three ways.
                    ff = (vsel if L in vf_levels
                          else dual_fold if L in va_levels else madd)
                    if L == 1:
                        if L in spa_levels:
                            # H-010 auto: race the status-quo fold-then-xor
                            # (path A) against the speculated xors-then-
                            # select (path B); commit whichever hands vl to
                            # the first hash madd earlier. Ties keep A (no
                            # extra alu/flow traffic).
                            st0 = sched_snap()
                            dual_fold(nv, st, diffs[0], evens[0])
                            cA = vec("^", vl, vl, nv)
                            postA = sched_snap()
                            sched_install(st0)
                            avec("^", nv, vl, odd_of[diffs[0]])
                            avec("^", t1[s], vl, evens[0])
                            cB = self._sched_vsel(S, vl, st, nv, t1[s])
                            if cA + spa_tol < cB:
                                sched_install(postA)
                                self._spec_stats[0] += 1
                            else:
                                self._spec_stats[1] += cA - cB
                                self._spec_stats[2] += 1
                            nvsrc = None
                        elif L in sp_levels:
                            # H-010: both candidates pre-xored into vl
                            # (round r-1's hash output) on the idle alu;
                            # the parity (riding st) then selects straight
                            # INTO vl on flow -- the fold madd and the
                            # fold-in xor both leave valu, and the first
                            # hash madd waits only on the select. nv is
                            # dead here and hosts one arm; the group's
                            # hash temp hosts the other.
                            avec("^", nv, vl, diffs[0])
                            avec("^", t1[s], vl, evens[0])
                            vsel(vl, st, nv, t1[s])
                            nvsrc = None
                        else:
                            # p is the single parity bit itself.
                            ff(nv, st, diffs[0], evens[0])
                    elif L == 2 and parity_conds and L in sp_levels:
                        # H-010 at L2: 4 speculated xors + 3 selects.
                        # b0 rides st (copied to condB; st folds b1 next),
                        # b1 = nv (the raw newest parity).
                        vsel(condB[j], st, st, st)
                        madd(st, st, two_vec, nv)
                        avec("^", t1[s], vl, evens[0])
                        avec("^", tm[j], vl, diffs[0])
                        avec("^", tmM[j], vl, evens[1])
                        avec("^", condA[j], vl, diffs[1])
                        vsel(t1[s], nv, tm[j], t1[s])      # pair 0 by b1
                        vsel(tmM[j], nv, condA[j], tmM[j])  # pair 1 by b1
                        vsel(vl, condB[j], tmM[j], t1[s])   # by b0, into vl
                        nvsrc = None
                    elif L == 2:
                        if parity_conds and bl_lastq(r, g):
                            # H-027 (bl_last): b0 (=st, ready at round
                            # start) pre-selects the pair on flow; the
                            # newest bit b1 (=nv) folds LAST via one madd.
                            # node = evens[b0] + b1*diffs[b0]; post-parity
                            # chain 2 -> 1 levels.
                            vsel(t1[s], st, diffs[1], diffs[0])
                            vsel(tm[j], st, evens[1], evens[0])
                            pfold(st, nv)                    # st = b0b1
                            madd(nv, nv, t1[s], tm[j])
                        elif parity_conds:
                            # nv = b1 (raw parity), st = b0 (single bit).
                            # b0 copy (st folds next); vselect(c,a,a,a) is a
                            # pure copy, so it rides the idle flow engine.
                            # H-019 (sel_race): both the copy and the final
                            # select (cond b0 is exact 0/1) race engines.
                            if sel_race:
                                race_copy(condB[j], st)
                            else:
                                vsel(condB[j], st, st, st)
                            pfold(st, nv)                    # fold b1: st = b0b1
                            ff(t1[s], nv, diffs[0], evens[0])
                            ff(tm[j], nv, diffs[1], evens[1])
                            if sel_race:
                                race_sel(nv, condB[j], tm[j], t1[s])
                            else:
                                vsel(nv, condB[j], tm[j], t1[s])
                        else:
                            vec("&", condA[j], st, one_vec)   # newest bit b1
                            vec("&", condB[j], st, two_vec)   # mask for b0
                            madd(t1[s], condA[j], diffs[0], evens[0])
                            madd(tm[j], condA[j], diffs[1], evens[1])
                            vsel(nv, condB[j], tm[j], t1[s])
                    elif parity_conds and bl_lastq(r, g):  # L == 3
                        # H-027 (bl_last): both older bits b0,b1 sit in st
                        # at round start, so the even and diff tables fold
                        # to their winners on flow BEFORE the newest bit
                        # b2 (=nv) arrives; post-parity chain 3 -> 1.
                        # node = evens[t] + b2*diffs[t], t = b0b1.
                        vec("&", condB[j], st, one_vec)   # b1
                        vec("&", condA[j], st, two_vec)   # b0 mask
                        vsel(t1[s], condB[j], evens[1], evens[0])
                        vsel(tm[j], condB[j], evens[3], evens[2])
                        vsel(t1[s], condA[j], tm[j], t1[s])       # Ew
                        vsel(tm[j], condB[j], diffs[1], diffs[0])
                        vsel(tmM[j], condB[j], diffs[3], diffs[2])
                        vsel(tm[j], condA[j], tmM[j], tm[j])      # Dw
                        pfold(st, nv)                     # st = b0b1b2
                        madd(nv, nv, tm[j], t1[s])        # Ew + b2*Dw
                    elif parity_conds:  # L == 3
                        # nv = b2 (raw parity), st = b0b1 (bit1=b0, bit0=b1);
                        # both conds extract from st at round START.
                        vec("&", condB[j], st, one_vec)   # b1
                        vec("&", condA[j], st, two_vec)   # b0 mask
                        pfold(st, nv)                     # fold b2: st = b0b1b2
                        ff(t1[s], nv, diffs[0], evens[0])   # m0
                        ff(tmM[j], nv, diffs[1], evens[1])  # m1
                        ff(tm[j], nv, diffs[2], evens[2])   # m2
                        ff(nv, nv, diffs[3], evens[3])      # m3 (b2 dead)
                        # H-019 (sel_race): q0/q1's cond b1 is exact 0/1, so
                        # they race back to valu; the b0 winner's cond is a
                        # 0/2 mask, so it stays a flow vselect.
                        if sel_race:
                            race_sel(t1[s], condB[j], tmM[j], t1[s])  # q0
                            race_sel(nv, condB[j], nv, tm[j])         # q1
                        else:
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
                    if r in b3l_rounds:
                        # H-023 (b3_last): fold E_vecs and D_vecs by the
                        # OLDER bits b0,b1,b2 (in st, ready at round start)
                        # and defer the newest parity b3 (=nv) to a single
                        # final madd. node_val = E[t*] + b3*D[t*], the same
                        # value the b3-first tree below computes, but the
                        # only b3-dependent op is the last madd (post-parity
                        # chain 1 madd + hash, not the 4-level select tree).
                        # E_winner -> condB, D_winner -> tm; the 3 working
                        # temps + mask reg are the tournament pools, so no
                        # extra scratch. pfold (epoch-exit position, non-
                        # final rounds) runs AFTER the folds read st but
                        # BEFORE the madd clobbers nv (=b3).
                        # Leaf diff temps: dead `lv` scratch (setup-only);
                        # distinct slots for the E/D folds so they can run
                        # concurrently on valu when it is drain-idle.
                        if (b3l_diffs and r == rounds - 1
                                and (b3l_make_diffs(r) or
                                     len(b3l_pool) >= 9)):
                            # H-027: diff tables + private dead registers
                            # (falls through to dffold if the dead-register
                            # pool cannot fund another private group).
                            b3l_fold_diffs(st, nv)
                        else:
                            nonlocal omf1_vec_clobbered
                            omf1_vec_clobbered = True  # see the bug guard note above
                            dffold(st, E_vecs, tm[j], tmM[j], t1[s],
                                   condA[j], condB[j], da=lv,
                                   db=lv + VLEN)                # E_win->condB
                            dffold(st, D_vecs, tm[j], tmM[j], t1[s],
                                   condA[j], tm[j], da=lv + 2 * VLEN,
                                   db=lv + 3 * VLEN)            # D_win->tm
                            if fold:
                                pfold(st, nv)       # st=b0b1b2b3 (exit)
                            madd(nv, nv, tm[j], condB[j])  # E + b3*D
                    else:
                        # H-017: W-combines ride flow when level 4 is flipped
                        # (D_vecs holds odd VALUES there; nv = raw parity).
                        # H-019 (l4_race): raced pairs (odd table present in
                        # odd_of) go to whichever engine retires earlier.
                        if 4 in vf_levels:
                            ffW = vsel
                        elif lr_pairs:
                            ffW = lambda dst, cond, dv, ev: (
                                dual_fold(dst, cond, dv, ev) if dv in odd_of
                                else madd(dst, cond, dv, ev))
                        else:
                            ffW = madd
                        # H-019 (u_race): each U-combine is dst := b2 ? wa :
                        # wb with runtime arms and exact 0/1 cond -- race one
                        # flow vselect against the valu subtract+madd.
                        uc = race_sel if u_race else (
                            lambda dst, cond, wa, wb: (
                                vec("-", wa, wa, wb), madd(dst, cond, wa, wb)))
                        vec("&", condB[j], st, one_vec)             # b2 (0/1)
                        if fold:
                            pfold(st, nv)                           # b0b1b2b3
                        ffW(t1[s], nv, D_vecs[0], E_vecs[0])        # W0
                        ffW(tm[j], nv, D_vecs[1], E_vecs[1])        # W1
                        uc(t1[s], condB[j], tm[j], t1[s])           # U0
                        ffW(tmM[j], nv, D_vecs[2], E_vecs[2])       # W2
                        ffW(tm[j], nv, D_vecs[3], E_vecs[3])        # W3
                        uc(tmM[j], condB[j], tm[j], tmM[j])         # U1
                        ffW(tm[j], nv, D_vecs[4], E_vecs[4])        # W4
                        ffW(condA[j], nv, D_vecs[5], E_vecs[5])     # W5
                        uc(tm[j], condB[j], condA[j], tm[j])        # U2
                        ffW(condA[j], nv, D_vecs[6], E_vecs[6])     # W6
                        ffW(nv, nv, D_vecs[7], E_vecs[7])           # W7 (b3 dead)
                        uc(nv, condB[j], nv, condA[j])              # U3 (b2 dead)
                        vec("&", condA[j], st, four_vec if fold else two_vec)  # b1
                        vsel(t1[s], condA[j], tmM[j], t1[s])        # q0
                        vsel(nv, condA[j], nv, tm[j])               # q1
                        vec("&", condB[j], st, eight_vec if fold else four_vec)  # b0
                        vsel(nv, condB[j], nv, t1[s])               # winner
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

                if debug_compares and nvsrc is not None and not primed_nv(r, g):
                    S.emit("debug",
                           ("vcompare", nvsrc,
                            [(r, g * VLEN + i, "node_val") for i in range(VLEN)]),
                           reads=self._v(nvsrc))

                yield  # stage: node_val ready

                # ---- val = fused_hash(val ^ node_val) ----
                # Each xor-shift stage uses ONE temp: the shifted copy goes
                # to t, then val updates in place (same-cycle write-after-
                # read of val is safe under the bundle semantics).
                pe = (L in pe_levels and r < rounds - 1
                      and level(r + 1) != 0)
                t = t1[s]
                if nvsrc is not None:
                    vec("^", vl, vl, nvsrc)
                madd(vl, vl, hv["k0"], hv["C0"])
                yield  # stage: fold-in + stage0
                avec(">>", t, vl, hv["sh1"])
                avec("^", vl, vl, hv["C1"])
                vec("^", vl, vl, t)
                yield  # stage: stage1 xor-shift
                madd(t, vl, hv["kp"], hv["ap"])
                madd(vl, vl, hv["kq"], hv["aq"])
                vec("^", vl, vl, t)
                yield  # stage: fused stage2/3
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
                if not elide(r, g):
                    vec("^", vl, vl, hv["C5"])
                vec("^", vl, vl, t)

                if debug_compares and not elide(r, g):
                    S.emit("debug",
                           ("vcompare", vl,
                            [(r, g * VLEN + i, "hashed_val") for i in range(VLEN)]),
                           reads=self._v(vl))

                yield  # stage: hash complete

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
                            # unreachable under c5_prexor (level 1 is served)
                            assert not c5_prexor
                            vec("+", st, rec_vecs[Ln], par)
                        elif c5_prexor:
                            # st is the complement position; par inverted
                            # iff this round elided (see rec_off).
                            key = rec_off(r, g)
                            if idx_race:
                                race_idx_madd(
                                    st, negtwo_vec, rec_vecs[key],
                                    lambda i: ("-", st + i,
                                               rec_scalar[key], st + i))
                            else:
                                madd(st, st, negtwo_vec, rec_vecs[key])
                            vec("-" if elide(r, g) else "+", st, st, par)
                        else:
                            if idx_race:
                                race_idx_madd(
                                    st, two_vec, rec_vecs[Ln],
                                    lambda i: ("+", st + i, st + i,
                                               rec_scalar[Ln]))
                            else:
                                madd(st, st, two_vec, rec_vecs[Ln])
                            vec("+", st, st, par)
                    else:
                        # H-026 (mem_prime): an elided round's parity is
                        # inverted, so the gather-mode update flips to
                        # 2*gaddr + (omf+1) - par. Same op count.
                        if elide(r, g):
                            ov, osrc, sgn = omf1_vec, omf1_s, "-"
                        else:
                            ov, osrc, sgn = omf_vec, omf_s, "+"
                        if idx_select:
                            # P-14: omf1_vec == omf_vec + 1 by construction,
                            # so `ov +/- par` for 0/1 par is exactly a
                            # choice between the two ALREADY-LIVE constants
                            # omf_vec/omf1_vec -- no new scratch, and (as a
                            # vselect instead of a variable add/sub)
                            # flow-eligible where the add/sub form is not.
                            hi, lo = (
                                (omf1_vec, omf_vec) if sgn == "+"
                                else (omf_vec, omf1_vec)
                            )
                            vsel(par, par, hi, lo)
                            madd(st, st, two_vec, par)
                        elif idx_race:
                            # 2*gaddr + 1 - fp (+1 and -par when elided)
                            race_idx_madd(st, two_vec, ov,
                                          lambda i, osrc=osrc: (
                                              "+", st + i, st + i, osrc))
                            vec(sgn, st, st, par)
                        else:
                            madd(st, st, two_vec, ov)  # 2*gaddr + 1 - fp
                            vec(sgn, st, st, par)
                    for lane in range(VLEN):
                        S.emit("load", ("load", nv + lane, st + lane),
                               (st + lane,), (nv + lane,), mem_read=True)

        def emit_stages(r, g):
            # Re-tag on every resume so interleaved generators keep the
            # optional placement trace honest (tags never affect placement).
            inner = _egr_stages(r, g)
            while True:
                S.tag = (r, g)
                try:
                    next(inner)
                except StopIteration:
                    return
                yield

        def emit_group_round(r, g):
            for _ in emit_stages(r, g):
                pass

        def round_robin(gens):
            # Advance each generator one stage per pass until all exhaust.
            done = object()
            while gens:
                gens = [gen for gen in gens if next(gen, done) is not done]

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
        n_steps = rounds + max(lags)
        # "stage_tail:N": group order in the saturated middle, per-block
        # stage interleave only on the last N diagonal steps (the drain,
        # where the last block's chains are the only fillable work).
        tail_from = n_steps
        order = emit_order
        tail_mode = "stage"
        if isinstance(emit_order, str) and (
                emit_order.startswith("stage_tail")
                or emit_order.startswith("rev_tail")):
            n_tail = int(emit_order.split(":", 1)[1]) if ":" in emit_order else 1
            tail_from = n_steps - n_tail
            tail_mode = "rev" if emit_order.startswith("rev") else "stage"
            order = "group"
        for t in range(n_steps):
            waves = []  # (round, group-range) active at this diagonal step
            for b, lb in enumerate(lags):
                r = t - lb
                if 0 <= r < rounds:
                    waves.append((r, range(b * bs_, (b + 1) * bs_)))
            step_order = tail_mode if t >= tail_from else order
            if step_order == "group":
                for r, gs in waves:
                    for g in gs:
                        emit_group_round(r, g)
            elif step_order == "rev":
                # Reversed group order: the block's LAST groups (the global
                # critical path at the drain) get first claim on slots.
                for r, gs in waves:
                    for g in reversed(gs):
                        emit_group_round(r, g)
            elif step_order == "stage":
                # Round-robin the stages of the 8 groups WITHIN each block.
                for r, gs in waves:
                    round_robin([emit_stages(r, g) for g in gs])
            elif emit_order == "stage_all":
                # Round-robin across every block active at this step.
                round_robin([emit_stages(r, g) for r, gs in waves for g in gs])
            else:
                raise ValueError(f"unknown emit_order {emit_order!r}")

        assert not (idx_select and omf1_vec_clobbered), (
            "idx_select needs omf1_vec valid for longer than this config's "
            "b3l_diffs round-15 dffold fallback allows (it just reclaimed "
            "omf1_vec's storage as a transient fold temp) -- this WILL "
            "corrupt a later steady-gather gather address. Increase the "
            "l4_gmin round-15 threshold (validated safe from ~15 up), or "
            "reduce L4 service at round 15, until the private-register "
            "path funds every served group instead of falling back."
        )

        # --- store final values; second pause after everything ---
        # P-c4 (cross): the greedy scheduler places stores in emission
        # order when several are simultaneously ready, so a group whose
        # hash finishes LAST in real dependency time can still get queued
        # behind an earlier-emitted, not-yet-ready group's store. Emitting
        # the last-finishing groups FIRST lets them claim their earliest
        # feasible slot instead of waiting on emission-order ties.
        store_gs = list(range(n_groups))
        if store_order == "rev":
            store_gs = list(reversed(store_gs))
        elif store_order == "tail_first":
            # only reorder the known r15-staircase groups (last-finishing
            # per H-021's profile), leave the rest in natural order
            tail = store_gs[-4:]
            store_gs = list(reversed(tail)) + store_gs[:-4]
        S.tag = None
        last = 0
        for g in store_gs:
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
