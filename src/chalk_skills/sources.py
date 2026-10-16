"""Resolve a source (a git URL or a local folder) to a checkout and read what it offers."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from chalk_skills.config import SourceSpec
from chalk_skills.errors import ChalkError

SCP_STYLE = re.compile(r"^[\w.-]+@[\w.-]+:")


def cache_root() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "chalk-skills"


def git(*args: str, cwd: Path | None = None) -> str:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=False, timeout=300
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ChalkError(f"git {' '.join(args)} failed: {error}") from error
    if done.returncode != 0:
        raise ChalkError(
            f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip()}"
        )
    return done.stdout.strip()


def is_remote_url(url: str) -> bool:
    return "://" in url or bool(SCP_STYLE.match(url))


@dataclass
class Source:
    spec: SourceSpec
    path: Path
    commit: str | None
    dirty: bool
    visibility: str
    pack_descriptions: dict[str, str]
    skills: dict[str, tuple[str, Path]] = field(default_factory=dict)  # name -> (pack, folder)
    duplicate_skills: dict[str, list[str]] = field(default_factory=dict)
    hooks: dict[str, Path] = field(default_factory=dict)  # id -> folder

    def pack_names(self) -> list[str]:
        packs_dir = self.path / "packs"
        if not packs_dir.is_dir():
            return []
        return sorted(p.name for p in packs_dir.iterdir() if p.is_dir())


def fetch_git(url: str, ref: str | None) -> tuple[Path, str]:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", url.split("://")[-1]).strip("-")[-40:]
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    checkout = cache_root() / "git" / f"{slug}-{digest}"
    if not (checkout / ".git").exists():
        checkout.mkdir(parents=True, exist_ok=True)
        git("init", "-q", cwd=checkout)
    fetch = ["fetch", "-q", "--depth", "1", "--force", "--no-tags", url, ref or "HEAD"]
    git(*fetch, cwd=checkout)
    git("checkout", "-q", "--force", "--detach", "FETCH_HEAD", cwd=checkout)
    git("clean", "-q", "-fdx", cwd=checkout)
    return checkout, git("rev-parse", "HEAD", cwd=checkout)


def local_git_state(path: Path) -> tuple[str | None, bool]:
    if not (path / ".git").exists():
        return None, False
    try:
        commit = git("rev-parse", "HEAD", cwd=path)
        dirty = bool(git("status", "--porcelain", cwd=path))
    except ChalkError:
        return None, False
    return commit, dirty


def read_source_manifest(path: Path, label: str) -> tuple[str, dict[str, str]]:
    manifest = path / "skills.toml"
    if not manifest.is_file():
        raise ChalkError(f"source {label} has no skills.toml at its root")
    try:
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ChalkError(f"source {label}: skills.toml is invalid: {error}") from error
    visibility = data.get("visibility", "private")  # unstated means private, the safe reading
    if visibility not in ("public", "private"):
        raise ChalkError(f'source {label}: visibility must be "public" or "private"')
    packs = {
        name: str(table.get("description", ""))
        for name, table in data.get("packs", {}).items()
        if isinstance(table, dict)
    }
    return visibility, packs


def resolve_source(spec: SourceSpec, root: Path) -> Source:
    if is_remote_url(spec.url):
        path, commit = fetch_git(spec.url, spec.ref)
        dirty = False
    else:
        path = Path(spec.url).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_dir():
            raise ChalkError(f"source {spec.url}: {path} is not a directory")
        commit, dirty = local_git_state(path)
    visibility, packs = read_source_manifest(path, spec.url)
    source = Source(spec, path, commit, dirty, visibility, packs)
    packs_dir = path / "packs"
    for pack in source.pack_names():
        for folder in sorted((packs_dir / pack).iterdir()):
            if not (folder / "SKILL.md").is_file():
                continue
            if folder.name in source.skills:
                source.duplicate_skills.setdefault(folder.name, [source.skills[folder.name][0]])
                source.duplicate_skills[folder.name].append(pack)
                continue
            source.skills[folder.name] = (pack, folder)
    hooks_dir = path / "hooks"
    if hooks_dir.is_dir():
        for folder in sorted(hooks_dir.iterdir()):
            if (folder / "hook.toml").is_file():
                source.hooks[folder.name] = folder
    return source
