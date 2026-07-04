"""Tests for the functional rule pipeline."""

from __future__ import annotations

import pytest

from minimatic.core import Expression, Symbol, is_expr
from minimatic.core.attributes import Flat, HoldAll, HoldFirst, Orderless
from minimatic.eval.context import EvaluationContext
from minimatic.eval.evaluator import evaluate
from minimatic.eval.pipeline import (
    BuiltinFallback,
    PipelineRule,
    RulePipeline,
    RuleSource,
)
from minimatic.pattern import blank, pattern


Plus = Symbol("Plus")
Times = Symbol("Times")
F = Symbol("F")
x = Symbol("x")
y = Symbol("y")
z = Symbol("z")


@pytest.fixture
def ctx():
    return EvaluationContext("test")


def pat_plus():
    """Plus[a_, b_] pattern."""
    return Expression(Plus, pattern(x, blank()), pattern(y, blank()))


def pat_times():
    """Times[a_, b_] pattern."""
    return Expression(Times, pattern(x, blank()), pattern(y, blank()))


class TestPipelineConstruction:
    def test_empty_pipeline_returns_original(self, ctx):
        pipeline = RulePipeline()
        expr = Expression(F, 1, 2)
        assert pipeline.apply(expr, ctx) == expr

    def test_non_expression_passes_through(self, ctx):
        pipeline = RulePipeline()
        assert pipeline.apply(42, ctx) == 42
        assert pipeline.apply("hello", ctx) == "hello"


class TestRuleMatching:
    def test_single_rule_match(self, ctx):
        pipeline = RulePipeline()
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("matched")))
        expr = Expression(Plus, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("matched")

    def test_single_rule_no_match(self, ctx):
        pipeline = RulePipeline()
        # Rule expects F but we give Plus — no match, but Plus has a global builtin
        # Use F (no builtin) to verify no-match returns original
        pat_f = Expression(F, pattern(x, blank()))
        pipeline.add_rule(PipelineRule(pat_f, Symbol("matched")))
        expr = Expression(F, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == expr

    def test_callable_replacement(self, ctx):
        pipeline = RulePipeline()

        def add_bindings(bindings):
            a = bindings[x]
            b = bindings[y]
            if isinstance(a, int) and isinstance(b, int):
                return a + b
            return Expression(Plus, a, b)

        pipeline.add_rule(PipelineRule(pat_plus(), add_bindings))
        expr = Expression(Plus, 3, 4)
        result = pipeline.apply(expr, ctx)
        assert result == 7


class TestPriorityOrdering:
    def test_higher_priority_wins(self, ctx):
        pipeline = RulePipeline()
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("low"), priority=10))
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("high"), priority=100))

        expr = Expression(Plus, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("high")

    def test_first_match_wins_at_same_priority(self, ctx):
        pipeline = RulePipeline()
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("first"), priority=50))
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("second"), priority=50))

        expr = Expression(Plus, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("first")


class TestConditionRules:
    def test_condition_pass(self, ctx):
        pipeline = RulePipeline()
        cond = Expression(Symbol("Greater"), x, 0)
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("matched"), condition=cond))

        ctx.set_own_values(x, [(x, 5, None)])
        expr = Expression(Plus, 5, 3)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("matched")

    def test_condition_fail(self, ctx):
        pipeline = RulePipeline()
        pat_f = Expression(F, pattern(x, blank()), pattern(y, blank()))
        cond = Expression(Symbol("Less"), x, 0)
        pipeline.add_rule(PipelineRule(pat_f, Symbol("matched"), condition=cond))

        ctx.set_own_values(x, [(x, 5, None)])
        expr = Expression(F, 5, 3)
        result = pipeline.apply(expr, ctx)
        assert result == expr


class TestInterceptRules:
    def test_intercept_before_overrides_builtin(self, ctx):
        pipeline = RulePipeline()

        def my_plus(expr, context):
            return Symbol("builtin_called")

        pipeline.add_builtin(BuiltinFallback(Plus, my_plus, frozenset()))
        pipeline.add_intercept_before(PipelineRule(pat_plus(), Symbol("intercepted")))

        expr = Expression(Plus, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("intercepted")

    def test_intercept_after_fallback(self, ctx):
        pipeline = RulePipeline()
        pat_f = Expression(F, pattern(x, blank()), pattern(y, blank()))
        pipeline.add_intercept_after(PipelineRule(pat_f, Symbol("after")))

        expr = Expression(F, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("after")


class TestHeadIndexing:
    def test_rules_for_different_heads(self, ctx):
        pipeline = RulePipeline()
        pipeline.add_rule(PipelineRule(pat_plus(), Symbol("plus_matched")))
        pipeline.add_rule(PipelineRule(pat_times(), Symbol("times_matched")))

        assert pipeline.apply(Expression(Plus, 1, 2), ctx) == Symbol("plus_matched")
        assert pipeline.apply(Expression(Times, 3, 4), ctx) == Symbol("times_matched")

    def test_rules_for_different_arg_symbols(self, ctx):
        pipeline = RulePipeline()

        x_up = Expression(F, x)
        pipeline.add_up_value(
            PipelineRule(x_up, Symbol("x_up"), source=RuleSource.UP_VALUES),
            x,
        )

        y_up = Expression(F, y)
        pipeline.add_up_value(
            PipelineRule(y_up, Symbol("y_up"), source=RuleSource.UP_VALUES),
            y,
        )

        assert pipeline.apply(Expression(F, x), ctx) == Symbol("x_up")
        assert pipeline.apply(Expression(F, y), ctx) == Symbol("y_up")


class TestBuiltinFallback:
    def test_builtin_called_when_no_rules_match(self, ctx):
        pipeline = RulePipeline()

        def my_impl(expr, context):
            return Symbol("builtin_result")

        pipeline.add_builtin(BuiltinFallback(F, my_impl, frozenset()))

        expr = Expression(F, 1, 2)
        result = pipeline.apply(expr, ctx)
        assert result == Symbol("builtin_result")


class TestParentPipeline:
    def test_child_inherits_parent_rules(self, ctx):
        parent = RulePipeline()
        child = RulePipeline(parent=parent)

        parent.add_rule(PipelineRule(pat_plus(), Symbol("parent_rule")))

        expr = Expression(Plus, 1, 2)
        assert child.apply(expr, ctx) == Symbol("parent_rule")

    def test_child_rule_shadows_parent(self, ctx):
        parent = RulePipeline()
        child = RulePipeline(parent=parent)

        parent.add_rule(PipelineRule(pat_plus(), Symbol("parent"), priority=50))
        child.add_rule(PipelineRule(pat_plus(), Symbol("child"), priority=100))

        expr = Expression(Plus, 1, 2)
        assert child.apply(expr, ctx) == Symbol("child")

    def test_child_builtin_inherits_parent(self, ctx):
        parent = RulePipeline()
        child = RulePipeline(parent=parent)

        def my_impl(expr, context):
            return Symbol("parent_builtin")

        parent.add_builtin(BuiltinFallback(F, my_impl, frozenset()))

        expr = Expression(F, 1, 2)
        assert child.apply(expr, ctx) == Symbol("parent_builtin")


class TestContextIntegration:
    def test_context_has_pipeline(self, ctx):
        assert hasattr(ctx, "pipeline")
        assert isinstance(ctx.pipeline, RulePipeline)

    def test_child_context_inherits_pipeline(self, ctx):
        child = EvaluationContext("child", parent=ctx)
        assert child.pipeline.parent is ctx.pipeline

    def test_pipeline_rule_via_context(self, ctx):
        ctx.pipeline.add_rule(PipelineRule(pat_plus(), Symbol("via_context")))
        expr = Expression(Plus, 1, 2)
        assert evaluate(expr, ctx) == Symbol("via_context")


class TestThreadSafety:
    def test_concurrent_pipeline_use(self, ctx):
        import threading

        ctx.pipeline.add_rule(PipelineRule(pat_plus(), Symbol("result")))

        results = []
        errors = []

        def worker():
            try:
                expr = Expression(Plus, 1, 2)
                result = ctx.pipeline.apply(expr, ctx)
                results.append(result)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert all(r == Symbol("result") for r in results)
