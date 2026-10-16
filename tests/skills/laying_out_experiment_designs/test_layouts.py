"""Tests for the experiment layout generator: design properties, aliasing, balance and the command line.

Needs numpy, pandas and pydoe 1.5.0, which the dev environment may lack; the tests skip without them. To run them:
`uv run --with numpy --with pandas --with pydoe==1.5.0 pytest tests/skills/laying_out_experiment_designs`.
"""

import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType

import pytest

numpy = pytest.importorskip("numpy")
pandas = pytest.importorskip("pandas")
pytest.importorskip("pydoe")

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LAYOUTS_PATH = (
    REPOSITORY_ROOT
    / "packs"
    / "experiments"
    / "laying-out-experiment-designs"
    / "scripts"
    / "layouts.py"
)


def load_layouts() -> ModuleType:
    specification = importlib.util.spec_from_file_location("experiment_layouts", LAYOUTS_PATH)
    if specification is None or specification.loader is None:
        raise RuntimeError("Cannot load layouts.py")
    module = importlib.util.module_from_spec(specification)
    sys.modules["experiment_layouts"] = module
    specification.loader.exec_module(module)
    return module


layouts = load_layouts()


def factors(count: int, low: float = 0.0, high: float = 1.0) -> dict[str, tuple[float, float]]:
    return {f"f{i}": (low, high) for i in range(count)}


def run_command(*arguments: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = layouts.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


# --- factors -------------------------------------------------------------------------------------------------


def test_parse_factors_reads_ranges_in_order() -> None:
    assert layouts.parse_factors(["lr=1e-4:1e-2", "depth=2:8"]) == {
        "lr": (1e-4, 1e-2),
        "depth": (2.0, 8.0),
    }


@pytest.mark.parametrize("spec", ["lr", "lr=1", "lr=3:3", "lr=5:1", "run_order=0:1", "=0:1"])
def test_parse_factors_rejects_bad_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        layouts.parse_factors([spec])


def test_parse_factors_rejects_duplicates_and_empty() -> None:
    with pytest.raises(ValueError):
        layouts.parse_factors(["a=0:1", "a=0:2"])
    with pytest.raises(ValueError):
        layouts.parse_factors([])


# --- factorial and screening ---------------------------------------------------------------------------------


def test_full_factorial_has_every_corner_in_real_units() -> None:
    design, notes = layouts.factorial({"temp": (20, 60), "conc": (1, 10), "ph": (6, 8)}, seed=1)
    assert len(design) == 8 and notes["runs"] == 8 and "resolution" not in notes
    assert set(design["temp"]) == {20.0, 60.0}
    assert len(design[["temp", "conc", "ph"]].drop_duplicates()) == 8
    assert sorted(design["run_order"]) == list(range(1, 9))


def test_same_seed_gives_the_same_order_and_another_seed_a_different_one() -> None:
    first, _ = layouts.factorial(factors(4), seed=7)
    again, _ = layouts.factorial(factors(4), seed=7)
    other, _ = layouts.factorial(factors(4), seed=8)
    assert first.equals(again)
    assert not first.equals(other)


def test_generator_fraction_reports_resolution_four_and_aliases() -> None:
    design, notes = layouts.factorial(factors(4), generator="a b c abc")
    assert len(design) == 8 and notes["resolution"] == 4
    assert "a = bcd" in notes["aliases"] and "ab = cd" in notes["aliases"]
    assert notes["letters"]["d"] == "f3"


def test_target_resolution_picks_the_smallest_fraction() -> None:
    _, notes = layouts.factorial(factors(6), resolution_target=3)
    assert notes["runs"] == 8 and notes["resolution"] == 3
    _, notes = layouts.factorial(factors(6), resolution_target=4)
    assert notes["runs"] == 16 and notes["resolution"] == 4
    _, notes = layouts.factorial(factors(5), resolution_target=5)
    assert notes["runs"] == 16 and notes["resolution"] == 5


def test_generator_and_resolution_together_are_rejected() -> None:
    with pytest.raises(ValueError):
        layouts.factorial(factors(4), generator="a b c abc", resolution_target=4)


def test_centres_are_added_at_the_midpoint_and_left_out_of_the_resolution() -> None:
    design, notes = layouts.factorial(factors(4), generator="a b c abc", centers=3)
    middle = design[(design[["f0", "f1", "f2", "f3"]] == 0.5).all(axis=1)]
    assert len(design) == 11 and len(middle) == 3 and notes["resolution"] == 4


def test_fold_over_mirrors_every_run_and_raises_the_resolution() -> None:
    design, notes = layouts.factorial(factors(7), resolution_target=3, fold_over=True, seed=2)
    assert len(design) == 16 and notes["resolution"] == 4
    first, second = design[design["block"] == 0], design[design["block"] == 1]
    mirrored = {tuple(1 - row) for row in first[[f"f{i}" for i in range(7)]].to_numpy()}
    assert mirrored == {tuple(row) for row in second[[f"f{i}" for i in range(7)]].to_numpy()}
    for _, group in design.groupby("block"):  # blocks are shuffled within, never together
        assert sorted(group["run_order"]) == list(
            range(group["run_order"].min(), group["run_order"].max() + 1)
        )


def test_fold_over_runs_block_zero_before_block_one() -> None:
    design, _ = layouts.factorial(factors(4), fold_over=True, seed=2)
    assert list(design["block"]) == [0] * 16 + [1] * 16
    assert list(design["run_order"]) == list(range(1, 33))


def test_resolution_of_a_full_factorial_is_none() -> None:
    from pydoe import ff2n

    assert layouts.resolution(ff2n(4)) is None


def test_seven_factor_half_fraction_reports_resolution_seven() -> None:
    _, notes = layouts.factorial(factors(7), generator="a b c d e f abcdef")
    assert notes["runs"] == 64 and notes["resolution"] == 7


def test_plackett_burman_run_counts_and_unsupported_sizes() -> None:
    assert layouts.screen(factors(11))[1]["runs"] == 12
    assert layouts.screen(factors(12))[1]["runs"] == 16
    design, _ = layouts.screen(factors(7))
    assert len(design) == 8 and (design.sum() > 0).all()
    with pytest.raises(ValueError):
        layouts.screen(factors(24))


def test_screen_rejects_fewer_than_three_factors() -> None:
    with pytest.raises(ValueError):
        layouts.screen(factors(2))


def test_plackett_burman_columns_are_orthogonal() -> None:
    design, _ = layouts.screen(factors(11))
    signs = 2 * design[[f"f{i}" for i in range(11)]].to_numpy() - 1
    assert (signs.T @ signs == 12 * numpy.eye(11)).all()


# --- response surface and sweeps -----------------------------------------------------------------------------


def test_circumscribed_composite_leaves_the_range_and_inscribed_does_not() -> None:
    wide = layouts.surface(factors(2), "ccd", face="circumscribed")[1]["actual_range"]
    assert wide["f0"][0] < 0.0 and wide["f0"][1] > 1.0
    for face in ("inscribed", "faced"):
        inside = layouts.surface(factors(2), "ccd", face=face)[1]["actual_range"]
        assert inside["f0"][0] >= -1e-9 and inside["f0"][1] <= 1 + 1e-9


def test_composite_run_count_is_factorial_plus_axial_plus_centres() -> None:
    design, _ = layouts.surface(factors(3), "ccd", center=(2, 2))
    assert len(design) == 8 + 6 + 4


def test_box_behnken_counts_and_no_corners() -> None:
    design, _ = layouts.surface(factors(3), "bbd", box_behnken_center=3)
    assert len(design) == 12 + 3
    spans = factors(3)
    at_extreme = [design[name].isin(span) for name, span in spans.items()]
    every_factor_at_an_extreme = at_extreme[0] & at_extreme[1] & at_extreme[2]
    assert not every_factor_at_an_extreme.any()  # a corner sets every factor to its low or high
    with pytest.raises(ValueError):
        layouts.surface(factors(2), "bbd")
    with pytest.raises(ValueError):
        layouts.surface(factors(3), "box")


def test_latin_hypercube_uses_each_bin_once_and_is_reproducible() -> None:
    design, _ = layouts.sweep({"a": (0, 10), "b": (-1, 1)}, 8, seed=4)
    for name, (low, high) in {"a": (0, 10), "b": (-1, 1)}.items():
        bins = numpy.floor((design[name] - low) / (high - low) * 8).astype(int)
        assert sorted(bins) == list(range(8))
    again, _ = layouts.sweep({"a": (0, 10), "b": (-1, 1)}, 8, seed=4)
    assert design.equals(again)
    with pytest.raises(ValueError):
        layouts.sweep({"a": (0, 1)}, 1)


# --- ordering ------------------------------------------------------------------------------------------------


def test_order_runs_within_a_column_keeps_groups_together() -> None:
    table = pandas.DataFrame({"plot": list("aaabbbccc"), "x": range(9)})
    ordered = layouts.order_runs(table, seed=3, within="plot")
    assert list(ordered["run_order"]) == list(range(1, 10))
    assert sorted(ordered["x"]) == list(range(9))
    plots = list(ordered["plot"])
    assert all(plots[i : i + 3] == [plots[i]] * 3 for i in (0, 3, 6))


def test_order_runs_replaces_an_existing_run_order_column() -> None:
    design, _ = layouts.factorial(factors(3), fold_over=True, seed=1)
    reshuffled = layouts.order_runs(design, seed=2, within="block")
    assert list(reshuffled["run_order"]) == list(range(1, len(design) + 1))
    assert reshuffled.columns.tolist().count("run_order") == 1


# --- allocation ----------------------------------------------------------------------------------------------


def test_permuted_blocks_balance_each_complete_block() -> None:
    schedule = layouts.allocate({"all": 24}, ["new", "old"], ratio=[2, 1], block_size=6, seed=5)
    assert list(schedule["unit_id"]) == list(range(1, 25))
    for _, block in schedule.groupby("block"):
        assert block["arm"].value_counts().to_dict() == {"new": 4, "old": 2}


def test_partial_final_block_is_reported() -> None:
    schedule = layouts.allocate({"all": 10}, ["a", "b"], block_size=4, seed=1)
    report = layouts.balance(schedule, 4)
    assert report["partial_block_size"] == {"all": 2}
    assert sum(report["counts"]["all"].values()) == 10


def test_strata_are_blocked_independently() -> None:
    schedule = layouts.allocate({"A": 8, "B": 4}, ["x", "y"], block_size=4, seed=2)
    counts = layouts.balance(schedule, 4)["counts"]
    assert counts == {"A": {"x": 4, "y": 4}, "B": {"x": 2, "y": 2}}


def test_label_sequence_keeps_input_positions_when_strata_interleave() -> None:
    schedule = layouts.allocate(["a", "b", "a", "b", "a", "a"], ["x", "y"], block_size=2, seed=3)
    assert list(schedule["unit_id"]) == [1, 2, 3, 4, 5, 6]
    assert list(schedule["stratum"]) == ["a", "b", "a", "b", "a", "a"]
    by_stratum = schedule.groupby("stratum")["arm"].value_counts()
    assert by_stratum["a"].to_dict() == {"x": 2, "y": 2} and by_stratum["b"].to_dict() == {
        "x": 1,
        "y": 1,
    }


def test_allocation_is_reproducible_and_seed_sensitive() -> None:
    first = layouts.allocate({"all": 30}, seed=9)
    assert first.equals(layouts.allocate({"all": 30}, seed=9))
    assert not first.equals(layouts.allocate({"all": 30}, seed=10))


@pytest.mark.parametrize(
    "arguments",
    [
        {"arms": ["a"]},
        {"arms": ["a", "a"]},
        {"arms": ["a", "b"], "ratio": [1]},
        {"arms": ["a", "b"], "ratio": [1, 0]},
        {"arms": ["a", "b"], "block_size": 3},
        {"arms": ["a", "b"], "block_size": 0},
        {"arms": ["a", "b"], "block_size": -2},
    ],
)
def test_allocation_rejects_bad_arguments(arguments: dict) -> None:
    with pytest.raises(ValueError):
        layouts.allocate({"all": 4}, **arguments)


def test_repeated_strata_labels_are_rejected() -> None:
    code, _, err = run_command("allocate", "--strata", "A=2", "A=3")
    assert code == 2 and "more than once" in json.loads(err)["error"]


def test_duplicate_cluster_ids_are_rejected() -> None:
    code, _, err = run_command("allocate", "--clusters", "c1", "c1", "c3")
    assert code == 2 and "unique" in json.loads(err)["error"]


def test_empty_stratum_is_allowed_and_negative_is_not() -> None:
    assert len(layouts.allocate({"all": 0})) == 0
    with pytest.raises(ValueError):
        layouts.allocate({"all": -1})


# --- Latin square --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("order", [2, 3, 5, 6])
def test_latin_square_has_each_treatment_once_per_row_and_column(order: int) -> None:
    square = layouts.latin_square(order, seed=order).to_numpy()
    symbols = set(square.ravel())
    assert len(symbols) == order
    assert all(set(row) == symbols for row in square) and all(
        set(col) == symbols for col in square.T
    )


def test_latin_square_rejects_order_one() -> None:
    with pytest.raises(ValueError):
        layouts.latin_square(1)


# --- command line --------------------------------------------------------------------------------------------


def test_factorial_command_writes_csv_and_json_note() -> None:
    code, out, err = run_command(
        "factorial",
        "--factor",
        "a=0:1",
        "--factor",
        "b=0:1",
        "--factor",
        "c=0:1",
        "--factor",
        "d=0:1",
        "--generator",
        "a b c abc",
        "--seed",
        "1",
    )
    assert code == 0 and out.splitlines()[0] == "run_order,a,b,c,d" and len(out.splitlines()) == 9
    assert json.loads(err)["resolution"] == 4


def test_commands_write_to_a_file_with_rounded_numbers(tmp_path: Path) -> None:
    target = tmp_path / "layout.csv"
    code, out, _ = run_command(
        "surface",
        "--kind",
        "ccd",
        "--face",
        "inscribed",
        "--center",
        "2,2",
        "--factor",
        "lr=1e-4:1e-2",
        "--factor",
        "wd=0:0.1",
        "--out",
        str(target),
    )
    assert code == 0 and out == ""
    table = pandas.read_csv(target)
    assert len(table) == 12 and table["wd"].between(0, 0.1).all()
    assert "9.99999999999994e-05" not in target.read_text()


def test_screen_and_sweep_commands() -> None:
    code, out, err = run_command(
        "screen", "--factor", "a=0:1", "--factor", "b=0:1", "--factor", "c=0:1"
    )
    assert code == 0 and json.loads(err)["runs"] == 4 and len(out.splitlines()) == 5
    code, out, _ = run_command("sweep", "--n", "6", "--factor", "a=0:1", "--factor", "b=5:9")
    assert code == 0 and len(out.splitlines()) == 7


def test_allocate_command_variants() -> None:
    code, out, err = run_command(
        "allocate", "--strata", "A=8", "B=4", "--arms", "x", "y", "--block-size", "4"
    )
    assert code == 0 and json.loads(err)["counts"] == {"A": {"x": 4, "y": 4}, "B": {"x": 2, "y": 2}}
    code, out, err = run_command("allocate", "--clusters", "c1", "c2", "c3", "c4", "--seed", "3")
    assert code == 0 and out.splitlines()[0] == "block,arm,cluster_id"
    note = json.loads(err)
    assert note["clusters"] == 4 and note["counts"] == {"all": {"treatment": 2, "control": 2}}
    assert note["partial_block_size"] == {"all": 0}
    assert {line.split(",")[-1] for line in out.splitlines()[1:]} == {"c1", "c2", "c3", "c4"}
    code, _, err = run_command("allocate")
    assert code == 2 and "error" in json.loads(err)


def test_square_command_and_error_exit() -> None:
    code, out, _ = run_command("square", "--order", "3")
    assert code == 0 and len(out.splitlines()) == 4
    code, _, err = run_command("allocate", "--n", "5", "--block-size", "3")
    assert code == 2 and "multiple" in json.loads(err)["error"]


@pytest.mark.parametrize("name", ["block", "run_order"])
def test_a_factor_cannot_take_a_column_the_layout_adds(name: str) -> None:
    with pytest.raises(ValueError, match="not run_order or block"):
        layouts.parse_factors([f"{name}=10:20"])


@pytest.mark.parametrize("text", ["1,100,2", "3", "2,-1", "a,b"])
def test_center_needs_exactly_two_counts(text: str) -> None:
    with pytest.raises(ValueError, match="expected two counts"):
        layouts.parse_center(text)


def test_center_reads_factorial_then_axial() -> None:
    assert layouts.parse_center("4,1") == (4, 1)
