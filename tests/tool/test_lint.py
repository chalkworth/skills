from __future__ import annotations

import json
from pathlib import Path

import pytest

from chalk_skills import lint as lint_module
from tests.tool.helpers import commit_all, make_source, run, write_skill


def clean(tmp_path, visibility="public") -> Path:
    return make_source(
        tmp_path / "src", {"experiments": ["alpha", "beta"], "docs": ["gamma"]}, visibility
    )


def problems(capsys, root) -> tuple[int, list[str]]:
    code, out, _ = run(capsys, "lint", "--root", str(root))
    return code, out.splitlines()


def test_clean_repository_passes(tmp_path, capsys):
    assert problems(capsys, clean(tmp_path)) == (0, [])


def test_name_must_equal_folder_and_description_must_exist(tmp_path, capsys):
    root = clean(tmp_path)
    (root / "packs/docs/gamma/SKILL.md").write_text("---\nname: other\ndescription: x\n---\n")
    (root / "packs/experiments/beta/SKILL.md").write_text("---\nname: beta\n---\n")
    code, lines = problems(capsys, root)
    assert code == 1
    assert any(
        l.startswith("packs/docs/gamma/SKILL.md:1:") and "must equal folder" in l for l in lines
    )
    assert any(
        l.startswith("packs/experiments/beta/SKILL.md:1:") and "description" in l for l in lines
    )


def test_block_scalar_descriptions_count(tmp_path, capsys):
    root = clean(tmp_path)
    (root / "packs/docs/gamma/SKILL.md").write_text(
        "---\nname: gamma\ndescription: >\n  Use when\n  testing.\n---\n"
    )
    assert problems(capsys, root) == (0, [])


def test_missing_frontmatter_is_reported(tmp_path, capsys):
    root = clean(tmp_path)
    (root / "packs/docs/gamma/SKILL.md").write_text("# no frontmatter\n")
    assert "no frontmatter" in problems(capsys, root)[1][0]


def test_duplicate_skill_names_across_packs(tmp_path, capsys):
    root = clean(tmp_path)
    write_skill(root, "docs", "alpha")
    code, lines = problems(capsys, root)
    assert code == 1 and any("skill name also used at" in l for l in lines)


def test_packs_and_manifest_must_agree(tmp_path, capsys):
    root = clean(tmp_path)
    write_skill(root, "extra", "delta")
    manifest = root / "skills.toml"
    manifest.write_text(manifest.read_text() + '\n[packs.ghost]\ndescription = "none"\n')
    lines = problems(capsys, root)[1]
    assert "packs/extra:0: pack is not described in skills.toml" in lines
    assert "skills.toml:0: pack ghost has no folder under packs/" in lines


@pytest.mark.parametrize(
    ("text", "needle"),
    [
        ("Use ${CLAUDE_SKILL_DIR}/x\n", "${CLAUDE_"),
        ("Run my-plugin:gamma first\n", "namespaced skill reference"),
        ("Run `other-skills:gamma` first\n", "namespaced skill reference"),
        ("A claim <!-- VERIFY(src 1.0): it holds -->\n", "unresolved VERIFY(src 1.0)"),
        ("A claim <!-- VERIFIED(src 1.0): it holds -->\n", "VERIFIED needs"),
    ],
)
def test_portability_and_marker_rules(tmp_path, capsys, text, needle):
    root = clean(tmp_path)
    (root / "packs/docs/gamma/notes.md").write_text("fine\n" + text)
    code, lines = problems(capsys, root)
    assert code == 1
    assert any(l.startswith("packs/docs/gamma/notes.md:2:") and needle in l for l in lines), lines


def test_claude_variable_is_caught_in_scripts_too(tmp_path, capsys):
    root = clean(tmp_path)
    (root / "packs/docs/gamma/run.sh").write_text("echo ${CLAUDE_PLUGIN_ROOT}\n")
    assert any("run.sh:1:" in l for l in problems(capsys, root)[1])


def test_upstream_and_license_go_together(tmp_path, capsys):
    root = clean(tmp_path)
    gamma = root / "packs/docs/gamma"
    (gamma / "UPSTREAM.json").write_text(json.dumps({"repository": "https://example.com/x"}))
    assert any("UPSTREAM.json without a LICENSE" in l for l in problems(capsys, root)[1])
    (gamma / "LICENSE").write_text("MIT")
    assert problems(capsys, root) == (0, [])
    (gamma / "UPSTREAM.json").unlink()
    assert any("LICENSE without an UPSTREAM.json" in l for l in problems(capsys, root)[1])


def test_upstream_must_be_valid_json_naming_a_source(tmp_path, capsys):
    root = clean(tmp_path)
    gamma = root / "packs/docs/gamma"
    (gamma / "LICENSE").write_text("MIT")
    (gamma / "UPSTREAM.json").write_text("{not json")
    assert any("invalid JSON" in l for l in problems(capsys, root)[1])
    (gamma / "UPSTREAM.json").write_text(json.dumps({"commit": "abc"}))
    assert any("needs a key naming the source" in l for l in problems(capsys, root)[1])
    (gamma / "UPSTREAM.json").write_text(json.dumps({"source": "x"}))
    assert problems(capsys, root) == (0, [])


@pytest.mark.parametrize("term", ["/home/someone", "/Users/someone", "C:/Users/someone"])
def test_denylist_applies_to_public_repositories(tmp_path, capsys, term):
    root = clean(tmp_path)
    (root / "README.md").write_text(f"line one\nmentions {term} here\n")
    commit_all(root)
    code, lines = problems(capsys, root)
    assert code == 1
    assert any(l.startswith("README.md:2: denylisted content") for l in lines), lines


def test_denylist_is_off_for_private_and_exempt_for_its_own_fixtures(tmp_path, capsys):
    private = clean(tmp_path, visibility="private")
    (private / "README.md").write_text("/home/someone\n")
    assert problems(capsys, private) == (0, [])
    public = make_source(tmp_path / "pub", {"p": ["a"]})
    fixture = public / "tests" / "fixtures" / "lint"
    fixture.mkdir(parents=True)
    (fixture / "bad.txt").write_text("/home/someone\n")
    assert problems(capsys, public) == (0, [])


def test_namespaced_check_ignores_urls_and_unknown_names(tmp_path, capsys):
    root = clean(tmp_path)
    notes = root / "packs/docs/gamma/notes.md"
    notes.write_text("See https://example.com/gamma and note:something and a ratio 1:2.\n")
    assert problems(capsys, root) == (0, [])


def test_denylist_is_a_module_constant():
    assert isinstance(lint_module.DENYLIST, tuple) and all(
        isinstance(p, str) for p in lint_module.DENYLIST
    )


def test_public_repository_may_not_use_a_private_source(tmp_path, capsys):
    root = clean(tmp_path)
    make_source(tmp_path / "priv", {"p": ["x"]}, visibility="private")
    (root / ".agents").mkdir()
    (root / ".agents/skills.toml").write_text('[[source]]\nurl = "../priv"\n')
    code, lines = problems(capsys, root)
    assert code == 1 and any("uses private source ../priv" in l for l in lines)


def test_same_author_provenance_needs_no_license(tmp_path, capsys):
    root = clean(tmp_path)
    gamma = root / "packs/docs/gamma"
    upstream = {"source": "example/own-repo", "same_author": True}
    (gamma / "UPSTREAM.json").write_text(json.dumps(upstream))
    assert problems(capsys, root) == (0, [])
