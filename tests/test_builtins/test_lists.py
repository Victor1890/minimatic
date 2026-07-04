"""Tests for List builtins module."""

from __future__ import annotations

# Force registration of builtins
import minimatic.builtins.lists  # noqa: F401
from minimatic.core.expression import Expression, is_expr
from minimatic.core.symbol import Symbol
from minimatic.eval.evaluator import evaluate

Length = Symbol("Length")
Part = Symbol("Part")
First = Symbol("First")
Last = Symbol("Last")
Range = Symbol("Range")
List = Symbol("List")
Plus = Symbol("Plus")
f = Symbol("f")


class TestLength:
    def test_length_list(self, ctx):
        result = evaluate(Expression(Length, Expression(List, 1, 2, 3)), ctx)
        assert result == 3

    def test_length_empty_list(self, ctx):
        result = evaluate(Expression(Length, Expression(List)), ctx)
        assert result == 0

    def test_length_nested_list(self, ctx):
        result = evaluate(Expression(Length, Expression(List, Expression(List, 1, 2), Expression(List, 3))), ctx)
        assert result == 2

    def test_length_non_list_expression(self, ctx):
        result = evaluate(Expression(Length, Expression(Plus, 1, 2, 3)), ctx)
        assert result == 0  # Plus[1,2,3] evaluates to 6 (atom)

    def test_length_atom(self, ctx):
        result = evaluate(Expression(Length, 42), ctx)
        assert result == 0

    def test_length_symbol(self, ctx):
        result = evaluate(Expression(Length, Symbol("x")), ctx)
        assert is_expr(result)
        assert result.head == Length

    def test_length_no_args(self, ctx):
        result = evaluate(Expression(Length), ctx)
        assert is_expr(result)
        assert result.head == Length


class TestPart:
    def test_part_basic(self, ctx):
        result = evaluate(Expression(Part, Expression(List, "a", "b", "c"), 2), ctx)
        assert result == "b"

    def test_part_first(self, ctx):
        result = evaluate(Expression(Part, Expression(List, 10, 20, 30), 1), ctx)
        assert result == 10

    def test_part_last(self, ctx):
        result = evaluate(Expression(Part, Expression(List, 10, 20, 30), -1), ctx)
        assert result == 30

    def test_part_negative_index(self, ctx):
        result = evaluate(Expression(Part, Expression(List, "a", "b", "c"), -2), ctx)
        assert result == "b"

    def test_part_nested(self, ctx):
        inner = Expression(List, Expression(List, 1, 2), Expression(List, 3, 4))
        result = evaluate(Expression(Part, inner, 2, 1), ctx)
        assert result == 3

    def test_part_out_of_bounds(self, ctx):
        result = evaluate(Expression(Part, Expression(List, 1, 2), 5), ctx)
        assert is_expr(result)
        assert result.head == Part

    def test_part_non_expression(self, ctx):
        result = evaluate(Expression(Part, 42, 1), ctx)
        assert is_expr(result)
        assert result.head == Part

    def test_part_non_integer_index(self, ctx):
        result = evaluate(Expression(Part, Expression(List, 1, 2), Symbol("x")), ctx)
        assert is_expr(result)
        assert result.head == Part

    def test_part_single_element(self, ctx):
        result = evaluate(Expression(Part, Expression(List, 42), 1), ctx)
        assert result == 42

    def test_part_expression_head(self, ctx):
        result = evaluate(Expression(Part, Expression(f, "a", "b", "c"), 2), ctx)
        assert result == "b"


class TestFirst:
    def test_first_basic(self, ctx):
        result = evaluate(Expression(First, Expression(List, "a", "b", "c")), ctx)
        assert result == "a"

    def test_first_single(self, ctx):
        result = evaluate(Expression(First, Expression(List, 42)), ctx)
        assert result == 42

    def test_first_empty(self, ctx):
        result = evaluate(Expression(First, Expression(List)), ctx)
        assert is_expr(result)
        assert result.head == First

    def test_first_non_list(self, ctx):
        result = evaluate(Expression(First, Symbol("x")), ctx)
        assert is_expr(result)
        assert result.head == First

    def test_first_no_args(self, ctx):
        result = evaluate(Expression(First), ctx)
        assert is_expr(result)
        assert result.head == First


class TestLast:
    def test_last_basic(self, ctx):
        result = evaluate(Expression(Last, Expression(List, "a", "b", "c")), ctx)
        assert result == "c"

    def test_last_single(self, ctx):
        result = evaluate(Expression(Last, Expression(List, 42)), ctx)
        assert result == 42

    def test_last_empty(self, ctx):
        result = evaluate(Expression(Last, Expression(List)), ctx)
        assert is_expr(result)
        assert result.head == Last

    def test_last_non_list(self, ctx):
        result = evaluate(Expression(Last, Symbol("x")), ctx)
        assert is_expr(result)
        assert result.head == Last

    def test_last_no_args(self, ctx):
        result = evaluate(Expression(Last), ctx)
        assert is_expr(result)
        assert result.head == Last


class TestRange:
    def test_range_single(self, ctx):
        result = evaluate(Expression(Range, 5), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == (1, 2, 3, 4, 5)

    def test_range_two_args(self, ctx):
        result = evaluate(Expression(Range, 2, 5), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == (2, 3, 4, 5)

    def test_range_three_args(self, ctx):
        result = evaluate(Expression(Range, 1, 10, 2), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == (1, 3, 5, 7, 9)

    def test_range_empty(self, ctx):
        result = evaluate(Expression(Range, 5, 1), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == ()

    def test_range_single_value(self, ctx):
        result = evaluate(Expression(Range, 1), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == (1,)

    def test_range_negative_step(self, ctx):
        result = evaluate(Expression(Range, 5, 1, -1), ctx)
        assert is_expr(result)
        assert result.head == List
        assert result.args == (5, 4, 3, 2, 1)

    def test_range_zero_step(self, ctx):
        result = evaluate(Expression(Range, 1, 5, 0), ctx)
        assert is_expr(result)
        assert result.head == Range

    def test_range_non_integer(self, ctx):
        result = evaluate(Expression(Range, 5.0), ctx)
        assert is_expr(result)
        assert result.head == Range

    def test_range_no_args(self, ctx):
        result = evaluate(Expression(Range), ctx)
        assert is_expr(result)
        assert result.head == Range

    def test_range_four_args(self, ctx):
        result = evaluate(Expression(Range, 1, 5, 1, 1), ctx)
        assert is_expr(result)
        assert result.head == Range
