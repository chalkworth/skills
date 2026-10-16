"""Tests for the experiment statistics helper: textbook values, identities and small simulations.

Needs numpy and scipy, which the dev environment may lack; the tests skip without them. To run them:
`uv run --with numpy --with scipy pytest tests/skills/designing_experiments`.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path
from types import ModuleType

import pytest

numpy = pytest.importorskip("numpy")
scipy_stats = pytest.importorskip("scipy.stats")

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
STATS_PATH = (
    REPOSITORY_ROOT / "packs" / "experiments" / "designing-experiments" / "scripts" / "stats.py"
)


def load_stats() -> ModuleType:
    specification = importlib.util.spec_from_file_location("experiment_stats", STATS_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot load stats.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules["experiment_stats"] = module
    specification.loader.exec_module(module)
    return module


experiment_stats = load_stats()


# --- intervals for rates -------------------------------------------------------------------------------------


def test_wilson_matches_textbook_values() -> None:
    zero_of_ten = experiment_stats.wilson_interval(0, 10)
    assert zero_of_ten.lower == pytest.approx(0.0, abs=1e-12)
    assert zero_of_ten.upper == pytest.approx(0.2775, abs=5e-4)
    five_of_ten = experiment_stats.wilson_interval(5, 10)
    assert five_of_ten.lower == pytest.approx(0.2366, abs=5e-4)
    assert five_of_ten.upper == pytest.approx(0.7634, abs=5e-4)


def test_wilson_rejects_bad_counts() -> None:
    with pytest.raises(ValueError):
        experiment_stats.wilson_interval(11, 10)
    with pytest.raises(ValueError):
        experiment_stats.wilson_interval(0, 0)


def test_clopper_pearson_matches_textbook_values() -> None:
    zero_of_ten = experiment_stats.clopper_pearson_interval(0, 10)
    assert zero_of_ten.lower == 0.0
    assert zero_of_ten.upper == pytest.approx(1.0 - 0.025 ** (1.0 / 10.0), abs=1e-9)
    assert zero_of_ten.upper == pytest.approx(0.3085, abs=5e-4)
    five_of_ten = experiment_stats.clopper_pearson_interval(5, 10)
    assert five_of_ten.lower == pytest.approx(0.1871, abs=5e-4)
    assert five_of_ten.upper == pytest.approx(0.8129, abs=5e-4)


def test_clopper_pearson_is_wider_than_wilson() -> None:
    wilson = experiment_stats.wilson_interval(3, 40)
    exact = experiment_stats.clopper_pearson_interval(3, 40)
    assert exact.lower <= wilson.lower
    assert exact.upper >= wilson.upper


def test_rule_of_three() -> None:
    assert experiment_stats.rule_of_three_upper_bound(100) == pytest.approx(0.02996, abs=1e-5)
    assert experiment_stats.rule_of_three_upper_bound(300) == pytest.approx(3.0 / 300.0, rel=1e-2)
    one_sided_exact = experiment_stats.clopper_pearson_interval(
        0, 100, confidence=0.90
    ).upper  # 95% one-sided
    assert experiment_stats.rule_of_three_upper_bound(100) == pytest.approx(
        one_sided_exact, rel=0.02
    )


# --- paired and clustered resampling, McNemar, Holm --------------------------------------------------------------


def test_paired_bootstrap_of_constant_gain_collapses_to_the_gain() -> None:
    baseline = [0.50, 0.60, 0.70, 0.55, 0.65]
    candidate = [value + 0.05 for value in baseline]
    result = experiment_stats.paired_bootstrap_delta(baseline, candidate, seed=1, resamples=500)
    assert result.estimate == pytest.approx(0.05)
    assert result.lower == pytest.approx(0.05)
    assert result.upper == pytest.approx(0.05)


def test_paired_bootstrap_is_reproducible_and_brackets_the_mean() -> None:
    generator = numpy.random.default_rng(3)
    baseline = generator.normal(0.5, 0.1, 40)
    candidate = baseline + generator.normal(0.02, 0.03, 40)
    first = experiment_stats.paired_bootstrap_delta(baseline, candidate, seed=7, resamples=2000)
    second = experiment_stats.paired_bootstrap_delta(baseline, candidate, seed=7, resamples=2000)
    assert first == second
    assert first.lower < first.estimate < first.upper
    assert first.lower > 0.0


def test_paired_bootstrap_rejects_mismatched_lengths() -> None:
    with pytest.raises(ValueError):
        experiment_stats.paired_bootstrap_delta([1.0, 2.0], [1.0, 2.0, 3.0])


def test_cluster_bootstrap_is_wider_than_row_bootstrap_when_rows_share_a_cluster() -> None:
    generator = numpy.random.default_rng(5)
    clusters = 12
    rows_per_cluster = 20
    cluster_effects = generator.normal(0.0, 1.0, clusters)
    values = numpy.repeat(cluster_effects, rows_per_cluster) + generator.normal(
        0.0, 0.1, clusters * rows_per_cluster
    )
    cluster_ids = numpy.repeat(numpy.arange(clusters), rows_per_cluster)
    by_cluster = experiment_stats.cluster_bootstrap_ci(values, cluster_ids, seed=1, resamples=2000)
    by_row = experiment_stats.cluster_bootstrap_ci(
        values, numpy.arange(values.size), seed=1, resamples=2000
    )
    assert by_cluster.unit_count == clusters
    assert (by_cluster.upper - by_cluster.lower) > 2.0 * (by_row.upper - by_row.lower)


def test_mcnemar_exact_matches_hand_calculation() -> None:
    result = experiment_stats.mcnemar_exact(2, 8)
    assert result.p_value == pytest.approx(2 * (1 + 10 + 45) / 1024)
    assert experiment_stats.mcnemar_exact(5, 5).p_value == pytest.approx(1.0)
    assert experiment_stats.mcnemar_exact(0, 0).p_value == 1.0
    assert experiment_stats.mcnemar_exact(0, 10).p_value == pytest.approx(2 / 1024)


def test_holm_adjust_matches_hand_calculation() -> None:
    assert experiment_stats.holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert experiment_stats.holm_adjust([0.5, 0.9]) == pytest.approx([1.0, 1.0])
    assert experiment_stats.holm_adjust([0.2]) == [0.2]


# --- design effect, sample size, minimum detectable difference -------------------------------------------------


def test_design_effect() -> None:
    assert experiment_stats.design_effect(10, 0.05) == pytest.approx(1.45)
    assert experiment_stats.design_effect(1, 0.9) == 1.0


def test_ten_to_eight_percent_needs_about_3200_per_arm() -> None:
    result = experiment_stats.required_seeds_for_rate_difference(0.10, 0.02)
    assert result.units_needed == 3213
    assert result.exact_power_at_units == pytest.approx(0.80, abs=0.01)


def test_rate_sample_size_design_effect_scales_units() -> None:
    plain = experiment_stats.required_seeds_for_rate_difference(0.10, 0.02)
    clustered = experiment_stats.required_seeds_for_rate_difference(
        0.10, 0.02, design_effect_multiplier=1.45
    )
    assert clustered.units_needed == math.ceil(plain.units_needed * 1.45)


def test_rate_sample_size_matches_cohen_h_within_a_few_percent() -> None:
    h_effect = 2.0 * math.asin(math.sqrt(0.10)) - 2.0 * math.asin(math.sqrt(0.08))
    z_total = scipy_stats.norm.ppf(0.975) + scipy_stats.norm.ppf(0.80)
    cohen_n = 2.0 * (z_total / h_effect) ** 2
    result = experiment_stats.required_seeds_for_rate_difference(0.10, 0.02)
    assert result.units_needed == pytest.approx(cohen_n, rel=0.03)


def test_rate_minimum_detectable_difference_inverts_the_sample_size() -> None:
    result = experiment_stats.minimum_detectable_rate_difference(0.10, 3213)
    assert result.minimum_detectable_difference == pytest.approx(0.02, abs=1e-4)
    with pytest.raises(ValueError):
        experiment_stats.minimum_detectable_rate_difference(0.10, 3)


def test_twenty_seeds_cannot_see_a_two_point_drop() -> None:
    result = experiment_stats.minimum_detectable_rate_difference(
        0.10, 20, direction=experiment_stats.ChangeDirection.INCREASE
    )
    assert result.minimum_detectable_difference > 0.25


def test_paired_rate_pairs_are_far_fewer_than_unpaired() -> None:
    paired = experiment_stats.required_pairs_for_paired_rate_difference(0.04, 0.02)
    unpaired = experiment_stats.required_seeds_for_rate_difference(0.10, 0.02)
    assert paired.units_needed == 783
    assert paired.units_needed < unpaired.units_needed / 3
    with pytest.raises(ValueError):
        experiment_stats.required_pairs_for_paired_rate_difference(0.01, 0.02)


def test_paired_delta_pairs_match_gpower_for_d_half() -> None:
    result = experiment_stats.required_pairs_for_paired_delta(
        paired_delta_sd=1.0, minimum_detectable_delta=0.5
    )
    assert result.units_needed == 34
    assert result.exact_power_at_units == pytest.approx(0.8078, abs=1e-3)


def test_two_sample_minimum_detectable_difference_for_64_per_arm_is_half_a_sd() -> None:
    result = experiment_stats.minimum_detectable_difference(standard_deviation=1.0, units=64)
    assert result.minimum_detectable_difference == pytest.approx(0.499, abs=0.002)


def test_paired_minimum_detectable_difference_scales_with_the_standard_deviation() -> None:
    unit = experiment_stats.minimum_detectable_difference(1.0, 34, paired=True)
    scaled = experiment_stats.minimum_detectable_difference(0.04, 34, paired=True)
    assert unit.minimum_detectable_difference == pytest.approx(0.495, abs=0.002)
    assert scaled.minimum_detectable_difference == pytest.approx(
        0.04 * unit.minimum_detectable_difference
    )


# --- simulation: power, pairing, optional stopping ---------------------------------------------------------------


def test_simulate_power_agrees_with_exact_power() -> None:
    def two_arm_test(generator: "numpy.random.Generator", sample_size: int) -> bool:
        baseline_failures = generator.binomial(sample_size, 0.10)
        candidate_failures = generator.binomial(sample_size, 0.08)
        pooled = (baseline_failures + candidate_failures) / (2 * sample_size)
        standard_error = math.sqrt(pooled * (1 - pooled) * 2 / sample_size)
        z_score = abs(baseline_failures - candidate_failures) / sample_size / standard_error
        return bool(z_score > 1.959964)

    estimate = experiment_stats.simulate_power(two_arm_test, 3213, simulations=3000, seed=11)
    assert estimate.lower <= 0.80 <= estimate.upper or abs(estimate.power - 0.80) < 0.03


def test_optional_stopping_inflates_false_wins_and_a_two_look_boundary_does_not() -> None:
    looks = 10
    per_look = 20
    boundaries = experiment_stats.group_sequential_boundaries(looks=2)

    def naive_peeking(generator: "numpy.random.Generator", sample_size: int) -> bool:
        differences = generator.normal(0.0, 1.0, (looks * per_look, 2))
        for look in range(1, looks + 1):
            count = look * per_look
            sample = differences[:count, 0] - differences[:count, 1]
            if abs(scipy_stats.ttest_1samp(sample, 0.0).pvalue) < 0.05:
                return True
        return False

    def two_look_boundary(generator: "numpy.random.Generator", sample_size: int) -> bool:
        draws = generator.normal(0.0, 1.0, sample_size)
        half = sample_size // 2
        z_half = draws[:half].sum() / math.sqrt(half)
        z_full = draws.sum() / math.sqrt(sample_size)
        return bool(
            abs(z_half) >= boundaries.z_boundaries[0] or abs(z_full) >= boundaries.z_boundaries[1]
        )

    peeking = experiment_stats.simulate_power(
        naive_peeking, looks * per_look, simulations=1500, seed=2
    )
    planned = experiment_stats.simulate_power(two_look_boundary, 200, simulations=6000, seed=2)
    assert peeking.lower > 0.12
    assert planned.lower < 0.05 < planned.upper + 0.01


def test_paired_seeds_are_deterministic_and_distinct() -> None:
    first = experiment_stats.paired_seeds(123, 50)
    assert first == experiment_stats.paired_seeds(123, 50)
    assert len(set(first)) == 50
    assert first != experiment_stats.paired_seeds(124, 50)


def test_paired_outcomes_match_the_discordant_rate_formula() -> None:
    generator = numpy.random.default_rng(9)
    pairs = 200_000
    baseline, candidate = experiment_stats.generate_paired_binary_outcomes(
        generator, pairs, 0.10, 0.08, 1.0
    )
    assert (baseline != candidate).mean() == pytest.approx(0.02, abs=0.002)
    baseline, candidate = experiment_stats.generate_paired_binary_outcomes(
        generator, pairs, 0.10, 0.08, 0.0
    )
    assert (baseline != candidate).mean() == pytest.approx(0.10 * 0.92 + 0.08 * 0.90, abs=0.003)


def test_exact_power_is_close_to_the_normal_formula() -> None:
    assert experiment_stats.exact_rate_power(300, 0.10, 0.08) < 0.2
    assert experiment_stats.exact_rate_power(3213, 0.10, 0.08) == pytest.approx(0.80, abs=0.01)
    assert experiment_stats.exact_rate_power(500, 0.10, 0.10) < 0.06


# --- group-sequential boundaries -------------------------------------------------------------------------------


def test_obrien_fleming_two_looks() -> None:
    boundaries = experiment_stats.group_sequential_boundaries(looks=2, alpha=0.05)
    assert boundaries.z_boundaries[0] == pytest.approx(2.797, abs=0.003)
    assert boundaries.z_boundaries[1] == pytest.approx(1.977, abs=0.003)
    assert sum(boundaries.alpha_spent_at_each_look) == pytest.approx(0.05, abs=1e-5)


def test_obrien_fleming_three_looks() -> None:
    boundaries = experiment_stats.group_sequential_boundaries(looks=3, alpha=0.05)
    assert boundaries.z_boundaries == pytest.approx([3.471, 2.454, 2.004], abs=0.004)


def test_pocock_two_looks() -> None:
    boundaries = experiment_stats.group_sequential_boundaries(
        looks=2, alpha=0.05, family=experiment_stats.BoundaryFamily.POCOCK
    )
    assert boundaries.z_boundaries == pytest.approx([2.178, 2.178], abs=0.003)


def test_one_look_is_the_fixed_sample_critical_value() -> None:
    boundaries = experiment_stats.group_sequential_boundaries(looks=1, alpha=0.05)
    assert boundaries.z_boundaries[0] == pytest.approx(1.96, abs=0.002)


def test_unequal_information_fractions_are_accepted_and_validated() -> None:
    boundaries = experiment_stats.group_sequential_boundaries(information_fractions=[0.5, 1.0])
    assert boundaries.z_boundaries[0] == pytest.approx(2.797, abs=0.003)
    with pytest.raises(ValueError):
        experiment_stats.group_sequential_boundaries(information_fractions=[0.5, 0.9])


# --- Beta-Binomial ----------------------------------------------------------------------------------------------


def test_beta_posterior_with_uniform_prior() -> None:
    posterior = experiment_stats.beta_posterior(20, 27)
    assert (posterior.alpha, posterior.beta) == (21.0, 8.0)
    assert posterior.mean == pytest.approx(21.0 / 29.0)
    assert posterior.lower == pytest.approx(scipy_stats.beta.ppf(0.025, 21, 8))
    assert posterior.lower < posterior.mean < posterior.upper


def test_probability_b_beats_a_matches_numerical_integration() -> None:
    from scipy import integrate

    posterior_a = experiment_stats.beta_posterior(12, 12)
    posterior_b = experiment_stats.beta_posterior(20, 27)
    exact = integrate.quad(
        lambda rate: (
            scipy_stats.beta.pdf(rate, posterior_b.alpha, posterior_b.beta)
            * scipy_stats.beta.cdf(rate, posterior_a.alpha, posterior_a.beta)
        ),
        0.0,
        1.0,
    )[0]
    estimate = experiment_stats.probability_b_beats_a(
        posterior_a, posterior_b, seed=4, draws=200_000
    )
    assert estimate == pytest.approx(exact, abs=0.005)


def test_margin_lowers_the_probability_and_direction_flips_it() -> None:
    posterior_a = experiment_stats.beta_posterior(30, 100)
    posterior_b = experiment_stats.beta_posterior(20, 100)
    lower_is_better = experiment_stats.BetterDirection.LOWER
    plain = experiment_stats.probability_b_beats_a(posterior_a, posterior_b, better=lower_is_better)
    beyond_margin = experiment_stats.probability_difference_beyond_margin(
        posterior_a, posterior_b, margin=0.05, better=lower_is_better
    )
    assert beyond_margin < plain
    assert experiment_stats.probability_b_beats_a(posterior_a, posterior_b) < 0.1


# --- campaign noise floor ---------------------------------------------------------------------------------------


def test_noise_floor_is_a_prediction_interval_half_width() -> None:
    scores = [0.50, 0.52, 0.49, 0.51, 0.50]
    result = experiment_stats.baseline_noise_floor(scores)
    standard_deviation = numpy.std(scores, ddof=1)
    expected = scipy_stats.t.ppf(0.975, 4) * standard_deviation * math.sqrt(1.0 + 1.0 / 5.0)
    assert result.noise_floor == pytest.approx(expected)
    assert result.baseline_mean == pytest.approx(0.504)
    with pytest.raises(ValueError):
        experiment_stats.baseline_noise_floor([0.5, 0.6])


def test_attempts_since_improvement_ignores_gains_inside_the_noise_floor() -> None:
    scores = [0.50, 0.51, 0.52, 0.505, 0.60, 0.61, 0.59]
    assert experiment_stats.attempts_since_improvement(scores, noise_floor=0.03) == 2
    assert experiment_stats.attempts_since_improvement(scores[:4], noise_floor=0.03) == 3
    lower = experiment_stats.BetterDirection.LOWER
    assert (
        experiment_stats.attempts_since_improvement([1.0, 0.9, 0.95, 0.96], 0.05, better=lower) == 2
    )
    assert experiment_stats.attempts_since_improvement([], 0.1) == 0


# --- command line -----------------------------------------------------------------------------------------------


def test_command_line_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = experiment_stats.main(
        ["seeds-for-rate", "--baseline-rate", "0.10", "--minimum-detectable-difference", "0.02"]
    )
    assert exit_code == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["units_needed"] == 3213


def test_command_line_reports_errors_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = experiment_stats.main(["wilson", "--successes", "5", "--trials", "3"])
    assert exit_code == 2
    assert "error" in json.loads(capsys.readouterr().err)


def test_command_line_holm_and_boundaries(capsys: pytest.CaptureFixture[str]) -> None:
    assert experiment_stats.main(["holm", "0.01", "0.04", "0.03"]) == 0
    assert json.loads(capsys.readouterr().out)["adjusted_p_values"] == pytest.approx(
        [0.03, 0.06, 0.06]
    )
    assert experiment_stats.main(["boundaries", "--looks", "2"]) == 0
    assert json.loads(capsys.readouterr().out)["z_boundaries"][0] == pytest.approx(2.797, abs=0.003)


def test_paired_minimum_detectable_difference_at_110_pairs() -> None:
    result = experiment_stats.minimum_detectable_difference(
        standard_deviation=0.04, units=110, paired=True
    )
    assert result.minimum_detectable_difference == pytest.approx(0.04 * 0.2688, abs=0.04 * 0.005)


@pytest.mark.parametrize("trials", [1, 4, 10, 14, 19, 24, 1000])
def test_wilson_bounds_are_exact_at_zero_and_all_successes(trials: int) -> None:
    none_succeeded = experiment_stats.wilson_interval(0, trials)
    assert none_succeeded.lower == 0.0
    all_succeeded = experiment_stats.wilson_interval(trials, trials)
    assert all_succeeded.upper == 1.0
    assert all_succeeded.lower <= all_succeeded.estimate <= all_succeeded.upper
