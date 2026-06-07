# tinyagent TUI — Design Token System (Paper Design)

> Status: proposal · scope: full token system + how it lands on the
> surfaces we want to redesign (transcript, composer, `/ @ $` menus,
> rail, status, streaming, approval). No code yet — this is the
> reference we draw from when we start cutting widgets.

---

## 0. North star

We have studied Codex CLI, Cursor's terminal chat, and the Grok Build
TUI. The shared feel we want:

1. **One column, top-to-bottom flow.** No persistent vertical pane
   split. The conversation is the page. Side surfaces (sessions, diff,
   usage…) are overlays that *cover* the conversation, not split it.
2. **Paper-grade quiet.** A near-flat surface, one accent, generous
   negative space. Color is reserved for *meaning*, never decoration.
3. **Smooth state.** Phase changes (idle → thinking → streaming →
   done) are visible but never jumpy. No layout reflow on each token.
4. **Mouse-first, keyboard-fluent.** Every glyph that can be clicked
   *looks* clickable. Every action has a key. Both arrive at the same
   intent.
5. **No mascot, no logo wall.** The wordmark is a single line of text
   in the header. The ASCII art goes away.

The token system below exists to enforce those five rules across
every widget.

---

## 1. Layer model

Three layers, in this order. Higher layers may only reference the
layer directly below them.

```
┌─ component tokens ─────────────────────────────┐  what a widget consumes
│   composer.border, transcript.user.prefix,    │
│   palette.row.hover.bg, status.pill.danger.bg │
└─ semantic tokens ──────────────────────────────┘  intent
│   surface.canvas, text.primary, accent.fg,    │
│   status.success.fg, role.assistant.fg        │
└─ primitives ───────────────────────────────────┘  raw values
    neutral.50…950, brand.500, motion.tick.4,
    glyph.bullet, space.2, border.soft
```

Widgets never read primitives directly. Themes only override
semantic tokens. The component layer is generated mechanically from
semantic tokens — it exists so we can name *roles* in code
(`composer.border`) instead of leaking semantics (`border.subtle`)
into every widget file.

---

## 2. Primitives

### 2.1 Color ramps

Neutrals are the spine. Two ramps — one warm-cool dark, one
paperlight — share index positions so themes swap cleanly.

```
neutral.dark            neutral.light            chroma reference
  50  #f3f6fa             50  #ffffff             these are NOT in
  100 #e6edf3             100 #f7f8fa             the default UI;
  200 #c9d1d9             200 #eaecef             reserved for code
  300 #8b949e             300 #a8b1bd             highlight + diff
  400 #6e7681             400 #6e7681
  500 #4a5260             500 #4a5260
  600 #2e3540             600 #353a44
  700 #22303a             700 #d0d7de
  800 #161c23             800 #eaecef
  850 #11161c             850 #f3f5f8
  900 #0b0f14             900 #fafbfc
  950 #07090d             950 #ffffff
```

Rule: in any theme, **only six neutrals appear on the canvas at one
time** (canvas, raised, sunken, border-subtle, border-strong, text).
More than six and the surface starts to feel busy.

Chromatic palette — minimal, semantic only:

```
brand     #58a6ff   the single accent. used for focus + agent identity.
success   #2ea043   tool ✓, additions, "complete"
warning   #e3b341   approval required, plan-mode, "blocked"
danger    #f85149   errors, removals, "failed"
info      #56d6a4   reading/searching (cool), neutral-positive
reason    #a371f7   reasoning blocks only — never UI chrome
```

Six accents, no more. Pink/orange disappear from the default theme.
Tool calls go cool-neutral (info / muted) until they resolve to
success or danger — this is the single biggest visual quieting.

### 2.2 Spacing

Terminals are character grids. We pick a one-cell unit and stick to
it. Variable values are illegal.

```
space.0 = 0 cells
space.1 = 1 cell    (inline gap, padding-x on tight rows)
space.2 = 2 cells   (default padding-x inside surfaces)
space.3 = 3 cells   (between major blocks in transcript)
space.4 = 4 cells   (overlay inset from edge)
space.6 = 6 cells   (composer max bottom margin)
```

There is no `space.5` on purpose. Designers reach for it when they
should be picking 4 or 6.

### 2.3 Lines & frames

```
border.none      —
border.soft      ╌  (uses dim neutral.700/200, single weight)
border.solid     ─  (neutral.600/300)
border.focus     ─  (brand, only on focused control)
border.danger    ─  (danger, only on approval/error)

corner.square    ┌ ┐ └ ┘
corner.round     ╭ ╮ ╰ ╯   ← default for surfaces
corner.heavy     ┏ ┓ ┗ ┛   ← reserved for modal/approval
```

We currently use `frame()` with `┌─┐` everywhere. Replace with
rounded corners for content surfaces, heavy corners *only* for
approval/blocking modals. This single change gives the UI a much
softer, Cursor-like read.

### 2.4 Glyphs

A whitelisted glyph set. If a widget reaches for a glyph not in this
table, it must add it here first.

```
prefix.user        ›        cyan/brand-soft, no bracket
prefix.assistant   (none)   assistant text starts at column 0
prefix.system      ·        muted, single bullet
prefix.tool.run    ⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏   braille spinner (see §6)
prefix.tool.ok     ✓        success
prefix.tool.fail   ✗        danger
prefix.tool.block  ◐        warning
prefix.tool.skip   ○        muted

bullet.dot         •
bullet.diamond     ◆        reasoning header
bullet.chevron     ›        inline hint
divider.thin       ────     soft, full width, 1 row, neutral.700/200
divider.dot        · · ·    centered, 1 row, neutral.500

caret.idle         ▏        brand, 50% opacity (via dim)
caret.streaming    ▍        brand, solid

pill.l  pill.r     ⦗ ⦘      status pills in bar
kbd.l   kbd.r      ⌜ ⌟      keycap brackets in hints

chrome.traffic      ●        mac traffic dots in the chrome bar
```

Banned (currently in the codebase, but they read as noisy /
inconsistent across fonts): `■`, `░▒▓█`, ASCII art logos, the
`-\|/` spinner.

### 2.5 Motion

Frame-based, not millisecond-based — we tick the renderer, not the
wall clock. Assume 30 fps event loop (33 ms per frame).

```
motion.tick.fast    2 frames    ≈ 66 ms — selection move, focus ring
motion.tick.beat    4 frames    ≈ 132 ms — spinner step
motion.tick.slow    8 frames    ≈ 266 ms — caret blink, fade
motion.tick.dwell   16 frames   ≈ 533 ms — toast lifetime min
motion.stream.gate  ≤ 1 frame  streaming text flush rate; never queue
```

The current code re-renders the whole transcript on every chunk,
which is why streaming looks "poor". The motion contract below
(§6.3) makes this a token-level constraint, not a per-widget
choice.

### 2.6 Depth (terminal-style)

We can't blur. We have three signals: background lightness, border
weight, z-stacking. Use them in that order.

```
elevation.0  canvas        — the page
elevation.1  raised        — transcript card, composer (bg +1 step)
elevation.2  overlay       — palette, mention menu (bg +1 step, border solid, drop-shadow row)
elevation.3  modal         — approval (bg +1 step, border heavy, dimmed canvas)
```

"Drop-shadow row" = one extra row painted in `neutral.900` directly
below the overlay, one cell to the right. Cheap, but reads as depth
on every terminal we tested.

---

## 3. Semantic tokens

These are the only names widgets reference. Themes override values
here.

```
surface.canvas        neutral.900 / .50      page background
surface.raised        neutral.850 / .100     transcript card, composer
surface.sunken        neutral.950 / .200     code blocks, tool output
surface.overlay       neutral.800 / .50      palette, mention menu
surface.modal         neutral.850 / .100     approval

border.subtle         neutral.700 / .200     idle surfaces
border.strong         neutral.600 / .300     hovered / scrollbar track
border.focus          brand                  focused control
border.danger         danger                 approval, error bar

text.primary          neutral.100 / .900     body
text.secondary        neutral.300 / .500     hints, metadata
text.tertiary         neutral.400 / .400     timestamps, "press / for…"
text.disabled         neutral.500 / .300     greyed entries
text.on-accent        neutral.950 / .50      text drawn over brand fill
text.on-danger        neutral.950 / .50      text drawn over danger fill

accent.fg             brand                  focus, links, agent name
accent.soft           brand @ 30%            via dim attr, never raw alpha

status.success.fg     success                ✓
status.success.soft   success-dim            row tint
status.warning.fg     warning
status.warning.soft   warning-dim
status.danger.fg      danger
status.danger.soft    danger-dim
status.info.fg        info
status.info.soft      info-dim

role.user.fg          info                   › prefix only
role.assistant.fg     text.primary           body
role.reasoning.fg     reason                 inside reasoning block
role.tool.idle.fg     text.secondary         tool name pre-resolution
role.tool.ok.fg       status.success.fg
role.tool.fail.fg     status.danger.fg
role.system.fg        text.tertiary

diff.added.bg         success-soft           inline + gutter
diff.removed.bg       danger-soft
diff.context.bg       surface.sunken
diff.gutter.fg        text.tertiary

selection.bg          accent.soft
selection.fg          text.primary
clickable.row.hover.bg    surface.overlay +1 step
clickable.row.press.bg    accent.soft
clickable.glyph.hover.fg  accent.fg
caret.idle.fg         accent.soft
caret.stream.fg       accent.fg
```

Critical change from today: `role.tool` is no longer hard-orange.
Tools are visually quiet until they resolve. This makes a 12-tool
turn feel calm instead of like a Christmas tree.

---

## 4. Component tokens & mockups

Each subsection: what tokens the component consumes, then an ASCII
sketch annotated.

### 4.1 Root layout

Two fixtures, one flow. The chrome bar (§4.1.1) pins the top with
wayfinding + state + ctx meter. The composer + hint row pin the
bottom. Everything between is the transcript, scrolling. No footer
status band; no in-canvas header row; no rail.

```
╭ ● ● ●  ◆ tinyagent │ ws:tinyagent │ model:gpt-5 │ ⎇ ta-review-…  ⠋ ⦗streaming⦘ ⦗approve queued⦘ │ ctx ▭▭▭▭▱▱▱ 24% ╮ ← chrome bar
│                                                                                                                    │
│  › fix the streaming jitter in Transcript                                                          20:48 · just now │   role.user.fg
│                                                                                                                    │
│  ◆ thought for 4s                                                                                       ⌜r⌟ collapse│   role.reasoning.fg
│    The reflow happens because we replace assistant.content on every chunk, which re-mounts the …                   │
│                                                                                                                    │
│  ✓ read    src/ui/widgets/Transcript.ts · 250 lines                                                            0.4s │
│  ✓ search  "card.lastAssistant" in src/ · 3 hits                                                               0.2s │
│            └ Transcript.ts:160   card.assistant.content = next;                                                    │
│            └ markdown.ts:42      streaming: turn.phase === "streaming"                                             │
│  ⠙ edit    src/ui/widgets/Transcript.ts                                                                    running…│
│                                                                                                                    │
│  We can keep the existing transcript card and mutate the assistant node's content in place. …                      │   role.assistant.fg
│                                                                                                                    │
│  ╭─ PATCH  src/ui/widgets/Transcript.ts                                              +3  −1   ⌜⏎⌟ apply  ⌜d⌟ diff ╮ │   surface.sunken
│  │ 159  +   if (next !== card.lastAssistant) {                                                                   │ │
│  │ 160  +     card.assistant.content = next;                                                                     │ │
│  │ 161  +     card.lastAssistant = next;                                                                         │ │
│  │ 162  −     card.assistant = rebuild(next);                                                                    │ │
│  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────╯ │
│                                                                                                                    │
│  Once that lands the per-chunk reflow disappears and the spinner can co-exist with the caret▍                      │   caret.stream
│                                                                                                                    │
│  ╭─ ask, plan, or /command ──────────────────────────────────────────────────────────────────────────────────────╮│   composer
│  │ implement the new design tokens ▍                                                                              ││   border.focus
│  ╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────╯│
│    ⌜enter⌟ send  ⌜⇧enter⌟ newline  ⌜/⌟ commands  ⌜@⌟ files  ⌜$⌟ skills                          ⌜esc⌟ cancel turn │   hints, text.tertiary
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

What changed vs the previous draft of this doc:

- **No in-canvas header row.** The chrome bar holds all wayfinding
  and the persistent phase pill. The conversation starts at row 2.
- **No footer status band.** Everything the status bar used to show
  (model, tokens, calls, phase, ctx) is in the chrome bar.
  Per-turn metrics (`0.4s`, `running…`) are inline on the tool row.
- **Tool calls live inline** in the transcript and resolve in place.
- **ASCII logo deleted.** The wordmark `◆ tinyagent` is one cell
  tall in the chrome bar.
- **No persistent rail.** Sessions / diff / usage are right-side
  overlays (§4.7).

#### 4.1.1 Chrome bar

The only persistent top fixture. Single row (44 px / one terminal
cell + frame padding). Carries identity, environment, transient
state pills, and the ctx meter.

```
● ● ●   ◆ tinyagent │ ws:NAME │ model:NAME │ ⎇ BRANCH       ⠋ ⦗phase⦘ [⦗transient⦘ …] │ ctx ▭▭▭▭▱▱▱ NN%
└──┬──┘ └──────────────┬─────────────────────┘ └───────────────┬───────────────────┘ └──────┬──────┘
   │                    │                                       │                            │
   │                    └ wayfinding · text.primary / secondary │                            └ ctx meter (§4.1.2)
   │                                                            └ status pills · only when active
   └ OS chrome (mac traffic dots / no-op on Linux)              spinner only when phase ∈ {thinking, streaming}
```

Rules:

- **Wayfinding truncates from the middle.** Workspace name pinned,
  branch truncated with ellipsis when needed. Model never truncates;
  if width is too tight, the branch field collapses to `⎇ …` and
  expands on hover.
- **Phase pill is always present.** One of `idle · thinking ·
  streaming · plan · paused · failed`. Background uses the
  corresponding `status.*.soft` tint; text uses `status.*.fg`.
- **Transient pills stack to the left of the phase pill.** Examples:
  `⦗approve queued⦘`, `⦗update available⦘`, `⦗ratelimit⦘`. Max two
  visible; overflow into `⦗+N⦘` that opens a popover on click.
- **The braille spinner sits outside the pill.** So the pill text
  never shifts when the spinner ticks. Spinner is hidden when phase
  is `idle` or `paused`.
- **Mouse**: workspace name opens `/sessions`. Model opens
  `/model`. Branch opens `/diff`. Pills open the relevant overlay
  (`approve queued` → approval modal, `update` → release notes).

#### 4.1.2 Ctx meter

Slim track + percentage. The meter is the only place in the chrome
bar where color encodes meaning beyond identity. Background is
`border.subtle`. Fill color shifts by remaining headroom:

```
0 – 79%      fill = accent.fg          (brand)       text = text.primary
80 – 94%     fill = status.warning.fg                text = status.warning.fg
95 – 100%    fill = status.danger.fg                 text = status.danger.fg
```

Width: 80 px (≈ 9 cells) when the chrome bar has room; collapses to
just `NN%` text (color still follows the threshold) when the bar is
< 88 cells wide. Threshold transitions are step changes, no
animation — we don't have to debate "is it yellow yet" mid-fade.

At ≥ 95%, the meter is paired with a `⦗compact⦘` transient pill that
opens the compaction overlay when clicked. We never auto-compact
without that pill having been shown for at least
`motion.tick.dwell`.

### 4.2 Transcript card

Tokens: `surface.raised`, `role.user.fg`, `role.reasoning.fg`,
`role.tool.*`, `role.assistant.fg`, `divider.thin`.

```
  › user prompt, wrapping at width-4. continuation lines indented   ← role.user.fg
    two cells, no bullet.
                                                                    ← space.1 gap
  ◆ thought for 4s                                                  ← bullet.diamond, dim
    reasoning body, role.reasoning.fg, dim. wraps at width-4.       ← role.reasoning.fg

  ⠋ search "streaming jitter" in src/ui/                            ← spinner while running
  ✓ search "streaming jitter" in src/ui/ · 7 hits                   ← resolves in place
    └ Transcript.ts:160 — `card.assistant.content = next;`          ← child line, dim
    └ markdown.ts:42 — `streaming: turn.phase === "streaming"`      ← dim

  assistant body in role.assistant.fg, full-width, word-wrap.       ← no card border
  code blocks rendered with surface.sunken bg + 1-cell padding.
```

Two important rules baked in:

1. **No per-turn box border.** A border per card creates the
   "split-pane" feel. Turns are separated by `divider.thin` only
   when the previous turn produced output; otherwise just a blank
   row.
2. **Tools resolve in place.** The same row that said `⠋ search …`
   becomes `✓ search …`. No append. No second row. This is the
   single biggest perceived-quality win.

### 4.3 Composer

Tokens: `surface.raised`, `border.subtle` / `border.focus`,
`text.tertiary`, `caret.*`.

```
focused:
  ╭─ ask, plan, or /command ─────────────────────────────────────╮   border.focus
  │ implement the new design tokens ▍                            │
  ╰──────────────────────────────────────────────────────────────╯
    ⌜enter⌟ send  ⌜⇧enter⌟ newline  ⌜/⌟ commands  …             text.tertiary

unfocused:
  ╭──────────────────────────────────────────────────────────────╮   border.subtle
  │ press / to start                                             │   text.tertiary
  ╰──────────────────────────────────────────────────────────────╯
```

Rules:

- Border weight encodes focus (subtle → focus). Color does **not**.
  We never paint the border accent unless focused.
- Title slot ("ask, plan, or /command") only renders when focused.
  Unfocused state shows a single muted placeholder *inside* the box.
- Hint row uses `kbd.l/kbd.r` brackets, not back-tick characters.

### 4.4 Slash · mention · skill menus (`/`, `@`, `$`)

This is the surface you flagged as buggy. The new contract:

- **Same component.** One picker widget, three trigger modes. All
  three share tokens; only the header glyph + dataset differ.
- **Always a popover, never a side rail.** Position absolute,
  anchored to the composer's left edge, *above* the composer when
  focused. Grows upward, max height 12 rows.
- **No "no match" empty rows.** If filter has zero hits, the
  popover collapses to a single row: `no matches · ⌜esc⌟ collapse`.
- **Hover ≠ select.** Mouse hover changes row tint to
  `surface.overlay` shifted +1 step; selection (keyboard or click)
  paints `selection.bg`. They are visually distinct.
- **Trigger badge in header.** `⦗ / ⦘ commands` · `⦗ @ ⦘ files` ·
  `⦗ $ ⦘ skills`, in `accent.fg`. Consistent placement = no
  surprise.

Mock — slash:

```
                       ╭─ ⦗ / ⦘ commands ──────────────────────╮  surface.overlay
                       │  /diff         show git diff           │  rows: text.primary
                       │  /diff-stat    show diff summary       │  selected: selection.bg
                       │ ›/replay       replay current run      │  prefix.chevron on sel
                       │  /sessions     list sessions           │
                       │  /skills       open skill forge        │
                       │  ⋯ 14 more · type to filter            │  text.tertiary
                       ╰────────────────────────────────────────╯
  ╭─ ask, plan, or /command ─────────────────────────────────────╮
  │ /rep▍                                                        │
  ╰──────────────────────────────────────────────────────────────╯
```

Mock — mention `@`:

```
                       ╭─ ⦗ @ ⦘ files ─────────────────────────╮
                       │ ›src/ui/widgets/Transcript.ts          │
                       │  src/ui/widgets/Composer.ts            │
                       │  src/design/tokens.ts                  │
                       │  ─── recent ───                        │  divider.thin
                       │  README.md                             │
                       ╰────────────────────────────────────────╯
  │ summarize @Tra▍                                              │
```

Mock — skill `$`:

```
                       ╭─ ⦗ $ ⦘ skills ────────────────────────╮
                       │ ›verify       run app, observe         │
                       │  review       review the diff          │
                       │  loop         run on interval          │
                       ╰────────────────────────────────────────╯
  │ $ver▍                                                        │
```

Why this fixes the "buggy & ugly" report:

- Today three different widgets render these. One implementation
  ends the inconsistency.
- The popover today is positioned `bottom: 5` with a fixed width
  60; on narrow terminals it clips the composer. New spec: anchor
  to the caret column, clamp to `viewport.width - space.4 * 2`,
  prefer-above with auto-flip.
- Today an empty result still renders a `(no match)` *option*,
  which is selectable. New spec: empty state is a label, not a
  row.

### 4.5 ~~Status bar~~ — *removed*

Folded into §4.1.1 (chrome bar). Per-turn metrics (`0.4s`,
`running…`) live inline on the tool row that produced them, not in
a parallel bar. Session totals (token count, call count) move to
the `/usage` overlay (§4.7) — they are review data, not glance
data.

Reason: a 1-row footer that's always present trains the eye to
*check* it. We don't want that. The chrome bar gets the eye when
the user enters; the conversation gets it from then on.

### 4.6 Approval modal

Tokens: `surface.modal`, `border.danger` + `corner.heavy`,
`status.danger.*`.

```
                  ┏━ ⦗ APPROVE ⦘ shell ────────────────────────────┓
                  ┃                                                  ┃
                  ┃  rm -rf node_modules                            ┃   surface.sunken
                  ┃                                                  ┃
                  ┃  in: /Users/kristian/work/dev/tinyagent         ┃   text.secondary
                  ┃                                                  ┃
                  ┃    ⌜y⌟ allow once     ⌜a⌟ allow                 ┃
                  ┃    ⌜n⌟ deny           ⌜e⌟ edit (future)         ┃
                  ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
   ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░  canvas dimmed
```

Only modal in the system. Heavy corners + danger border = "this
blocks". No other surface uses these.

Current wire protocol resolves approvals as approve/deny/cancel/expire.
Do not render `edit` as an active shortcut until the backend can accept an
edited approval payload.

### 4.7 Overlay panels (sessions, diff, usage, …)

Today these live in the rail. New spec: they slide in from the
right as **overlays** over the transcript, 80 columns wide max,
full height, dismissed with `esc`.

Tokens: `surface.overlay`, `border.strong`, header uses
`accent.fg`. Overlays do not stack — opening one closes any other.

This kills the "two-pane forever" feel without losing any panel.

---

## 5. Themes

Themes override semantic tokens only. We ship four:

| theme           | bias                       | use                       |
| --------------- | -------------------------- | ------------------------- |
| `paper-dark`    | warm-neutral dark, default | most users                |
| `paper-light`   | matching light             | bright environments       |
| `mono`          | no chroma except accent    | screen recording, demos   |
| `high-contrast` | WCAG AAA, single accent    | accessibility             |

`dracula` and `gruvbox` remain in `themes/community/` but are no
longer in the default cycle. Reason: they were each built on a
different chroma philosophy and break our "color = meaning" rule.

`paper-dark` overrides (extract):

```
surface.canvas    #0d1117    (was #0b0f14, slightly warmer)
surface.raised    #131822
surface.sunken    #0a0e14
surface.overlay   #1a2030
border.subtle     #1f2733
border.strong    #2a3340
border.focus      #5b9dff    brand
text.primary      #e8eef5
text.secondary    #9aa4b1
text.tertiary     #6a7480
accent.fg         #5b9dff
status.success.fg #4ac26b
status.warning.fg #d9a341
status.danger.fg  #ef5350
status.info.fg    #56d6a4
role.reasoning.fg #b48aff
```

`mono`:

```
all role.* and status.* = text.primary
caret.stream.fg, accent.fg, border.focus = #ffffff (or term default fg)
diff.added.bg, diff.removed.bg use inverse + dim, no color
```

This is also the theme our tests render against, so visual
regressions stay color-blind by default.

---

## 6. Motion contracts

### 6.1 Spinner

One spinner, one set of frames, one tick rate. `braille` only.
`-\|/` and `░▒▓█` are removed.

```
frames:  ⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏        (10 frames)
tick:    motion.tick.beat            (≈ 132 ms per step)
color:   role.tool.idle.fg while running
         status.success.fg on resolve (1 final paint, no spinner)
         status.danger.fg on fail
```

### 6.2 Caret

```
idle (composer focused):     ▏  caret.idle.fg, blink @ motion.tick.slow
streaming (assistant body):  ▍  caret.stream.fg, solid (no blink)
streaming gap > 1s:          ⠋  same braille, but at end of line
```

The "streaming gap" rule means the user always knows whether the
agent is *typing* or *thinking*. Today it just stops.

### 6.3 Streaming text flush

The contract that fixes "poor text generation":

1. The reducer receives chunks. It appends to a `string` buffer,
   does **not** rebuild nodes.
2. The renderer reads the buffer once per frame and calls
   `assistant.content = buffer`. It never replaces the node.
3. The composer, status bar, and tools are repainted on the same
   frame, not on chunk arrival. → no layout reflow per token.
4. Max one repaint per frame, regardless of chunk count. Bursty
   chunks coalesce.

This is a token-level rule (`motion.stream.gate ≤ 1 frame`)
because it has to be enforced at the renderer, not the widget.

### 6.4 Phase transitions

```
idle      →  thinking    : status pill fade-in over motion.tick.beat
thinking  →  streaming   : spinner stops; caret.stream appears in transcript
streaming →  done        : caret.stream removed; divider.thin appears
*         →  approval    : modal opens, canvas dims to surface.sunken
*         →  failed      : status pill turns danger; no shake, no flash
```

No bell, no flash, no shake. Codex and Cursor both stay quiet at
state-change. We do too.

---

## 7. Mouse model

Tokens for hit-targets. Every clickable surface gets a defined
hover state and (optionally) a press state.

```
clickable.row.hover.bg     surface.overlay shifted +1
clickable.row.press.bg     accent.soft
clickable.glyph.hover.fg   accent.fg
clickable.scrollbar.track  border.subtle
clickable.scrollbar.thumb  border.strong
```

Clickable surfaces:

- Transcript turn header (collapse/expand reasoning).
- Tool call rows (expand output).
- Status bar pills (open relevant overlay).
- Slash/mention/skill menu rows.
- Header workspace name (open sessions overlay).
- Composer hint chips (`⌜/⌟ commands` etc — click triggers it).

The cursor changes via terminal mouse events; for terminals without
cursor shape support we paint `▸` in the gutter on hover.

---

## 8. Density modes

Two presets, one token.

```
density.comfortable   (default)     space.2 padding, space.1 between rows
density.compact                     space.1 padding, space.0 between rows
```

Compact is for ≤ 80-column terminals. Selected by viewport probe at
startup, overridable via `/density`.

---

## 9. What dies, what changes, what survives

| current artifact                          | fate                                                                  |
| ----------------------------------------- | --------------------------------------------------------------------- |
| `tinyagent` ASCII logo (`design/ascii.ts`)| **dies** — replaced by one-line header wordmark                       |
| pane split (`Rail`, width 56)             | **dies** — rail panels become overlays                                |
| per-turn card border                      | **dies** — replaced by divider-on-demand                              |
| `frame("transcript", …)` outer box        | **dies** — transcript is the page                                     |
| orange tool color (`color.orange`)        | **changes** — tools idle = `text.secondary`, resolve = success/danger |
| `pink` and `orange` raw tokens            | **die** — not in semantic layer; removed from primitives              |
| `spinners.scanline`, `dots`, `ascii`      | **die** — only `braille`                                              |
| `dracula`, `gruvbox` themes               | **survive** but move to `themes/community/`                           |
| `/` slash menu (`PaletteWidget`)          | **merges** into single `PickerWidget` (§4.4)                          |
| `@` mention menu (`MentionMenuWidget`)    | **merges** into `PickerWidget`                                        |
| `$` skill mode                            | **merges** into `PickerWidget`                                        |
| `(no match)` selectable row               | **dies** — replaced by inline empty label                             |
| `frame()` square corners                  | **changes** — `╭╮╰╯` default, `┏┓┗┛` reserved for modal               |
| `design/tokens.ts` (flat colors)          | **changes** — split into `primitives.ts`, `semantic.ts`, `theme.ts`   |
| transcript reflow per chunk               | **dies** — replaced by §6.3 contract                                  |
| status bar (1-row footer)                 | **dies** — folded into chrome bar (§4.1.1)                            |
| in-canvas `╭─ tinyagent · … ─╮` header    | **dies** — chrome bar carries wayfinding                              |
| ctx as comma-joined `24% ctx` text        | **changes** — slim meter + threshold colors (brand/warning/danger)    |
| approval inside the rail                  | **changes** — only modal in the system                                |

---

## 10. File layout (target)

```
tui/src/design/
  primitives.ts      neutrals, brand, status, space, motion, glyphs
  semantic.ts        the table in §3
  components.ts      composer.*, transcript.*, picker.* …
  themes/
    paper-dark.ts
    paper-light.ts
    mono.ts
    high-contrast.ts
    community/
      dracula.ts
      gruvbox.ts
  glyphs.ts          the whitelist in §2.4
  motion.ts          ticks + phase transitions
  index.ts           re-export `tokens` (semantic+component merge)
```

Widgets import from `design/index` only. No widget references
`primitives.ts` directly — that's lintable.

---

## 11. Open questions (for you)

These are decisions I'd like your call on before I cut code.

1. **Header wordmark.** `tinyagent` lowercase, or `Tinyagent`, or a
   single glyph like `◆ tinyagent`? I default to lowercase
   `tinyagent` for the Codex/Cursor feel.
2. **Overlay direction.** Right-side slide (Cursor-style) or
   bottom-up sheet (Grok Build-style) for sessions / diff / usage?
   I default to right-side; sheets compete with the composer.
3. **Reasoning visibility.** Default visible (Codex) or collapsed
   behind a `⌜r⌟` toggle (Cursor)? I default to collapsed —
   reasoning is noise once you trust the agent.
4. **Mouse selection.** Do we adopt terminal-native text selection
   (works everywhere, no styling) or paint our own selection layer
   (looks better, breaks copy in some terminals)? I default to
   native.
5. **Density auto-switch threshold.** 80 cols or 100 cols? I
   default to 100 — gives more room to breathe.

Once you sign off on the above five, the next step is splitting
`design/tokens.ts` into the three-layer module in §10 and porting
one widget end-to-end (proposal: the composer + picker, since they
were called out as worst). Everything else follows mechanically.
