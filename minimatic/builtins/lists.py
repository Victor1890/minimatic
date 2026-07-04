"""
List built-in functions.

Implements basic list manipulation following Wolfram Language semantics.
Lists are represented as Expression objects with List head.
"""

from typing import Any

from minimatic.core import (
    Expression,
    Symbol,
    is_expr,
    is_integer,
    is_symbol,
)
from minimatic.core.atoms import is_atom
from minimatic.eval.context import EvaluationContext

from .registry import register_builtin

# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

List = Symbol("List")


def _is_list(expr: Any) -> bool:
    """Check if expr is a List expression."""
    return is_expr(expr) and is_symbol(expr.head) and expr.head.name == "List"


# ═══════════════════════════════════════════════════════════════════════════════
# LENGTH
# ═══════════════════════════════════════════════════════════════════════════════

Length = Symbol("Length")


@register_builtin(Length, auto_evaluate=True)
def length_builtin(expr: Expression, context: EvaluationContext) -> Any:
    """
    Length[expr]. Returns the number of arguments in expr.

    Examples:
        Length[{1, 2, 3}] → 3
        Length[Plus[1, 2]] → 2
        Length[x] → Length[x]  (unevaluated)
    """
    args = expr.args
    if len(args) < 1:
        return expr

    target = args[0]
    if is_expr(target):
        return len(target.args)
    if is_atom(target):
        return 0
    return expr


# ═══════════════════════════════════════════════════════════════════════════════
# PART
# ═══════════════════════════════════════════════════════════════════════════════

Part = Symbol("Part")


@register_builtin(Part, auto_evaluate=True)
def part_builtin(expr: Expression, context: EvaluationContext) -> Any:
    """
    Part[expr, i] or Part[expr, i, j, ...]. Extract part of an expression.

    Uses 1-based indexing. Negative indices count from the end.

    Examples:
        Part[{a, b, c}, 2] → b
        Part[{a, b, c}, -1] → c
        Part[f[a, b], 1] → a
        Part[{{1,2},{3,4}}, 2, 1] → 3
        Part[{a, b}, 5] → Part[{a, b}, 5]  (unevaluated)
    """
    args = expr.args
    if len(args) < 2:
        return expr

    result = args[0]
    for idx in args[1:]:
        if not is_expr(result):
            return expr

        if not is_integer(idx):
            return expr

        n = len(result.args)
        if idx == 0:
            return expr

        # Resolve negative index
        resolved = n + idx if idx < 0 else idx - 1  # 1-based to 0-based

        if resolved < 0 or resolved >= n:
            return expr

        result = result.args[resolved]

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# FIRST
# ═══════════════════════════════════════════════════════════════════════════════

First = Symbol("First")


@register_builtin(First, auto_evaluate=True)
def first_builtin(expr: Expression, context: EvaluationContext) -> Any:
    """
    First[list]. Returns the first element of a list.

    Examples:
        First[{a, b, c}] → a
        First[{}] → First[{}]  (unevaluated)
    """
    args = expr.args
    if len(args) < 1:
        return expr

    target = args[0]
    if _is_list(target) and len(target.args) > 0:
        return target.args[0]

    return expr


# ═══════════════════════════════════════════════════════════════════════════════
# LAST
# ═══════════════════════════════════════════════════════════════════════════════

Last = Symbol("Last")


@register_builtin(Last, auto_evaluate=True)
def last_builtin(expr: Expression, context: EvaluationContext) -> Any:
    """
    Last[list]. Returns the last element of a list.

    Examples:
        Last[{a, b, c}] → c
        Last[{}] → Last[{}]  (unevaluated)
    """
    args = expr.args
    if len(args) < 1:
        return expr

    target = args[0]
    if _is_list(target) and len(target.args) > 0:
        return target.args[-1]

    return expr


# ═══════════════════════════════════════════════════════════════════════════════
# RANGE
# ═══════════════════════════════════════════════════════════════════════════════

Range = Symbol("Range")


@register_builtin(Range, auto_evaluate=True)
def range_builtin(expr: Expression, context: EvaluationContext) -> Any:
    """
    Range[n], Range[min, max], or Range[min, max, step].

    Generates a list of integers.

    Examples:
        Range[5] → {1, 2, 3, 4, 5}
        Range[2, 5] → {2, 3, 4, 5}
        Range[1, 10, 2] → {1, 3, 5, 7, 9}
        Range[5.0] → Range[5.0]  (unevaluated)
    """
    args = expr.args
    if len(args) < 1 or len(args) > 3:
        return expr

    if not all(is_integer(a) for a in args):
        return expr

    if len(args) == 1:
        n = args[0]
        if n < 1:
            return Expression(List)
        result = list(range(1, n + 1))
    elif len(args) == 2:
        lo, hi = args[0], args[1]
        if lo > hi:
            return Expression(List)
        result = list(range(lo, hi + 1))
    else:
        lo, hi, step = args[0], args[1], args[2]
        if step == 0:
            return expr
        if step > 0 and lo > hi:
            return Expression(List)
        if step < 0 and lo < hi:
            return Expression(List)
        result = list(range(lo, hi + 1, step)) if step > 0 else list(range(lo, hi - 1, step))

    return Expression(List, *result)
