"""
Main evaluation loop implementing the Wolfram Language
standard evaluation procedure.
"""

import threading
from collections.abc import Callable
from typing import Any

from minimatic.core import (
    Expression,
    Flat,
    HoldAll,
    HoldAllComplete,
    HoldFirst,
    HoldRest,
    Listable,
    Orderless,
    SequenceHold,
    Symbol,
    is_atom,
    is_expr,
    is_symbol,
)

from .context import EvaluationContext, get_current_context
from .transforms import apply_flat, apply_listable, apply_orderless, flatten_sequences

# Lazy import to avoid circular dependency
_builtin_dispatch = None
_builtin_attributes = None


def _get_builtin_dispatch():
    """Lazy import of built-in dispatch function."""
    global _builtin_dispatch
    if _builtin_dispatch is None:
        from minimatic.builtins.registry import dispatch_builtin

        _builtin_dispatch = dispatch_builtin
    return _builtin_dispatch


def _get_builtin_attributes():
    """Lazy import of built-in attributes function."""
    global _builtin_attributes
    if _builtin_attributes is None:
        from minimatic.builtins.registry import builtin_attributes

        _builtin_attributes = builtin_attributes
    return _builtin_attributes


# System constants
DEFAULT_RECURSION_LIMIT = 256
DEFAULT_ITERATION_LIMIT = 1000


class RecursionLimitError(Exception):
    """Raised when $RecursionLimit is exceeded."""

    pass


class IterationLimitError(Exception):
    """Raised when $IterationLimit is exceeded."""

    pass


# Thread-local evaluation state
class EvalState:
    def __init__(self):
        self.recursion_depth = 0
        self.iteration_count = 0
        self.recursion_limit = DEFAULT_RECURSION_LIMIT
        self.iteration_limit = DEFAULT_ITERATION_LIMIT
        self.trace_enabled = False


_eval_thread_local = threading.local()


def _get_eval_state() -> EvalState:
    """Get or create thread-local EvalState."""
    if not hasattr(_eval_thread_local, "state"):
        _eval_thread_local.state = EvalState()
    return _eval_thread_local.state


def evaluate(expr: Any, context: EvaluationContext | None = None) -> Any:
    """
    Main evaluation loop following the Wolfram Language standard evaluation procedure.

    Algorithm:
    1. Dispatch by expression type (Atom, Symbol, Expression)
    2. For Atoms: return self
    3. For Symbols: apply OwnValues
    4. For Expressions:
       a. Evaluate head (unless HoldAllComplete)
       b. Resolve effective attributes
       c. Evaluate arguments (respecting Hold attributes)
       d. Flatten Sequences
       e. Apply Flat (associativity)
       f. Apply Orderless (commutativity)
       g. Apply Listable (threading)
       h. Try rules (UpValues, DownValues, SubValues, NValues, Built-in)
       i. If changed, re-evaluate (check iteration limit)
       j. Return stable expression
    """
    if context is None:
        context = get_current_context()

    # Step 1: Check recursion limit
    state = _get_eval_state()
    is_top_level = state.recursion_depth == 0
    state.recursion_depth += 1
    if is_top_level:
        state.iteration_count = 0
    if state.recursion_depth > state.recursion_limit:
        state.recursion_depth -= 1
        raise RecursionLimitError(f"Recursion depth of {state.recursion_limit} exceeded")

    try:
        # Step 1: Dispatch by expression type
        if is_atom(expr):
            # Atoms evaluate to themselves
            return expr

        if is_symbol(expr):
            # Apply OwnValues to symbols
            return _evaluate_symbol(expr, context)

        # Expression evaluation
        if not is_expr(expr):
            # Unknown type, return as-is
            return expr

        return _evaluate_expression(expr, context)

    finally:
        _get_eval_state().recursion_depth -= 1


def _evaluate_symbol(sym: Symbol, context: EvaluationContext) -> Any:
    """Evaluate a symbol by applying its OwnValues."""
    from minimatic.pattern import match as pattern_match
    from minimatic.pattern import replace_with_bindings

    own_values = context.get_own_values(sym)

    if not own_values:
        return sym  # No definitions

    # Try each OwnValue rule
    for pattern_expr, replacement, condition in own_values:
        match_result = pattern_match(pattern_expr, sym)

        if not match_result:
            continue

        # Check condition if present
        if condition is not None:
            cond_substituted = replace_with_bindings(condition, match_result.bindings)
            cond_result = evaluate(cond_substituted, context)
            if cond_result is not True and cond_result != Symbol("True"):
                continue

        # Apply replacement and re-evaluate
        result = replace_with_bindings(replacement, match_result.bindings)
        return evaluate(result, context)

    return sym


def _evaluate_expression(expr: Expression, context: EvaluationContext) -> Any:
    """Evaluate a compound expression."""

    # Step 3a: Evaluate head (unless HoldAllComplete)
    head = expr.head
    effective_attrs = _resolve_attributes(expr, context)

    # Check for HoldAllComplete on effective attributes
    has_hold_all_complete = HoldAllComplete in effective_attrs

    if not has_hold_all_complete:
        # Evaluate head
        if is_symbol(head):
            # Check OwnValues for head
            head = _evaluate_symbol(head, context)
        elif is_expr(head):
            head = evaluate(head, context)

        # If head changed, create new expression
        if head != expr.head:
            expr = Expression(head, *expr.args, _attrs=expr.attributes)

    # Step 3b: Resolve attributes (already done above)
    # effective_attrs computed from head + expression attributes

    # Step 3c: Evaluate arguments (respecting Hold attributes)
    evaluated_args = _evaluate_arguments(expr, context, effective_attrs)

    # Check if any argument changed
    args_changed = tuple(evaluated_args) != expr.args

    if args_changed:
        expr = Expression(expr.head, *evaluated_args, _attrs=expr.attributes)

    # Step 3d: Flatten Sequences (unless SequenceHold or HoldAllComplete)
    has_sequence_hold = SequenceHold in effective_attrs

    if not has_hold_all_complete and not has_sequence_hold:
        expr = flatten_sequences(expr, hold_sequence=False)

    # Step 3e: Apply structural attributes
    has_flat = Flat in effective_attrs
    has_orderless = Orderless in effective_attrs

    if has_flat:
        expr = apply_flat(expr, is_flat=True)

    if has_orderless:
        expr = apply_orderless(expr, is_orderless=True)

    # Step 3f: Apply Listable attribute
    has_listable = Listable in effective_attrs

    if has_listable:
        threaded = apply_listable(expr, is_listable=True)
        if threaded != expr:
            # If threading occurred, evaluate the result and return
            return evaluate(threaded, context)

    # Step 3h: Try rules in priority order
    new_expr = _apply_rules(expr, context)

    # Step 3i: Check if changed and re-evaluate
    if new_expr != expr:
        state = _get_eval_state()
        state.iteration_count += 1
        if state.iteration_count > state.iteration_limit:
            raise IterationLimitError(f"Iteration limit of {state.iteration_limit} exceeded")

        # Re-evaluate from top (Step 1)
        return evaluate(new_expr, context)

    # Step 3j: Return stable expression
    return expr


def _resolve_attributes(expr: Expression, context: EvaluationContext) -> frozenset[Symbol]:
    """
    Step 3b: Resolve effective attributes.

    Attributes come from three sources (merged):
    - Head symbol's attributes from the context (user-defined)
    - Built-in function's registered attributes
    - Expression's own attributes (take precedence)
    """
    head_attrs = frozenset()
    if is_symbol(expr.head):
        head_attrs = context.get_attributes(expr.head)

    # Also check built-in registered attributes
    builtin_attributes = _get_builtin_attributes()
    builtin_attrs = builtin_attributes(expr.head) if is_symbol(expr.head) else frozenset()

    # Combine: head_ctx_attrs ∪ builtin_attrs ∪ expr_attrs
    # expr_attrs take precedence
    return head_attrs | builtin_attrs | expr.attributes


def _evaluate_arguments(
    expr: Expression,
    context: EvaluationContext,
    effective_attrs: frozenset[Symbol],
) -> list[Any]:
    """
    Step 3c: Evaluate arguments respecting Hold attributes.

    Hold attributes control which arguments are evaluated:
    - HoldAllComplete or HoldAll: none evaluated
    - HoldFirst: first held, rest evaluated
    - HoldRest: first evaluated, rest held
    - Default (no Hold): all evaluated
    """
    has_hold_all_complete = HoldAllComplete in effective_attrs
    has_hold_all = HoldAll in effective_attrs
    has_hold_first = HoldFirst in effective_attrs
    has_hold_rest = HoldRest in effective_attrs

    if has_hold_all_complete or has_hold_all:
        # Hold all arguments
        return list(expr.args)
    elif has_hold_first:
        # Hold first, evaluate rest
        evaluated_args = [expr.args[0]] if expr.args else []
        evaluated_args.extend(evaluate(arg, context) for arg in expr.args[1:])
        return evaluated_args
    elif has_hold_rest:
        # Evaluate first, hold rest
        if expr.args:
            evaluated_args = [evaluate(expr.args[0], context)]
            evaluated_args.extend(expr.args[1:])
            return evaluated_args
        return []
    else:
        # Evaluate all arguments
        return [evaluate(arg, context) for arg in expr.args]


def _apply_rules(expr: Expression, context: EvaluationContext) -> Any:
    """
    Step 3h: Apply rules via the functional pipeline.

    Delegates to RulePipeline which handles:
    - UpValues (from arguments)
    - DownValues (from head symbol)
    - SubValues (from head expression)
    - NValues (numeric approximation)
    - Built-in fallback
    - User-defined interception rules
    """
    return context.pipeline.apply(expr, context)


def try_evaluate(
    expr: Any,
    context: EvaluationContext | None = None,
    default: Any = None,
) -> Any:
    """
    Evaluate expression, returning default if evaluation fails.
    """
    try:
        return evaluate(expr, context)
    except (RecursionLimitError, IterationLimitError):
        return default


def FixedPoint(
    func: Callable[[Any], Any],
    expr: Any,
    max_iterations: int = 100,
    same_test: Callable | None = None,
) -> Any:
    """
    Apply func repeatedly until the result no longer changes.

    Args:
        func: Function to apply
        expr: Starting expression
        max_iterations: Maximum number of iterations
        same_test: Optional equality test function

    Returns:
        Fixed point of func starting from expr
    """
    if same_test is None:

        def same_test(a: Any, b: Any) -> bool:
            return a == b

    for _ in range(max_iterations):
        new_expr = func(expr)
        if same_test(new_expr, expr):
            return expr
        expr = new_expr

    return expr


def evaluate_iterated(expr: Any, n: int, context: EvaluationContext | None = None) -> Any:
    """
    Evaluate expression n times.
    """
    for _ in range(n):
        expr = evaluate(expr, context)
    return expr


def set_recursion_limit(limit: int) -> int:
    """Set $RecursionLimit and return old value."""
    state = _get_eval_state()
    old = state.recursion_limit
    state.recursion_limit = limit
    return old


def set_iteration_limit(limit: int) -> int:
    """Set $IterationLimit and return old value."""
    state = _get_eval_state()
    old = state.iteration_limit
    state.iteration_limit = limit
    return old


def get_recursion_limit() -> int:
    """Get current $RecursionLimit."""
    return _get_eval_state().recursion_limit


def get_iteration_limit() -> int:
    """Get current $IterationLimit."""
    return _get_eval_state().iteration_limit
