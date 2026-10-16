"""`vendor`: copy the selected skills into a repository and write the lockfile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chalk_skills import visibility
from chalk_skills.config import Config, load_config
from chalk_skills.errors import ChalkError
from chalk_skills.fsutil import copy_tree, read_json, remove_path, tree_hashes
from chalk_skills.hookdef import HookDef, load_hook
from chalk_skills.hooks import SelectedHook, project_context, sync_hooks
from chalk_skills.lockfile import (
    CONFIG_PATH,
    LOCK_PATH,
    empty_lock,
    read_lock,
    write_lock,
)
from chalk_skills.sources import Source, resolve_source

AGENTS_SKILLS = ".agents/skills"
CLAUDE_SKILLS = ".claude/skills"
CLAUDE_MANIFEST = ".generated-from-agents.json"


@dataclass(frozen=True)
class Chosen:
    name: str
    source: Source
    pack: str
    folder: Path


def select_skills(sources: list[Source]) -> dict[str, Chosen]:
    chosen: dict[str, Chosen] = {}

    def add(source: Source, name: str) -> None:
        if name in source.duplicate_skills:
            packs = ", ".join(source.duplicate_skills[name])
            raise ChalkError(f"skill {name} is in more than one pack of {source.spec.url}: {packs}")
        pack, folder = source.skills[name]
        if name in chosen and chosen[name].source is not source:
            raise ChalkError(
                f"skill {name} comes from two sources: {chosen[name].source.spec.url}"
                f" and {source.spec.url}"
            )
        chosen[name] = Chosen(name, source, pack, folder)

    for source in sources:
        known_packs = source.pack_names()
        for pack in source.spec.packs:
            if pack not in known_packs:
                raise ChalkError(f"unknown pack {pack} in source {source.spec.url}")
            for name, (owner, _) in sorted(source.skills.items()):
                if owner == pack:
                    add(source, name)
            for name, packs in source.duplicate_skills.items():
                if pack in packs:
                    add(source, name)
        for name in source.spec.skills:
            if name not in source.skills:
                raise ChalkError(f"unknown skill {name} in source {source.spec.url}")
            add(source, name)
    return dict(sorted(chosen.items()))


def select_hooks(config: Config, sources: list[Source]) -> list[SelectedHook]:
    selected: list[SelectedHook] = []
    for hook_id in sorted(set(config.hooks)):
        owners = [s for s in sources if hook_id in s.hooks]
        if not owners:
            raise ChalkError(f"no source defines hook {hook_id}")
        if len(owners) > 1:
            urls = ", ".join(s.spec.url for s in owners)
            raise ChalkError(f"hook {hook_id} is defined by more than one source: {urls}")
        hook: HookDef = load_hook(owners[0].hooks[hook_id], hook_id)
        selected.append(SelectedHook(hook, owners[0].spec.url, owners[0].commit))
    return selected


def claude_manifest_names(root: Path) -> set[str]:
    path = root / CLAUDE_SKILLS / CLAUDE_MANIFEST
    if not path.is_file():
        return set()
    try:
        data = read_json(path)
    except ChalkError:
        return set()
    names = data.get("skills", []) if isinstance(data, dict) else []
    return {n for n in names if isinstance(n, str)}


def check_clashes(root: Path, chosen: dict[str, Chosen], old: dict[str, Any], mirror: bool) -> None:
    old_skills = set(old["skills"])
    old_mirror = bool(old["mirror_claude"])
    manifest = claude_manifest_names(root)
    for name, pick in chosen.items():
        if (root / AGENTS_SKILLS / name).exists() and name not in old_skills:
            raise ChalkError(f"repo-owned skill {name} clashes: {AGENTS_SKILLS}/{name} exists")
        claude = root / CLAUDE_SKILLS / name
        ours = name in old_skills and old_mirror
        foreign = mirror and claude.exists() and not ours and name not in manifest
        if foreign and tree_hashes(claude) != tree_hashes(pick.folder):
            raise ChalkError(f"repo-owned skill {name} clashes: {CLAUDE_SKILLS}/{name} exists")


def apply_skills(root: Path, chosen: dict[str, Chosen], old: dict[str, Any], mirror: bool) -> None:
    for name in sorted(set(old["skills"]) - set(chosen)):
        remove_path(root / AGENTS_SKILLS / name)
        if old["mirror_claude"]:
            remove_path(root / CLAUDE_SKILLS / name)
    if old["mirror_claude"] and not mirror:
        for name in sorted(set(old["skills"]) & set(chosen)):
            remove_path(root / CLAUDE_SKILLS / name)
    for name, pick in chosen.items():
        targets = [root / AGENTS_SKILLS / name]
        if mirror:
            targets.append(root / CLAUDE_SKILLS / name)
        for target in targets:
            remove_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            copy_tree(pick.folder, target)


def vendor(root: Path, only_hooks: bool = False) -> list[str]:
    """Run vendor (or just the hook part) in `root`. Returns lines to print."""
    config = load_config(root / CONFIG_PATH)
    sources = [resolve_source(spec, root) for spec in config.sources]
    visibility.guard(config, root, [s.spec.url for s in sources if s.visibility == "private"])
    chosen = {} if only_hooks else select_skills(sources)
    selected_hooks = select_hooks(config, sources)
    old = read_lock(root / LOCK_PATH) or empty_lock()
    lines: list[str] = []
    lock = dict(old)
    if not only_hooks:
        check_clashes(root, chosen, old, config.mirror_claude)
        apply_skills(root, chosen, old, config.mirror_claude)
        lock.update(
            {
                "mirror_claude": config.mirror_claude,
                "sources": [
                    {
                        "url": s.spec.url,
                        "ref": s.spec.ref,
                        "commit": s.commit,
                        "dirty": s.dirty,
                        "packs": sorted(s.spec.packs),
                        "skills": sorted(s.spec.skills),
                    }
                    for s in sources
                ],
                "skills": {
                    name: {
                        "source": pick.source.spec.url,
                        "pack": pick.pack,
                        "files": tree_hashes(root / AGENTS_SKILLS / name),
                    }
                    for name, pick in chosen.items()
                },
            }
        )
        lines.append(f"vendored {len(chosen)} skill(s) from {len(sources)} source(s)")
    hooks, hook_files = sync_hooks(
        project_context(root), selected_hooks, config.clis, old["hooks"], old["hook_files"]
    )
    lock.update({"hooks": hooks, "hook_files": hook_files, "clis": list(config.clis)})
    write_lock(root / LOCK_PATH, lock)
    lines.append(f"wrote {len(hooks)} hook(s)")
    return lines
