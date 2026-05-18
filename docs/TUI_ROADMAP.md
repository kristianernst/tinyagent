# tinyagent TUI — 5-Month State-of-the-Art Roadmap

Author: TUI working group · Status: in flight · Last updated: 2026-05-18

## North star

A terminal interface that feels native to the agent. Streaming markdown,
syntax-highlighted diffs, a real composer with a cursor, click-to-focus
panels, drag-to-resize splits, and a command palette — all running on the
existing `tinyagent` backend (`POST /v1/runs`, SSE `/v1/runs/:id/events`,
`/v1/workspaces/...`).

We benchmark against Grok Build, Codex CLI, OpenCode, and Claude Code:

| Capability                       | Grok Build | Codex CLI | OpenCode | Claude Code | tinyagent (today)        | tinyagent (after M5)   |
| -------------------------------- | ---------- | --------- | -------- | ----------- | ------------------------ | ---------------------- |
| Reactive widget tree             | yes        | yes       | yes      | yes         | no — stdout printf       | yes — `@opentui/core`  |
| Streaming markdown               | yes        | yes       | yes      | yes         | raw text                 | streaming md + ts-hl   |
| Split / unified diff             | yes        | yes       | yes      | yes         | plain text               | `DiffRenderable`       |
| Slash command palette            | yes        | yes       | yes      | yes         | static string list       | overlay, fuzzy, mouse  |
| Mouse cursor in composer         | yes        | yes       | yes      | partial     | none — `readline`        | full, kitty kbd        |
| Click-to-focus / drag-resize     | yes        | partial   | yes      | partial     | none                     | yes                    |
| Text selection + copy            | yes        | yes       | yes      | yes         | terminal-passthrough     | in-app + clipboard     |
| Plan-mode banner / nudges        | yes        | yes       | yes      | yes         | line of text             | first-class            |
| Approval modal with focus        | yes        | yes       | yes      | yes         | inline text              | overlay + buttons      |
| Theme system                     | yes        | yes       | yes      | yes         | name only                | tokens → widget props  |
| Headless / `--task` parity       | yes        | yes       | yes      | yes         | yes                      | yes (regression-tested)|
| Keymap config (`tui.json`)       | partial    | yes       | yes      | partial     | hardcoded                | context-aware JSON     |

## Architectural diagnosis (today)

The current TUI (`tui/src/`) sits on a powerful base (`@opentui/core` ≥ 0.1.107)
but barely uses it. `opentui.ts` opens a renderer with `useMouse: true`, then
the render loop simply writes a hand-assembled string via
`process.stdout.write(...)` and calls `requestRender()`. Components like
`Transcript.ts`, `Composer.ts`, `DiffViewer.ts` return strings; `frame()` in
`design/borders.ts` draws box-drawing characters by hand. `Composer` is twelve
lines: `> ${value}`. Input is `readline.question("> ")`. There is no mounted
widget tree, so:

* Mouse events are emitted by `@opentui/core` but never observed.
* `ScrollBoxRenderable`, `MarkdownRenderable`, `DiffRenderable`, `Input/Textarea`,
  `SelectRenderable`, `CodeRenderable`, `ASCIIFontRenderable`, `Slider`,
  `TabSelect`, `TextTable`, syntax-highlighting via tree-sitter — none of it
  is wired up.
* Theming is nominal: `theme.ts` exports `{ name, color, semantic, font }`
  but no widget reads it; everything is bare ANSI-free strings.
* `app.tsx` mixes spawn/connect, state bootstrap, run lifecycle, command
  dispatch, replay logic, eval/skills/update plumbing in a single 553-line
  module.
* `RootShell.ts` re-implements multi-panel layout by string-concatenating
  components, then padding each line manually inside `frame()`.

This is what the user means by "this mess." The refactor target is to keep
the reducer + protocol + backend client (which are fine) and rebuild the
view layer as a reactive Renderable tree.

## Design pillars

1. **Streaming-first** — the transcript is built around `MarkdownRenderable`
   with `streaming: true`; deltas are appended in place, the trailing block
   stays unstable until model completion.
2. **Mouse-class** — every interactive element accepts a `MouseEvent`:
   focus, scroll, drag-select, click-to-resolve.
3. **Keyboard-class** — Kitty keyboard protocol enabled when available;
   keybindings are JSON-loaded with contexts (`global`, `composer`,
   `transcript`, `palette`, `modal`).
4. **Composable** — every panel is a `Renderable` with a focused border,
   not a string. Panels dock left/right/full; the user can drag-resize.
5. **Reactive** — the store is the source of truth; components subscribe
   to projections via selectors, update in place, never re-mount.
6. **Themable** — tokens are RGBA, applied to widget props
   (`borderColor`, `focusedBorderColor`, `selectedBackgroundColor`).
7. **Resilient** — every panel handles `undefined`/empty state with a
   neutral placeholder; no panel ever throws on a partial run.
8. **Testable** — `renderRootShell()` continues to exist as a plain-text
   diagnostic projection for unit tests; `@opentui/core/testing` is used
   for snapshot tests of the widget tree.

## Months at a glance

* **Month 1** — Foundations: real Renderable tree, layout, keymap engine,
  app split.
* **Month 2** — Transcript: streaming markdown, composer with cursor,
  slash palette.
* **Month 3** — Panels: diff, tools, plan, approvals, sessions, replay.
* **Month 4** — Mouse, selection, focus, drag-resize.
* **Month 5** — Theming, perf, accessibility, tests, docs.

Each month ends with a green test run and a tagged build.

---

## Month 1 — Foundations

### Goals

Stand up a real reactive shell. After M1 the TUI should *look* the same to
the user, but the rendering path is OpenTUI Renderables, not stdout
printf. This is the swap that unblocks every other month.

### Work

* **M1.1 Renderer host** — replace `opentui.ts`'s string-printf with a
  proper renderer host. `createRenderer()` returns
  `{ root, refresh, dispose }` where `root` is the `RootRenderable`.
* **M1.2 Mount** — `mountApp(store, root)` builds the static layout tree
  (header, transcript scrollbox, rail, composer, status bar) and returns
  an unsubscribe.
* **M1.3 Store wiring** — components subscribe to selectors, not to the
  whole state. Selectors return memoizable shapes; the dispatcher decides
  what to re-bind.
* **M1.4 Layout primitives** — `tui/src/ui/layout.ts` provides
  `flexRow`, `flexCol`, `stack`, `gap()`, `divider()` helpers that wrap
  `BoxRenderable` / Yoga.
* **M1.5 Theme tokens** — `tui/src/ui/theme.ts` extends `design/tokens`
  into a `Theme` with `background`, `surface`, `border`, `borderFocus`,
  `text`, `mutedText`, `accent`, `success`, `warning`, `danger`,
  `selection`, plus per-tool colors. Widgets accept theme via props.
* **M1.6 Keymap engine** — `tui/src/ui/keymap.ts` defines `KeyContext`
  (`global | composer | transcript | palette | modal | scrollback`)
  and `KeyBinding[]` arrays per context. Loaded from
  `~/.config/tinyagent/tui.json` if present, else defaults.
* **M1.7 Kitty keyboard opt-in** — `useKittyKeyboard: { disambiguate:
  true, alternateKeys: true, events: false }`, with graceful fallback if
  the terminal rejects.
* **M1.8 App split** — `app.tsx` becomes a 50-line `bootstrap.ts`;
  business modules move to `controller/` (`runs.ts`, `replay.ts`,
  `commands.ts`, `update.ts`, `skills.ts`, `eval.ts`, `errors.ts`).
* **M1.9 `renderRootShell()` as snapshot path** — keep the plain-text
  function around as a state→text projection for unit tests, but stop
  using it as the production render.

### Acceptance

* `bun test` green (existing 30+ tests using `renderRootShell` keep
  passing).
* `bun src/main.ts --provider fake --task "echo"` runs end-to-end on
  the new shell.
* No `console.log` in render path; no manual `process.stdout.write` of
  framed content.
* `tui.json` discovery documented.

### Risks

* OpenTUI's split-footer screen mode interacts oddly with our existing
  `console.log` paths from spawn output. Mitigation: route spawn logs
  through a debug sink, not stdout.

---

## Month 2 — Transcript & Composer

### Goals

The two parts the user actually looks at all day.

### Work

* **M2.1 Transcript scrollbox** — `ScrollBoxRenderable` with
  `stickyScroll: true`, `stickyStart: "bottom"`, `viewportCulling: true`.
* **M2.2 Turn cards** — each turn is a `BoxRenderable` containing:
  * user prompt (`TextRenderable`, styled)
  * collapsible reasoning section (`SelectRenderable`-like toggle)
  * streaming assistant `MarkdownRenderable`
    (`streaming: true`, `syntaxStyle: theme.syntax`, `treeSitterClient`)
  * tool list (`ToolCard` row per call with status icon, label,
    truncated output preview, expand-on-focus)
  * status line (started/completed timestamps, duration, tokens)
* **M2.3 Composer** — `TextareaRenderable` with `minHeight: 1`,
  `maxHeight: 10`, history (Ctrl+R reverse-i-search, ↑/↓ recent),
  word-jump (Alt+←/→), kill/yank (Ctrl+K/Ctrl+U/Ctrl+Y), home/end,
  multiline (Shift+Enter), submit (Enter), interrupt (Ctrl+C).
* **M2.4 Slash palette overlay** — when first char is `/`, an overlay
  `BoxRenderable` (positioned above composer) shows matching commands.
  Fuzzy match by title and id. Enter executes. Esc dismisses. Mouse
  click selects.
* **M2.5 Auto-scroll discipline** — auto-scroll to bottom unless the
  user has scrolled up; show "↓ new" hint that jumps when clicked.
* **M2.6 ASCII splash** — show `ASCIIFontRenderable` "tinyagent" on
  empty transcript, with provider/model/profile sub-line.
* **M2.7 Spinner** — phase-bound spinner widget; "thinking" uses
  braille, "streaming" uses a moving caret, "approval" uses the
  alert glyph.
* **M2.8 Reasoning visibility** — internal reasoning visible only when
  `state.ui.showReasoning`; toggle with `/reason` and Ctrl+Alt+R.

### Acceptance

* Live `model.text.delta` events stream into the assistant markdown
  block without re-rendering the whole transcript.
* Composer cursor visible; Alt-arrows jump by word; history nav works.
* `/h` opens palette; arrow keys cycle; Enter selects.
* `bun src/main.ts --provider fake --task "hi"` finishes with a clean
  bottom-aligned transcript.

### Risks

* Streaming markdown reparse cost on every delta. Mitigation:
  `streaming: true` defers final-block parsing until completion; we
  also coalesce deltas at a 30 ms boundary.

---

## Month 3 — Panels

### Goals

Replace the rail-of-strings with real, focusable panels.

### Work

* **M3.1 Diff viewer** — `DiffRenderable` with `view: "unified" | "split"`
  toggle (Tab), `showLineNumbers: true`, `syntaxStyle` per filetype.
  Status line shows file count, additions/deletions, truncation.
* **M3.2 Tool timeline** — `SelectRenderable` of tool calls; split
  view shows args, output, duration, status; right-arrow expands;
  Enter opens the relevant file/diff.
* **M3.3 Plan board** — when `sessionMode === "plan"`, a structured
  list of plan steps with status, assignee, ETA (parsed from a plan
  event the backend already emits).
* **M3.4 Approval modal** — overlay `BoxRenderable` centered, with
  `[A]pprove`, `[D]eny`, `[V]iew args` buttons; mouse and keyboard;
  blocking until resolved; risk color binding.
* **M3.5 Session rail** — `SelectRenderable` of conversations with
  preview pane (turns count, last activity, last failure).
* **M3.6 Context graph** — `TextTableRenderable` of workspace files
  with size, git status, last touched.
* **M3.7 Usage** — three bars (input, output, cached) plus modelCalls
  histogram (ASCII).
* **M3.8 Replay cinema** — scrubber (`SliderRenderable`) over event
  seq; left pane is projected transcript; right pane is the raw event
  JSON; status line shows replay duration.
* **M3.9 Failure panel** — `SelectRenderable` of recovery actions,
  each tied to a runnable command; Enter executes.
* **M3.10 Eval lab** — `TextTableRenderable` of results with sort
  (Ctrl+S), filter (Ctrl+F), drill-down view.
* **M3.11 Skill forge** — `SelectRenderable` of drafts with preview;
  Enter installs.
* **M3.12 Update panel** — current/latest/channel, action buttons,
  rollback access.

### Acceptance

* Every panel reachable by slash command and visible in a split
  view (transcript left, panel right).
* Tab cycles focus across panels; Esc returns focus to composer.
* `bun test` green; new snapshot tests for each panel.

---

## Month 4 — Mouse, Selection, Focus

### Goals

Cursor and mouse parity with Grok Build / Cursor CLI.

### Work

* **M4.1 Renderer mouse plumbing** — register a top-level mouse handler
  that dispatches to the focus stack; `targetFps: 60`,
  `enableMouseMovement: true`.
* **M4.2 Focus stack** — `tui/src/ui/focus.ts` tracks the current
  focused renderable, draws the focused border color, and listens for
  Tab / Shift+Tab.
* **M4.3 Click-to-focus** — Box gets `onMouseDown` that focuses; the
  transcript scrollbox handles drag-to-select; the diff and code blocks
  do too.
* **M4.4 Selection + clipboard** — `Selection` driven by mouse drag,
  copied with Ctrl+C (when something is selected) or Cmd+C via
  Kitty keyboard. Falls back to OS terminal selection if mouse-capture
  is disabled (config flag).
* **M4.5 Scroll wheel** — wired through `ScrollBoxRenderable`'s
  acceleration; `Shift+Wheel` for horizontal in diffs.
* **M4.6 Drag-resize** — divider element between transcript and rail
  accepts drag; persists the ratio in store.
* **M4.7 Click composer to position cursor** — `TextareaRenderable`
  already supports this; just enable the mouse handler.
* **M4.8 Right-click menu** — small overlay with Copy, Copy as
  Markdown, Open in `$EDITOR`.
* **M4.9 Mouse-toggle config** — `tui.json: { mouseCapture: bool }`;
  default true, off mode preserves native terminal selection.

### Acceptance

* You can click into the composer at column 7 and start typing there.
* You can drag-select text in the transcript and Ctrl+C it.
* You can drag the divider to resize panels.
* Scroll wheel scrolls the transcript and persists position when new
  content arrives (auto-scroll suppressed).

### Risks

* Mouse-capture conflicts with iTerm2 select-on-click. Mitigation: the
  off mode + a sticky `/mouse off` toggle.

---

## Month 5 — Theming, Perf, Accessibility, Tests, Docs

### Goals

Make it look hand-crafted and never drop a frame.

### Work

* **M5.1 Themes** — `tiny-dark` (default), `tiny-light`,
  `solarized-dark`, `dracula`, `gruvbox`, `system` (reads
  `COLORFGBG`).
* **M5.2 User themes** — `~/.config/tinyagent/themes/<name>.json`,
  hot-reload via `/theme reload`.
* **M5.3 Perf** — coalesce reducer updates at 30 ms; reduce
  `requestRender()` to once per coalesced batch; profile via
  `gatherStats: true` and surface in `/debug`.
* **M5.4 Responsive breakpoints** — at width < 100 cols the rail
  collapses; at width < 70 the transcript runs full-width and panels
  open as overlays (`screenMode: "alternate-screen"` toggle).
* **M5.5 Accessibility** — `--no-mouse`, `--no-color`,
  `--reduce-motion` flags; ASCII fallback for spinners and icons.
* **M5.6 Tests** — keep `renderRootShell` snapshot tests; add
  Renderable snapshot tests using `@opentui/core/testing`; golden
  replay fixtures.
* **M5.7 Docs** — `docs/TUI.md` quick-start, `docs/TUI_KEYBINDINGS.md`,
  `docs/TUI_THEMES.md`, asciinema demo links.
* **M5.8 Examples** — `examples/tui_headless.sh` for scripting,
  `examples/tui_kiosk.md` for read-only review mode.

### Acceptance

* All five themes look intentional.
* 10 k-event fixture replays into the live transcript in < 250 ms
  with auto-scroll.
* `bun test` green; coverage on store and command dispatch unchanged.

---

## File layout (target)

```
tui/src/
  main.ts                 # entry, parseArgs
  bootstrap.ts            # spawn/connect, store, mount, dispose
  controller/
    runs.ts               # startRunTask, stop, abort wiring
    commands.ts           # parse + dispatch
    replay.ts             # load/rewind/fork
    eval.ts
    skills.ts
    update.ts
    errors.ts
  state/
    reducer.ts            # unchanged behavior
    store.ts
    selectors.ts
    fixtures.ts
  protocol/
    events.ts
    schema.ts
  backend/
    client.ts
    connect.ts
    spawn.ts
    sse.ts
  ui/
    renderer.ts           # createRenderer({ root, refresh })
    mount.ts              # mountApp(store, root, controllers)
    layout.ts             # flexRow/Col, divider, gap
    theme.ts              # Theme type, themes, applyTheme()
    focus.ts              # focus stack, click-to-focus
    keymap.ts             # contexts, default bindings
    keyboard.ts           # Kitty opt-in
    mouse.ts              # mouse dispatch
    overlays.ts           # palette/modal/menu primitives
    widgets/
      Transcript.tsx
      TurnCard.tsx
      Composer.tsx
      Palette.tsx
      StatusBar.tsx
      Splash.tsx
      Spinner.tsx
      Diff.tsx
      ToolTimeline.tsx
      PlanBoard.tsx
      ApprovalModal.tsx
      SessionRail.tsx
      ContextGraph.tsx
      Usage.tsx
      Replay.tsx
      Failure.tsx
      EvalLab.tsx
      SkillForge.tsx
      Update.tsx
      HeadlessHint.tsx
      AcpHint.tsx
      Debug.tsx
  legacy/
    renderRootShell.ts    # plain-text projection kept for tests
```

## Telemetry & success criteria

* **TTI** — first paint < 80 ms on `bun src/main.ts --provider fake`.
* **Tick budget** — store→render coalesced to < 16 ms (60 fps).
* **Replay throughput** — ≥ 50 k events / s in `replayForPerf`.
* **Memory** — < 80 MB resident for a 50-turn session.

## Out of scope (deliberately)

* Multi-process TUI (we keep the spawn-or-connect model).
* GPU / image rendering (`@opentui/core` 3d module).
* Native Zig integration changes.
* Backend protocol changes — the surface is fixed by `surface-event-contract.md`.

## Open questions

* Should we own a built-in tree-sitter loader, or rely on the system
  WASM? (M2 decision)
* Should panel state be persisted across runs in `tui.state.json`? (M4)
* Do we want a separate "review" alt-screen for `/diff` and `/replay`?
  (M4 decision; probably yes for diffs > 200 lines.)
