# tinyagent TUI — Quick start

The tinyagent TUI is a reactive terminal UI built on `@opentui/core` that
talks to the tinyagent backend over HTTP + SSE. See
[TUI_ROADMAP.md](./TUI_ROADMAP.md) for the design philosophy and the
multi-month plan that produced it.

## Run

```bash
uv tool install --force --editable .
tinyagent
```

For source-level TUI development:

```bash
cd tui
bun install
bun src/main.ts --provider fake --workspace ../
```

Common flags:

- `--workspace .` — workspace root
- `--provider fake` — `fake | openai-compatible | openai-responses |
  openai-codex | open-responses | anthropic | gemini`
- `--model <name>`
- `--profile <name>`
- `--approval-mode never | on-request | yolo`
- `--server http://127.0.0.1:8080` — connect to an existing
  `tinyagent serve` backend instead of spawning one
- `tinyagent tui "echo hi"` — run a single task headless and exit from the
  Python launcher
- `--task "echo hi"` — direct `bun src/main.ts` equivalent

## Layout

```
╭─ ◆ tinyagent │ ws:... │ model:... │ ⎇ branch   ⠋ ⦗phase⦘ │ ctx ▰▱ 24% ╮
│                                                                            │
│  transcript (streaming turns, inline tools, no per-turn cards)             │
│                                                                            │
│  overlays (picker, approval, history, context menu) cover the transcript   │
│                                                                            │
│  ╭─ ask, plan, or /command ─────────────────────────────────────────────╮  │
│  │ composer  (multiline, history, mouse cursor)                         │  │
│  ╰──────────────────────────────────────────────────────────────────────╯  │
│    ⌜enter⌟ send  ⌜⇧enter⌟ newline  ⌜/⌟ commands  ⌜@⌟ files  ⌜$⌟ skills    │
╰────────────────────────────────────────────────────────────────────────────╯
```

## Keybindings

| Combo                  | Action                                |
|------------------------|---------------------------------------|
| `Enter`                | send the prompt                       |
| `Shift+Enter`          | newline                               |
| `Up` / `Down`          | history nav (in composer)             |
| `Ctrl+R`               | reverse history search                |
| `Ctrl+K` / `Ctrl+P`    | command palette                       |
| `Ctrl+B`               | open the sessions overlay             |
| `Ctrl+D`               | open `/diff`                          |
| `Ctrl+U`               | open `/usage`                         |
| `Ctrl+L`               | clear (visual)                        |
| `Ctrl+O`               | copy last reply                       |
| `Ctrl+C`               | interrupt active run / quit if idle   |
| `Alt+t`                | cycle theme                           |
| `Alt+r`                | toggle reasoning visibility           |
| `Alt+d`                | toggle debug overlay                  |
| `Tab` / `Shift+Tab`    | cycle focus across composer/transcript |
| `Escape`               | close overlay; deny/dismiss approval  |
| `A` / `D` (in modal)   | approve / deny the pending tool       |

Bindings live in `tui/src/ui/keymap.ts`. A `~/.config/tinyagent/tui.json`
override is honored on next startup (M1 default; full editor lands in M3).

## Mouse

- Click any panel to focus it.
- Click in the composer to position the cursor.
- Scroll wheel in the transcript to scroll.
- Drag in the transcript to select text; Ctrl+C copies the selection.

To disable mouse capture (useful with iTerm2's select-on-click), set
`TINYAGENT_TUI_MOUSE=off` and restart. The default mode keeps mouse
capture on.

## Slash commands

`/help` shows the catalog. Highlights:

- `/new`, `/resume`, `/sessions` — conversation lifecycle.
- `/plan`, `/build`, `/always-approve`, `/ask` — session/approval modes.
- `/approve`, `/deny` — resolve a pending approval.
- `/diff`, `/context`, `/usage`, `/model` — inspection panels.
- `/replay`, `/rewind <seq>`, `/fork <seq>`, `/review` — replay & recovery.
- `/eval <suite-path>`, `/skills [draft|show|install]`,
  `/update [check|apply|rollback]` — extension surfaces.
- `/extensions` — MCP / LSP / feature toggles from the backend.
- `/settings [set <key> <value> | save | reset]` — adjust theme,
  reasoning visibility, diff view, and mouse capture; persist to
  `tui.json`.
- `/headless`, `/acp` — show headless / ACP equivalents.
- `/theme`, `/reason`, `/palette`, `/debug` — UI toggles.
- `/rail` remains accepted for compatibility and opens the `/sessions`
  right-side overlay; the persistent split rail is disabled in the Paper shell.
- `/stop`, `/quit`.

## Inline mentions

The composer auto-detects three mention triggers as you type:

| Trigger | Source                              | Inserts                  |
|---------|-------------------------------------|--------------------------|
| `/`     | slash commands                       | `/command-id `           |
| `@`     | workspace files                      | `@path/to/file `         |
| `$`     | installed skills (`state.skills`)    | `$skill-name `           |

The mention overlay appears above the composer with a filtered list as
soon as a trigger is typed at start-of-input or after whitespace.
Arrow keys navigate the list, Enter inserts the selection, Esc dismisses.

## Animations

Overlay open/close (picker, approval modal, history search, context menu)
fade in/out via OpenTUI's `Timeline`. All animations degrade to no-ops in
headless mode and when the runtime can't construct a timeline.

## Themes

Built-in cycle: `paper-dark` (default), `paper-light`, `mono`.
Community themes such as `dracula` and `gruvbox` remain available by name.
Cycle with `Alt+t` or `/theme`. Custom themes load on startup from
`$XDG_CONFIG_HOME/tinyagent/themes/<name>.json` (defaults to
`~/.config/tinyagent/themes/`). Each theme file is a JSON object with
at minimum a `name`, `background`, `surface`, `border`, and `text`;
unset keys inherit from `tiny-dark`.

## Custom keybindings

Put a `tui.json` in `$XDG_CONFIG_HOME/tinyagent/`. Two forms are
accepted (merged in order):

```json
{
  "bindings": [
    { "context": "global", "combo": "Ctrl+J", "action": "open-palette" }
  ],
  "keymap": {
    "composer": { "Alt+Enter": "newline" }
  }
}
```

Valid contexts are `global`, `composer`, `transcript`, `palette`,
`modal`, `rail` (legacy alias). Valid actions live in `tui/src/ui/keymap.ts`.

## Persistent history

Composer history is written to
`$XDG_DATA_HOME/tinyagent/composer-history` (default
`~/.local/share/tinyagent/composer-history`) after every send, capped at
500 entries. `Ctrl+R` opens a reverse-incremental search overlay over
this history.

## Right-click menu

Right-click the transcript or composer to open a context menu with "Copy last
reply", "Copy conversation", and panel-specific actions ("Stop run").
Selections are written to the system
clipboard via `pbcopy` (macOS), `xclip` (Linux), or `clip` (Windows).

## Test surface

Unit tests live in `tui/tests/`. The plain-text projection produced by
`renderRootShell()` in `tui/src/components/RootShell.ts` is preserved
as the snapshot surface for tests — even though the real shell renders
through OpenTUI Renderables, that string projection is the easiest way
to assert what panels are visible and what content they include.

Run them with:

```bash
cd tui
bun test
```
