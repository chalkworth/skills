"""`check`: compare the vendored files, the config and the hook entries with the lockfile."""

from __future__ import annotations

from pathlib import Path

from chalk_skills.config import load_config
from chalk_skills.fsutil import tree_hashes
from chalk_skills.hooks import project_context, verify_hooks
from chalk_skills.lockfile import CONFIG_PATH, LOCK_PATH, lock_selection, read_lock, selection
from chalk_skills.vendor import AGENTS_SKILLS, CLAUDE_SKILLS


def compare_folder(label: str, folder: Path, recorded: dict[str, str]) -> list[str]:
    if not folder.is_dir():
        return [f"{label}: missing"]
    actual = tree_hashes(folder)
    problems = []
    for rel in sorted(set(recorded) | set(actual)):
        if rel not in actual:
            problems.append(f"{label}/{rel}: missing")
        elif rel not in recorded:
            problems.append(f"{label}/{rel}: extra file, not in the lockfile")
        elif actual[rel] != recorded[rel]:
            problems.append(f"{label}/{rel}: changed")
    return problems


def check(root: Path) -> list[str]:
    """Every problem found; empty when the tree matches the lockfile."""
    lock = read_lock(root / LOCK_PATH)
    if lock is None:
        return [f"{LOCK_PATH}: missing; run chalk-skills vendor"]
    problems: list[str] = []
    wanted = selection(load_config(root / CONFIG_PATH))
    recorded = lock_selection(lock)
    if wanted != recorded:
        differing = sorted(k for k in wanted if wanted[k] != recorded[k])
        problems.append(
            f"{CONFIG_PATH} differs from the lockfile ({', '.join(differing)}); run chalk-skills vendor"
        )
    for name, skill in sorted(lock["skills"].items()):
        problems += compare_folder(
            f"{AGENTS_SKILLS}/{name}", root / AGENTS_SKILLS / name, skill["files"]
        )
        if lock["mirror_claude"]:
            problems += compare_folder(
                f"{CLAUDE_SKILLS}/{name}", root / CLAUDE_SKILLS / name, skill["files"]
            )
    problems += verify_hooks(project_context(root), lock["hooks"])
    return problems
