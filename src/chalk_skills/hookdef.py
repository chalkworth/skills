"""Read `hooks/<id>/hook.toml` from a source repository."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chalk_skills.config import ALL_CLIS
from chalk_skills.errors import ChalkError

HOOK_KEYS = {"description", "script", "runner", *ALL_CLIS}
CLI_KEYS = {"event", "matcher", "args", "timeout", "extra", "group"}


@dataclass(frozen=True)
class CliSpec:
    event: str
    matcher: str | None = None
    args: str = ""
    timeout: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    group: str | None = None  # Antigravity's named group; defaults to the hook id


@dataclass(frozen=True)
class HookDef:
    id: str
    folder: Path
    script: str
    runner: str
    description: str
    clis: dict[str, CliSpec]


def load_hook(folder: Path, hook_id: str) -> HookDef:
    where = f"hook {hook_id}"
    try:
        data = tomllib.loads((folder / "hook.toml").read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as error:
        raise ChalkError(f"{where}: hook.toml is invalid: {error}") from error
    unknown = sorted(set(data) - HOOK_KEYS)
    if unknown:
        raise ChalkError(f"{where}: unknown key(s) {', '.join(unknown)}")
    script = data.get("script")
    if not isinstance(script, str) or not (folder / script).is_file():
        raise ChalkError(f"{where}: `script` must name a file in the hook folder")
    runner = data.get("runner", "python3 -I" if script.endswith(".py") else "sh")
    clis: dict[str, CliSpec] = {}
    for cli in ALL_CLIS:
        table = data.get(cli)
        if table is None:
            continue
        extra_keys = sorted(set(table) - CLI_KEYS)
        if extra_keys or not isinstance(table.get("event"), str):
            raise ChalkError(
                f"{where}: [{cli}] needs `event`; unknown key(s): {extra_keys or 'none'}"
            )
        clis[cli] = CliSpec(
            event=table["event"],
            matcher=table.get("matcher"),
            args=table.get("args", ""),
            timeout=table.get("timeout"),
            extra=dict(table.get("extra", {})),
            group=table.get("group"),
        )
    return HookDef(hook_id, folder, script, runner, str(data.get("description", "")), clis)
