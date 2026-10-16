from __future__ import annotations

import json
from pathlib import Path

from tests.tool.helpers import config_for, make_source, make_target, run, snapshot

CLAUDE_COMMAND = (
    'f="$CLAUDE_PROJECT_DIR/.agents/hooks/axi-session/axi_session_start.py"; '
    '[ -f "$f" ] || exit 0; exec python3 -I "$f" --format claude'
)


def codex_command(fmt: str) -> str:
    return (
        "sh -c 'r=$(git rev-parse --show-toplevel 2>/dev/null) && "
        'f="$r/.agents/hooks/axi-session/axi_session_start.py" && '
        f'[ -f "$f" ] && exec python3 -I "$f" --format {fmt}; exit 0\''
    )


GOLDEN = {
    ".claude/settings.json": {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": CLAUDE_COMMAND, "timeout": 20}]}
            ]
        }
    },
    ".codex/hooks.json": {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": codex_command("codex"),
                            "timeout": 20,
                            "additionalContextLimit": 16000,
                        }
                    ]
                }
            ]
        }
    },
    ".cursor/hooks.json": {
        "version": 1,
        "hooks": {"sessionStart": [{"command": codex_command("cursor")}]},
    },
    ".agents/hooks.json": {
        "axi-session": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3 -I .agents/hooks/axi-session/axi_session_start.py"
                            " --format antigravity",
                            "timeout": 20,
                        }
                    ]
                }
            ]
        }
    },
}


def setup(tmp_path, hooks='hooks = ["axi-session"]\n', extra=""):
    source = make_source(tmp_path / "source", {"p": ["alpha"]}, hooks=True)
    target = make_target(tmp_path / "target", config_for(source, ["p"], extra=hooks + extra))
    return source, target


def load(target: Path, rel: str):
    return json.loads((target / rel).read_text())


def test_golden_entries_into_empty_configs(tmp_path, capsys):
    _, target = setup(tmp_path)
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    for rel, expected in GOLDEN.items():
        assert load(target, rel) == expected, rel
        assert (target / rel).read_text().endswith("}\n")
    assert (target / ".agents/hooks/axi-session/axi_session_start.py").is_file()
    assert not (target / ".agents/hooks/axi-session/hook.toml").exists()
    assert run(capsys, "check", "--root", str(target))[0] == 0


def test_pi_extension_content(tmp_path, capsys):
    _, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    text = (target / ".pi/extensions/axi-session.ts").read_text()
    assert 'pi.on("before_agent_start"' in text
    assert '".agents",\n  "hooks",\n  "axi-session",\n  "axi_session_start.py",' in text
    assert 'spawnSync("python3", ["-I", SCRIPT, "--format", "plain"]' in text
    assert "timeout: 20000" in text
    assert 'customType: "axi-session"' in text
    assert "return undefined; // fail open" in text


def test_clis_option_limits_the_configs_written(tmp_path, capsys):
    _, target = setup(tmp_path, extra='clis = ["claude", "pi"]\n')
    run(capsys, "vendor", "--root", str(target))
    assert (target / ".claude/settings.json").is_file()
    assert (target / ".pi/extensions/axi-session.ts").is_file()
    assert not (target / ".codex").exists() and not (target / ".cursor").exists()
    assert not (target / ".agents/hooks.json").exists()


def seed_foreign(target: Path) -> dict[str, str]:
    foreign = {
        ".claude/settings.json": {
            "permissions": {"deny": ["Edit(./user/**)"]},
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
                "SessionStart": [{"hooks": [{"type": "command", "command": "echo mine"}]}],
            },
            "zzz": 1,
        },
        ".codex/hooks.json": {
            "hooks": {"PostToolUse": [{"matcher": "Edit", "hooks": [{"command": "x"}]}]}
        },
        ".cursor/hooks.json": {
            "version": 1,
            "hooks": {"sessionStart": [{"command": "echo cursor"}]},
        },
        ".agents/hooks.json": {"ruff-lint": {"PostToolUse": [{"hooks": []}]}},
    }
    for rel, data in foreign.items():
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(json.dumps(data, indent=2) + "\n")
    return {rel: (target / rel).read_text() for rel in foreign}


def test_merge_keeps_foreign_entries_and_key_order(tmp_path, capsys):
    _, target = setup(tmp_path)
    seed_foreign(target)
    run(capsys, "vendor", "--root", str(target))
    claude = load(target, ".claude/settings.json")
    assert list(claude) == ["permissions", "hooks", "zzz"]
    assert list(claude["hooks"]) == ["Stop", "SessionStart"]
    assert claude["permissions"] == {"deny": ["Edit(./user/**)"]}
    session = claude["hooks"]["SessionStart"]
    assert session[0] == {"hooks": [{"type": "command", "command": "echo mine"}]}
    assert session[1] == GOLDEN[".claude/settings.json"]["hooks"]["SessionStart"][0]
    assert load(target, ".codex/hooks.json")["hooks"]["PostToolUse"][0]["matcher"] == "Edit"
    cursor = load(target, ".cursor/hooks.json")["hooks"]["sessionStart"]
    assert cursor[0] == {"command": "echo cursor"} and len(cursor) == 2
    assert "ruff-lint" in load(target, ".agents/hooks.json")


def test_second_run_is_a_no_op(tmp_path, capsys):
    _, target = setup(tmp_path)
    seed_foreign(target)
    run(capsys, "vendor", "--root", str(target))
    first = snapshot(target)
    run(capsys, "vendor", "--root", str(target))
    run(capsys, "hooks", "--root", str(target))
    assert snapshot(target) == first


def test_removing_a_hook_removes_only_its_entries(tmp_path, capsys):
    source, target = setup(tmp_path)
    before = seed_foreign(target)
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/skills.toml").write_text(config_for(source, ["p"]))
    assert run(capsys, "vendor", "--root", str(target))[0] == 0
    for rel, text in before.items():
        assert json.loads((target / rel).read_text()) == json.loads(text), rel
    assert not (target / ".pi/extensions/axi-session.ts").exists()
    assert not (target / ".agents/hooks/axi-session").exists()
    assert run(capsys, "check", "--root", str(target))[0] == 0


def test_removing_a_hook_deletes_configs_it_created(tmp_path, capsys):
    source, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/skills.toml").write_text(config_for(source, ["p"]))
    run(capsys, "vendor", "--root", str(target))
    for rel in GOLDEN:
        assert not (target / rel).exists(), rel


def test_check_detects_a_hand_edited_entry(tmp_path, capsys):
    _, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    path = target / ".claude/settings.json"
    data = json.loads(path.read_text())
    data["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 5
    path.write_text(json.dumps(data, indent=2) + "\n")
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1 and ".claude/settings.json: entry of hook axi-session was edited" in out
    data["hooks"]["SessionStart"][0]["hooks"][0]["command"] = "changed"
    path.write_text(json.dumps(data, indent=2) + "\n")
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1 and "is missing or edited" in out
    run(capsys, "hooks", "--root", str(target))
    assert run(capsys, "check", "--root", str(target))[0] == 0
    # The edited command is now somebody else's entry and stays; ours is written again beside it.
    groups = load(target, ".claude/settings.json")["hooks"]["SessionStart"]
    assert groups[0]["hooks"][0]["command"] == "changed"
    assert groups[1] == GOLDEN[".claude/settings.json"]["hooks"]["SessionStart"][0]


def test_check_detects_a_changed_hook_script_and_pi_file(tmp_path, capsys):
    _, target = setup(tmp_path)
    run(capsys, "vendor", "--root", str(target))
    (target / ".agents/hooks/axi-session/axi_session_start.py").write_text("print('x')\n")
    (target / ".pi/extensions/axi-session.ts").write_text("// edited\n")
    code, out, _ = run(capsys, "check", "--root", str(target))
    assert code == 1
    assert ".agents/hooks/axi-session/axi_session_start.py: changed" in out
    assert ".pi/extensions/axi-session.ts: changed" in out


def test_unknown_hook_is_an_error(tmp_path, capsys):
    _, target = setup(tmp_path, hooks='hooks = ["nope"]\n')
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "no source defines hook nope" in err


def test_foreign_pi_extension_is_not_overwritten(tmp_path, capsys):
    _, target = setup(tmp_path)
    (target / ".pi/extensions").mkdir(parents=True)
    (target / ".pi/extensions/axi-session.ts").write_text("// mine\n")
    code, _, err = run(capsys, "vendor", "--root", str(target))
    assert code == 1 and "was not written by chalk-skills" in err


def test_global_hooks_write_user_level_configs(tmp_path, capsys, isolated_env):
    home = isolated_env
    source = make_source(tmp_path / "source", {"p": ["alpha"]}, hooks=True)
    config = home / ".config/chalk-skills/global.toml"
    config.parent.mkdir(parents=True)
    config.write_text(config_for(source, extra='hooks = ["axi-session"]\n'))
    script = home / ".local/share/chalk-skills/hooks/axi-session/axi_session_start.py"
    (home / ".codex").mkdir()
    (home / ".codex/hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "gh-axi"}]},
                        {"hooks": [{"type": "command", "command": "keep-me"}]},
                    ]
                }
            }
        )
    )
    code, out, _ = run(capsys, "hooks", "--global", "--adopt", "gh-axi", "--adopt", "absent")
    assert code == 0 and "removed foreign Codex entry SessionStart: gh-axi" in out
    assert script.is_file()
    codex = json.loads((home / ".codex/hooks.json").read_text())["hooks"]["SessionStart"]
    assert codex[0]["hooks"][0]["command"] == "keep-me"
    assert f'f="{script}"' in codex[1]["hooks"][0]["command"]
    claude = json.loads((home / ".claude/settings.json").read_text())
    assert claude["hooks"]["SessionStart"][0]["hooks"][0]["command"] == (
        f'f="{script}"; [ -f "$f" ] || exit 0; exec python3 -I "$f" --format claude'
    )
    assert (home / ".cursor/hooks.json").is_file()
    assert f'"{script}"' in (home / ".pi/agent/extensions/axi-session.ts").read_text()
    assert not (home / ".agents/hooks.json").exists()
    lock = json.loads((home / ".local/share/chalk-skills/global.lock.json").read_text())
    assert "antigravity" not in lock["hooks"]["axi-session"]["entries"]
    first = snapshot(home)
    run(capsys, "hooks", "--global")
    assert snapshot(home) == first
