# chalkworth/skills

Agent skills for coding-agent CLIs (Claude Code, Codex, Cursor, Pi, Antigravity, Copilot),
and `chalk-skills`, which copies the ones a repository asks for into it and keeps them pinned.

A repository lists what it wants in `.agents/skills.toml`:

```toml
[[source]]
url = "https://github.com/chalkworth/skills"
ref = "v0.1.0"
packs = ["experiments"]
skills = ["diagramming-in-markdown"]
```

```sh
uvx --from git+https://github.com/chalkworth/skills@v0.1.0 chalk-skills vendor
uvx --from git+https://github.com/chalkworth/skills@v0.1.0 chalk-skills check   # in CI
```

`vendor` writes the skills to `.agents/skills/`, which Codex, Pi, Antigravity and Copilot read,
and, with `mirror_claude = true`, a copy to `.claude/skills/` for Claude Code. It records every
file's hash in `.agents/skills.lock.json`. `check` fails when a vendored file was edited in
place or the lockfile is out of date.

## Commands

Every command takes `--root DIR` (default: the current directory) and runs as
`chalk-skills <command>` or `python -m chalk_skills <command>`.

- `vendor`: resolve each source, copy the selected skills and hook scripts, merge the hook
  entries into each CLI's config, and write the lockfile. A second run changes nothing. Skills
  that the old lockfile lists and the config no longer selects are removed. A folder the lockfile
  does not list is never touched, and a name that clashes with one is an error.
- `check`: offline. Exits 1 and lists every vendored file that is missing, changed or extra,
  every hook entry that was edited, and any difference between the config and the lockfile.
- `lint`: run in a source repository. Checks frontmatter, pack descriptions, duplicate names,
  portability (`${CLAUDE_...}`, namespaced skill references), unresolved `VERIFY` and `SELECT`
  markers, `UPSTREAM.json` and `LICENSE` pairs, and, for a public repository, the content
  denylist in `chalk_skills/lint.py`. It prints `path:line: message` and exits 1 on any problem.
- `hooks`: rewrite only the hook entries. `hooks --global` does the same for the user's own
  configs (see Hooks). `--adopt COMMAND`, repeatable, first removes a matching entry from
  `~/.codex/hooks.json`, for replacing a bare command with the managed one.
- `install --global PACK... --source DIR`: symlink the packs' skills into `~/.claude/skills`,
  `~/.agents/skills` and `~/.pi/agent/skills`. An existing folder is refused unless you pass
  `--replace`, which moves it to `~/.cache/chalk-skills/replaced/<timestamp>/`. `--uninstall`
  removes only links that point into the source.

## Target config

`.agents/skills.toml` in the repository that consumes skills:

| Key | Meaning |
| -- | -- |
| `mirror_claude` | Also write `.claude/skills/<name>`. Default `false`. |
| `public` | `true` or `false` overrides detecting whether this repository is public. |
| `hooks` | Hook ids to install from the sources that define them. |
| `clis` | Which CLIs get hook entries: `claude`, `codex`, `cursor`, `antigravity`, `pi`. Default all. |
| `[[source]]` | `url` (git URL, or a local path, absolute or relative to the root), `ref` (git ref; ignored for a local path), `packs`, `skills`. |

Selected skills are the packs plus the named skills. An unknown pack or skill, or one name
coming from two sources, is an error. A source's `skills.toml` says `visibility = "public"` or
`"private"` (private when missing). Vendoring a private source into a public repository is
refused. The target counts as public when `public = true`, or when `gh repo view` says so. If `gh`
is missing or fails, a private source is refused until you set `public = false`.

A source repository has `skills.toml` at the root, skills at `packs/<pack>/<skill>/SKILL.md`, and
hooks at `hooks/<id>/hook.toml` beside their script.

## Hooks

`hooks/axi-session/` registers the AXI session-start script for every CLI. `hook.toml` gives
the script, the command that runs it, and for each CLI the event, optional matcher, arguments,
timeout and extra keys. Vendoring copies the script to `.agents/hooks/<id>/` and writes:

- Claude Code: `.claude/settings.json`, command relative to `$CLAUDE_PROJECT_DIR`.
- Codex: `.codex/hooks.json`, command relative to the git root.
- Cursor: `.cursor/hooks.json`, same command form as Codex.
- Antigravity: `.agents/hooks.json`, in a group named after the hook.
- Pi: `.pi/extensions/<id>.ts`, generated from a template.

Entries are merged. The tool owns an entry when its command string is in the lockfile, and
leaves every other entry, key and the key order alone. Removing a hook from the config removes
its entries, and any containers or files the tool created. With `hooks --global`, the hook ids and
sources come from `~/.config/chalk-skills/global.toml` (same shape as the target config), the
scripts go to `~/.local/share/chalk-skills/hooks/`, the lock to
`~/.local/share/chalk-skills/global.lock.json`, and Antigravity is skipped.

## Packs

| Pack | Skills |
| -- | -- |
| `experiments` | designing-experiments, laying-out-experiment-designs, testing-ideas-with-simulation, checking-a-derivation |
| `docs` | diagramming-in-markdown |

## Licence

Apache-2.0. Skills adapted from other projects keep their own `LICENSE` and an `UPSTREAM.json`
naming the source.
