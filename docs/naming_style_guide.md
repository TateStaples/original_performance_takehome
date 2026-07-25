# Naming Style Guide

This guide governs a repo-wide identifier-readability pass: renaming variables,
parameters, and (where cryptic) private helper functions to be self-explanatory,
without changing any behavior. It applies to Python, Rust, and prose docs alike.

## Philosophy

- **Prefer long and descriptive over short and clever.** A name should let a
  reader who doesn't already know this codebase's jargon understand roughly
  what a value holds, without needing to open `research/backlog.md` to
  decode it. `b3l_rounds` forces a reader to already know `b3_last` means
  "newest-parity-bit fold ordered last"; the renamed variable should say that
  directly (e.g. `newest_parity_last_fold_rounds`).
- **Long is fine; vague is not.** `data`, `tmp`, `val2`, `result` are not
  improvements over a terse abbreviation — they're a different way of saying
  nothing. Every rename must add real information about *what the value is*
  or *what role it plays*, not just spell out more letters.
- **Keep the minimum abbreviation, not zero abbreviation.** A few
  domain-standard short forms are clearer *as abbreviations* than spelled out
  (see Allowed short forms below). The goal is approachability, not maximum
  character count.
- **A rename must not change behavior.** This is a pure identifier pass. If
  making a name accurate would require understanding a genuinely ambiguous
  or dead piece of code, flag it instead of guessing.
- **Preserve the link to research history.** Many names here encode a
  specific accepted hypothesis (`H-023`, `H-027`, ...) from
  `research/backlog.md`. When renaming such a variable, keep the `H-xxx`
  reference in a comment if one already existed, so the new name and the
  historical record can still be cross-referenced.

## Allowed short forms (do not spell out)

These are either fixed external vocabulary or genuinely-conventional math/CS
shorthand — spelling them out would make the code *harder* to match against
their spec or convention, not easier:

- **ISA mnemonics** (`alu`, `valu`, `load`, `store`, `flow`, `debug`, and all
  opcode names inside slot tuples — `select`, `vselect`, `vbroadcast`,
  `multiply_add`, `cond_jump`, etc.) — these are the fixed instruction set
  defined in `docs/isa.md` and executed by the frozen grader. See
  "Hard-protected names" below; they are not eligible for renaming at all,
  by any pass, anywhere.
- `i`, `j`, `k` — trivial loop counters with a small, obvious scope (a single
  `for` loop body, no closures capturing them, no reuse of the letter for a
  second meaning later in the same scope).
- `dest`, `addr`, `src` — standard in this codebase and in `docs/isa.md` for
  "destination/address/source scratch slot"; renaming these would make the
  code *less* consistent with the spec doc, not more.
- Standard math/CS abbreviations used in a way a general engineer already
  knows: `idx` (index), `len`, `min`/`max`, `cfg` (config), `ctx` (context).

Everything else — and especially any abbreviation that mixes a research
shorthand prefix/suffix with a number or letter grade (`l4_`, `b3l_`, `bl_`,
`c5_`, `vf_`, `sp_`, `mp_`, `lv_`, `nv`, `gmin`, `maxT`, ...) — should be
spelled out into words once its meaning is confirmed from context (comments,
docstrings, and the matching `H-xxx` entry in `research/backlog.md` /
`research/graveyard.md` if one exists).

## Hard-protected names — never rename, anywhere

These names form the contract with `tests/` (which must never be modified —
see the repo's anti-cheating rule in `Readme.md`/`docs/problem.md`) or are
literal ISA data rather than identifiers we control:

1. **Everything under `tests/`** — no file in that directory is edited by
   this pass, full stop.
2. On `perf_takehome.py`'s `KernelBuilder`: the class name `KernelBuilder`,
   the method name `build_kernel`, the attribute `instrs`, and the method
   name `debug_info`. `tests/submission_tests.py` imports and calls these by
   exact name. (`build_kernel`'s *parameter* names are safe to rename — the
   grader calls it positionally.)
3. **Every ISA engine name and opcode string literal** used as a dict key or
   as the first element of a slot tuple (`"alu"`, `"valu"`, `"load"`,
   `"store"`, `"flow"`, `"debug"`, `"const"`, `"load_offset"`, `"vload"`,
   `"vstore"`, `"select"`, `"vselect"`, `"add_imm"`, `"halt"`, `"pause"`,
   `"trace_write"`, `"cond_jump"`, `"cond_jump_rel"`, `"jump"`,
   `"jump_indirect"`, `"coreid"`, `"compare"`, `"vcompare"`, `"comment"`,
   `"multiply_add"`, `"vbroadcast"`, and the alu op symbols `"+" "-" "*" "//"
   "cdiv" "^" "&" "|" "<<" ">>" "%" "<" "=="`). These are data the frozen
   `Machine.step` dispatches on by exact string match, not variable names —
   never touch the *value*, only the identifier of whatever Python variable
   might hold a collection of them.
4. **Numeric ISA constants' values** (`SLOT_LIMITS`'s contents, `VLEN = 8`,
   `N_CORES = 1`, `SCRATCH_SIZE = 1536`) are fixed hardware facts. The
   Python identifiers holding them may be renamed (with every reference
   updated), but the numbers themselves are not "magic numbers to clean up."

Everything else — `KernelBuilder`'s other attributes/methods, all of
`problem.py`, all of `rust_harness/`, all of `tools/` — is fair game,
*provided every consumer of a renamed symbol is updated in the same pass*
(see Cross-file coordination below).

## Cross-file coordination

Some names are load-bearing across file boundaries even though they aren't
in the hard-protected list — renaming them requires updating every consumer
in the same commit:

- `KernelBuilder`'s internal attributes/methods used by `tools/` scripts
  (e.g. `scratch_debug`, `build_kernel_scheduled` and its flag kwargs like
  `b3_last`, `l4_race`, `mem_prime`, ... — see `tools/run_variant.py`'s
  `BASE_KWARGS`, `tools/diagnose_kernel.py`, `tools/sched_profile.py`).
- `problem.py`'s exports consumed by `perf_takehome.py`'s
  `from problem import (...)` block (`Engine`, `DebugInfo`, `SLOT_LIMITS`,
  `Machine`, `Tree`, `Input`, `HASH_STAGES`, `reference_kernel`,
  `build_mem_image`, `reference_kernel2`, ...).
- Concepts mirrored in `rust_harness/` (a typed Rust port of `KernelBuilder`
  and the simulator, per its own doc comments) should get the *same* English
  name as their Python counterpart, translated to idiomatic Rust
  (`snake_case` locals, `CamelCase` types) — not a different translation
  chosen independently per language.

A single reconciled rename glossary (produced before any file is edited) is
the source of truth for all of the above, so no two files independently
invent different English names for the same concept.

## Naming patterns

- **Booleans**: prefix `is_`/`has_`/`should_`/`enable_` when the name
  wouldn't otherwise read as a boolean (`is_final_round`, not `final`).
  Existing flag kwargs that already read as a gate (e.g. `store_pair`,
  `derive_consts`) can keep an imperative/gerund shape if renaming to an
  `enable_`-prefixed form wouldn't add clarity — use judgment, don't
  mechanically prefix everything.
- **Collections**: plural nouns (`served_rounds`, not `served_round_list`
  or `l4_gmin` for a set of rounds).
- **Counts/limits**: suffix `_count`/`_limit`/`_size` (`group_count`, not
  `n_groups_` or `maxT`).
- **Per-scope index/loop variables** that already have a clear referent from
  an enclosing named collection may stay short (`for round in rounds:` is
  better than `for r in rounds:`, but if `r` is used across a 40-line
  function alongside `g` for "group" and `i` for "batch index", promote all
  three to `round`, `group`, `batch_index` together, consistently).
- **Units/roles over storage mechanism**: name what a value *means*, not
  where the previous author happened to put it (`gather_source_level`, not
  `lv_` — "lv" described that it lived in "lv scratch", not what it is).

## Worked example

`perf_takehome.py:906`, from the `b3_last` (H-023/H-027) fold-order-reversal
feature:

```python
# before
if b3_last is True:
    b3l_rounds = {r for r in range(rounds) if level(r) == L4}
elif b3_last:
    b3l_rounds = set(b3_last)
else:
    b3l_rounds = set()

# after (illustrative — confirm exact semantics against the surrounding
# comment and research/backlog.md H-023/H-027 before finalizing)
if reverse_newest_parity_fold is True:
    newest_parity_last_rounds = {
        round_index for round_index in range(rounds)
        if fold_level(round_index) == LEVEL_4
    }
elif reverse_newest_parity_fold:
    newest_parity_last_rounds = set(reverse_newest_parity_fold)
else:
    newest_parity_last_rounds = set()
```

Note the kwarg `b3_last` itself is renamed too (`reverse_newest_parity_fold`)
— every call site (`build_kernel`'s dispatch, `tools/run_variant.py`'s
`BASE_KWARGS`, any sweep config) must be updated together.

## Scope excluded from this pass

- `research/*.md` (`LOOP.md`, `RESEARCH.md`, `backlog.md`, `graveyard.md`,
  `strains/*/STATE.md`): this is a dated, historical research log, not
  reference documentation — entries describe the code *as it was at a given
  commit*, often already superseded. Rewriting old jargon into new names
  would misrepresent history rather than clarify it. Leave as-is.
- `docs/naive_algorithm.tex` Part I (the reference-algorithm writeup): uses
  standalone mathematical notation ($T$, $N$, $H$, $I$, $V$, $B$, $R$), not
  code identifiers — out of scope. Part II (the optimization explainer) may
  reference renamed code identifiers by name and should be checked/updated
  for consistency.
- `docs/isa.md`: documents the fixed ISA itself; its opcode/engine names are
  hard-protected (above) and not ours to rename. Prose clarity edits only if
  something is actually unclear (unlikely — it already reads well).
