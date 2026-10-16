"""Find VERIFY and SELECT markers that an imported skill still carries unresolved.

An imported skill marks each version-bound claim with an HTML comment, which is invisible when
rendered and easy to grep:

    <!-- VERIFY(Simulator 6.1.0): the extension version is 1.4.0 -->
    <!-- SELECT(Simulator 6.1.0): asset root 6.1 | asset root 6.2 -->

Checking the claim turns the marker into its resolved form, which the lint accepts:

    <!-- VERIFIED(Simulator 6.1.0): the extension version is 1.4.0 => extension.toml says 1.4.0 -->
    <!-- SELECTED(Simulator 6.1.0): asset root 6.1 | asset root 6.2 => 6.1: the default ends in /6.1 -->

Markers inside fenced code blocks and inline code spans are examples, not claims, and are ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

RESOLUTION_SEPARATOR = "=>"
FENCE_PATTERN = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
INLINE_CODE_PATTERN = re.compile(r"`[^`]*`")
MARKER_START_PATTERN = re.compile(r"<!--\s*(VERIFY|SELECT|VERIFIED|SELECTED)\b")
MARKER_PATTERN = re.compile(
    r"<!--\s*(VERIFY|SELECT|VERIFIED|SELECTED)\(([^)]*)\)\s*:\s*(.*?)\s*-->"
)


class MarkerState(Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class MarkerFinding:
    path: Path
    line_number: int
    keyword: str
    source: str
    claim: str
    state: MarkerState
    problem: str

    def describe(self) -> str:
        location = f"{self.path}:{self.line_number}"
        if self.state is MarkerState.MALFORMED:
            return f"{location}: malformed marker: {self.problem}"
        return f"{location}: {self.keyword}({self.source}): {self.claim}"


def collect_markdown_files(targets: list[Path]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        if target.is_dir():
            files.extend(sorted(target.rglob("*.md")))
        else:
            files.append(target)
    return files


def classify_marker(keyword: str, body: str) -> tuple[MarkerState, str]:
    """The state of one well-formed marker and, if malformed, why."""
    if keyword not in ("VERIFIED", "SELECTED"):
        return MarkerState.OPEN, ""
    claim, separator, evidence = body.partition(RESOLUTION_SEPARATOR)
    if separator == "" or evidence.strip() == "" or claim.strip() == "":
        return MarkerState.MALFORMED, f"{keyword} needs '<claim> {RESOLUTION_SEPARATOR} <evidence>'"
    return MarkerState.RESOLVED, ""


def scan_text(path: Path, text: str) -> list[MarkerFinding]:
    findings: list[MarkerFinding] = []
    open_fence = ""  # the opening run of ` or ~ while inside a fenced block, else ""
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        fence_match = FENCE_PATTERN.match(raw_line)
        if open_fence != "":
            # CommonMark: only the same character, at least as long, with nothing after it, closes.
            if fence_match is not None and fence_match.group(2).strip() == "":
                closing_run = fence_match.group(1)
                if closing_run[0] == open_fence[0] and len(closing_run) >= len(open_fence):
                    open_fence = ""
            continue
        if fence_match is not None:
            open_fence = fence_match.group(1)
            continue
        line = INLINE_CODE_PATTERN.sub("", raw_line)
        starts = list(MARKER_START_PATTERN.finditer(line))
        parsed = list(MARKER_PATTERN.finditer(line))
        if len(parsed) != len(starts):
            findings.append(
                MarkerFinding(
                    path,
                    line_number,
                    "",
                    "",
                    raw_line.strip(),
                    MarkerState.MALFORMED,
                    "expected '<!-- KEYWORD(source): claim -->' on one line",
                )
            )
            continue
        for match in parsed:
            keyword, source, body = match.group(1), match.group(2).strip(), match.group(3)
            state, problem = classify_marker(keyword, body)
            if state is MarkerState.OPEN and (source == "" or body.strip() == ""):
                state, problem = MarkerState.MALFORMED, "a marker needs a source in () and a claim"
            findings.append(
                MarkerFinding(path, line_number, keyword, source, body.strip(), state, problem)
            )
    return findings


def scan_paths(targets: list[Path]) -> list[MarkerFinding]:
    findings: list[MarkerFinding] = []
    for markdown_file in collect_markdown_files(targets):
        findings.extend(scan_text(markdown_file, markdown_file.read_text(encoding="utf-8")))
    return findings


def unresolved(findings: list[MarkerFinding]) -> list[MarkerFinding]:
    return [finding for finding in findings if finding.state is not MarkerState.RESOLVED]
