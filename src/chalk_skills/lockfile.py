"""The lockfile `.agents/skills.lock.json`, and the part of the config it records."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from chalk_skills import __version__
from chalk_skills.config import Config
from chalk_skills.fsutil import dump_json, read_json

LOCK_VERSION = 1
LOCK_PATH = ".agents/skills.lock.json"
CONFIG_PATH = ".agents/skills.toml"


def selection(config: Config) -> dict[str, Any]:
    """What the config asks for, in the form the lock stores it, so the two can be compared."""
    return {
        "mirror_claude": config.mirror_claude,
        "clis": list(config.clis),
        "hooks": sorted(config.hooks),
        "sources": [
            {
                "url": s.url,
                "ref": s.ref,
                "packs": sorted(s.packs),
                "skills": sorted(s.skills),
            }
            for s in config.sources
        ],
    }


def lock_selection(lock: dict[str, Any]) -> dict[str, Any]:
    return {
        "mirror_claude": lock.get("mirror_claude", False),
        "clis": lock.get("clis", []),
        "hooks": sorted(lock.get("hooks", {})),
        "sources": [
            {k: s.get(k) for k in ("url", "ref", "packs", "skills")}
            for s in lock.get("sources", [])
        ],
    }


def empty_lock() -> dict[str, Any]:
    return {
        "version": LOCK_VERSION,
        "tool_version": __version__,
        "mirror_claude": False,
        "clis": [],
        "sources": [],
        "skills": {},
        "hooks": {},
        "hook_files": {},
    }


def read_lock(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return {**empty_lock(), **read_json(path)}


def write_lock(path: Path, lock: dict[str, Any]) -> None:
    text = dump_json({**lock, "tool_version": __version__})
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
