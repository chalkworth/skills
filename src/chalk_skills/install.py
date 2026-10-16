"""`install --global`: symlink a source's packs into the user-level skill folders."""

from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

from chalk_skills.errors import ChalkError
from chalk_skills.sources import cache_root, read_source_manifest

TARGETS = {
    "claude": ".claude/skills",
    "agents": ".agents/skills",
    "pi": ".pi/agent/skills",
}


def pack_skills(source: Path, packs: list[str]) -> dict[str, Path]:
    read_source_manifest(source, str(source))  # the source must be a skills repository
    found: dict[str, Path] = {}
    for pack in packs:
        pack_dir = source / "packs" / pack
        if not pack_dir.is_dir():
            raise ChalkError(f"unknown pack {pack} in {source}")
        for folder in sorted(pack_dir.iterdir()):
            if (folder / "SKILL.md").is_file():
                if folder.name in found:
                    raise ChalkError(f"skill {folder.name} is in more than one of the packs")
                found[folder.name] = folder.resolve()
    return found


def all_packs(source: Path) -> list[str]:
    packs_dir = source / "packs"
    return sorted(p.name for p in packs_dir.iterdir() if p.is_dir()) if packs_dir.is_dir() else []


def install_global(
    home: Path, source: Path, packs: list[str], replace: bool, stamp: str | None = None
) -> list[str]:
    skills = pack_skills(source, packs)
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    lines: list[str] = []
    plan: list[tuple[str, Path, Path]] = []
    for label, rel in TARGETS.items():
        for name, folder in skills.items():
            link = home / rel / name
            if link.is_symlink() and Path(os.readlink(link)) == folder:
                continue
            if link.exists() or link.is_symlink():
                if not replace:
                    raise ChalkError(
                        f"{link} already exists and is not a link to this source; use --replace"
                    )
                plan.append((label, link, folder))
            else:
                plan.append((label, link, folder))
    for label, link, folder in plan:
        if link.exists() or link.is_symlink():
            moved = cache_root() / "replaced" / stamp / label / link.name
            moved.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(link), str(moved))
            lines.append(f"moved {link} to {moved}")
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(folder, link)
        lines.append(f"linked {link}")
    if not lines:
        lines.append("already installed")
    return lines


def uninstall_global(home: Path, source: Path, packs: list[str]) -> list[str]:
    skills = pack_skills(source, packs or all_packs(source))
    root = (source / "packs").resolve()
    lines = []
    for rel in TARGETS.values():
        for name in skills:
            link = home / rel / name
            if not link.is_symlink():
                continue
            target = Path(os.readlink(link))
            if root in target.parents:
                link.unlink()
                lines.append(f"removed {link}")
    return lines or ["nothing to remove"]
