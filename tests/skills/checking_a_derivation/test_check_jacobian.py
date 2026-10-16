"""Tests for the three-way Jacobian check. Needs sympy and mpmath; the tests skip without them."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

sympy = pytest.importorskip("sympy")
mpmath = pytest.importorskip("mpmath")

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPOSITORY_ROOT
    / "packs"
    / "experiments"
    / "checking-a-derivation"
    / "scripts"
    / "check_jacobian.py"
)


def load_check_jacobian() -> ModuleType:
    specification = importlib.util.spec_from_file_location("check_jacobian", SCRIPT_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot load check_jacobian.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules["check_jacobian"] = module
    specification.loader.exec_module(module)
    return module


check_jacobian = load_check_jacobian()


def demo_ranges() -> dict[object, tuple[float, float]]:
    state_symbols, _, omega = check_jacobian.demo_model()
    ranges = {symbol: (-3.0, 3.0) for symbol in state_symbols}
    ranges[omega] = (0.2, 2.0)
    return ranges


def test_correct_jacobian_matches_on_all_terms() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    report = check_jacobian.check_jacobian(
        state_symbols, equations, check_jacobian.demo_code_jacobian(1.0), demo_ranges()
    )
    assert report.all_terms_match


def test_planted_sign_flip_is_reported_at_the_exact_entry() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    report = check_jacobian.check_jacobian(
        state_symbols, equations, check_jacobian.demo_code_jacobian(-1.0), demo_ranges()
    )
    wrong_entries = {(mismatch.row, mismatch.column) for mismatch in report.mismatches}
    assert wrong_entries == {(2, 4)}
    comparisons = {mismatch.comparison for mismatch in report.mismatches}
    assert check_jacobian.Comparison.CODE_VS_FINITE_DIFFERENCE in comparisons
    assert check_jacobian.Comparison.CODE_VS_DERIVED in comparisons


def test_finite_difference_matches_known_derivative() -> None:
    def model(point: list[float]) -> list[float]:
        return [point[0] ** 2 * point[1]]

    jacobian = check_jacobian.central_finite_difference_jacobian(model, [2.0, 3.0])
    assert jacobian[0][0] == pytest.approx(12.0, rel=1e-6)
    assert jacobian[0][1] == pytest.approx(4.0, rel=1e-6)


def test_finite_difference_wraps_angle_rows_across_the_cut() -> None:
    import math

    def model(point: list[float]) -> list[float]:
        return [check_jacobian.wrap_angle(point[0])]

    near_cut = [math.pi - 1.0e-7]
    unwrapped = check_jacobian.central_finite_difference_jacobian(model, near_cut)
    wrapped = check_jacobian.central_finite_difference_jacobian(model, near_cut, frozenset({0}))
    assert abs(unwrapped[0][0]) > 1.0e3
    assert wrapped[0][0] == pytest.approx(1.0, rel=1e-3)


def test_limiting_form_catches_a_wrong_branch() -> None:
    state_symbols, equations, omega = check_jacobian.demo_model()
    derived = sympy.Matrix(equations).jacobian(sympy.Matrix(state_symbols))
    delta = check_jacobian.DEMO_TIME_STEP_RATIONAL
    vy = state_symbols[3]
    correct = sympy.zeros(5, 5)
    correct[0, 4] = -sympy.Rational(1, 2) * delta**2 * vy
    wrong = sympy.zeros(5, 5)
    wrong[0, 4] = sympy.Rational(1, 2) * delta**2 * vy
    # Compare a single entry by checking the only differing position.
    mismatch_rows = {
        (row, column)
        for row, column, _, _ in check_jacobian.limiting_form_mismatches(derived, wrong, omega)
    }
    correct_rows = {
        (row, column)
        for row, column, _, _ in check_jacobian.limiting_form_mismatches(derived, correct, omega)
    }
    assert (0, 4) in mismatch_rows
    assert (0, 4) not in correct_rows


def test_symbolic_difference_is_zero_for_equal_trig_forms() -> None:
    angle = sympy.Symbol("angle", real=True)
    assert check_jacobian.symbolic_difference_is_zero(
        sympy.sin(2 * angle), 2 * sympy.sin(angle) * sympy.cos(angle)
    )
    assert not check_jacobian.symbolic_difference_is_zero(sympy.sin(angle), sympy.cos(angle))


def test_demo_runs_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert check_jacobian.main(["--demo"]) == 0
    printed = capsys.readouterr().out
    assert "correct Jacobian:\nnumeric: all terms match (4 named edge points" in printed
    assert "symbolic: all 25 entries proven equal" in printed
    assert "small_omega" in printed
    assert "limiting form at omega -> 0: all terms match" in printed


def test_random_sampling_misses_a_wrong_small_omega_branch_but_a_named_edge_point_catches_it() -> (
    None
):
    state_symbols, equations, _ = check_jacobian.demo_model()
    buggy_code = check_jacobian.demo_code_jacobian(1.0, sign_of_limiting_branch=-1.0)

    random_only_report = check_jacobian.check_jacobian(
        state_symbols, equations, buggy_code, demo_ranges()
    )
    assert random_only_report.all_terms_match

    report = check_jacobian.check_jacobian(
        state_symbols,
        equations,
        buggy_code,
        demo_ranges(),
        edge_points=check_jacobian.demo_edge_points(),
    )
    assert not report.all_terms_match
    assert {mismatch.point_name for mismatch in report.mismatches} == {"small_omega"}
    assert {(mismatch.row, mismatch.column) for mismatch in report.mismatches} == {(0, 4), (1, 4)}
    assert "at small_omega" in report.summary()


def test_edge_point_missing_a_state_symbol_is_rejected() -> None:
    state_symbols, equations, omega = check_jacobian.demo_model()
    incomplete_point = check_jacobian.NamedPoint("incomplete", {omega: 1.0e-9})
    with pytest.raises(ValueError, match="incomplete"):
        check_jacobian.check_jacobian(
            state_symbols,
            equations,
            check_jacobian.demo_code_jacobian(1.0),
            demo_ranges(),
            edge_points=[incomplete_point],
        )


def test_symbolic_comparison_flags_a_planted_sign_flip_and_proves_the_correct_matrix() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    correct_report = check_jacobian.check_jacobian(
        state_symbols,
        equations,
        check_jacobian.demo_code_jacobian(1.0),
        demo_ranges(),
        code_expressions=check_jacobian.demo_code_expressions(1.0),
    )
    assert correct_report.symbolic_status is check_jacobian.SymbolicStatus.ALL_PROVEN_EQUAL
    assert "symbolic: all 25 entries proven equal" in correct_report.summary()

    flipped_report = check_jacobian.check_jacobian(
        state_symbols,
        equations,
        check_jacobian.demo_code_jacobian(-1.0),
        demo_ranges(),
        code_expressions=check_jacobian.demo_code_expressions(-1.0),
    )
    assert flipped_report.symbolic_status is check_jacobian.SymbolicStatus.NOT_PROVEN_EQUAL
    assert [(entry.row, entry.column) for entry in flipped_report.symbolic_mismatches] == [(2, 4)]
    assert "symbolic: 1 entries not proven equal" in flipped_report.summary()


def test_report_says_step_two_was_not_run_without_code_expressions() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    report = check_jacobian.check_jacobian(
        state_symbols, equations, check_jacobian.demo_code_jacobian(1.0), demo_ranges()
    )
    assert report.symbolic_status is check_jacobian.SymbolicStatus.NOT_RUN
    assert "symbolic: NOT RUN" in report.summary()


def test_symbolic_comparison_rejects_a_matrix_of_the_wrong_shape() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    with pytest.raises(ValueError, match="shape"):
        check_jacobian.check_jacobian(
            state_symbols,
            equations,
            check_jacobian.demo_code_jacobian(1.0),
            demo_ranges(),
            code_expressions=sympy.zeros(2, 2),
        )


def test_nearly_equal_distinct_parameters_are_warned_about_by_point_name() -> None:
    state_symbols, equations, _ = check_jacobian.demo_model()
    _, _, vx, vy, omega = state_symbols
    equal_speed_point = check_jacobian.NamedPoint(
        "equal_speeds", {state_symbols[0]: 0.0, state_symbols[1]: 0.0, vx: 2.0, vy: 2.0, omega: 0.5}
    )
    report = check_jacobian.check_jacobian(
        state_symbols,
        equations,
        check_jacobian.demo_code_jacobian(1.0),
        demo_ranges(),
        edge_points=[equal_speed_point],
        distinct_parameter_groups=[(vx, vy)],
        point_count=5,
    )
    assert report.all_terms_match
    assert [warning.point_name for warning in report.near_equal_warnings] == ["equal_speeds"]
    assert "warning: vx and vy are nearly equal" in report.summary()


def test_demo_edge_points_use_unequal_velocities() -> None:
    _, _, velocity_x, velocity_y, _ = check_jacobian.demo_model()[0]
    for edge_point in check_jacobian.demo_edge_points():
        assert not check_jacobian.values_nearly_equal(
            edge_point.values[velocity_x], edge_point.values[velocity_y]
        )
