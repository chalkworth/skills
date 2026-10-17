"""check_mermaid.py finds a Chrome without downloading one and reads every mermaid fence."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "packs/docs/diagramming-in-markdown/scripts/check_mermaid.py"
)


def load():
    spec = importlib.util.spec_from_file_location("check_mermaid", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_mermaid"] = module
    spec.loader.exec_module(module)
    return module


check_mermaid = load()


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


@pytest.fixture
def bare(monkeypatch, tmp_path: Path) -> Path:
    """No Chrome on PATH or named in the environment; returns an empty home."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    monkeypatch.delenv("PUPPETEER_EXECUTABLE_PATH", raising=False)
    monkeypatch.setattr(check_mermaid, "MAC_APPS", ())
    home = tmp_path / "home"
    home.mkdir()
    return home


def test_a_named_executable_wins(bare: Path, monkeypatch):
    chrome = executable(bare / "my-chrome")
    monkeypatch.setenv("PUPPETEER_EXECUTABLE_PATH", str(chrome))
    assert check_mermaid.find_chrome(bare) == str(chrome)


def test_chrome_on_path_comes_before_caches(bare: Path, monkeypatch, tmp_path: Path):
    on_path = executable(tmp_path / "bin" / "chromium")
    monkeypatch.setenv("PATH", str(on_path.parent))
    executable(bare / ".cache/puppeteer/chrome/linux-1/chrome-linux64/chrome")
    assert check_mermaid.find_chrome(bare) == str(on_path)


def test_the_newest_cached_headless_shell_is_used(bare: Path):
    shell = ".cache/ms-playwright/chromium_headless_shell-{}/chrome-headless-shell-linux64/chrome-headless-shell"
    executable(bare / shell.format(999))
    newest = executable(bare / shell.format(1248))
    assert check_mermaid.find_chrome(bare) == str(newest)


def test_nothing_found_is_none(bare: Path):
    assert check_mermaid.find_chrome(bare) is None


def test_fences_are_found_with_their_line_numbers():
    text = "# Page\n\n```mermaid\nflowchart TD\n  a --> b\n```\n\ntext\n\n```mermaid\npie\n```\n"
    assert check_mermaid.diagrams(text) == [(3, "flowchart TD\n  a --> b\n"), (10, "pie\n")]


def test_other_fences_are_ignored():
    assert check_mermaid.diagrams("```python\nx = 1\n```\n") == []


def test_no_chrome_exits_2(bare: Path, monkeypatch, tmp_path: Path, capsys):
    monkeypatch.setattr(check_mermaid.Path, "home", staticmethod(lambda: bare))
    page = tmp_path / "page.md"
    page.write_text("```mermaid\npie\n```\n", encoding="utf-8")
    assert check_mermaid.main([str(page)]) == 2
    assert "no Chrome" in capsys.readouterr().err
