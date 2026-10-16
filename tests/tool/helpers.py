"""Helpers: temporary source repositories and targets."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from chalk_skills.cli import main

REPO = Path(__file__).resolve().parents[2]


def set_gh(tmp_path: Path, answer: str | None) -> None:
    """Make `gh repo view` print `answer`, or fail when it is None."""
    gh = tmp_path / "bin" / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n" if answer is None else f"#!/bin/sh\necho {answer}\n")


def hide_gh(tmp_path: Path, monkeypatch) -> None:
    """A PATH with git but no gh at all."""
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git"))
    monkeypatch.setenv("PATH", str(only_git))


def git(path: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)


def write_skill(root: Path, pack: str, name: str, files: dict[str, str] | None = None) -> Path:
    folder = root / "packs" / pack / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Use when testing {name}.\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    for rel, text in (files or {}).items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding="utf-8")
    return folder


def make_source(
    path: Path,
    packs: dict[str, list[str]],
    visibility: str = "public",
    hooks: bool = False,
    tag: str | None = None,
    use_git: bool = True,
) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    manifest = [f'visibility = "{visibility}"', ""]
    for pack in packs:
        manifest += [f"[packs.{pack}]", f'description = "The {pack} pack"', ""]
    (path / "skills.toml").write_text("\n".join(manifest), encoding="utf-8")
    for pack, names in packs.items():
        (path / "packs" / pack).mkdir(parents=True, exist_ok=True)
        for name in names:
            write_skill(path, pack, name)
    if hooks:
        shutil.copytree(REPO / "hooks", path / "hooks", dirs_exist_ok=True)
    if use_git:
        commit_all(path, tag)
    return path


def commit_all(path: Path, tag: str | None = None) -> None:
    if not (path / ".git").exists():
        git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "--allow-empty", "-m", "commit")
    if tag:
        git(path, "tag", "-f", tag)


def make_target(path: Path, config: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / ".agents").mkdir(exist_ok=True)
    (path / ".agents" / "skills.toml").write_text(config, encoding="utf-8")
    return path


def config_for(source: Path, packs=(), skills=(), extra: str = "", ref: str | None = None) -> str:
    lines = [extra, "[[source]]", f'url = "{source}"']
    if ref:
        lines.append(f'ref = "{ref}"')
    lines.append(f"packs = {list(packs)!r}".replace("'", '"'))
    lines.append(f"skills = {list(skills)!r}".replace("'", '"'))
    return "\n".join(lines) + "\n"


def run(capsys, *argv: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def snapshot(root: Path) -> dict[str, tuple[str, int]]:
    """Every file under root: its text (or link target) and permission bits."""
    found = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            found[rel] = (f"-> {os.readlink(path)}", 0)
        elif path.is_file():
            found[rel] = (path.read_text(encoding="utf-8"), stat.S_IMODE(path.stat().st_mode))
    return found
