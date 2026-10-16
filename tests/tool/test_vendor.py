from __future__ import annotations

import json
import os
from pathlib import Path

from tests.tool.helpers import (
    commit_all,
    config_for,
    hide_gh,
    make_source,
    make_target,
    run,
    set_gh,
    snapshot,
    write_skill,
)

SOURCE_PACKS = {"experiments": ["alpha", "beta"], "docs": ["gamma"]}


def setup(tmp_path, extra="", packs=("experiments",), skills=(), visibility="public", **source_kw):
    source = make_source(tmp_path / "source", SOURCE_PACKS, visibility=visibility, **source_kw)
    target = make_target(tmp_path / "target", config_for(source, packs, skills, extra))
    return source, target


def lock_of(target: Path) -> dict:
    return json.loads((target / ".agents/skills.lock.json").read_text())


def test_vendor_then_check_ok(tmp_path, capsys):
    _, target = setup(tmp_path, skills=["gamma"])
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    assert sorted(p.name for p in (target / ".agents/skills").iterdir()) == [
        "alpha",
        "beta",
        "gamma",
    ]
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 0 and "OK" in out
    lock = lock_of(target)
    assert lock["skills"]["gamma"]["pack"] == "docs"
    assert "SKILL.md" in lock["skills"]["alpha"]["files"]


def test_local_edit_fails_check_and_revendor_restores(tmp_path, capsys):
    _, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    skill_md = target / ".agents/skills/alpha/SKILL.md"
    skill_md.write_text("edited\n")
    (target / ".agents/skills/alpha/extra.txt").write_text("x")
    (target / ".agents/skills/beta/SKILL.md").unlink()
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1
    assert ".agents/skills/alpha/SKILL.md: changed" in out
    assert ".agents/skills/alpha/extra.txt: extra file" in out
    assert ".agents/skills/beta/SKILL.md: missing" in out
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    assert run(capsys, "check", "--root", str(target))[0] == 0
    assert not (target / ".agents/skills/alpha/extra.txt").exists()


def test_second_vendor_changes_nothing(tmp_path, capsys):
    source, target = setup(tmp_path, extra="mirror_claude = true\n", skills=["gamma"])
    script = write_skill(source, "experiments", "alpha", {"scripts/run.sh": "echo hi\n"})
    (script / "scripts/run.sh").chmod(0o755)
    os.symlink("SKILL.md", script / "link.md")
    commit_all(source)
    run(capsys, "vendor", "--root", str(target))
    first = snapshot(target)
    assert first[".agents/skills/alpha/scripts/run.sh"][1] == 0o755
    assert first[".agents/skills/alpha/link.md"][0] == "-> SKILL.md"
    run(capsys, "vendor", "--root", str(target))
    assert snapshot(target) == first
    lock_text = (target / ".agents/skills.lock.json").read_text()
    assert (
        lock_text.endswith("}\n")
        and lock_text == json.dumps(json.loads(lock_text), indent=2, sort_keys=True) + "\n"
    )


def test_deselected_skill_is_pruned_but_repo_owned_stays(tmp_path, capsys):
    source, target = setup(tmp_path, extra="mirror_claude = true\n")
    (target / ".agents/skills/mine").mkdir(parents=True)
    (target / ".agents/skills/mine/SKILL.md").write_text("mine")
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/skills.toml").write_text(
        config_for(source, (), ["alpha"], "mirror_claude = true\n")
    )
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    for base in (".agents/skills", ".claude/skills"):
        assert not (target / base / "beta").exists()
        assert (target / base / "alpha/SKILL.md").exists()
    assert (target / ".agents/skills/mine/SKILL.md").read_text() == "mine"


def test_repo_owned_skill_clash_is_refused(tmp_path, capsys):
    _, target = setup(tmp_path)
    (target / ".agents/skills/alpha").mkdir(parents=True)
    (target / ".agents/skills/alpha/SKILL.md").write_text("mine")
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "repo-owned skill alpha clashes" in err
    assert (target / ".agents/skills/alpha/SKILL.md").read_text() == "mine"
    assert not (target / ".agents/skills.lock.json").exists()


def test_unknown_pack_and_skill_are_errors(tmp_path, capsys):
    source, target = setup(tmp_path, packs=("nope",))
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "unknown pack nope" in err
    (target / ".agents/skills.toml").write_text(config_for(source, (), ["missing"]))
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "unknown skill missing" in err


def test_same_skill_from_two_sources_is_an_error(tmp_path, capsys):
    one = make_source(tmp_path / "one", {"p": ["same"]})
    two = make_source(tmp_path / "two", {"q": ["same"]})
    target = make_target(tmp_path / "target", config_for(one, ["p"]) + config_for(two, ["q"]))
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "skill same comes from two sources" in err


def test_private_source_into_public_target_is_refused(tmp_path, capsys):
    _, target = setup(tmp_path, extra="public = true\n", visibility="private")
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "private" in err and "public repository" in err
    assert not (target / ".agents/skills").exists()


def test_private_source_into_private_target_is_allowed(tmp_path, capsys):
    _, target = setup(tmp_path, extra="public = false\n", visibility="private")
    assert run(capsys, "vendor", "--root", str(target))[0] == 0


def test_public_source_needs_no_visibility_answer(tmp_path, capsys):
    _, target = setup(tmp_path)
    assert run(capsys, "vendor", "--root", str(target))[0] == 0


def test_gh_unavailable_refuses_private_source_with_a_hint(tmp_path, capsys, monkeypatch):
    _, target = setup(tmp_path, visibility="private")
    hide_gh(tmp_path, monkeypatch)
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "public = false" in err


def test_gh_answers_decide_when_the_config_is_silent(tmp_path, capsys):
    _, target = setup(tmp_path, visibility="private")
    set_gh(tmp_path, "PUBLIC")
    assert run(capsys, "vendor", "--root", str(target))[0] == 1
    set_gh(tmp_path, "PRIVATE")
    assert run(capsys, "vendor", "--root", str(target))[0] == 0


def test_mirror_claude_writes_both_copies(tmp_path, capsys):
    _, target = setup(tmp_path, extra="mirror_claude = true\n")
    run(capsys, "vendor", "--root", str(target))
    assert snapshot(target / ".agents/skills") == snapshot(target / ".claude/skills")
    (target / ".claude/skills/alpha/SKILL.md").write_text("edited")
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1 and ".claude/skills/alpha/SKILL.md: changed" in out


def test_turning_mirror_off_removes_the_claude_copies(tmp_path, capsys):
    source, target = setup(tmp_path, extra="mirror_claude = true\n")
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/skills.toml").write_text(config_for(source, ["experiments"]))
    run(capsys, "vendor", "--root", str(target))
    assert not (target / ".claude/skills/alpha").exists()
    assert (target / ".agents/skills/alpha").exists()


def test_generated_manifest_names_do_not_clash(tmp_path, capsys):
    _, target = setup(tmp_path, extra="mirror_claude = true\n")
    claude = target / ".claude/skills"
    (claude / "alpha").mkdir(parents=True)
    (claude / "alpha/SKILL.md").write_text("generated by the repository's own sync")
    (claude / ".generated-from-agents.json").write_text(json.dumps({"skills": ["alpha"]}))
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    assert "Use when testing alpha" in (claude / "alpha/SKILL.md").read_text()


def test_unlisted_claude_folder_clashes_unless_identical(tmp_path, capsys):
    source, target = setup(tmp_path, extra="mirror_claude = true\n")
    claude = target / ".claude/skills"
    (claude / "alpha").mkdir(parents=True)
    (claude / "alpha/SKILL.md").write_text("mine")
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "repo-owned skill alpha clashes" in err
    (claude / "alpha/SKILL.md").write_text(
        (source / "packs/experiments/alpha/SKILL.md").read_text()
    )
    assert run(capsys, "vendor", "--root", str(target))[0] == 0


def test_config_change_without_revendor_fails_check(tmp_path, capsys):
    source, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/skills.toml").write_text(config_for(source, ["experiments", "docs"]))
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1 and "differs from the lockfile" in out and "run chalk-skills vendor" in out


def test_check_without_a_lockfile_fails(tmp_path, capsys):
    _, target = setup(tmp_path)
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1 and "skills.lock.json: missing" in out


def test_git_source_is_pinned_to_the_resolved_commit(tmp_path, capsys):
    source = make_source(tmp_path / "source", SOURCE_PACKS, tag="v0.1.0")
    first = Path(os.popen(f"git -C {source} rev-parse HEAD").read().strip())
    write_skill(source, "experiments", "alpha", {"new.txt": "later"})
    commit_all(source)
    target = make_target(
        tmp_path / "target",
        config_for(source, ["experiments"], ref="v0.1.0").replace(
            f'url = "{source}"', f'url = "file://{source}"'
        ),
    )
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    lock = lock_of(target)
    assert lock["sources"][0]["commit"] == str(first)
    assert lock["sources"][0]["dirty"] is False and lock["sources"][0]["ref"] == "v0.1.0"
    assert not (target / ".agents/skills/alpha/new.txt").exists()
    assert (tmp_path / "cache/chalk-skills/git").is_dir()
    assert run(capsys, "check", "--root", str(target))[0] == 0


def test_local_source_records_commit_and_dirty_flag(tmp_path, capsys):
    source, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    entry = lock_of(target)["sources"][0]
    assert len(entry["commit"]) == 40 and entry["dirty"] is False
    (source / "untracked.txt").write_text("x")
    run(capsys, "vendor", "--root", str(target))
    assert lock_of(target)["sources"][0]["dirty"] is True


def test_local_source_without_git_has_no_commit(tmp_path, capsys):
    _, target = setup(tmp_path, use_git=False)
    run(capsys, "vendor", "--root", str(target))
    assert lock_of(target)["sources"][0]["commit"] is None


def test_relative_local_source_path(tmp_path, capsys):
    make_source(tmp_path / "target" / "vendor-src", SOURCE_PACKS)
    target = make_target(tmp_path / "target", '[[source]]\nurl = "vendor-src"\npacks = ["docs"]\n')
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    assert (target / ".agents/skills/gamma/SKILL.md").exists()
