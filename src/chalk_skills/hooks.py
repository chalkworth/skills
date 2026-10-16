"""Write each CLI's hook entries for the selected hooks, merging into the configs already there.

An entry is owned by this tool when its command string is recorded in the lockfile. Every other
entry, key and the key order are left as they are. A second run changes nothing.
"""

from __future__ import annotations

import copy
import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chalk_skills.errors import ChalkError
from chalk_skills.fsutil import (
    copy_tree,
    read_json,
    remove_path,
    sha256_bytes,
    tree_hashes,
)
from chalk_skills.hookdef import CliSpec, HookDef

JSON_CLIS = ("claude", "codex", "cursor", "antigravity")
TEMPLATES: dict[str, dict[str, Any]] = {
    "claude": {},
    "codex": {},
    "cursor": {"version": 1},
    "antigravity": {},
}


@dataclass(frozen=True)
class HookContext:
    """Where hooks go: a project (paths relative to its root) or the user's home."""

    base: Path
    script_dir: str  # folder holding every hook's folder, relative to base
    is_global: bool
    config_files: dict[str, str]  # cli -> config file relative to base ("pi" is a folder template)
    pi_file: str  # extension path template relative to base, with {id}

    def hook_dir(self, hook_id: str) -> str:
        return f"{self.script_dir}/{hook_id}"

    def script_ref(self, hook: HookDef) -> str:
        return f"{self.hook_dir(hook.id)}/{hook.script}"


def project_context(root: Path) -> HookContext:
    return HookContext(
        base=root,
        script_dir=".agents/hooks",
        is_global=False,
        config_files={
            "claude": ".claude/settings.json",
            "codex": ".codex/hooks.json",
            "cursor": ".cursor/hooks.json",
            "antigravity": ".agents/hooks.json",
        },
        pi_file=".pi/extensions/{id}.ts",
    )


def global_context(home: Path) -> HookContext:
    return HookContext(
        base=home,
        script_dir=".local/share/chalk-skills/hooks",
        is_global=True,
        config_files={
            "claude": ".claude/settings.json",
            "codex": ".codex/hooks.json",
            "cursor": ".cursor/hooks.json",
        },  # Antigravity has no user-level hooks
        pi_file=".pi/agent/extensions/{id}.ts",
    )


# ---------------------------------------------------------------- command strings


def _args(spec: CliSpec) -> str:
    return f" {spec.args}" if spec.args else ""


def build_command(cli: str, hook: HookDef, spec: CliSpec, ctx: HookContext) -> str:
    rel = ctx.script_ref(hook)
    if ctx.is_global:
        target = str(ctx.base / rel)
        if "'" in target or '"' in target:
            raise ChalkError(f"cannot register a hook under a path with quotes: {target}")
    else:
        target = rel
    tail = f'exec {hook.runner} "$f"{_args(spec)}'
    if cli == "claude":
        folder = target if ctx.is_global else f"$CLAUDE_PROJECT_DIR/{target}"
        return f'f="{folder}"; [ -f "$f" ] || exit 0; {tail}'
    if cli in ("codex", "cursor"):
        if ctx.is_global:
            return f'sh -c \'f="{target}" && [ -f "$f" ] && {tail}; exit 0\''
        return (
            "sh -c 'r=$(git rev-parse --show-toplevel 2>/dev/null) && "
            f'f="$r/{target}" && [ -f "$f" ] && {tail}; exit 0\''
        )
    return f"{hook.runner} {target}{_args(spec)}"  # antigravity, project only


# ---------------------------------------------------------------- planned entries


@dataclass
class Planned:
    hook: str
    cli: str
    file: str  # relative to base
    path: tuple[str, ...]  # keys down to the list that holds the entry
    command: str
    item: dict[str, Any]
    grouped: bool  # item is {"matcher"?, "hooks": [entry]} rather than the entry itself


def plan_entry(cli: str, hook: HookDef, ctx: HookContext) -> Planned:
    spec = hook.clis[cli]
    command = build_command(cli, hook, spec, ctx)
    entry: dict[str, Any] = {"command": command}
    if cli != "cursor":
        entry = {"type": "command", **entry}
    if spec.timeout is not None:
        entry["timeout"] = spec.timeout
    entry.update(spec.extra)
    grouped = cli != "cursor"
    item: dict[str, Any] = entry
    if grouped:
        item = {"matcher": spec.matcher, "hooks": [entry]} if spec.matcher else {"hooks": [entry]}
    path = ("hooks", spec.event)
    if cli == "antigravity":
        path = (spec.group or hook.id, spec.event)
    return Planned(hook.id, cli, ctx.config_files[cli], path, command, item, grouped)


def inner(item: dict[str, Any], grouped: bool) -> dict[str, Any]:
    return item["hooks"][0] if grouped else item


def owned_hash(item: dict[str, Any], grouped: bool) -> str:
    """Hash of what this tool wrote: the entry, and its matcher when it sits in a group."""
    owned = {"entry": inner(item, grouped), "matcher": item.get("matcher") if grouped else None}
    return sha256_bytes(json.dumps(owned, sort_keys=True).encode())


def render_pi(hook: HookDef, spec: CliSpec, ctx: HookContext) -> str:
    runner = shlex.split(hook.runner)
    args = [*runner[1:], "SCRIPT", *shlex.split(spec.args)]
    rendered = ", ".join("SCRIPT" if a == "SCRIPT" else json.dumps(a) for a in args)
    if ctx.is_global:
        script_line = f"const SCRIPT = {json.dumps(str(ctx.base / ctx.script_ref(hook)))};\n"
        imports = 'import { spawnSync } from "node:child_process";\n'
    else:
        segments = ["..", "..", *ctx.script_ref(hook).split("/")]
        joined = ",\n  ".join(json.dumps(s) for s in segments)
        script_line = (
            f"const SCRIPT = join(\n  dirname(fileURLToPath(import.meta.url)),\n  {joined},\n);\n"
        )
        imports = (
            'import { spawnSync } from "node:child_process";\n'
            'import { dirname, join } from "node:path";\n'
            'import { fileURLToPath } from "node:url";\n'
        )
    timeout_ms = (spec.timeout or 20) * 1000
    description = hook.description or f"The {hook.id} hook"
    event = json.dumps(spec.event)
    return (
        f"// {description}\n"
        f"// Written by chalk-skills for the hook {hook.id}; change the hook, not this file.\n"
        f"// Pi has no hook that can add context, so this runs the script once, on the first\n"
        f"// {spec.event}, and adds its output as a message. Fails open: a missing script, an error\n"
        f"// or empty output adds nothing.\n\n"
        f"{imports}\n"
        f"{script_line}\n"
        "export default function (pi: any) {\n"
        "  let done = false;\n"
        f"  pi.on({event}, async (_event: any, ctx: any) => {{\n"
        "    if (done) return undefined;\n"
        "    done = true;\n"
        "    try {\n"
        f"      const out = spawnSync({json.dumps(runner[0])}, [{rendered}], {{\n"
        "        input: JSON.stringify({ cwd: ctx?.cwd ?? process.cwd() }),\n"
        '        encoding: "utf8",\n'
        f"        timeout: {timeout_ms},\n"
        "      });\n"
        '      const text = out.error || out.status !== 0 ? "" : String(out.stdout ?? "").trim();\n'
        "      if (!text) return undefined;\n"
        f"      return {{ message: {{ customType: {json.dumps(hook.id)}, content: text,"
        " display: false } };\n"
        "    } catch {\n"
        "      return undefined; // fail open\n"
        "    }\n"
        "  });\n"
        "}\n"
    )


# ---------------------------------------------------------------- merging into JSON configs


def _find(container: Any, command: str) -> tuple[int, dict[str, Any], dict[str, Any], bool] | None:
    """(index, item, entry, grouped) of the entry with this command in a list, if any."""
    if not isinstance(container, list):
        return None
    for index, item in enumerate(container):
        if not isinstance(item, dict):
            continue
        if item.get("command") == command:
            return index, item, item, False
        for entry in item.get("hooks", []) if isinstance(item.get("hooks"), list) else []:
            if isinstance(entry, dict) and entry.get("command") == command:
                return index, item, entry, True
    return None


def _walk(data: Any, path: tuple[str, ...]) -> Any:
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


@dataclass
class FileState:
    created: set[str] = field(default_factory=set)  # path prefixes this tool created; "" = the file


def _load(base: Path, rel: str, cli: str) -> tuple[dict[str, Any], bool]:
    path = base / rel
    if not path.is_file():
        return copy.deepcopy(TEMPLATES[cli]), True
    data = read_json(path)
    if not isinstance(data, dict):
        raise ChalkError(f"{path} must hold a JSON object")
    return data, False


def _prune(data: dict[str, Any], path: tuple[str, ...], created: set[str]) -> None:
    for depth in range(len(path), 0, -1):
        prefix = path[:depth]
        node = _walk(data, prefix)
        key = "/".join(prefix)
        if node is None or node or key not in created:
            continue
        parent = _walk(data, prefix[:-1]) if depth > 1 else data
        del parent[prefix[-1]]
        created.discard(key)


def apply_json_file(
    base: Path,
    rel: str,
    cli: str,
    old_records: list[dict[str, Any]],
    desired: list[Planned],
    old_created: list[str],
) -> tuple[list[str], dict[tuple[str, tuple[str, ...]], dict[str, Any]]]:
    """Merge the desired entries into one config file. Returns the created prefixes and, for each
    (command, path) written, the lock record."""
    data, file_created = _load(base, rel, cli)
    created = {""} if file_created else set(old_created)
    wanted = {(p.command, p.path) for p in desired}
    for record in old_records:
        path = tuple(record["path"])
        if (record["command"], path) in wanted:
            continue
        container = _walk(data, path)
        found = _find(container, record["command"])
        if found is None:
            continue
        index, item, entry, grouped = found
        if grouped:
            item["hooks"].remove(entry)
            if not item["hooks"]:
                container.pop(index)
        else:
            container.pop(index)
        _prune(data, path, created)
    records: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for plan in desired:
        node: Any = data
        for depth, key in enumerate(plan.path):
            last = depth == len(plan.path) - 1
            if key not in node:
                node[key] = [] if last else {}
                created.add("/".join(plan.path[: depth + 1]))
            node = node[key]
        if not isinstance(node, list):
            raise ChalkError(f"{base / rel}: {'/'.join(plan.path)} is not a list")
        found = _find(node, plan.command)
        item = copy.deepcopy(plan.item)
        if found is None:
            node.append(item)
        else:
            index, existing, _, grouped = found
            if grouped and len(existing["hooks"]) > 1:
                existing["hooks"][existing["hooks"].index(found[2])] = inner(item, True)
                item = existing
            else:
                node[index] = item
        records[(plan.command, plan.path)] = {
            "path": list(plan.path),
            "command": plan.command,
            "sha256": owned_hash(item, plan.grouped),
        }
    path = base / rel
    if data == TEMPLATES[cli] and "" in created:
        if path.is_file():
            path.unlink()
        return [], records
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return sorted(created), records


# ---------------------------------------------------------------- sync and verify


@dataclass(frozen=True)
class SelectedHook:
    hook: HookDef
    source: str
    commit: str | None


def _install_scripts(
    ctx: HookContext, selected: list[SelectedHook], old_hooks: dict[str, Any]
) -> None:
    base = ctx.base
    for hook_id in sorted(set(old_hooks) - {s.hook.id for s in selected}):
        remove_path(base / ctx.hook_dir(hook_id))
    for chosen in selected:
        folder = base / ctx.hook_dir(chosen.hook.id)
        if folder.exists() and chosen.hook.id not in old_hooks:
            raise ChalkError(f"repo-owned hook folder {folder} clashes with hook {chosen.hook.id}")
        remove_path(folder)
        _copy_hook(chosen.hook, folder)


def _sync_json(
    ctx: HookContext, plans: list[Planned], old_hooks: dict[str, Any], old_files: dict[str, Any]
) -> tuple[dict[str, Any], dict[tuple[str, str, tuple[str, ...]], dict[str, Any]]]:
    old_by_file: dict[str, list[dict[str, Any]]] = {}
    old_cli: dict[str, str] = {}
    for record in old_hooks.values():
        for cli, entry in record.get("entries", {}).items():
            if cli != "pi":
                old_by_file.setdefault(entry["file"], []).extend(entry["records"])
                old_cli[entry["file"]] = cli
    files: dict[str, Any] = {}
    produced: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for rel in sorted(set(old_by_file) | {p.file for p in plans}):
        desired = [p for p in plans if p.file == rel]
        cli = old_cli.get(rel) or desired[0].cli
        created, records = apply_json_file(
            ctx.base,
            rel,
            cli,
            old_by_file.get(rel, []),
            desired,
            old_files.get(rel, {}).get("created", []),
        )
        if created or records:
            files[rel] = {"created": created}
        for (command, path), record in records.items():
            produced[(rel, command, path)] = record
    return files, produced


def _sync_pi(
    ctx: HookContext, pi_files: dict[str, str], old_hooks: dict[str, Any]
) -> dict[str, str]:
    """Write the Pi extension files; returns each file's hash."""
    old_pi = {
        entry["file"]
        for record in old_hooks.values()
        for cli, entry in record.get("entries", {}).items()
        if cli == "pi"
    }
    for rel in sorted(old_pi - set(pi_files)):
        remove_path(ctx.base / rel)
    hashes: dict[str, str] = {}
    for rel, text in sorted(pi_files.items()):
        target = ctx.base / rel
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current is not None and rel not in old_pi and current != text:
            raise ChalkError(f"{target} exists and was not written by chalk-skills")
        if current != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        hashes[rel] = sha256_bytes(text.encode())
    return hashes


def sync_hooks(
    ctx: HookContext,
    selected: list[SelectedHook],
    clis: tuple[str, ...],
    old_hooks: dict[str, Any],
    old_files: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Install the hooks' scripts and entries, remove what the old lock owned and is now gone.

    Returns the lock's `hooks` and `hook_files` sections."""
    _install_scripts(ctx, selected, old_hooks)
    active = [c for c in clis if c in ctx.config_files or c == "pi"]
    plans: list[Planned] = []
    pi_texts: dict[str, str] = {}
    for chosen in selected:
        for cli in active:
            if cli == "pi" and cli in chosen.hook.clis:
                rel = ctx.pi_file.format(id=chosen.hook.id)
                pi_texts[rel] = render_pi(chosen.hook, chosen.hook.clis[cli], ctx)
            elif cli in chosen.hook.clis:
                plans.append(plan_entry(cli, chosen.hook, ctx))
    files, produced = _sync_json(ctx, plans, old_hooks, old_files)
    pi_hashes = _sync_pi(ctx, pi_texts, old_hooks)

    hooks: dict[str, Any] = {}
    for chosen in selected:
        entries: dict[str, Any] = {}
        for plan in (p for p in plans if p.hook == chosen.hook.id):
            entry = entries.setdefault(plan.cli, {"file": plan.file, "records": []})
            entry["records"].append(produced[(plan.file, plan.command, plan.path)])
        rel = ctx.pi_file.format(id=chosen.hook.id)
        if rel in pi_hashes:
            entries["pi"] = {"file": rel, "sha256": pi_hashes[rel]}
        hooks[chosen.hook.id] = {
            "source": chosen.source,
            "commit": chosen.commit,
            "files": tree_hashes(ctx.base / ctx.hook_dir(chosen.hook.id)),
            "entries": entries,
        }
    return hooks, files


def _copy_hook(hook: HookDef, dest: Path) -> None:
    copy_tree(hook.folder, dest)
    (dest / "hook.toml").unlink()


def verify_hooks(ctx: HookContext, lock_hooks: dict[str, Any]) -> list[str]:
    """Problems between the lock and what is on disk, for hooks and their config entries."""
    problems: list[str] = []
    base = ctx.base
    for hook_id, record in sorted(lock_hooks.items()):
        folder = base / ctx.hook_dir(hook_id)
        recorded = record["files"]
        actual = tree_hashes(folder) if folder.is_dir() else {}
        rel_folder = ctx.hook_dir(hook_id)
        for name in sorted(set(recorded) | set(actual)):
            if name not in actual:
                problems.append(f"{rel_folder}/{name}: missing")
            elif name not in recorded:
                problems.append(f"{rel_folder}/{name}: not in the lockfile")
            elif actual[name] != recorded[name]:
                problems.append(f"{rel_folder}/{name}: changed")
        for cli, entry in sorted(record["entries"].items()):
            path = base / entry["file"]
            if cli == "pi":
                if not path.is_file():
                    problems.append(f"{entry['file']}: missing")
                elif sha256_bytes(path.read_bytes()) != entry["sha256"]:
                    problems.append(f"{entry['file']}: changed")
                continue
            if not path.is_file():
                problems.append(f"{entry['file']}: missing (hook {hook_id}, {cli})")
                continue
            data = read_json(path)
            for rec in entry["records"]:
                found = _find(_walk(data, tuple(rec["path"])), rec["command"])
                if found is None:
                    problems.append(
                        f"{entry['file']}: entry of hook {hook_id} is missing or edited"
                    )
                    continue
                _, item, _, grouped = found
                if owned_hash(item, grouped) != rec["sha256"]:
                    problems.append(f"{entry['file']}: entry of hook {hook_id} was edited")
    return problems


def adopt_codex(home: Path, commands: list[str]) -> list[str]:
    """Delete foreign entries from the user's Codex hooks.json whose command matches. Returns what
    was removed, for printing."""
    path = home / ".codex" / "hooks.json"
    if not commands or not path.is_file():
        return []
    data = read_json(path)
    removed: list[str] = []
    events = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
    for event, items in list(events.items()):
        if not isinstance(items, list):
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                kept.append(item)
                continue
            if item.get("command") in commands:
                removed.append(f"{event}: {item['command']}")
                continue
            entries = item.get("hooks")
            if isinstance(entries, list):
                left = [
                    e for e in entries if not (isinstance(e, dict) and e.get("command") in commands)
                ]
                removed += [
                    f"{event}: {e['command']}"
                    for e in entries
                    if isinstance(e, dict) and e not in left
                ]
                if entries and not left:
                    continue
                item["hooks"] = left
            kept.append(item)
        if kept:
            events[event] = kept
        else:
            del events[event]
    if removed:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return removed
