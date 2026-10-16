"""`hooks --global`: install hooks for the user, from `~/.config/chalk-skills/global.toml`."""

from __future__ import annotations

from pathlib import Path

from chalk_skills import __version__
from chalk_skills.config import load_config
from chalk_skills.fsutil import dump_json
from chalk_skills.hooks import adopt_codex, global_context, sync_hooks
from chalk_skills.lockfile import empty_lock, read_lock
from chalk_skills.sources import resolve_source
from chalk_skills.vendor import select_hooks

GLOBAL_CONFIG = ".config/chalk-skills/global.toml"
GLOBAL_LOCK = ".local/share/chalk-skills/global.lock.json"


def run_global(home: Path, adopt: list[str]) -> list[str]:
    config_path = home / GLOBAL_CONFIG
    config = load_config(config_path)
    sources = [resolve_source(spec, home) for spec in config.sources]
    selected = select_hooks(config, sources)
    lock_path = home / GLOBAL_LOCK
    old = read_lock(lock_path) or empty_lock()
    lines = [f"removed foreign Codex entry {entry}" for entry in adopt_codex(home, adopt)]
    hooks, hook_files = sync_hooks(
        global_context(home), selected, config.clis, old["hooks"], old["hook_files"]
    )
    lock = {
        "version": old["version"],
        "tool_version": __version__,
        "clis": [c for c in config.clis if c != "antigravity"],
        "sources": [
            {"url": s.spec.url, "ref": s.spec.ref, "commit": s.commit, "dirty": s.dirty}
            for s in sources
        ],
        "hooks": hooks,
        "hook_files": hook_files,
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if not lock_path.is_file() or lock_path.read_text(encoding="utf-8") != dump_json(lock):
        lock_path.write_text(dump_json(lock), encoding="utf-8")
    lines.append(f"wrote {len(hooks)} global hook(s)")
    return lines
