# Evaluation Procedure

> **Status**: Living document — reflects current implementation.

This document describes how minimatic evaluates symbolic expressions. It is the deep-dive reference for the evaluation engine; see [DESIGN.md](DESIGN.md) for the high-level architecture.

---

## 1. Overview

The evaluation engine is a seven-module system within `minimatic/eval/` plus the pattern matcher in `minimatic/pattern/matcher.py`. It evaluates symbolic expressions by recursively applying rules until a **fixed point** is reached — the expression stops changing.

| Module | File | Purpose |
|--------|------|---------|
| Evaluator | `eval/evaluator.py` (406 lines) | Main loop, recursion/iteration tracking, helpers |
| Pipeline | `eval/pipeline.py` (278 lines) | Priority-ordered rule dispatch |
| Context | `eval/context.py` (231 lines) | Namespaces: symbol tables, attributes, values, scoping |
| Rules | `eval/rules.py` (165 lines) | Rule and RuleDelayed data structures |
| Values | `eval/values.py` (184 lines) | Value type definitions and storage |
| Transforms | `eval/transforms.py` (211 lines) | Sequence flattening, Flat, Orderless, Listable |
| Matcher | `pattern/matcher.py` (828 lines) | Pattern matching engine with backtracking |

---

## 2. Entry Point

```python
evaluate(expr: Any, context: EvaluationContext | None = None) -> Any
```

`evaluator.py:91`

The `evaluate` function is the single entry point. It dispatches by expression type:

```
evaluate(expr)
├── is_atom(expr)  → return expr                    (self-evaluating)
├── is_symbol(expr) → _evaluate_symbol(expr, ctx)   (apply OwnValues)
├── is_expr(expr)   → _evaluate_expression(expr, ctx) (full procedure)
└── otherwise       → return expr                    (unknown type, pass through)
```

Before dispatch, a **recursion guard** (line 115-122) increments the thread-local `recursion_depth` counter. If it exceeds `recursion_limit` (default 256), a `RecursionLimitError` is raised. The counter is always decremented in a `finally` block (line 142).

If the call is at **top level** (`recursion_depth == 0` before increment), the `iteration_count` is reset to 0 (line 118-119). This ensures each top-level evaluation gets a fresh iteration budget.

---

## 3. Standard Evaluation Procedure

For `Expression` values, `_evaluate_expression()` (`evaluator.py:176`) implements the full procedure. The steps below follow the evaluator's internal numbering.

### Step 3a — Evaluate Head

`evaluator.py:179-196`

Unless `HoldAllComplete` is in the effective attributes:

1. If head is a **Symbol**: evaluate via `_evaluate_symbol()` to resolve OwnValues.
2. If head is an **Expression**: evaluate recursively via `evaluate()`.
3. If head changed, create a new `Expression` with the evaluated head.

Example: `f[1, 2]` where `f = g` evaluates to `g[1, 2]`.

### Step 3b — Resolve Attributes

`evaluator.py:252-271`

Attributes are merged from three sources via frozenset union:

```
effective_attrs = head_ctx_attrs | builtin_attrs | expr.attributes
```

| Source | How obtained | Precedence |
|--------|-------------|------------|
| Context attributes | `context.get_attributes(head)` | Lowest |
| Builtin attributes | `builtin_attributes(head)` from registry | Middle |
| Expression attributes | `expr.attributes` (set at construction) | Highest |

Expression-level attributes take precedence because they appear last in the union. This enables per-expression overrides (e.g., `Hold[expr]` puts `Hold` on the expression, not the `Hold` symbol).

### Step 3c — Evaluate Arguments

`evaluator.py:274-310`

Arguments are evaluated according to the **Hold attributes** in the effective attribute set:

| Attribute | Behavior |
|-----------|----------|
| `HoldAllComplete` or `HoldAll` | All arguments held (not evaluated) |
| `HoldFirst` | First argument held, rest evaluated |
| `HoldRest` | First argument evaluated, rest held |
| *(none of the above)* | All arguments evaluated |

Each non-held argument is evaluated via `evaluate(arg, context)`. If any argument changed, a new `Expression` is constructed with the evaluated arguments.

### Step 3d — Flatten Sequences

`evaluator.py:210-214` → `transforms.py:13-46`

Unless `SequenceHold` or `HoldAllComplete` is in the effective attributes, `Sequence[...]` objects are spliced into the argument list:

```
h[a, Sequence[x, y], b] → h[a, x, y, b]
h[a, Sequence[], b]     → h[a, b]          (empty Sequence vanishes)
```

### Step 3e — Apply Flat

`evaluator.py:217-221` → `transforms.py:49-89`

If `Flat` is in the effective attributes, nested expressions with the same head are flattened (associativity):

```
Plus[Plus[a, b], c] → Plus[a, b, c]
```

Flattening is recursive — deeply nested structures like `f[f[f[a, b], c], d]` become `f[a, b, c, d]`.

### Step 3f — Apply Orderless

`evaluator.py:223-224` → `transforms.py:92-113`

If `Orderless` is in the effective attributes, arguments are sorted into **canonical order** (`transforms.py:116-144`):

1. Numbers (sorted by numeric value)
2. Strings (alphabetical)
3. Symbols (alphabetical by name)
4. Expressions (by depth, then leaf count, then string representation)

A new expression is created only if the order actually changed.

### Step 3g — Apply Listable

`evaluator.py:226-233` → `transforms.py:165-211`

If `Listable` is in the effective attributes, the function **threads** over `List` arguments:

```
Plus[{a, b}, c] → {Plus[a, c], Plus[b, c]}
```

Requirements:
- At least one argument must be a `List`.
- All `List` arguments must have the same length.

If threading occurred, the result is **immediately evaluated** and returned (line 233), bypassing the rule-application step. This prevents double-threading.

### Step 3h — Try Rules

`evaluator.py:235-236` → delegates to `pipeline.py:137-204`

The evaluator calls `_apply_rules(expr, context)`, which delegates entirely to `context.pipeline.apply(expr, context)`. See [Section 4](#4-rule-pipeline) for the full pipeline architecture.

**Critical design point**: For pattern-based rules, the pipeline returns a **substitution only** — no evaluation occurs. The fixed-point loop in step 3i handles re-evaluation. For builtins, the implementation is called directly and returns a fully evaluated result.

### Step 3i — Fixed-Point Check

`evaluator.py:238-246`

If the expression changed after rule application (`new_expr != expr`):

1. Increment `iteration_count`.
2. If `iteration_count > iteration_limit` (default 1000), raise `IterationLimitError`.
3. **Re-evaluate from the top**: call `evaluate(new_expr, context)`.

This is the fixed-point loop. It continues until:
- The expression stabilizes (no rules match), OR
- The iteration limit is exceeded.

### Step 3j — Return Stable Expression

`evaluator.py:249`

If no rules matched and the expression is unchanged, return it as-is.

---

## 4. Rule Pipeline

The `RulePipeline` class (`pipeline.py:70-278`) is the central dispatch mechanism. Each `EvaluationContext` owns a pipeline instance, and the evaluator delegates all rule application to it.

### Pipeline Components

| Component | File:Line | Purpose |
|-----------|-----------|---------|
| `RuleSource` | `pipeline.py:24-32` | Enum: `USER_INTERCEPT`, `UP_VALUES`, `DOWN_VALUES`, `SUB_VALUES`, `N_VALUES`, `BUILTIN` |
| `PipelineRule` | `pipeline.py:35-52` | Frozen dataclass: `(pattern, replacement, condition, source, priority)` |
| `BuiltinFallback` | `pipeline.py:55-67` | Frozen dataclass: `(symbol, implementation, attributes)` — wraps a builtin |
| `RulePipeline` | `pipeline.py:70-278` | Indexed rule store with parent chaining |

### Rule Application Order

`pipeline.py:137-204`

The pipeline tries each source in priority order. The **first successful transformation** wins:

| Priority | Source | How matched | File:Line |
|----------|--------|-------------|-----------|
| 1 | `intercept_before` | User-defined pre-rules | `pipeline.py:156` |
| 2 | UpValues | By argument symbol (left-to-right) | `pipeline.py:161` |
| 3 | DownValues | By head symbol | `pipeline.py:166-171` |
| 4 | SubValues | By `head.head` symbol | `pipeline.py:174-179` |
| 5 | NValues | Via DownValues on `N` | `pipeline.py:182` |
| 6 | Built-in | Three-level fallback chain | `pipeline.py:185-197` |
| 7 | `intercept_after` | User-defined post-rules | `pipeline.py:200` |

If no source matches, the original expression is returned unchanged.

### Rule Matching

Each `PipelineRule` is matched against the expression using the pattern matcher (`pattern/matcher.py`). The process (`pipeline.py:255-278`):

1. Call `match(rule.pattern, expr)` — returns a `MatchResult` with bindings.
2. If no match, skip to the next rule.
3. If a **condition** is present, substitute bindings into the condition, evaluate it, and skip if the result is not `True`.
4. Apply the **replacement**:
   - If callable: `rule.replacement(bindings)` — the function receives bindings directly.
   - Otherwise: `replace_with_bindings(rule.replacement, bindings)` — structural substitution.

### Three-Level Builtin Resolution

`pipeline.py:185-197`

When the pipeline reaches step 6 (built-in fallback), it checks three levels:

1. **Pipeline-local**: `self._builtins.get(expr.head)` — builtins registered on this specific pipeline instance.
2. **Parent pipeline**: `self.parent._builtins.get(expr.head)` — if this pipeline has a parent (scoped context).
3. **Global registry**: `get_builtin(expr.head)` from `builtins/registry.py` — the global `_registry` dict populated at import time.

This allows scoped pipelines to override specific builtins while still falling back to global implementations.

### Parent Chaining

Both rules and builtins chain through parent pipelines:

```python
def _get_rules(self, head: Symbol) -> list[PipelineRule]:
    rules = list(self._rules_by_head.get(head, []))
    if self.parent is not None:
        rules.extend(self.parent._get_rules(head))
    return rules
```

`pipeline.py:224-229`

This means a child pipeline inherits all rules from its parent, plus can add its own. The same applies to UpValue rules (`pipeline.py:231-236`).

---

## 5. Pattern Matching Integration

The pattern matcher (`pattern/matcher.py`) is called from two places in the evaluation engine:

1. **OwnValues** (`evaluator.py:157`): `pattern_match(pattern_expr, sym)` — matches a symbol against its definition pattern.
2. **Rule pipeline** (`pipeline.py:259`): `match(rule.pattern, expr)` — matches an expression against a rule pattern.

### MatchResult

`matcher.py:91-118`

```python
@dataclass(frozen=True)
class MatchResult:
    success: bool
    bindings: Bindings
```

- Supports boolean context (`__bool__` returns `success`).
- Supports `NO_MATCH` sentinel for early bail-out.
- `bindings` maps bound `Symbol`s to their matched values.

### Binding Substitution

`matcher.py:728-781`

`replace_with_bindings(expr, bindings, flatten_lists=True)` performs structural substitution:

- Bound symbols are replaced with their values.
- When `flatten_lists=True`: bound `List[...]` sequences are flattened into argument lists (needed for `BlankSequence`/`BlankNullSequence` results).
- When `flatten_lists=False`: simple symbol substitution (used by `Module`).
- Returns the original expression if nothing changed (structural sharing).

### Condition Evaluation

Conditions require the evaluator. The pattern matcher accepts an optional `evaluator` parameter:

- `Condition` patterns (`matcher.py:272-296`): Match inner pattern, then evaluate the test. If `evaluator=None`, the pattern fails to match (fail-safe, not an error).
- `PatternTest` patterns (`matcher.py:312-335`): Same approach — match inner, apply test via evaluator.

In the rule pipeline, conditions are evaluated lazily (`pipeline.py:265-272`):

```python
if rule.condition is not None:
    from minimatic.eval.evaluator import evaluate
    cond_substituted = replace_with_bindings(rule.condition, match_result.bindings)
    cond_result = evaluate(cond_substituted, context)
    if cond_result is not True and cond_result != Symbol("True"):
        return expr
```

---

## 6. Thread Safety

The evaluation engine is safe for concurrent use from multiple threads. Each thread has independent state via `threading.local()`.

### Thread-Local Components

| Component | Storage | File:Line | Purpose |
|-----------|---------|-----------|---------|
| `EvalState` | `_eval_thread_local.state` | `evaluator.py:81-88` | Recursion depth, iteration count, limits |
| Context stack | `_thread_local.stack` | `context.py:169-176` | Per-thread context stack, initialized to `[GlobalContext]` |

### `EvalState` Fields

`evaluator.py:72-78`

| Field | Default | Description |
|-------|---------|-------------|
| `recursion_depth` | 0 | Current call depth (incremented on entry, decremented in `finally`) |
| `iteration_count` | 0 | Number of rewrites in current evaluation (reset at top-level) |
| `recursion_limit` | 256 | Maximum call depth before `RecursionLimitError` |
| `iteration_limit` | 1000 | Maximum rewrites before `IterationLimitError` |
| `trace_enabled` | False | Reserved for future tracing support |

### Symbol Interning

Symbol interning (`core/symbol.py:20`) uses a `threading.Lock` for thread-safe creation and lookup of interned symbols. Two symbols with the same name are always the same object (`is` comparison is valid).

---

## 7. Error Handling

### RecursionLimitError

`evaluator.py:59-62`

Raised when `recursion_depth > recursion_limit` (default 256). This catches infinite recursion in OwnValues or expression evaluation.

```python
if state.recursion_depth > state.recursion_limit:
    state.recursion_depth -= 1
    raise RecursionLimitError(f"Recursion depth of {state.recursion_limit} exceeded")
```

`evaluator.py:120-122`

### IterationLimitError

`evaluator.py:65-68`

Raised when `iteration_count > iteration_limit` (default 1000). This catches infinite rewriting where the expression keeps changing but never stabilizes.

```python
if state.iteration_count > state.iteration_limit:
    raise IterationLimitError(f"Iteration limit of {state.iteration_limit} exceeded")
```

`evaluator.py:242-243`

**Key difference**: Recursion limit tracks call depth (nested evaluations). Iteration limit tracks rewrites (the expression changing shape). A single top-level evaluation can trigger many iterations without increasing recursion depth.

### BindingConflict

`pattern/bindings.py:311`

Raised when attempting to bind a symbol that is already bound to a different value. This is caught internally during sequence matching (`matcher.py:531, 590`) to enable backtracking — the matcher tries alternative match positions.

### Pattern Matching Fail-Safe

If `evaluator=None` is passed to `match()`, `Condition` and `PatternTest` patterns fail to match silently (no match, not an error). This allows pattern matching to be used in contexts where evaluation is not available.

---

## 8. Helper Functions

### `try_evaluate`

`evaluator.py:328-339`

```python
def try_evaluate(expr, context=None, default=None) -> Any:
```

Wraps `evaluate()` in a try/except for `RecursionLimitError` and `IterationLimitError`, returning `default` on failure. Useful for speculative evaluation where failure is expected.

### `FixedPoint`

`evaluator.py:342-371`

```python
def FixedPoint(func, expr, max_iterations=100, same_test=None) -> Any:
```

Applies `func` repeatedly until `same_test(new_expr, expr)` returns `True`. Defaults to structural equality (`==`). Returns after `max_iterations` even if not converged.

This is distinct from the evaluator's built-in fixed-point loop: `FixedPoint` applies an arbitrary function, while the evaluator applies the full standard evaluation procedure.

### `evaluate_iterated`

`evaluator.py:374-380`

```python
def evaluate_iterated(expr, n, context=None) -> Any:
```

Evaluates expression exactly `n` times, returning the final result. Each call goes through the full evaluation procedure.

### Limit Management

| Function | File:Line | Purpose |
|----------|-----------|---------|
| `set_recursion_limit(limit)` | `evaluator.py:383-388` | Set `$RecursionLimit`, returns old value |
| `set_iteration_limit(limit)` | `evaluator.py:391-396` | Set `$IterationLimit`, returns old value |
| `get_recursion_limit()` | `evaluator.py:399-401` | Get current `$RecursionLimit` |
| `get_iteration_limit()` | `evaluator.py:404-406` | Get current `$IterationLimit` |

All limits are per-thread (thread-local state).

---

## 9. Component Interaction

The following diagram shows the call graph for evaluating `Plus[x, 1]` where `x = 5`:

```
evaluate(Plus[x, 1], GlobalContext)
│
├─ is_expr(Plus[x, 1]) → _evaluate_expression()
│
├─ [3a] Evaluate head
│  └─ _evaluate_symbol(Plus, ctx)
│     └─ No OwnValues → return Plus
│
├─ [3b] Resolve attributes
│  └─ effective_attrs = {Flat, Orderless, Listable, NumericFunction}
│     (from builtin registry for Plus)
│
├─ [3c] Evaluate arguments
│  ├─ evaluate(x, ctx)
│  │  └─ _evaluate_symbol(x, ctx)
│  │     └─ OwnValues: x → 5 → evaluate(5) → 5
│  └─ evaluate(1, ctx) → 1
│  └─ new expr: Plus[5, 1]
│
├─ [3d] Flatten sequences → Plus[5, 1] (no change)
│
├─ [3e] Apply Flat → Plus[5, 1] (no nested Plus)
│
├─ [3f] Apply Orderless → Plus[1, 5] (sorted)
│
├─ [3g] Apply Listable → Plus[1, 5] (no Lists)
│
├─ [3h] Try rules → context.pipeline.apply()
│  │
│  ├─ [1] intercept_before → no match
│  ├─ [2] UpValues → no match
│  ├─ [3] DownValues → no match
│  ├─ [4] SubValues → no match
│  ├─ [5] NValues → no match
│  ├─ [6] Built-in fallback
│  │  └─ registry["Plus"] → plus_builtin(Plus[1, 5], ctx)
│  │     └─ Returns 6
│  └─ [7] intercept_after → not reached
│
├─ [3i] new_expr (6) != expr (Plus[1, 5]) → iterate
│  └─ evaluate(6, ctx) → 6 (atom, self-evaluating)
│
└─ return 6
```

---

## 10. Evaluation Semantics Summary

| Concept | Mechanism | Controlled by |
|---------|-----------|---------------|
| Self-evaluation | Atoms return themselves | `is_atom()` |
| Symbol lookup | OwnValues pattern matching | `context.get_own_values()` |
| Head evaluation | Recursive `evaluate()` | `HoldAllComplete` |
| Argument evaluation | Per-argument `evaluate()` | `HoldAll`, `HoldFirst`, `HoldRest` |
| Sequence flattening | Splice `Sequence[...]` into args | `SequenceHold` |
| Associativity | Flatten nested same-head exprs | `Flat` attribute |
| Commutativity | Canonical sort arguments | `Orderless` attribute |
| Threading | Thread over `List` args | `Listable` attribute |
| Rule dispatch | Pattern match → substitute | `RulePipeline.apply()` |
| Builtin execution | Direct call, no substitution | `BuiltinFallback.implementation()` |
| Fixed-point | Re-evaluate until stable | `$IterationLimit` |
| Recursion guard | Track call depth | `$RecursionLimit` |
| Thread isolation | `threading.local()` state | Built into all shared state |
