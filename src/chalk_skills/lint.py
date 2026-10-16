"""`lint`: check a source repository's skills for the rules every consumer relies on."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

from chalk_skills.markers import scan_text, unresolved

# Checked over every tracked text file when the repository is public. Case-insensitive.
DENYLIST: tuple[str, ...] = (
    r"/home/[a-z]",
    r"/Users/[a-z]",
    r"C:[/\\]Users[/\\]",
)
# Paths (prefixes) that may contain denylisted text: this module defines the list, and the tests
# build fixtures that must trip it.
DENYLIST_EXEMPT: tuple[str, ...] = (
    "src/chalk_skills/lint.py",
    "tests/tool/",
    "tests/fixtures/lint/",
)
SKILL_TEXT_SUFFIXES = {".md", ".json", ".toml", ".txt", ".yaml", ".yml", ".py", ".sh"}
PORTABILITY_EXEMPT_FILES = {"UPSTREAM.json", "LICENSE", "LICENSE.md", "LICENSE.txt"}
CLAUDE_VARIABLE = re.compile(r"\$\{CLAUDE_")
# A plugin-style `namespace:skill-name` reference; only names of skills in this repository count.
NAMESPACED_SKILL = re.compile(r"(?<![\w/.:-])([a-z][a-z0-9-]*):([a-z][a-z0-9-]*)\b")
UPSTREAM_KEYS = ("source", "upstream", "repository")
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt")
SKIPPED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
}

Problem = tuple[str, int, str]  # path (relative), line (0 when not a line), message


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """The top-level `key: value` pairs of a `---` frontmatter block, or None when there is none.

    Handles quoted values, `>` and `|` block scalars and indented continuation lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    key: str | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return {k: v.strip() for k, v in fields.items()}
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if match and not line.startswith((" ", "\t")):
            key, value = match.group(1), match.group(2).strip()
            if value in (">", "|", ">-", "|-"):
                value = ""
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
                value = value[1:-1]
            fields[key] = value
        elif key is not None and line.startswith((" ", "\t")):
            fields[key] = f"{fields[key]} {line.strip()}".strip()
    return None  # no closing marker


def tracked_files(root: Path) -> list[Path]:
    """Git's tracked files when `root` is a git checkout, else every file outside cache folders."""
    if (root / ".git").exists():
        done = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if done.returncode == 0:
            names = [n for n in done.stdout.decode().split("\0") if n]
            return sorted(root / n for n in names if (root / n).is_file())
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and not SKIPPED_DIRS.intersection(p.relative_to(root).parts)
    )


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return None


def skill_folders(root: Path) -> list[Path]:
    packs = root / "packs"
    if not packs.is_dir():
        return []
    return sorted(
        f
        for pack in sorted(packs.iterdir())
        if pack.is_dir()
        for f in sorted(pack.iterdir())
        if f.is_dir()
    )


def lint_skills(root: Path, problems: list[Problem]) -> None:
    seen: dict[str, str] = {}
    names = {folder.name for folder in skill_folders(root)}
    for folder in skill_folders(root):
        rel = folder.relative_to(root).as_posix()
        skill_md = folder / "SKILL.md"
        if not skill_md.is_file():
            problems.append((rel, 0, "no SKILL.md"))
            continue
        fields = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fields is None:
            problems.append((f"{rel}/SKILL.md", 1, "no frontmatter"))
        else:
            if fields.get("name") != folder.name:
                problems.append(
                    (
                        f"{rel}/SKILL.md",
                        1,
                        f"name {fields.get('name')!r} must equal folder {folder.name!r}",
                    )
                )
            if not fields.get("description"):
                problems.append((f"{rel}/SKILL.md", 1, "description is missing or empty"))
        if folder.name in seen:
            problems.append((rel, 0, f"skill name also used at {seen[folder.name]}"))
        seen[folder.name] = rel
        lint_upstream(folder, root, problems)
        lint_text(folder, root, problems, names)


def lint_upstream(folder: Path, root: Path, problems: list[Problem]) -> None:
    rel = folder.relative_to(root).as_posix()
    upstream = folder / "UPSTREAM.json"
    has_license = any((folder / name).is_file() for name in LICENSE_NAMES)
    if upstream.is_file():
        same_author = False
        try:
            data = json.loads(upstream.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            problems.append((f"{rel}/UPSTREAM.json", 1, f"invalid JSON: {error}"))
        else:
            if not isinstance(data, dict) or not any(k in data for k in UPSTREAM_KEYS):
                keys = " or ".join(UPSTREAM_KEYS)
                problems.append(
                    (f"{rel}/UPSTREAM.json", 1, f"needs a key naming the source: {keys}")
                )
            # A skill moved from the author's own repository needs no licence of its own.
            same_author = isinstance(data, dict) and data.get("same_author") is True
        if not has_license and not same_author:
            problems.append((rel, 0, "UPSTREAM.json without a LICENSE"))
    elif has_license:
        problems.append((rel, 0, "LICENSE without an UPSTREAM.json"))


def namespaced_references(line: str, skill_names: set[str]) -> list[str]:
    return [
        m.group(0)
        for m in NAMESPACED_SKILL.finditer(line)
        if m.group(2) in skill_names and m.group(1) not in ("http", "https", "file")
    ]


def lint_text(folder: Path, root: Path, problems: list[Problem], skill_names: set[str]) -> None:
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        if path.suffix not in SKILL_TEXT_SUFFIXES or path.name in PORTABILITY_EXEMPT_FILES:
            continue
        text = read_text(path)
        if text is None:
            continue
        rel = path.relative_to(root).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            if CLAUDE_VARIABLE.search(line):
                problems.append((rel, number, "uses ${CLAUDE_...}, which only Claude Code expands"))
            for reference in namespaced_references(line, skill_names):
                problems.append((rel, number, f"namespaced skill reference {reference!r}"))
        if path.suffix == ".md":
            for finding in unresolved(scan_text(path, text)):
                detail = (
                    finding.problem
                    if finding.problem
                    else f"unresolved {finding.keyword}({finding.source}): {finding.claim}"
                )
                problems.append((rel, finding.line_number, detail))


def load_manifest(root: Path, problems: list[Problem]) -> dict:
    path = root / "skills.toml"
    if not path.is_file():
        problems.append(("skills.toml", 0, "missing"))
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        problems.append(("skills.toml", 0, f"invalid TOML: {error}"))
        return {}


def lint_packs(root: Path, manifest: dict, problems: list[Problem]) -> None:
    packs_dir = root / "packs"
    folders = {p.name for p in packs_dir.iterdir() if p.is_dir()} if packs_dir.is_dir() else set()
    described = {
        name: table for name, table in manifest.get("packs", {}).items() if isinstance(table, dict)
    }
    for name in sorted(folders - set(described)):
        problems.append((f"packs/{name}", 0, "pack is not described in skills.toml"))
    for name in sorted(set(described) - folders):
        problems.append(("skills.toml", 0, f"pack {name} has no folder under packs/"))
    for name, table in sorted(described.items()):
        if not str(table.get("description", "")).strip():
            problems.append(("skills.toml", 0, f"pack {name} has no description"))


def lint_denylist(root: Path, problems: list[Problem]) -> None:
    patterns = [re.compile(p, re.IGNORECASE) for p in DENYLIST]
    for path in tracked_files(root):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(DENYLIST_EXEMPT):
            continue
        text = read_text(path)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for pattern in patterns:
                if pattern.search(line):
                    problems.append(
                        (rel, number, f"denylisted content (pattern {pattern.pattern})")
                    )


def lint_private_references(root: Path, manifest: dict, problems: list[Problem]) -> None:
    """A public repository must not list a private source in its own target config."""
    config = root / ".agents" / "skills.toml"
    if manifest.get("visibility") != "public" or not config.is_file():
        return
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return
    for source in data.get("source", []):
        url = source.get("url", "") if isinstance(source, dict) else ""
        if "://" in url:
            continue
        path = (root / url).resolve()
        try:
            other = tomllib.loads((path / "skills.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if other.get("visibility", "private") != "public":
            problems.append(
                (".agents/skills.toml", 0, f"public repository uses private source {url}")
            )


def lint(root: Path) -> list[Problem]:
    problems: list[Problem] = []
    manifest = load_manifest(root, problems)
    lint_skills(root, problems)
    lint_packs(root, manifest, problems)
    if manifest.get("visibility") == "public":
        lint_denylist(root, problems)
        lint_private_references(root, manifest, problems)
    return problems


def format_problem(problem: Problem) -> str:
    path, line, message = problem
    return f"{path}:{line}: {message}"
