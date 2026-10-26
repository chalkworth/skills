# Chrome

Read when the change touches a prompt, a footer, or an in-place redraw. The shape to pick is in `SKILL.md`.

## Bordered

```
────────────────────────────────────────
waiting: review used its 3 attempts
  advice: 3 findings left
  recommended: fix
[a]pprove  [f]ix  [s]kip  [x] abort
────────────────────────────────────────
```

The rules are dim and run the measured width. The text between them is the program's own prompt: the question, any advice, and the keys.

## Block

Same text, on a full-width band tinted from the terminal's background. Draw it only when the background query in `references/waiting-and-colour.md` returned a colour. Otherwise draw bordered.

## Plain

```
waiting: review used its 3 attempts
  advice: 3 findings left
[a]pprove [f]ix [s]kip [x] abort >
```

One line for the keys, ending in `>`. No rules, no cursor motion, no escapes.

## Redraw

The first draw writes the block from top rule to bottom rule.

A later draw (advice arrives, the clock ticks, the terminal resizes) starts at the block's first line, clears the lines the block occupied, and writes the new block there. The old block does not remain below the new one.

After the first draw, the cursor returns to the block's first line. It does not open a new row for the same prompt.

When the new block is taller than the old one, clear the old height first, then write the new lines. When it is shorter, clear the leftover lines.

On a resize, measure the width again and rebuild the prompt and the status block. Clip each line to one column short of the width, with `…` at the end of a line that does not fit. The left side of the line is the action or the question, so it survives the clip.

Check the block at about 40 columns and at about 100. A line that wraps has failed.

After the person answers, erase the closing rule and leave the question and the answer in the scrollback. The next status block draws under that.
