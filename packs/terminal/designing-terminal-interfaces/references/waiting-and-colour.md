# Waiting and colour

Read when the change touches a spinner or colour. The prompt shapes are in `references/chrome.md`.

## Waiting

The view already redraws on a tick (once a second is typical). Advance one frame of the waiting mark on that tick.

A braille spinner uses `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏`, one glyph per tick, dim, to the left of the action. Trailing dots (`·`, `··`, `···`) sit at the end of the action text and suit a quieter pane.

A shimmer that recolours the letters needs a timer around 150ms and 256 colours. A status pane does not use one.

`NO_COLOR` non-empty, or `TERM=dumb`, skips the glyph. The action text stays.

## Colour

Use the 16-colour set.

| Role | SGR |
| -- | -- |
| Current action | bold (`1`) |
| Timing, paths, model names, rules | dim (`2`) |
| Passed | green (`32`) |
| Failed | red (`31`) |
| Waiting, or a fallback | yellow (`33`) |

Turn colour off when `NO_COLOR` is non-empty or `TERM` is `dumb`. Off a terminal, print no escapes at all.

## Background query

Only the `block` prompt sends it, and only when stdin is a tty.

Send OSC 11 (`ESC ] 11 ; ? BEL`) and wait at most 200ms for a reply of the form `ESC ] 11 ; rgb:RR/GG/BB`. From that colour, tint toward white on a dark background and toward black on a light one, lightly enough that body text still reads. Prefer a 24-bit background when `COLORTERM` contains `truecolor` or `24bit`. Otherwise approximate with the 256-colour cube.

No reply, or stdin is not a tty: draw the bordered prompt. Do not send the query from a pipe, and do not send it for a bordered or plain prompt.
