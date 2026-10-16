from __future__ import annotations

import os

from tests.tool.helpers import make_source, run

DIRS = (".claude/skills", ".agents/skills", ".pi/agent/skills")


def install(capsys, source, *args):
    return run(capsys, "install", "--global", *args, "--source", str(source))


def test_install_links_every_skill_into_the_three_folders(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha", "beta"], "docs": ["gamma"]})
    code, _, _ = install(capsys, source, "experiments")
    assert code == 0
    for rel in DIRS:
        for name in ("alpha", "beta"):
            link = isolated_env / rel / name
            assert link.is_symlink() and os.readlink(link) == str(
                source / "packs/experiments" / name
            )
        assert not (isolated_env / rel / "gamma").exists()


def test_install_is_idempotent(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha"]})
    install(capsys, source, "experiments")
    code, out, _ = install(capsys, source, "experiments")
    assert code == 0 and "already installed" in out


def test_existing_folder_is_refused_without_replace(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha"]})
    existing = isolated_env / ".claude/skills/alpha"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("mine")
    code, _, err = install(capsys, source, "experiments")
    assert code == 1 and "--replace" in err
    assert not (isolated_env / ".agents/skills/alpha").exists()  # nothing was changed
    assert (existing / "SKILL.md").read_text() == "mine"


def test_replace_moves_the_folder_aside(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha"]})
    existing = isolated_env / ".claude/skills/alpha"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("mine")
    code, out, _ = install(capsys, source, "experiments", "--replace")
    assert code == 0 and "moved" in out
    assert existing.is_symlink()
    moved = list((tmp_path / "cache/chalk-skills/replaced").glob("*/claude/alpha/SKILL.md"))
    assert [p.read_text() for p in moved] == ["mine"]


def test_uninstall_removes_only_links_into_the_source(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha", "beta"]})
    install(capsys, source, "experiments")
    other = tmp_path / "elsewhere"
    other.mkdir()
    (isolated_env / ".agents/skills/alpha").unlink()
    os.symlink(other, isolated_env / ".agents/skills/alpha")
    code, _, _ = install(capsys, source, "--uninstall")
    assert code == 0
    assert not (isolated_env / ".claude/skills/alpha").exists()
    assert not (isolated_env / ".pi/agent/skills/beta").exists()
    assert (isolated_env / ".agents/skills/alpha").is_symlink()  # points elsewhere: left alone


def test_unknown_pack_is_an_error(tmp_path, capsys, isolated_env):
    source = make_source(tmp_path / "source", {"experiments": ["alpha"]})
    code, _, err = install(capsys, source, "nope")
    assert code == 1 and "unknown pack nope" in err
