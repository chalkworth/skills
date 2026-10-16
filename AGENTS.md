# chalkworth/skills

Agent skills in packs, and `chalk-skills`, the tool that vendors them into a repository and
writes each coding-agent CLI's hook entries for them.

## Layout

- `packs/<pack>/<skill>/SKILL.md`: a skill belongs to the pack whose folder holds it.
  `skills.toml` describes the packs and says whether this repository is public.
- `hooks/<id>/hook.toml`: a hook command and how each CLI registers it.
- `src/chalk_skills/`: the tool. Standard library only.
- `tests/`: the tool's tests, and one folder per skill with scripts.

## Checks

```sh
uv sync
uv run pytest
uv run ruff check && uv run ruff format --check
uv run chalk-skills lint
```

## Rules for skills

- Portable: `name` and `description` frontmatter, paths relative to the skill's folder, plain
  skill names, no CLI-only interpolation such as `${CLAUDE_SKILL_DIR}`. `chalk-skills lint`
  checks this.
- An imported skill keeps its `LICENSE` and an `UPSTREAM.json` naming its source and commit.
- This repository is public: nothing from private work, hosts or paths. Private skills go in
  chalkworth/skills-private.
- Repositories that vendor a skill never edit their copy. Change it here, tag, and re-vendor.
