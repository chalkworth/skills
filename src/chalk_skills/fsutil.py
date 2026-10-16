"""File helpers: hashing, copying a skill folder, and deterministic JSON."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

IGNORED_DIRS = {"__pycache__", ".git"}
IGNORED_SUFFIXES = {".pyc"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def entry_hash(path: Path) -> str:
    """Hash of a file's bytes, or of a symlink's target text (so a link is not followed)."""
    if path.is_symlink():
        return sha256_bytes(b"symlink\0" + os.readlink(path).encode())
    return sha256_bytes(path.read_bytes())


def tree_hashes(folder: Path) -> dict[str, str]:
    """Relative path to hash for every file and symlink under `folder`, ignoring caches."""
    found: dict[str, str] = {}
    for current, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
        base = Path(current)
        # A symlink to a directory shows up in `dirs`; record it as a link and do not descend.
        for name in list(dirs):
            if (base / name).is_symlink():
                dirs.remove(name)
                found[(base / name).relative_to(folder).as_posix()] = entry_hash(base / name)
        for name in files:
            path = base / name
            if path.suffix in IGNORED_SUFFIXES:
                continue
            found[path.relative_to(folder).as_posix()] = entry_hash(path)
    return dict(sorted(found.items()))


def copy_tree(source: Path, dest: Path) -> None:
    """Copy `source` to `dest` (which must not exist), keeping modes and symlinks."""
    for rel in tree_hashes(source):
        src = source / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
        else:
            shutil.copyfile(src, dst)
            os.chmod(dst, src.stat().st_mode & 0o777)
    dest.mkdir(parents=True, exist_ok=True)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def dump_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_text_if_changed(path: Path, text: str) -> None:
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    from chalk_skills.errors import ChalkError

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ChalkError(f"{path} is not valid JSON: {error}") from error
