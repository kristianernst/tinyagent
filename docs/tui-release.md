# TinyAgent TUI Release Notes

## Install

TinyAgent keeps Python runtime dependencies separate from the Bun/OpenTUI client.

```bash
uv tool install .
tinyagent doctor --workspace . --provider fake --port 0
tinyagent tui --workspace . --provider fake
```

For packaged wheels, the launcher uses the bundled `tinyagent/tui/dist/main.js`. In a source checkout, it uses `tui/src/main.ts`.

The product release channel is alpha. Install and update behavior is documented in [install-update.md](install-update.md). The TUI and Python backend ship as one versioned payload, and `/update` exposes the same update state as `tinyagent update`.

## Headless Parity

Every shipped TUI action has a CLI or protocol equivalent:

```text
run/build     tinyagent run "<task>" --output-format json
stream        tinyagent run "<task>" --stream jsonl --debug 1
usage         tinyagent run "<task>" --output-format json | jq .usage
replay        tinyagent replay <run_path>
fork          tinyagent fork <run_path> --at <event_seq>
eval          tinyagent eval <suite_path>
skill draft   tinyagent skills draft-from-run <run_path>
stdio         tinyagent agent stdio --protocol tinyagent
ACP prototype tinyagent agent stdio --protocol acp
```

The TUI `/headless` panel renders these equivalents from the active session.

## Machine Protocols

`tinyagent run --output-format json` emits one JSON object after the run completes. `--stream jsonl` remains event-only JSONL and does not append a final human summary.

`tinyagent agent stdio` is the JSON-RPC prototype. It reads newline-delimited JSON-RPC requests from stdin, writes responses and `session.event` notifications to stdout, and reserves stderr for diagnostics.

Supported prototype methods:

```text
session.start
session.prompt
session.cancel
approval.resolve
```

`--protocol acp` uses the same transport with ACP-oriented capability metadata so adapter work can validate session/event/approval mappings without adding another runtime path yet.

## Terminal Matrix

Smoke targets for beta:

```text
iTerm2          split-footer and fullscreen
WezTerm         split-footer and resize
kitty           mouse optional, keyboard complete
Apple Terminal  no mouse required, fixed status width
VS Code terminal keyboard complete, no mouse required
Windows Terminal protocol smoke through stdio/headless paths
tmux            split-footer, resize, and no status jitter
SSH             no mouse required, JSON/stdio protocol works over remote shell
```

Acceptance checks:

```text
No terminal corruption on resize
No width jitter in status bar
Mouse is optional
Ctrl+C and /stop both cancel active work
Replay handles 10k events
Diff viewer bounds 200k-character diffs
```

## Beta Feedback Loop

Capture one issue per failed workflow:

```text
start/run
approve/deny
stop/cancel
diff review
context graph
replay/fork
eval lab
skill forge
stdio/ACP prototype
```
