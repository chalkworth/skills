"""Tests for the queueing helpers: textbook values, identities and the t interval."""

import importlib.util
import math
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QUEUEING_PATH = (
    REPOSITORY_ROOT
    / "packs"
    / "experiments"
    / "testing-ideas-with-simulation"
    / "scripts"
    / "queueing.py"
)


def load_queueing() -> ModuleType:
    specification = importlib.util.spec_from_file_location("queueing", QUEUEING_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot load queueing.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules["queueing"] = module
    specification.loader.exec_module(module)
    return module


queueing = load_queueing()


def erlang_c_direct_sum(servers: int, offered_load: float) -> float:
    """The textbook sum form, used as an independent check of the recursion."""
    utilisation = offered_load / servers
    top = offered_load**servers / math.factorial(servers) / (1 - utilisation)
    bottom = sum(offered_load**k / math.factorial(k) for k in range(servers)) + top
    return top / bottom


def test_two_servers_at_half_utilisation_wait_with_probability_one_third() -> None:
    assert queueing.erlang_c(2, 1.0) == pytest.approx(1 / 3)


def test_one_server_waits_with_probability_utilisation() -> None:
    assert queueing.erlang_c(1, 0.7) == pytest.approx(0.7)


@pytest.mark.parametrize(("servers", "offered_load"), [(3, 2.5), (5, 4.0), (12, 10.0), (30, 27.0)])
def test_recursion_matches_direct_sum(servers: int, offered_load: float) -> None:
    assert queueing.erlang_c(servers, offered_load) == pytest.approx(
        erlang_c_direct_sum(servers, offered_load)
    )


def test_call_centre_textbook_case() -> None:
    # 10 Erlangs on 12 agents: about 0.449 chance of waiting (also computed independently with scipy-free sums)
    assert queueing.erlang_c(12, 10.0) == pytest.approx(0.44939, abs=1e-4)


def test_unstable_load_is_rejected() -> None:
    with pytest.raises(ValueError):
        queueing.erlang_c(2, 2.0)


def test_mm1_matches_closed_form() -> None:
    metrics = queueing.mmc_metrics(arrival_rate=0.8, service_rate=1.0, servers=1)
    assert metrics.mean_wait_in_queue == pytest.approx(0.8 / (1.0 * (1.0 - 0.8)))
    assert metrics.mean_time_in_system == pytest.approx(1 / (1.0 - 0.8))


def test_littles_law_holds_for_mmc() -> None:
    metrics = queueing.mmc_metrics(arrival_rate=5.0, service_rate=2.0, servers=3)
    assert metrics.mean_number_in_system == pytest.approx(
        metrics.arrival_rate * metrics.mean_time_in_system
    )
    assert metrics.mean_number_in_system - metrics.mean_queue_length == pytest.approx(5.0 / 2.0)


def test_mg1_with_exponential_service_equals_mm1() -> None:
    wait = queueing.mg1_mean_wait_in_queue(
        arrival_rate=0.8, mean_service_time=1.0, service_time_cv=1.0
    )
    assert wait == pytest.approx(queueing.mmc_metrics(0.8, 1.0, 1).mean_wait_in_queue)


def test_mg1_constant_service_halves_the_wait() -> None:
    exponential = queueing.mg1_mean_wait_in_queue(0.8, 1.0, 1.0)
    constant = queueing.mg1_mean_wait_in_queue(0.8, 1.0, 0.0)
    assert constant == pytest.approx(exponential / 2)


def test_finite_source_single_unit_single_server() -> None:
    metrics = queueing.finite_source_metrics(
        1, 1, mean_time_between_requests=30.0, mean_service_time=5.0
    )
    assert metrics.fraction_of_sources_waiting_or_served == pytest.approx(5.0 / 35.0)
    assert metrics.mean_waiting == pytest.approx(0.0)


def test_finite_source_matches_simulation_checked_value() -> None:
    # Six robots, two operators, 30 minutes between requests, 5 minutes of help: 15.5% of robot time lost
    # (a SimPy model with 15 replications gave 15.6% +/- 0.2%).
    metrics = queueing.finite_source_metrics(
        6, 2, mean_time_between_requests=30.0, mean_service_time=5.0
    )
    assert metrics.fraction_of_sources_waiting_or_served == pytest.approx(0.15538, abs=1e-4)


def test_finite_source_is_less_congested_than_infinite_source_with_same_offered_load() -> None:
    finite = queueing.finite_source_metrics(6, 2, 30.0, 5.0)
    infinite = queueing.mmc_metrics(arrival_rate=6 / 30.0, service_rate=1 / 5.0, servers=2)
    assert finite.mean_waiting < infinite.mean_queue_length


def test_t_interval_for_known_sample() -> None:
    summary = queueing.summarize_replications([10.0, 12.0, 11.0, 13.0, 9.0])
    assert summary.mean == pytest.approx(11.0)
    # s = sqrt(2.5), t(4, 0.975) = 2.776, half width = 2.776 * s / sqrt(5)
    assert summary.half_width == pytest.approx(2.776 * math.sqrt(2.5) / math.sqrt(5))
    assert summary.lower == pytest.approx(summary.mean - summary.half_width)


def test_t_critical_value_beyond_table_approaches_normal() -> None:
    assert queueing.t_critical_value(60, 0.95) == pytest.approx(2.000, abs=0.005)
    assert queueing.t_critical_value(1000, 0.95) == pytest.approx(1.962, abs=0.002)


def test_single_replication_is_rejected() -> None:
    with pytest.raises(ValueError):
        queueing.summarize_replications([1.0])


def test_command_line_mmc_prints_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        queueing.main(["mmc", "--arrival-rate", "5", "--service-rate", "2", "--servers", "3"]) == 0
    )
    assert '"probability_of_waiting"' in capsys.readouterr().out


def test_command_line_reports_unstable_queue_as_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        queueing.main(["mmc", "--arrival-rate", "9", "--service-rate", "2", "--servers", "3"]) == 2
    )
    assert "error" in capsys.readouterr().err
