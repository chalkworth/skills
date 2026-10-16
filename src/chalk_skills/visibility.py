"""Whether a target repository is public, and the guard against vendoring private skills into one."""

from __future__ import annotations

import subprocess
from pathlib import Path

from chalk_skills.config import Config
from chalk_skills.errors import ChalkError

PUBLIC = "public"
PRIVATE = "private"
UNKNOWN = "unknown"


def ask_gh(root: Path) -> str:
    """The repository's visibility according to `gh`, or UNKNOWN when gh is missing or fails."""
    try:
        done = subprocess.run(
            ["gh", "repo", "view", "--json", "visibility", "-q", ".visibility"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return UNKNOWN
    if done.returncode != 0:
        return UNKNOWN
    answer = done.stdout.strip().upper()
    if answer == "PUBLIC":
        return PUBLIC
    if answer in ("PRIVATE", "INTERNAL"):
        return PRIVATE
    return UNKNOWN


def target_visibility(config: Config, root: Path) -> str:
    if config.public is True:
        return PUBLIC
    if config.public is False:
        return PRIVATE
    return ask_gh(root)


def guard(config: Config, root: Path, private_sources: list[str]) -> None:
    """Refuse when a private source would be vendored into a public or unknown-visibility target."""
    if not private_sources:
        return
    names = ", ".join(private_sources)
    state = target_visibility(config, root)
    if state == PUBLIC:
        raise ChalkError(
            f"refusing to vendor private source(s) {names} into a public repository"
            " (public = true or gh reports PUBLIC)"
        )
    if state == UNKNOWN:
        raise ChalkError(
            f"cannot tell whether this repository is public, and {names} is private;"
            " set `public = false` in .agents/skills.toml to vendor it here"
        )
