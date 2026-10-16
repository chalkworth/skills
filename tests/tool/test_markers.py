"""The VERIFY/SELECT marker scan, ported from the checks in the repository it came from."""

from __future__ import annotations

import re
from pathlib import Path

from chalk_skills import markers

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "skill_markers"
    / "remote-simulator"
    / "SKILL.md"
)
RESOLVED = re.compile(r"<!-- (VERIFIED|SELECTED)\(([^)]*)\): (.*?) => .*? -->")


def status(*targets: Path) -> int:
    """0 when every marker under the targets is resolved, else 1."""
    return 1 if markers.unresolved(markers.scan_paths(list(targets))) else 0


def reopen(match: re.Match[str]) -> str:
    keyword = "VERIFY" if match.group(1) == "VERIFIED" else "SELECT"
    return f"<!-- {keyword}({match.group(2)}): {match.group(3)} -->"


def write_skill(directory: Path, text: str) -> Path:
    path = directory / "SKILL.md"
    path.write_text(text, encoding="utf-8")
    return path


def test_open_marker_reports_location_and_claim(tmp_path):
    path = write_skill(
        tmp_path, "intro\n\nThe port is 8226. <!-- VERIFY(Sim 6.1.0): port is 8226 -->\n"
    )
    findings = markers.unresolved(markers.scan_paths([tmp_path]))
    assert [f.describe() for f in findings] == [f"{path}:3: VERIFY(Sim 6.1.0): port is 8226"]


def test_select_marker_is_open_until_selected(tmp_path):
    write_skill(tmp_path, "<!-- SELECT(6.1.0): root 6.1 | root 6.2 -->\n")
    assert status(tmp_path) == 1
    write_skill(
        tmp_path, "<!-- SELECTED(6.1.0): root 6.1 | root 6.2 => 6.1: the default says so -->\n"
    )
    assert status(tmp_path) == 0


def test_resolved_marker_without_evidence_is_malformed(tmp_path):
    write_skill(
        tmp_path, "<!-- VERIFIED(6.1.0): port is 8226 -->\n<!-- VERIFIED(6.1.0): port => -->\n"
    )
    states = [f.state for f in markers.scan_paths([tmp_path])]
    assert states == [markers.MarkerState.MALFORMED] * 2


def test_unclosed_marker_is_malformed(tmp_path):
    write_skill(tmp_path, "<!-- VERIFY(6.1.0): port is 8226\n")
    assert status(tmp_path) == 1


def test_examples_in_code_are_ignored(tmp_path):
    text = "Write `<!-- VERIFY(src): claim -->` like this:\n\n```markdown\n<!-- VERIFY(src): claim -->\n```\n"
    write_skill(tmp_path, text)
    assert status(tmp_path) == 0


def test_directory_scan_covers_references(tmp_path):
    write_skill(tmp_path, "clean\n")
    (tmp_path / "references").mkdir()
    (tmp_path / "references" / "notes.md").write_text("<!-- VERIFY(src): claim -->\n")
    found = markers.unresolved(markers.scan_paths([tmp_path]))
    assert [f.path.name for f in found] == ["notes.md"]


def test_fixture_fails_until_every_claim_is_verified(tmp_path):
    verified = FIXTURE.read_text(encoding="utf-8")
    resolved = list(RESOLVED.finditer(verified))
    assert len(resolved) >= 5
    assert status(FIXTURE) == 0
    working = RESOLVED.sub(reopen, verified)
    assert len(markers.unresolved(markers.scan_text(Path("SKILL.md"), working))) == len(resolved)
    assert status(write_skill(tmp_path, working)) == 1
    for count, marker in enumerate(resolved, start=1):
        working = working.replace(reopen(marker), marker.group(0), 1)
        expected = 0 if count == len(resolved) else 1
        assert status(write_skill(tmp_path, working)) == expected
    assert working == verified


def test_fixture_refutes_the_newer_asset_root():
    text = FIXTURE.read_text(encoding="utf-8")
    assert "Assets/6.2 (upstream main text)" in text
    assert "so the 6.2 string is wrong on 6.1.0" in text


OPEN = "<!-- VERIFY(Sim 6.1.0): a claim -->"


def open_count(text: str) -> int:
    return len(markers.unresolved(markers.scan_text(Path("SKILL.md"), text)))


def test_tilde_fence_is_not_closed_by_a_backtick_line():
    assert open_count(f"~~~\n```\n{OPEN}\n~~~\n") == 0


def test_four_backtick_fence_wrapping_a_three_backtick_example():
    assert open_count(f"````markdown\n```\nexample\n```\n{OPEN}\n````\n") == 0


def test_longer_closing_fence_closes_and_marker_after_it_is_found():
    assert open_count(f"```\ninside\n`````\n{OPEN}\n") == 1


def test_shorter_or_other_character_fence_does_not_close():
    assert open_count(f"~~~~\n~~~\n{OPEN}\n~~~~\n") == 0
    assert open_count(f"```\n~~~\n{OPEN}\n```\n") == 0
