# Activity

Read when the change touches how running work or a log tail is shown. Colour and the spinner are in `references/waiting-and-colour.md`.

## Grouped

One bold action, then a branch per line under it. The last branch uses `└`. The others use `├`.

```
● review 3/6 · fixing 4 findings · 4m
  ├ fixer   deepseek-v4-flash   0m41s
  └ ===== 212 passed =====
```

A single line under the action still uses `└`.

Consecutive items of the same kind share the action. Two shell commands are one "ran" with two branches, not two headings.

Write any queued branches before the next history line, so they stay with the action they belong to.

## Other densities

| The reader needs | Show |
| -- | -- |
| Each item's own timing | A marker, the name, the argument, and the duration, one line per item |
| Only that work happened | One dim summary: `ran 2 shell commands, searched 1 pattern` |
| Nothing more than the status line | No list |

A fact the status block shows is not repeated as a history line. In a compact view the log tail is the last branch. In a detailed view the tail is history, and the status block does not print it again.

## Fitting

The status block may use half the height. Keep at least three branches when they fit. When more calls are open than fit, the last branch is `+N`.

Clip each branch at the width rule in `references/chrome.md`. At about 40 columns the model name may be the part that disappears. Keep the role (`fixer`) on the left.

Secondary text (the model, the clock, the path, the log tail) is dim. The action is bold. Outcome marks, when a branch has one, follow the colour rules in `SKILL.md`.
