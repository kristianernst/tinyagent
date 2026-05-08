# Stage 3 — Pi Profile and Extensibility

## Goal

Make the Pi-style philosophy real inside tinyagent by adding a lean default profile and a small resource-loading seam.

## Why this is necessary

A design philosophy is not real until it can be evaluated. Today, tinyagent’s default profile is robust but broad. It includes dynamic context tools, skills, LSP/MCP names, finish gates, context planning, and a relatively rich tool surface. That may be useful, but it is not Pi-like.

Stage 3 creates a separate `tiny-pi` profile so tinyagent can test whether a radically smaller tool/prompt surface performs better on common tasks, reduces bloat, and improves model behavior.

## Substages

1. `stage_03a_tiny_pi_profile.md`
2. `stage_03b_resource_loader.md`
3. `stage_03c_extension_abi.md`

## Primary changes

- Add `TinyPiProfile` or profile variant `ApexCoderProfile(profile_variant="pi")`.
- Add CLI/runtime profile selection.
- Add a resource loader that discovers optional resources without hardwiring them into `Kernel`.
- Clarify extension ABI and load order.
- Add eval comparison between `tiny-pi` and `tiny-coder`.

## `tiny-pi` target behavior

Default context:

- system prompt under 1,500 tokens if possible;
- task;
- minimal environment envelope;
- project instructions if found;
- a short note that the agent can use files and shell to inspect state;
- no default MCP/LSP/todo memory/dynamic source list unless configured.

Default tools:

- `read_file`;
- model-specific edit tool: `apply_patch`, `str_replace_edit`, or `write_file`;
- `shell`;
- optional `list_files` or grep/find/ls aliases if evals show value.

Default behavior:

- no built-in todo requirement;
- if planning is needed, write a file or concise message;
- no required diff/test finish gate in pure Pi mode, but do not permit false test claims;
- optional “safe Pi” variant can retain finish gates.

## Resource loader target

The resource loader should discover:

- project/user skills;
- explicit extension files;
- prompt templates;
- context files;
- optional theme/UI metadata if product shells need it later.

But it should return a data snapshot. `Kernel` receives resources. `Kernel` does not search the filesystem for all resource types itself.

## Exit criteria

- CLI can run `--profile tiny-pi` or equivalent.
- Runtime/API can start runs with profile selection or configured default profile.
- `tiny-pi` has fewer static prompt/tool tokens than `tiny-coder`.
- `tiny-pi` can run basic eval cases.
- Resource loading is optional and does not bloat `tiny-pi` when disabled.

## Risks

### Risk: `tiny-pi` loses too much safety

Separate safety from profile minimality. Policy and artifact boundaries remain active. The profile controls prompt/tool surface, not core safety invariants.

### Risk: resource loader becomes a plugin framework

Keep it boring. It returns loaded resources. It does not orchestrate runs.

### Risk: profile selection spreads through CLI/server code

Use a small profile factory/registry instead of ad hoc conditionals.
