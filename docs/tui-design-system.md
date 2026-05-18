# TinyAgent TUI Design System

The product direction is a dense terminal control surface, not a browser chat app.

## Visual Language

- Dark terminal base.
- High contrast text.
- Low-noise neon accents.
- ASCII identity for startup, plan, approval, done, and failure states.
- Fixed-width spinner frames only.
- No emoji in the status bar.

## Tokens

The TypeScript source of truth is `tui/src/design/tokens.ts`.

Core colors:

- background: `#0b0f14`
- surface: `#11161c`
- border: `#22303a`
- focus: `#58a6ff`
- text: `#e6edf3`
- muted: `#8b949e`
- success: `#2ea043`
- danger: `#f85149`
- approval: `#f0883e`

## Shell Layout

Default mode is split footer:

- transcript in normal scrollback
- composer and status pinned to the footer
- optional right rail for tools, context, usage, diff, and debug

Fullscreen mode is reserved for session browser, diff forge, replay, evals, and model comparison.

## Required Panels

- transcript
- composer
- status bar
- session rail
- context graph
- tool timeline
- approval gate
- diff forge
- plan board
- usage panel
- replay cinema
- model lab
- eval lab
- skill forge
- debug overlay

Each panel must be renderable from reducer state or explicit command data.
