# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [0.1.1] - 2026-06-30

### Added
- Comparison builtins: `Less`, `Greater`, `LessEqual`, `GreaterEqual`, `Equal`, `Unequal`
- Logic builtins: `And`, `Or`, `Not`
- Predicates: `EvenQ`, `OddQ`
- ROADMAP with phased development plan

### Changed
- Simplified evaluation pipeline
- Improved documentation and tests (579 tests passing)

## [0.1.0] - 2026-06-12

### Added
- Immutable interned symbols
- Immutable expressions with `(head, args, attributes)` structure
- Evaluation attributes: `Hold`, `HoldAll`, `HoldFirst`, `HoldRest`, `HoldAllComplete`, `SequenceHold`, `Flat`, `Orderless`, `Listable`
- Standard Wolfram-style evaluation procedure
- Pattern matching with backtracking: `Blank`, `BlankSequence`, `BlankNullSequence`, `Pattern`, `Condition`, `Alternatives`, `PatternTest`, `Optional`, `Repeated`, `RepeatedNull`, `Verbatim`, `HoldPattern`
- Immutable frozenset-backed bindings for match results
- Evaluation contexts with lexical and dynamic scoping
- Value types: `OwnValues`, `DownValues`, `UpValues`, `SubValues`, `NValues`
- Sequence flattening and structural transforms
- Rule pipeline with priority-ordered dispatch (intercept-before, UpValues, DownValues, SubValues, NValues, builtins, intercept-after)
- Arithmetic builtins: `Plus`, `Times`, `Power`, `Minus`, `Divide`, `Subtract`, `Abs`, `Sqrt`, `Exp`, `Log`, `Sum`, `Product`
- Control flow builtins: `Set`, `SetDelayed`, `If`, `Which`, `Switch`, `CompoundExpression`, `Evaluate`, `ReleaseHold`, `Hold`, `HoldForm`, `Do`, `While`, `For`, `Table`, `Nest`, `NestList`, `Fold`, `Map`, `Module`, `Block`, `With`
- Predicate builtins: `TrueQ`, `SameQ`, `UnsameQ`, `NumericQ`, `AtomQ`, `HeadQ`, `ListQ`, `StringQ`, `IntegerQ`, `RealQ`
- Builtin registry with `@register_builtin` decorator
- Test suite with pytest
- Ruff linting and Pyright type checking

## [0.0.1] - 2025-09-27

### Added
- Initial project structure
- Core expression classes
- Basic arithmetic evaluation
- README documentation
- MIT License
