---
name: designing-terminal-interfaces
description: Use when designing or changing a terminal view, such as a status pane, a prompt, progress, colour, or a layout in a fixed width, including inside a multiplexer pane (herdr, tmux). Scaffolding an OpenRouter agent project in TypeScript goes to create-agent-tui.
---

# Designing terminal interfaces

History scrolls. The prompt and the status block stay on screen and are redrawn in place.

Measure the width before drawing. Clip every chrome line so it cannot wrap. On a resize, rebuild the prompt and the status block at the new width.

## Prompt shape

Use one shape for every prompt in the view.

| Shape | When |
| -- | -- |
| `plain` | The output is a pipe, a log, or a mode that must not move the cursor. One line, a `>` prompt, no escape sequences. |
| `bordered` | The view shares the terminal with a multiplexer. Full-width `─` rules above and below the prompt. No background query. |
| `block` | This process owns the tty, and a background-colour query returns within 200ms. A full-width tinted band. If the query fails, draw `bordered`. |

A status pane inside herdr or tmux uses `bordered`. A pipe uses `plain`.

An answer that is a single key stays a single key. A note is one cooked line.

## Running work

The status block leads with the current action in bold. Lines that belong under it are branches, `├` for every line but the last and `└` for the last. Consecutive items of the same kind sit under one action. Timing, paths, and model names are dim.

Put a marker on each item when that item's own timing is what the reader needs. Use one summary line when the items are noise. Leave the list out when the status block already shows the same fact.

The status block may use up to half the height. Show as many branches as fit, and at least three when the height allows. End with `+N` for the rest.

## Waiting and colour

Advance a spinner or a trail of dots on the view's existing refresh. A view that already redraws once a second keeps that tick.

Bold marks the current action. Dim marks secondary text. Green, red, and yellow mark outcomes. A non-empty `NO_COLOR`, or `TERM=dumb`, prints no escapes. Fill a background only after a background query has succeeded.

A program launched for its own screen may print a banner on startup. A status pane skips the banner.

→ Changing a prompt, a footer, or an in-place redraw: read `references/chrome.md` (required).

→ Changing how running work or a log tail is shown: read `references/activity.md` (required).

→ Changing a spinner or colour: read `references/waiting-and-colour.md` (required).

Scaffolding an OpenRouter agent TUI in TypeScript is the `create-agent-tui` skill. Read it when the task is to generate that project.
