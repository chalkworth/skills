"""The test-nudge hook: each detector fires on the edit it is for, and each guard keeps it quiet."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "hooks" / "test-nudge" / "test_nudge.py"


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("test_nudge", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_nudge"] = module
    spec.loader.exec_module(module)
    return module


nudge = _load_hook()

BASE = """
import pytest
from app import run, parse

def test_run_ok(tmp_path):
    out = run(["--name", "a"], cwd=tmp_path)
    assert out.code == 0
    assert out.stdout == "a"

@pytest.mark.parametrize("text, want", [("1", 1), ("2", 2)])
def test_parse(text, want):
    assert parse(text) == want

def test_wait(server):
    server.start(timeout=2)
    assert server.up
"""
SLEPT = BASE.replace("server.start(timeout=2)", "server.start(timeout=2)\n    time.sleep(1.5)")


def _wait(decorator: str) -> str:
    return BASE.replace("def test_wait", f"{decorator}\ndef test_wait")


def _add(text: str) -> str:
    return BASE + text


CASES = {
    # detectors
    "copied body": _add(
        '\ndef test_run_other(tmp_path):\n    result = run(["--name", "b"], cwd=tmp_path)\n'
        '    assert result.code == 0\n    assert result.stdout == "b"\n'
    ),
    "sleep": SLEPT,
    "timeout raised": BASE.replace("timeout=2", "timeout=30"),
    "flaky marker": _wait("@pytest.mark.flaky(reruns=3)"),
    "skip marker": _wait("@pytest.mark.skip(reason='flaky on CI')"),
    "bare pytest.skip": BASE.replace(
        "    server.start", "    pytest.skip('slow')\n    server.start"
    ),
    "prose": _add(
        '\ndef test_help(capsys):\n    run(["--help"])\n    assert "Runs the pipeline on the '
        'current branch and opens a pull request" in capsys.readouterr().out\n'
    ),
    "cross product": _add(
        "\n@pytest.mark.parametrize('a', [1, 2, 3])\n@pytest.mark.parametrize('b', ['x', 'y', 'z'])"
        "\ndef test_ab(a, b):\n    assert parse(f'{a}{b}') is None\n"
    ),
    "second axis on a table": BASE.replace(
        '@pytest.mark.parametrize("text, want"',
        '@pytest.mark.parametrize("base", [2, 8, 10, 16])\n@pytest.mark.parametrize("text, want"',
    ),
    # guards
    "new distinct test": _add(
        '\ndef test_parse_rejects_empty():\n    with pytest.raises(ValueError):\n        parse("")\n'
    ),
    "body too small to call a copy": _add(
        '\ndef test_parse_3():\n    assert parse("3") == 3\n'
        '\ndef test_parse_4():\n    assert parse("4") == 4\n'
    ),
    "timeout lowered": BASE.replace("timeout=2", "timeout=1"),
    "skipif": _wait("@pytest.mark.skipif(sys.platform == 'win32', reason='posix')"),
    "targeted xfail": _wait("@pytest.mark.xfail(raises=TimeoutError)"),
    "pytest.skip under if": BASE.replace(
        "    server.start",
        "    if not has_bwrap():\n        pytest.skip('no bwrap')\n    server.start",
    ),
    "sleep in a helper coroutine": _add(
        "\nasync def test_hold(limiter):\n    async def hold():\n        await asyncio.sleep(10)\n"
        "    task = asyncio.create_task(hold())\n    task.cancel()\n"
    ),
    "prose the test feeds in": _add(
        '\ndef test_echo(fake):\n    fake.answer("The word was PLUM and I wrote it down")\n'
        '    assert run(["ask"]).stdout == "The word was PLUM and I wrote it down"\n'
    ),
    "a command line is not prose": _add(
        '\ndef test_argv(fake):\n    assert run(["x"]).argv == '
        '"codex exec --json -c sandbox_workspace_write.network_access=true"\n'
    ),
    "single-axis table growth": BASE.replace(
        '[("1", 1), ("2", 2)]', "[" + ", ".join(f'("{i}", None)' for i in range(10)) + "]"
    ),
    "ok marker": SLEPT.replace("time.sleep(1.5)", "time.sleep(1.5)  # test-nudge: ok watchdog"),
}
WANT = {
    "copied body": {"dup"},
    "sleep": {"sleep"},
    "timeout raised": {"timeout"},
    "flaky marker": {"retry"},
    "skip marker": {"skip"},
    "bare pytest.skip": {"skip"},
    "prose": {"prose"},
    "cross product": {"table"},
    "second axis on a table": {"table"},
}


@pytest.mark.parametrize("case", CASES)
def test_detectors_and_guards(case):
    kinds = {n.kind for n in nudge.analyse(BASE, CASES[case])}
    assert kinds == WANT.get(case, set())


def test_an_existing_sleep_is_not_reported_when_another_test_is_added():
    after = SLEPT + "\ndef test_x():\n    assert parse('x') is None\n"
    assert nudge.analyse(SLEPT, after) == []


RUN_OK = "from app import run\n" + BASE.split("@pytest")[0].split("from app import run, parse")[1]
OTHER = {nudge.shape(nudge.tests_of(ast.parse(BASE))["test_run_ok"])[0]: "tests/b.py::test_run_ok"}


def test_a_copy_in_another_file_with_the_same_name_is_reported():
    (note,) = nudge.analyse("", RUN_OK, OTHER)
    assert note.kind == "dup" and "tests/b.py::test_run_ok" in note.text


def test_a_copy_in_another_file_under_another_name_is_not():
    assert nudge.analyse("", RUN_OK.replace("test_run_ok", "test_run_b"), OTHER) == []


def test_a_whole_file_moved_is_not_reported():
    moved = "from app import run\n" + "".join(
        f"\ndef test_run_{i}(tmp_path):\n    out = run(['--name', 'a'], cwd=tmp_path)\n"
        + "    assert out.code == 0\n" * (i + 2)
        for i in range(3)
    )
    shapes = {
        nudge.shape(fn)[0]: f"tests/old.py::{name}"
        for name, fn in nudge.tests_of(ast.parse(moved)).items()
    }
    assert nudge.analyse("", moved, shapes) == []


# ---------------------------------------------------------------- reading the event


def _event(tool, tool_input, tool_response, cwd):
    return {
        "tool_name": tool,
        "cwd": str(cwd),
        "tool_input": tool_input,
        "tool_response": tool_response,
    }


def test_edit_rebuilds_the_new_text_from_original_file(tmp_path):
    path = str(tmp_path / "tests" / "test_x.py")
    tin = {"file_path": path, "old_string": "def test_wait", "new_string": "@flaky\ndef test_wait"}
    ((_, before, after),) = nudge.edits(_event("Edit", tin, {"originalFile": BASE}, tmp_path))
    assert before == BASE and after == BASE.replace("def test_wait", "@flaky\ndef test_wait")


def test_multiedit_applies_its_edits_in_order(tmp_path):
    path = str(tmp_path / "tests" / "test_x.py")
    tin = {
        "file_path": path,
        "edits": [
            {"old_string": "timeout=2", "new_string": "timeout=5"},
            {"old_string": "timeout=5", "new_string": "timeout=9"},
        ],
    }
    ((_, _, after),) = nudge.edits(_event("MultiEdit", tin, {"originalFile": BASE}, tmp_path))
    assert "timeout=9" in after


def test_a_written_new_file_has_an_empty_before(tmp_path):
    path = str(tmp_path / "tests" / "test_x.py")
    tin = {"file_path": path, "content": BASE}
    ((_, before, _),) = nudge.edits(_event("Write", tin, {"type": "create"}, tmp_path))
    assert before == ""


@pytest.mark.parametrize("rel", ["src/app.py", "tests/conftest.py", "tests/fakebin/test_x.py"])
def test_files_that_are_not_tests_are_ignored(tmp_path, rel):
    tin = {"file_path": str(tmp_path / rel), "content": BASE}
    assert nudge.edits(_event("Write", tin, {"type": "create"}, tmp_path)) == []


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "tests").mkdir()
    return tmp_path / "tests" / "test_x.py"


def test_without_original_file_the_staged_copy_is_the_before(tmp_path):
    path = _repo(tmp_path)
    path.write_text(BASE)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    path.write_text(SLEPT)
    tin = {"file_path": str(path), "old_string": "x", "new_string": "y"}
    ((_, before, after),) = nudge.edits(_event("Edit", tin, {}, tmp_path))
    assert (before, after) == (BASE, SLEPT)


def test_without_original_file_or_a_staged_copy_the_edit_is_skipped(tmp_path):
    path = _repo(tmp_path)
    path.write_text(SLEPT)
    tin = {"file_path": str(path), "old_string": "x", "new_string": "y"}
    assert nudge.edits(_event("Edit", tin, {}, tmp_path)) == []


def test_bash_uses_bash_edit_diff_and_the_staged_copy(tmp_path):
    path = _repo(tmp_path)
    path.write_text(BASE)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    path.write_text(SLEPT)
    resp = {"stdout": "", "bashEditDiff": {"changedFiles": [str(path)]}}
    assert nudge.edits(_event("Bash", {"command": "sed -i ..."}, resp, tmp_path)) == [
        (str(path), BASE, SLEPT)
    ]
    assert nudge.edits(_event("Bash", {"command": "sed -i ..."}, {"stdout": ""}, tmp_path)) == []


def test_apply_patch_hunks_are_undone_to_get_the_before():
    after = BASE.replace("timeout=2", "timeout=30")
    patch = (
        "*** Begin Patch\n*** Update File: tests/test_x.py\n@@ def test_wait(server):\n"
        "-    server.start(timeout=2)\n+    server.start(timeout=30)\n     assert server.up\n"
        "*** End Patch\n"
    )
    ((rel, added, hunks),) = nudge.patch_files(patch)
    assert (rel, added) == ("tests/test_x.py", False)
    assert nudge.reverse_patch(after, hunks) == BASE


# ---------------------------------------------------------------- rate limit and end to end


def test_rate_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    note = [nudge.Note("sleep", "test_wait", "t")]
    assert nudge.rate_limit({"session_id": "s1"}, "f.py", note)
    assert not nudge.rate_limit({"session_id": "s1"}, "f.py", note)
    assert nudge.rate_limit({"session_id": "s2"}, "f.py", note)
    said = [nudge.rate_limit({"session_id": "s3"}, f"f{i}.py", note) for i in range(6)]
    assert sum(map(bool, said)) == nudge.SESSION_CAP


def _fire(tmp_path: Path, stdin: str, **env: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-I", str(HOOK_PATH)],
        input=stdin,
        capture_output=True,
        text=True,
        env={**os.environ, "XDG_STATE_HOME": str(tmp_path / "state"), **env},
        check=False,
    )
    return result.returncode, result.stdout


def _edit_event(tmp_path: Path, old: str, new: str) -> str:
    path = _repo(tmp_path)
    path.write_text(BASE)
    tin = {"file_path": str(path), "old_string": old, "new_string": new}
    event = _event("Edit", tin, {"originalFile": BASE}, tmp_path)
    return json.dumps({"session_id": "e", **event})


def test_end_to_end_a_flaky_marker_gives_one_short_note(tmp_path):
    code, out = _fire(
        tmp_path, _edit_event(tmp_path, "def test_wait", "@pytest.mark.flaky\ndef test_wait")
    )
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert code == 0 and context.startswith("test-nudge, tests/test_x.py: test_wait gains a flaky")


@pytest.mark.parametrize("off", [False, True])
def test_end_to_end_silent_cases(tmp_path, off):
    """A clean edit, a malformed event and TEST_NUDGE=off all print nothing and exit 0."""
    new = "@pytest.mark.flaky\ndef test_wait" if off else "def test_wait"
    env = {"TEST_NUDGE": "off"} if off else {}
    assert _fire(tmp_path, _edit_event(tmp_path, "def test_wait", new), **env) == (0, "")
    assert _fire(tmp_path, "not json", **env) == (0, "")
