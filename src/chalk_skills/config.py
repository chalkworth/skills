"""The target config (`.agents/skills.toml`) and the user config for global hooks."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from chalk_skills.errors import ChalkError

ALL_CLIS = ("claude", "codex", "cursor", "antigravity", "pi")
TOP_KEYS = {"mirror_claude", "public", "hooks", "clis", "source"}
SOURCE_KEYS = {"url", "ref", "packs", "skills"}


@dataclass(frozen=True)
class SourceSpec:
    url: str
    ref: str | None = None
    packs: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    sources: tuple[SourceSpec, ...] = ()
    mirror_claude: bool = False
    public: bool | None = None
    hooks: tuple[str, ...] = ()
    clis: tuple[str, ...] = ALL_CLIS
    path: Path | None = field(default=None, compare=False)


def _strings(table: dict, key: str, where: str) -> tuple[str, ...]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ChalkError(f"{where}: `{key}` must be a list of strings")
    return tuple(value)


def parse_config(text: str, where: str) -> Config:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ChalkError(f"{where}: invalid TOML: {error}") from error
    unknown = sorted(set(data) - TOP_KEYS)
    if unknown:
        raise ChalkError(f"{where}: unknown key(s) {', '.join(unknown)}")
    for key in ("mirror_claude", "public"):
        if key in data and not isinstance(data[key], bool):
            raise ChalkError(f"{where}: `{key}` must be true or false")
    clis = _strings(data, "clis", where) if "clis" in data else ALL_CLIS
    bad = [cli for cli in clis if cli not in ALL_CLIS]
    if bad:
        raise ChalkError(f"{where}: unknown cli {', '.join(bad)} (known: {', '.join(ALL_CLIS)})")
    sources = []
    raw_sources = data.get("source", [])
    if not isinstance(raw_sources, list):
        raise ChalkError(f"{where}: `source` must be an array of tables ([[source]])")
    for index, raw in enumerate(raw_sources, start=1):
        label = f"{where}: source #{index}"
        if not isinstance(raw, dict) or not isinstance(raw.get("url"), str) or not raw["url"]:
            raise ChalkError(f"{label}: `url` is required")
        extra = sorted(set(raw) - SOURCE_KEYS)
        if extra:
            raise ChalkError(f"{label}: unknown key(s) {', '.join(extra)}")
        ref = raw.get("ref")
        if ref is not None and not isinstance(ref, str):
            raise ChalkError(f"{label}: `ref` must be a string")
        sources.append(
            SourceSpec(
                url=raw["url"],
                ref=ref,
                packs=_strings(raw, "packs", label),
                skills=_strings(raw, "skills", label),
            )
        )
    return Config(
        sources=tuple(sources),
        mirror_claude=data.get("mirror_claude", False),
        public=data.get("public"),
        hooks=_strings(data, "hooks", where),
        clis=clis,
    )


def load_config(path: Path) -> Config:
    if not path.is_file():
        raise ChalkError(f"no target config at {path}")
    config = parse_config(path.read_text(encoding="utf-8"), str(path))
    return Config(**{**config.__dict__, "path": path})
