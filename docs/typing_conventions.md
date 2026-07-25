# Typing Conventions

This guide governs a repo-wide pass that adds static type hints to the Python
code (annotations only — no behavior, logic, or identifier changes). It is the
type-hint companion to `docs/naming_style_guide.md`. Validation is `pyright`
in `basic` mode plus the frozen grader (`python tests/submission_tests.py`,
which must stay at exactly the same cycle count).

## Golden rule: annotations only, behavior unchanged

- This is a **pure annotation pass**. Do not change control flow, numeric
  constants, logic, or any runtime value. Every edit must be invisible to the
  program's output — the grader must report the identical cycle count before
  and after.
- **Do not rename anything.** Naming is a separate, already-completed pass.
  In particular, `dev.py` deliberately keeps the *old* research shorthand
  parameter names (`l4_gmin`, `skew`, `b3_last`, `parity_conds`, ...) because
  `tools/run_variant.py` and `tools/sched_profile.py` call it by those names.
  Add types to those parameters; never rename them.
- Never touch anything under `tests/`. Never rename the hard-protected names
  from the naming guide (`KernelBuilder`, `build_kernel`, `instrs`,
  `debug_info`, ISA opcode/engine string literals, ISA constant values).

## Enable lazy annotations everywhere

Add this as the **first statement after the module docstring**, before any
other import:

```python
from __future__ import annotations
```

Nothing in this repo introspects annotations at runtime (no `get_type_hints`,
no `__annotations__` reads), so making annotations lazy strings is zero-risk:
it removes any runtime evaluation cost and lets forward references (a method
returning its own class, a type defined later) work without quotes.

## Shared type aliases (defined in `problem.py`)

`problem.py` is the contract. It defines and exports these aliases — **import
them, do not redefine them** in other files:

```python
Engine = Literal["alu", "valu", "load", "store", "flow", "debug"]
Slot = tuple[Any, ...]              # (opcode_str, *operands); operands are
                                    # usually scratch addresses (int)
Instruction = dict[Engine, list[Slot]]   # one VLIW bundle
Program = list[Instruction]              # the whole compiled kernel
```

`SLOT_LIMITS` is `dict[Engine, int]`. When a file builds instructions or
slots, annotate with `Instruction` / `Slot` / `Program` and add them to the
existing `from problem import (...)` block as needed.

## What to annotate

- **Every function and method**: all parameters and the return type.
  Procedures that return nothing get `-> None` explicitly.
- **Nested closures** (there are many inside `build_kernel_scheduled`): type
  their params and returns too — a closure that returns a scratch address is
  `-> int`, one that emits and returns nothing is `-> None`.
- **Container locals initialized empty**, where the element type isn't obvious
  to the checker: annotate at first assignment, e.g.
  `named_instr: Instruction = {}`, `values_by_name: dict[str, list[int]] = {}`,
  `self.last_write: dict[int, int] = {}`.
- **Instance attributes** whose type isn't obvious from the constructor
  assignment: annotate in `__init__` (e.g. `self.bundles: list[Instruction] = []`).
  For an attribute created lazily in another method, a bare declaration in
  `__init__` (`self.trace: TextIO | None`) documents the type with no runtime
  effect.
- **`@dataclass` fields**: already annotated; fix any that are wrong (e.g.
  `dict[int, (str, int)]` should be `dict[int, tuple[str, int]]`).

## Type vocabulary for this codebase

- **Scratch/memory addresses, cycle numbers, slot counts, tree indices**:
  plain `int`. The naming pass already made these names self-describing
  (`dest_addr`, `cycle`, `forest_height`), so a semantic alias would add churn
  without clarity. Use `int`.
- **ISA slots**: `Slot`. A slot builder returns `Slot`; a list of them is
  `list[Slot]`.
- **Instruction bundles / programs**: `Instruction` / `Program`.
- **Engine keys**: `Engine`.
- **Flag parameters** on `build_kernel_scheduled` (dev.py) and similar:
  match the default. `bool` for `x=False`; `tuple[int, int]` for a fixed pair
  default like `(4, 3)`; `tuple[int, ...]` for a variable-length tuple default
  like `()` used as a collection of levels/rounds; `set[int]` where a set is
  built; `str` for `"group"`-style mode selectors. When a param accepts more
  than one shape (e.g. `b3_last` may be `True`, a falsey `()`, or an iterable
  of rounds), use a union such as `bool | tuple[int, ...]` or
  `bool | Iterable[int]` — read the body to see what it actually accepts.
- **Lambdas / function-valued dicts**: `Callable[[int, int], int]`, etc.,
  from `collections.abc`.
- **Generators**: `Iterator[T]` (from `collections.abc`) for the return type
  of a function with `yield`.
- Prefer built-in generics (`list`, `dict`, `tuple`, `set`) and PEP 604
  unions (`X | None`), not `typing.List` / `typing.Optional`.

## Narrowing `Optional`

Where a value is typed `T | None` but an invariant guarantees it is set at a
given point (e.g. trace-file methods only run while tracing), narrow with an
`assert x is not None`. This is idiomatic and consistent with the codebase,
which already uses `assert` for invariants — and it is provably output-neutral
here because the asserted path is the only one that reaches the code.

## Validation (run before returning)

For every file you touch:

```bash
python -m py_compile <file>
pyright --pythonversion 3.13 <file>      # target: 0 errors
```

Aim for **0 pyright errors**. If the only remaining errors originate in a
file you do not own or are unresolved-import errors from a file another agent
is editing concurrently, note them — the driver runs a final whole-repo
pyright pass and resolves cross-file issues there. Do not add `# type: ignore`
to silence a real error; fix the annotation instead. A narrow, well-justified
`# type: ignore[code]` is acceptable only for a genuine checker limitation,
with a one-line comment saying why.

## Out of scope

- `tests/` — never edited.
- `research/*.md`, `docs/*.tex` — prose/history, no code annotations.
- `.venv/` — third-party, never edited.
