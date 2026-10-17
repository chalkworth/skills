"""The AXI session-start hook, with the tools and the npm registry replaced by stubs."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = ROOT / "hooks" / "axi-session" / "axi_session_start.py"
NOW = 1_000_000_000.0


def _load_hook() -> ModuleType:
    spec = importlib.util.spec_from_file_location("axi_session_start", HOOK_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["axi_session_start"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = _load_hook()
    monkeypatch.setattr(module, "CACHE_PATH", tmp_path / "cache" / "axi-latest-versions.json")
    return module


def _repo(path: Path, remote_url: str | None) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    if remote_url:
        subprocess.run(["git", "remote", "add", "origin", remote_url], cwd=path, check=True)
    return path


def _stub_tools(
    hook: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    installed: dict[str, str],
    latest: dict[str, str],
) -> None:
    monkeypatch.setattr(
        hook.shutil, "which", lambda name: f"/bin/{name}" if name in installed else None
    )
    monkeypatch.setattr(
        hook, "run_tool", lambda executable, working_directory: f"{executable} summary"
    )
    monkeypatch.setattr(hook, "installed_version", lambda package: installed.get(package))
    monkeypatch.setattr(hook, "fetch_latest_version", lambda package: latest.get(package))


def _claude(hook: ModuleType, working_directory: Path, now: float) -> dict:
    text = hook.render("claude", *hook.gather(str(working_directory), now))
    return json.loads(text) if text else {}


def test_github_summary_only_in_repos_with_a_github_remote(hook, tmp_path, monkeypatch) -> None:
    installed = {"gh-axi": "0.1.38", "chrome-devtools-axi": "0.1.40"}
    _stub_tools(hook, monkeypatch, installed, latest=installed)
    on_github = _repo(tmp_path / "on-github", "https://github.com/example/repo.git")
    elsewhere = _repo(tmp_path / "elsewhere", "ssh://git.example.com/repo.git")

    github_context = _claude(hook, on_github, NOW)["hookSpecificOutput"]["additionalContext"]
    other_context = _claude(hook, elsewhere, NOW + 1)["hookSpecificOutput"]["additionalContext"]

    assert "gh-axi summary" in github_context
    assert "chrome-devtools-axi summary" in github_context
    assert "gh-axi summary" not in other_context
    assert "chrome-devtools-axi summary" in other_context


def test_every_installed_summary_tool_is_summarised_in_order(hook, tmp_path, monkeypatch) -> None:
    installed = {"gh-axi": "1", "chrome-devtools-axi": "1", "lavish-axi": "1"}
    _stub_tools(hook, monkeypatch, installed, latest=installed)
    repo = _repo(tmp_path / "repo", "git@github.com:example/repo.git")

    context = _claude(hook, repo, NOW)["hookSpecificOutput"]["additionalContext"]

    assert context.split("\n\n") == [f"{tool} summary" for tool in installed]


def test_a_repository_can_skip_summaries(hook, tmp_path, monkeypatch) -> None:
    installed = {"gh-axi": "1", "chrome-devtools-axi": "1", "lavish-axi": "1"}
    _stub_tools(hook, monkeypatch, installed, latest=installed)
    ran: list[str] = []
    monkeypatch.setattr(
        hook, "run_tool", lambda executable, working_directory: ran.append(executable) or "s"
    )
    repo = _repo(tmp_path / "repo", "git@github.com:example/repo.git")
    (repo / ".agents").mkdir()
    (repo / ".agents" / "axi-session.toml").write_text('skip = ["lavish-axi", "gh-axi"]\n')
    subdirectory = repo / "src"
    subdirectory.mkdir()

    hook.gather(str(subdirectory), NOW)

    assert ran == ["chrome-devtools-axi"]


@pytest.mark.parametrize("config", ["skip = [", 'skip = "lavish-axi"', "skip = [1]"])
def test_a_bad_repository_config_skips_nothing(hook, tmp_path, monkeypatch, config) -> None:
    repo = _repo(tmp_path / "repo", None)
    (repo / ".agents").mkdir()
    (repo / ".agents" / "axi-session.toml").write_text(config + "\n")
    assert hook.skipped_tools(str(repo)) == set()


def test_outdated_packages_go_to_the_person_once_a_day(hook, tmp_path, monkeypatch) -> None:
    _stub_tools(hook, monkeypatch, {"gh-axi": "0.1.9"}, latest={"gh-axi": "0.1.10"})
    repo = _repo(tmp_path / "repo", None)

    first = _claude(hook, repo, NOW)
    same_day = _claude(hook, repo, NOW + 3600)
    next_day = _claude(hook, repo, NOW + 25 * 3600)

    assert "gh-axi 0.1.9 → 0.1.10" in first["systemMessage"]
    assert "npm i -g gh-axi@latest" in first["systemMessage"]
    assert "systemMessage" not in same_day
    assert "systemMessage" in next_day
    assert (
        "hookSpecificOutput" not in first
    )  # no GitHub remote, no other tool: nothing for the agent


def test_current_packages_and_unreachable_registry_stay_silent(hook, tmp_path, monkeypatch) -> None:
    repo = _repo(tmp_path / "repo", None)
    _stub_tools(hook, monkeypatch, {"tasks-axi": "0.2.6"}, latest={"tasks-axi": "0.2.6"})
    assert _claude(hook, repo, NOW) == {}

    hook.CACHE_PATH.unlink()
    _stub_tools(hook, monkeypatch, {"tasks-axi": "0.2.5"}, latest={})
    assert _claude(hook, repo, NOW) == {}
    assert not hook.CACHE_PATH.exists()  # nothing learned, so the next session tries again


def test_versions_compare_numerically(hook) -> None:
    assert hook.outdated_packages(
        {"a": "0.1.9", "b": "0.2.0", "c": "1.0.0"}, {"a": "0.1.10", "b": "0.1.99"}
    ) == ["a 0.1.9 → 0.1.10"]


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("cursor", {"additional_context": "s\n\nTell the user: N"}),
        (
            "antigravity",
            {"injectSteps": [{"systemMessage": {"systemMessage": "s\n\nTell the user: N"}}]},
        ),
    ],
)
def test_json_formats_carry_context_and_notice(hook, monkeypatch, output_format, expected) -> None:
    monkeypatch.setattr(hook, "update_notice", lambda outdated: "N")
    assert json.loads(hook.render(output_format, ["s"], ["x 1 → 2"])) == expected


@pytest.mark.parametrize("output_format", ["codex", "plain"])
def test_text_formats_are_plain_context(hook, output_format) -> None:
    assert hook.render(output_format, ["a", "b"], []) == "a\n\nb"


@pytest.mark.parametrize("output_format", ["claude", "codex", "cursor", "antigravity", "plain"])
def test_nothing_to_say_prints_nothing(hook, output_format) -> None:
    assert hook.render(output_format, [], []) == ""


def test_working_directory_comes_from_the_payload(hook) -> None:
    assert hook.working_directory_of({"cwd": "/a"}) == "/a"
    assert hook.working_directory_of({"workspacePaths": ["/b", "/c"]}) == "/b"
    assert hook.working_directory_of({}) == str(Path.cwd())


@pytest.mark.parametrize("output_format", ["claude", "codex", "cursor", "antigravity", "plain"])
def test_hook_never_fails_and_is_silent_without_tools(tmp_path, output_format) -> None:
    completed = subprocess.run(
        [sys.executable, str(HOOK_PATH), "--format", output_format],
        input=json.dumps({"cwd": str(tmp_path)}),
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": "/nonexistent",
            "HOME": str(tmp_path),
            "XDG_CACHE_HOME": str(tmp_path / "cache"),
        },
        timeout=30,
    )
    assert completed.returncode == 0
    assert completed.stdout == ""
