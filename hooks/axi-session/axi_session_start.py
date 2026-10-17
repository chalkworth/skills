#!/usr/bin/env python3
"""Session-start context for the AXI command-line tools (https://github.com/kunchenguid/axi).

A SessionStart hook for coding-agent CLIs (Claude Code, Codex, Cursor, Antigravity, Pi). Each one registers
it with its own `--format`, since their output contracts differ:

- gh-axi's live summary (open issues and PRs, its commands) is added only when the session's repo has a github.com
  remote. Elsewhere it would always say "0 open" and cost a GitHub round-trip.
- chrome-devtools-axi's and lavish-axi's summaries are added whenever the tool is installed, so agents know to use
  them.
- A repository can leave summaries out with `.agents/axi-session.toml` at its root: `skip = ["lavish-axi"]`. A
  skipped tool is not run.
- Once a day, installed AXI packages are compared with the npm registry, and the person is told when one is behind.
  Version skew has broken these tools before.

The hook always exits 0 and stays silent on any error, so it never interrupts work.

Usage:
    axi_session_start.py [--format claude|codex|cursor|antigravity|plain]
        SessionStart JSON on stdin (optional), the CLI's hook output on stdout. Default format: claude.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GITHUB_TOOL = "gh-axi"
SUMMARY_TOOLS: tuple[str, ...] = ("chrome-devtools-axi", "lavish-axi")  # summarised when installed
VERSION_CHECKED_PACKAGES: tuple[str, ...] = (GITHUB_TOOL, *SUMMARY_TOOLS, "quota-axi", "tasks-axi")
FORMATS: tuple[str, ...] = ("claude", "codex", "cursor", "antigravity", "plain")
GITHUB_HOST = "github.com"
REPO_CONFIG = Path(".agents") / "axi-session.toml"
TOOL_TIMEOUT_SECONDS = 8
REGISTRY_URL = "https://registry.npmjs.org/{package}/latest"
REGISTRY_TIMEOUT_SECONDS = 3
VERSION_CHECK_INTERVAL_SECONDS = 24 * 60 * 60
CACHE_PATH = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    / "chalk-skills"
    / "axi-latest-versions.json"
)


def run_tool(executable: str, working_directory: str) -> str:
    """The tool's no-argument output (its live summary), or '' if it fails or is slow."""
    try:
        completed = subprocess.run(
            [executable],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def has_github_remote(working_directory: str) -> bool:
    try:
        completed = subprocess.run(
            ["git", "remote", "-v"],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and GITHUB_HOST in completed.stdout


def skipped_tools(working_directory: str) -> set[str]:
    """The tools the repository's `.agents/axi-session.toml` lists under `skip`, or none."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if completed.returncode != 0:
        return set()
    try:
        with (Path(completed.stdout.strip()) / REPO_CONFIG).open("rb") as config:
            skip = tomllib.load(config).get("skip", [])
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    return {tool for tool in skip if isinstance(tool, str)} if isinstance(skip, list) else set()


def installed_version(package: str) -> str | None:
    """The version of a globally installed npm package, found through its executable's symlink."""
    executable = shutil.which(package)
    if executable is None:
        return None
    directory = Path(executable).resolve().parent
    while directory != directory.parent:
        manifest = directory / "package.json"
        if manifest.is_file():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if data.get("name") == package:
                return str(data.get("version", "")) or None
        directory = directory.parent
    return None


def fetch_latest_version(package: str) -> str | None:
    try:
        with urllib.request.urlopen(
            REGISTRY_URL.format(package=package), timeout=REGISTRY_TIMEOUT_SECONDS
        ) as response:
            return str(json.load(response).get("version", "")) or None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def latest_versions(packages: list[str], now: float) -> dict[str, str]:
    """Latest npm versions, from a cache refreshed at most once a day. Empty when there's nothing fresh to report."""
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    if now - float(cache.get("checked_at", 0)) < VERSION_CHECK_INTERVAL_SECONDS:
        return {}  # Checked today: the person was already told, if anything was behind.
    with ThreadPoolExecutor(max_workers=len(packages) or 1) as executor:
        fetched = dict(zip(packages, executor.map(fetch_latest_version, packages), strict=True))
    versions = {package: version for package, version in fetched.items() if version}
    if versions:
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            CACHE_PATH.write_text(
                json.dumps({"checked_at": now, "versions": versions}), encoding="utf-8"
            )
        except OSError:
            pass
    return versions


def version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.split("-")[0].split("."):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(0)
    return tuple(parts)


def outdated_packages(installed: dict[str, str], latest: dict[str, str]) -> list[str]:
    """'name installed → latest' for each installed package behind the registry."""
    outdated: list[str] = []
    for package, installed_version_text in installed.items():
        latest_version_text = latest.get(package)
        if latest_version_text and version_key(latest_version_text) > version_key(
            installed_version_text
        ):
            outdated.append(f"{package} {installed_version_text} → {latest_version_text}")
    return outdated


def gather(working_directory: str, now: float) -> tuple[list[str], list[str]]:
    """The tool summaries for the agent, in a fixed order, and the outdated packages for the person."""
    tools = [tool for tool in SUMMARY_TOOLS if shutil.which(tool)]
    if shutil.which(GITHUB_TOOL) and has_github_remote(working_directory):
        tools.insert(0, GITHUB_TOOL)
    skipped = skipped_tools(working_directory)
    tools = [tool for tool in tools if tool not in skipped]
    with ThreadPoolExecutor(max_workers=len(tools) or 1) as executor:
        summaries = list(executor.map(lambda tool: run_tool(tool, working_directory), tools))
    context_sections = [summary for summary in summaries if summary]

    installed: dict[str, str] = {}
    for package in VERSION_CHECKED_PACKAGES:
        version = installed_version(package)
        if version:
            installed[package] = version
    outdated: list[str] = []
    if installed:
        outdated = outdated_packages(installed, latest_versions(list(installed), now))
    return context_sections, outdated


def update_notice(outdated: list[str]) -> str:
    return (
        "AXI tools behind npm (version skew has broken them before): "
        + ", ".join(outdated)
        + ". Update with `npm i -g "
        + " ".join(f"{entry.split()[0]}@latest" for entry in outdated)
        + "`."
    )


def render(output_format: str, context_sections: list[str], outdated: list[str]) -> str:
    """The hook's stdout for one CLI: '' when there is nothing to say."""
    context = "\n\n".join(context_sections)
    notice = update_notice(outdated) if outdated else ""
    if output_format == "claude":
        output: dict = {}
        if context:
            output["hookSpecificOutput"] = {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        if notice:
            output["systemMessage"] = notice  # shown to the person, not the agent
        return json.dumps(output) if output else ""
    # The other CLIs have no channel to the person at session start, so the agent is asked to pass it on.
    if notice:
        context = "\n\n".join(part for part in (context, f"Tell the user: {notice}") if part)
    if not context:
        return ""
    if output_format == "cursor":
        return json.dumps({"additional_context": context})
    if output_format == "antigravity":
        return json.dumps({"injectSteps": [{"systemMessage": {"systemMessage": context}}]})
    return context  # codex adds plain stdout as developer context; pi's extension reads it as text


def working_directory_of(hook_input: dict) -> str:
    """The session's directory: `cwd` (Claude, Codex), the first workspace (Antigravity), else this process's."""
    workspaces = hook_input.get("workspacePaths")
    first_workspace = workspaces[0] if isinstance(workspaces, list) and workspaces else None
    return str(hook_input.get("cwd") or first_workspace or os.getcwd())


def main(argv: list[str]) -> None:
    output_format = "claude"
    if len(argv) == 2 and argv[0] == "--format" and argv[1] in FORMATS:
        output_format = argv[1]
    hook_input: dict = {}
    if not sys.stdin.isatty():
        try:
            loaded = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            loaded = {}
        hook_input = loaded if isinstance(loaded, dict) else {}
    try:
        text = render(output_format, *gather(working_directory_of(hook_input), time.time()))
    except Exception:  # noqa: BLE001 - a session-start hook must never interrupt work
        text = ""
    if text:
        print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
