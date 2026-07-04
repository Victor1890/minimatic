# Minimatic

> **Experimental Prototype**
> Research-grade software. APIs, semantics, and internal structure are subject to change without notice.

A minimal implementation of a Wolfram Language-style symbolic computation engine in Python. Minimatic provides immutable symbolic expressions, pattern matching, and an evaluation loop with structural attributes (Flat, Orderless, Listable) and hold semantics.

---

## Architecture

```
minimatic/
  core/          Fundamental data structures
    symbol.py      Immutable interned symbols
    expression.py  Immutable expressions: (head, args, attributes)
    atoms.py       Python-native primitives (int, float, complex, str, bool, None)
    attributes.py  Evaluation attributes (Hold, Flat, Orderless, Listable, ...)

  pattern/       Wolfram-style pattern matching
    blanks.py      Wildcard patterns (_, __, ___)
    structural.py  Pattern, Condition, Alternatives, PatternTest, Optional, ...
    bindings.py    Immutable match result bindings
    matcher.py     Core matching engine

  eval/          Evaluation engine
    evaluator.py   Standard evaluation procedure
    context.py     Evaluation contexts with scoping
    pipeline.py    Functional rule pipeline (pattern-matching dispatch)
    rules.py       Rule and RuleDelayed types
    values.py      OwnValues, DownValues, UpValues, SubValues, NValues
    transforms.py  Sequence flattening, Flat, Orderless, Listable transforms

  builtins/      Built-in function implementations
    registry.py    Function registration and dispatch
    arithmetic.py  Plus, Times, Power, Minus, Divide, Abs, Sqrt, Exp, Log, Sum, Product
```

---

## Core Types

### Symbol

Interned, immutable symbolic identifiers. Two symbols with the same name are the same object.

```python
from minimatic.core import Symbol, symbol, gensym

x = Symbol("x")
y = symbol("y")
g = gensym("tmp")  # Symbol("tmp1")

x is Symbol("x")   # True (interned)
```

### Expression

Immutable compound structures: `(head, args, attributes)`.

```python
from minimatic.core import Expression, Symbol

Plus = Symbol("Plus")
expr = Expression(Plus, 1, 2, 3)

expr.head       # Symbol("Plus")
expr.args       # (1, 2, 3)
expr.attributes # frozenset()

# With attributes
from minimatic.core import Hold
held = Expression(Plus, 1, 2, _attrs={Hold})
held.has_attr(Hold)  # True
```

### Atoms

Python's native types are used directly -- no wrappers.

| Python type | Head symbol |
|-------------|-------------|
| `int` | `Integer` |
| `float` | `Real` |
| `complex` | `Complex` |
| `str` | `String` |
| `bool` | `Symbol` |
| `None` | `Symbol` |

---

## Evaluation

The evaluator implements the standard Wolfram Language evaluation procedure:

```
1. Dispatch by type     Atom → self.  Symbol → OwnValues.  Expression → continue.
2. Evaluate head        (skip if HoldAllComplete)
3. Resolve attributes   head_attrs ∪ expression_attrs
4. Evaluate arguments   (respecting HoldAll / HoldFirst / HoldRest)
5. Flatten Sequences    splice Sequence[...] into argument lists
6. Apply Flat           Plus[Plus[a,b], c] → Plus[a,b,c]
7. Apply Orderless      canonical sort arguments
8. Apply Listable       f[{a,b}, c] → {f[a,c], f[b,c]}
9. Try rules            via functional RulePipeline (see below)
10. Fixed-point check   if changed, re-evaluate (up to $IterationLimit)
```

Step 9 delegates to `RulePipeline`, a functional rule application engine that uses the pattern matcher to apply rules from multiple sources in priority order:

```
1. User intercept-before rules   (highest priority)
2. UpValues                      (from arguments, indexed by arg symbol)
3. DownValues                    (from head symbol, indexed by head)
4. SubValues                     (from head expression)
5. NValues                       (numeric approximation)
6. Built-in fallback             (native implementation)
7. User intercept-after rules    (lowest priority)
```

```python
from minimatic.core import Symbol, Expression
from minimatic.eval import evaluate, GlobalContext

ctx = GlobalContext

Plus = Symbol("Plus")

evaluate(Expression(Plus, 1, 2, 3), ctx)                   # 6
evaluate(Expression(Plus, Expression(Plus, 1, 2), 3), ctx) # 6 (Flat)
```

### Hold Attributes

| Attribute | Effect |
|-----------|--------|
| `HoldAll` | No arguments evaluated |
| `HoldFirst` | First argument not evaluated |
| `HoldRest` | Arguments after first not evaluated |
| `HoldAllComplete` | Nothing evaluated (including head) |
| `SequenceHold` | `Sequence[...]` not flattened |

### Value Types

| Type | Purpose |
|------|---------|
| `OwnValues` | Symbol definitions (`x = 5`) |
| `DownValues` | Function definitions (`f[x_] := ...`) |
| `UpValues` | Operator overloading (`expr_f := ...`) |
| `SubValues` | Subscripted functions (`f[a][b] := ...`) |
| `NValues` | Numeric approximation (`N[expr]`) |

### Extending Evaluation with the Rule Pipeline

The rule pipeline lets you intercept, override, or extend evaluation by adding pattern-matching rules at specific priority levels.

```python
from minimatic.core import Symbol, Expression
from minimatic.eval import evaluate, EvaluationContext
from minimatic.eval.pipeline import PipelineRule, RuleSource
from minimatic.pattern import pattern, blank

Plus = Symbol("Plus")
x, y = Symbol("x"), Symbol("y")

ctx = EvaluationContext("custom")

# Add a simplification rule: Plus[0, x_] → x
zero_plus = Expression(Plus, 0, pattern(x, blank()))
ctx.pipeline.add_rule(PipelineRule(zero_plus, x))

evaluate(Expression(Plus, 0, 5), ctx)  # 5

# Add a rule that fires before all others (including builtins)
pat = Expression(Plus, pattern(x, blank()), pattern(y, blank()))
ctx.pipeline.add_intercept_before(
    PipelineRule(pat, lambda b: b[x] + b[y] if isinstance(b[x], int) and isinstance(b[y], int) else Expression(Plus, b[x], b[y]))
)

# Add an UpValue (operator overloading on an argument)
F = Symbol("F")
ctx.pipeline.add_up_value(
    PipelineRule(Expression(F, x), Symbol("special")),
    x,  # indexed by this argument symbol
)

# Context inheritance: child contexts inherit parent rules
child_ctx = EvaluationContext("child", parent=ctx)
evaluate(Expression(Plus, 0, 3), child_ctx)  # 5 (inherited rule)
```

| Method | Priority | Description |
|--------|----------|-------------|
| `add_intercept_before(rule)` | 1000+ | Fires before everything, including builtins |
| `add_up_value(rule, arg_sym)` | 100 | Operator overloading on argument symbols |
| `add_rule(rule)` | 0 | Standard rule, indexed by head symbol |
| `add_intercept_after(rule)` | -100 | Fires after builtins, as last resort |

---

## Pattern Matching

Full Wolfram Language-style pattern matching with backtracking.

### Pattern Types

| Pattern | Syntax | Description |
|---------|--------|-------------|
| Blank | `_` or `_h` | Matches any single expression (optionally with head constraint) |
| BlankSequence | `__` or `__h` | Matches one or more expressions |
| BlankNullSequence | `___` or `___h` | Matches zero or more expressions |
| Pattern | `x_` or `x_h` | Named binding |
| Condition | `pat /; test` | Conditional match |
| Alternatives | `a \| b` | Match either pattern |
| PatternTest | `pat ? test` | Test predicate |
| Optional | `x_ : default` | Optional with default |
| Repeated | `pat..` | One or more |
| RepeatedNull | `pat...` | Zero or more |
| Verbatim | `Verbatim[expr]` | Literal match |
| HoldPattern | `HoldPattern[pat]` | Prevent pattern evaluation |

```python
from minimatic.core import Symbol, Expression
from minimatic.core.attributes import Flat, Orderless
from minimatic.pattern import match, pattern, blank, blank_seq, alternatives, condition, optional, replace_with_bindings, Bindings

x, y = Symbol("x"), Symbol("y")
Plus = Symbol("Plus")

# Basic matching
r = match(Expression(Plus, pattern(x), pattern(y)), Expression(Plus, 1, 2))
r.success   # True
r[x]        # 1
r[y]        # 2

# Head-constrained blank
from minimatic.core import Integer
match(blank(Integer), 42).success    # True
match(blank(Integer), 3.14).success  # False

# Sequence matching
r = match(
    Expression(Plus, blank_seq(), pattern(y)),
    Expression(Plus, 1, 2, 3)
)
r[y]  # 3

# Flat matching (pass expr_attrs from evaluator context)
r = match(
    Expression(Plus, pattern(x), pattern(y), pattern(z)),
    Expression(Plus, Expression(Plus, 1, 2), 3),
    expr_attrs=frozenset({Flat})
)
r[x], r[y], r[z]  # 1, 2, 3

# Orderless matching
r = match(
    Expression(Plus, pattern(x), pattern(y)),
    Expression(Plus, 3, 1),
    expr_attrs=frozenset({Orderless})
)
# x and y bound to 1 and 3 (in some order)

# Substitution
b = Bindings({x: 1, y: 2})
replace_with_bindings(Expression(Plus, x, y), b)  # Plus[1, 2]
```

### Bindings

Immutable match results backed by `frozenset`. Safe for backtracking.

```python
from minimatic.pattern import Bindings, BindingConflict

b = Bindings({x: 42})
b2 = b.bind(y, 3.14)  # New Bindings; b unchanged

b.bind(x, 99)  # Raises BindingConflict
```

---

## Built-in Functions

Registered via `@register_builtin` decorator with attribute metadata.

### Arithmetic

| Function | Signature | Description |
|----------|-----------|-------------|
| `Plus` | `Plus[a, b, ...]` | Addition: `Plus[1, 2, 3]` → `6` |
| `Times` | `Times[a, b, ...]` | Multiplication: `Times[2, 3, 4]` → `24` |
| `Power` | `Power[base, exp]` | Exponentiation: `Power[2, 10]` → `1024` |
| `Minus` | `Minus[x]` | Unary minus: `Minus[5]` → `-5` |
| `Divide` | `Divide[num, den]` | Division: `Divide[10, 2]` → `5` |
| `Subtract` | `Subtract[a, b]` | Subtraction: `Subtract[10, 3]` → `7` |
| `Abs` | `Abs[x]` | Absolute value: `Abs[-5]` → `5` |
| `Sqrt` | `Sqrt[x]` | Square root: `Sqrt[9]` → `3` |
| `Exp` | `Exp[x]` | Exponential: `Exp[1]` → `2.718...` |
| `Log` | `Log[x]` or `Log[base, x]` | Logarithm: `Log[E, 1024]` → `10` |
| `Sum` | `Sum[expr, {i, n}]` | Summation: `Sum[i, {i, 1, 10}]` → `55` |
| `Product` | `Product[expr, {i, n}]` | Product: `Product[i, {i, 1, 5}]` → `120` |

### Control Flow

| Function | Signature | Description |
|----------|-----------|-------------|
| `Set` | `Set[x, val]` | Immediate assignment: `Set[x, 5]` → `5` |
| `SetDelayed` | `SetDelayed[x, body]` | Delayed assignment: `SetDelayed[x, Random[]]` |
| `If` | `If[cond, then]` or `If[cond, then, else]` | Branch: `If[True, 1, 2]` → `1` |
| `Which` | `Which[test1, val1, ...]` | Dispatch: `Which[False, "a", True, "b"]` → `"b"` |
| `Switch` | `Switch[expr, pat1, val1, ..., default]` | Match: `Switch[2, 1, "a", 2, "b"]` → `"b"` |
| `CompoundExpression` | `CompoundExpression[a, b, ..., c]` | Sequential: `CompoundExpression[1, 2, 3]` → `3` |
| `Evaluate` | `Evaluate[expr]` | Force evaluation inside held expressions |
| `ReleaseHold` | `ReleaseHold[expr]` | Unwrap Hold: `ReleaseHold[Hold[1+2]]` → `3` |
| `Hold` | `Hold[expr]` | Prevent evaluation: `Hold[1+2]` → `Hold[1+2]` |
| `HoldForm` | `HoldForm[expr]` | Prevent evaluation (display) |
| `Do` | `Do[body, {i, n}]` | Loop: `Do[Print[i], {i, 1, 5}]` |
| `While` | `While[test, body]` | Loop: `While[test, body]` → `Null` |
| `For` | `For[start, test, incr, body]` | C-style: `For[Set[i,0], i<5, i++, body]` |
| `Table` | `Table[expr, {i, n}]` | Collect: `Table[i^2, {i, 1, 5}]` → `{1,4,9,16,25}` |
| `Nest` | `Nest[f, x, n]` | Apply n times: `Nest[f, x, 3]` → `f[f[f[x]]]` |
| `NestList` | `NestList[f, x, n]` | With intermediates: `NestList[f, x, 2]` → `{x, f[x], f[f[x]]}` |
| `Fold` | `Fold[f, x, list]` | Left fold: `Fold[Plus, 0, {1,2,3}]` → `6` |
| `Map` | `Map[f, list]` | Apply: `Map[f, {1,2,3}]` → `{f[1], f[2], f[3]}` |
| `Module` | `Module[{x=val}, body]` | Lexical scope: `Module[{x=10}, x+5]` → `15` |
| `Block` | `Block[{x=val}, body]` | Dynamic scope (save/restore) |
| `With` | `With[{x=val}, body]` | Constants: `With[{x=10}, x+5]` → `15` |

### Predicates

| Function | Signature | Description |
|----------|-----------|-------------|
| `TrueQ` | `TrueQ[expr]` | `TrueQ[True]` → `True`, `TrueQ[42]` → `False` |
| `SameQ` | `SameQ[a, b]` | `SameQ[1, 1]` → `True`, `SameQ[a, b]` → `False` |
| `UnsameQ` | `UnsameQ[a, b]` | Inverse of SameQ |
| `NumericQ` | `NumericQ[expr]` | `NumericQ[42]` → `True`, `NumericQ["x"]` → `False` |
| `AtomQ` | `AtomQ[expr]` | `AtomQ[42]` → `True`, `AtomQ[f[x]]` → `False` |
| `HeadQ` | `HeadQ[expr, head]` | `HeadQ[{1,2}, List]` → `True` |
| `ListQ` | `ListQ[expr]` | `ListQ[{1,2}]` → `True`, `ListQ[42]` → `False` |
| `StringQ` | `StringQ[expr]` | `StringQ["hi"]` → `True`, `StringQ[42]` → `False` |
| `IntegerQ` | `IntegerQ[expr]` | `IntegerQ[42]` → `True`, `IntegerQ[3.14]` → `False` |
| `RealQ` | `RealQ[expr]` | `RealQ[3.14]` → `True`, `RealQ[42]` → `False` |

```python
from minimatic.core import Symbol, Expression
from minimatic.eval import evaluate, GlobalContext
from minimatic.builtins import arithmetic, control

ctx = GlobalContext
Plus, Times, Power = Symbol("Plus"), Symbol("Times"), Symbol("Power")

# Arithmetic
evaluate(Expression(Plus, 1, 2, 3), ctx)                      # 6
evaluate(Expression(Times, 2, 3, 4), ctx)                     # 24
evaluate(Expression(Power, 2, 10), ctx)                       # 1024
evaluate(Expression(Plus, Expression(Times, 2, 3), 4), ctx)   # 10

# Control flow
If = Symbol("If")
evaluate(Expression(If, True, "yes", "no"), ctx)              # "yes"

Table = Symbol("Table")
i = Symbol("i")
evaluate(Expression(Table,
    Expression(Plus, i, 1),
    Expression(Symbol("List"), i, 1, 5)
), ctx)  # List[2, 3, 4, 5, 6]

# Scoping
Module = Symbol("Module")
x = Symbol("x")
evaluate(Expression(Module,
    Expression(Symbol("List"), Expression(Symbol("Set"), x, 10)),
    Expression(Plus, x, 5)
), ctx)  # 15
```

---

## Current Limitations

- **No parser** -- expressions are constructed programmatically via `Expression(head, *args)`
- **No lexer/AST** -- the `.m` example files are not yet parsed by this engine
- **Limited built-ins** -- arithmetic, control flow, comparison, and logic only; no list manipulation or string functions
- **No syntactic sugar** -- `DownValues`/`UpValues` infrastructure exists but no shorthand syntax for defining them

---

## Running

```python
from minimatic.core import Symbol, Expression
from minimatic.eval import evaluate, GlobalContext
from minimatic.builtins import arithmetic, control  # Registers all builtins

ctx = GlobalContext
Plus, Times, Power = Symbol("Plus"), Symbol("Times"), Symbol("Power")

# Build expressions programmatically
expr = Expression(Plus, 1, 2, 3)
print(evaluate(expr, ctx))  # 6

# Control flow
If = Symbol("If")
print(evaluate(Expression(If, True, "yes", "no"), ctx))  # "yes"

# Loops
Table = Symbol("Table")
i = Symbol("i")
result = evaluate(Expression(Table,
    Expression(Plus, Symbol("i"), 1),
    Expression(Symbol("List"), i, 1, 5)
), ctx)
print(result)  # List[2, 3, 4, 5, 6]

# Scoping
Module = Symbol("Module")
x = Symbol("x")
result = evaluate(Expression(Module,
    Expression(Symbol("List"), Expression(Symbol("Set"), x, 10)),
    Expression(Plus, x, 5)
), ctx)
print(result)  # 15
```

---

## License

MIT
