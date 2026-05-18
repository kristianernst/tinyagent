# Install And Update

tinyagent is versioned as an alpha product. The Python backend and OpenTUI client ship as one release unit so `tinyagent`, `tinyagent-tui`, the `/v1` protocol, and `tui/dist` stay in lockstep.

Current alpha version:

```text
0.1.0a0
```

## Install Model

The product home remains stable across releases:

```text
~/.tinyagent/
  config.toml
  install.json
  version.json
  workspaces/
  updates/
  versions/
  current -> versions/<version>
```

State lives under `~/.tinyagent/workspaces`. Versioned release payloads live under `~/.tinyagent/versions`. Updating switches `~/.tinyagent/current` after the payload has been downloaded, checksum-verified, unpacked, and checked for expected files.

Package-manager installs are respected:

```text
source checkout   use git pull/build
python package    use uv/pip/pipx
standalone        use tinyagent update apply
```

`tinyagent update apply` refuses to mutate package-managed installs unless the install has a managed `install.json` receipt.

## Commands

```sh
tinyagent version --json
tinyagent install --manifest ./manifest.json --channel alpha
tinyagent update status
tinyagent update check --channel alpha
tinyagent update apply --channel alpha
tinyagent update rollback
```

During alpha development, a local manifest can be used:

```sh
tinyagent update check --manifest ./manifest.json
tinyagent update apply --manifest ./manifest.json
```

The TUI exposes the same surface:

```text
/update
/update check
/update apply
/update rollback
```

The TUI blocks apply and rollback while a run is active.

Automatic checks are conservative. The product server checks in the background only when a manifest is configured through `TINYAGENT_UPDATE_MANIFEST` or `~/.tinyagent/config.toml`:

```toml
[updates]
channel = "alpha"
manifest_url = "https://releases.tinyagent.dev/alpha/manifest.json"
auto_check_interval_hours = 24
```

Source checkouts do not hit the network unless a manifest is configured or passed explicitly.

## Manifest Shape

```json
{
  "schema": 1,
  "channel": "alpha",
  "version": "0.1.0a1",
  "published_at": "2026-05-17T00:00:00Z",
  "artifacts": [
    {
      "platform": "darwin-arm64",
      "url": "tinyagent-0.1.0a1-darwin-arm64.tar",
      "sha256": "<64 hex chars>",
      "size": 123456,
      "expected_files": ["bin/tinyagent", "tui/dist/main.js"]
    }
  ]
}
```

The updater accepts `darwin-arm64`, `darwin-x64`, `linux-arm64`, `linux-x64`, `windows-x64`, or `any` artifacts. Relative artifact URLs resolve relative to the manifest.

## Release Rule

Do not publish backend-only or TUI-only releases. A release is valid only when:

```text
uv run pytest
uv run ruff check .
bun test
bun run build
uv build
```

all pass, and the built wheel/sdist include `tinyagent/tui/dist/main.js` but exclude `node_modules`.
