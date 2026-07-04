"""
Functional rule pipeline for expression evaluation.

Replaces the imperative _apply_rules dispatch with a pattern-matching-based
rule application engine that supports:
- Indexed rule lookup by head symbol
- User-defined interception rules
- Priority-based rule ordering
- Seamless integration with builtins
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from minimatic.core import Expression, Symbol, is_expr, is_symbol
from minimatic.pattern import match, replace_with_bindings

if TYPE_CHECKING:
    from minimatic.eval.context import EvaluationContext


class RuleSource(Enum):
    """Source of a rule in the pipeline."""

    USER_INTERCEPT = auto()
    UP_VALUES = auto()
    DOWN_VALUES = auto()
    SUB_VALUES = auto()
    N_VALUES = auto()
    BUILTIN = auto()


@dataclass(frozen=True)
class PipelineRule:
    """
    A rule in the evaluation pipeline.

    Attributes:
        pattern: Pattern expression to match against
        replacement: Replacement expression or callable(bindings) -> expr
        condition: Optional guard expression (evaluated with match bindings)
        source: Where this rule came from
        priority: Ordering — higher values are tried first
    """

    pattern: Any
    replacement: Any
    condition: Any | None = None
    source: RuleSource = RuleSource.DOWN_VALUES
    priority: int = 0


@dataclass(frozen=True)
class BuiltinFallback:
    """
    A built-in function registered as a pipeline fallback.

    Builtins receive the fully-evaluated expression and context,
    and return the final result (unlike pattern rules which only
    substitute — the fixed-point loop handles evaluation).
    """

    symbol: Symbol
    implementation: Callable[[Expression, EvaluationContext], Any]
    attributes: frozenset[Symbol]


class RulePipeline:
    """
    Functional rule pipeline for expression evaluation.

    Collects rules from multiple sources, indexes them by head symbol,
    and applies them using the existing pattern matcher.

    Sources are tried in priority order:
    1. intercept_before — user-defined rules that fire first
    2. UpValues — operator overloading on arguments
    3. DownValues — function definitions on head
    4. SubValues — subscripted function definitions
    5. NValues — numeric approximation
    6. Built-in — native implementation (calls directly, no substitution)
    7. intercept_after — user-defined rules that fire last
    """

    def __init__(self, parent: RulePipeline | None = None):
        self.parent = parent

        # Rules indexed by head symbol for O(1) lookup
        self._rules_by_head: dict[Symbol, list[PipelineRule]] = {}

        # UpValues indexed by argument symbol
        self._up_values_by_arg: dict[Symbol, list[PipelineRule]] = {}

        # Built-in fallbacks indexed by symbol
        self._builtins: dict[Symbol, BuiltinFallback] = {}

        # User-defined interception rules
        self._intercept_before: list[PipelineRule] = []
        self._intercept_after: list[PipelineRule] = []

    def add_rule(self, rule: PipelineRule, head: Symbol | None = None) -> None:
        """
        Add a rule, optionally specifying the head symbol for indexing.

        If head is not provided, it is extracted from the pattern:
        - Expression head: pattern.head if it's a Symbol
        - Fallback: rule is added to a global unindexed list (not recommended)
        """
        if head is None and is_expr(rule.pattern) and is_symbol(rule.pattern.head):
            head = rule.pattern.head

        if head is not None:
            if head not in self._rules_by_head:
                self._rules_by_head[head] = []
            self._rules_by_head[head].append(rule)

    def add_up_value(self, rule: PipelineRule, arg_symbol: Symbol) -> None:
        """Add an UpValue rule indexed by the argument symbol it applies to."""
        if arg_symbol not in self._up_values_by_arg:
            self._up_values_by_arg[arg_symbol] = []
        self._up_values_by_arg[arg_symbol].append(rule)

    def add_builtin(self, fallback: BuiltinFallback) -> None:
        """Register a built-in function as a fallback."""
        self._builtins[fallback.symbol] = fallback

    def add_intercept_before(self, rule: PipelineRule) -> None:
        """Add a user-defined rule that fires before all other rules."""
        self._intercept_before.append(rule)

    def add_intercept_after(self, rule: PipelineRule) -> None:
        """Add a user-defined rule that fires after builtins."""
        self._intercept_after.append(rule)

    def apply(self, expr: Any, context: EvaluationContext) -> Any:
        """
        Apply rules to an expression.

        Tries each source in priority order, returning the first
        successful transformation. If no rule matches, returns the
        original expression unchanged.

        For pattern-based rules, the result is a substitution only —
        no evaluation occurs. The fixed-point loop in the evaluator
        handles re-evaluation.

        For builtins, the implementation is called directly and returns
        a fully evaluated result.
        """
        if not is_expr(expr):
            return expr

        # 1. User intercept-before rules (highest priority)
        result = self._try_rules(self._intercept_before, expr, context)
        if result != expr:
            return result

        # 2. UpValues — check arguments left-to-right
        result = self._try_up_values(expr, context)
        if result != expr:
            return result

        # 3. DownValues from head symbol
        if is_symbol(expr.head):
            rules = self._get_rules(expr.head)
            if rules:
                result = self._try_rules(rules, expr, context)
                if result != expr:
                    return result

        # 4. SubValues — head is Expression[sym, ...]
        if is_expr(expr.head) and is_symbol(expr.head.head):
            rules = self._get_rules(expr.head.head)
            if rules:
                result = self._try_rules(rules, expr, context)
                if result != expr:
                    return result

        # 5. NValues — numeric approximation
        # Currently handled via DownValues on N, no separate index needed

        # 6. Built-in fallback
        if is_symbol(expr.head):
            builtin = self._builtins.get(expr.head)
            if builtin is None and self.parent is not None:
                builtin = self.parent._builtins.get(expr.head)
            if builtin is None:
                # Fall back to global builtin registry
                from minimatic.builtins.registry import get_builtin

                global_builtin = get_builtin(expr.head)
                if global_builtin is not None:
                    return global_builtin.implementation(expr, context)
            elif builtin is not None:
                return builtin.implementation(expr, context)

        # 7. User intercept-after rules (lowest priority)
        result = self._try_rules(self._intercept_after, expr, context)
        if result != expr:
            return result

        return expr

    def _try_up_values(self, expr: Expression, context: EvaluationContext) -> Any:
        """Try UpValues from all arguments, left-to-right. First match wins."""
        for arg in expr.args:
            arg_sym = None
            if is_symbol(arg):
                arg_sym = arg
            elif is_expr(arg) and is_symbol(arg.head):
                arg_sym = arg.head

            if arg_sym is not None:
                rules = self._get_up_value_rules(arg_sym)
                if rules:
                    result = self._try_rules(rules, expr, context)
                    if result != expr:
                        return result

        return expr

    def _get_rules(self, head: Symbol) -> list[PipelineRule]:
        """Get all rules for a head symbol, including from parent pipeline."""
        rules = list(self._rules_by_head.get(head, []))
        if self.parent is not None:
            rules.extend(self.parent._get_rules(head))
        return rules

    def _get_up_value_rules(self, arg_symbol: Symbol) -> list[PipelineRule]:
        """Get UpValue rules for an argument symbol, including parent."""
        rules = list(self._up_values_by_arg.get(arg_symbol, []))
        if self.parent is not None:
            rules.extend(self.parent._get_up_value_rules(arg_symbol))
        return rules

    def _try_rules(
        self, rules: list[PipelineRule], expr: Any, context: EvaluationContext
    ) -> Any:
        """Try a list of rules against an expression. Returns first match or original."""
        if not rules:
            return expr

        # Sort by priority (highest first)
        sorted_rules = sorted(rules, key=lambda r: -r.priority)

        for rule in sorted_rules:
            result = self._try_rule(rule, expr, context)
            if result != expr:
                return result

        return expr

    def _try_rule(
        self, rule: PipelineRule, expr: Any, context: EvaluationContext
    ) -> Any:
        """Try a single rule. Returns transformed expression or original."""
        match_result = match(rule.pattern, expr)

        if not match_result:
            return expr

        # Check condition if present
        if rule.condition is not None:
            from minimatic.eval.evaluator import evaluate

            cond_substituted = replace_with_bindings(rule.condition, match_result.bindings)
            cond_result = evaluate(cond_substituted, context)

            if cond_result is not True and cond_result != Symbol("True"):
                return expr

        # Apply replacement — substitution only, no evaluation
        if callable(rule.replacement):
            return rule.replacement(match_result.bindings)

        return replace_with_bindings(rule.replacement, match_result.bindings)
