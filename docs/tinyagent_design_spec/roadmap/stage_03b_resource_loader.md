# Stage 3b — Resource Loader

## Problem

`Kernel` currently constructs extension host, skill registry, context registry, and default context sources directly. As tinyagent grows, this will push more discovery logic into the core.

Pi’s design separates resources from the agent loop: extensions, skills, prompt templates, themes, and context files can be loaded by a resource loader. Tinyagent should adopt a small version of that idea.

## Target design

Introduce:

```python
@dataclass(frozen=True)
class LoadedResources:
    extensions: tuple[Extension, ...] = ()
    skill_sources: tuple[SkillSource, ...] = ()
    context_sources: tuple[ContextSource, ...] = ()
    prompt_templates: tuple[PromptTemplate, ...] = ()
    context_files: tuple[ContextFile, ...] = ()

class ResourceLoader:
    def load(self, workspace: Path, *, profile: str) -> LoadedResources: ...
```

`Kernel` receives resources or extensions. It should not own broad discovery policy.

## Discovery locations

Initial resource types:

| Resource | Project path | User path | Default in `tiny-pi`? |
| --- | --- | --- | ---: |
| AGENTS.md instructions | existing logic | existing logic | Yes |
| skills | `.tinyagent/skills`, `.agent/skills` | `~/.tinyagent/skills` | Only descriptions if tool enabled |
| extension files | `.tinyagent/extensions/*.py` | `~/.tinyagent/extensions/*.py` | No by default unless opted in |
| prompt templates | `.tinyagent/prompts` | `~/.tinyagent/prompts` | Optional |
| context files | `.tinyagent/context` | optional | Optional |

Do not load arbitrary Python extension files silently in untrusted workspaces. Require explicit trust or CLI flag.

## Trust model

Resource loading must respect workspace trust:

- trusted workspace: project extensions can load if enabled;
- untrusted workspace: project extensions disabled by default; skills can be listed/read as text but not execute code;
- user resources: enabled according to user config;
- product server: explicit config controls resources.

## Integration plan

1. Add `tinyagent/core/resources.py`.
2. Move skill source discovery into `ResourceLoader` or wrap current `default_skill_sources()`.
3. Keep existing `ExtensionHost`, but construct it from loaded resources.
4. Add CLI flags:
   - `--no-discovery`;
   - `--extension path.py`;
   - `--skill-source path` if useful later.
5. Add product config fields later.

## Tests

- No-discovery mode loads no project/user optional resources.
- Untrusted workspace does not load Python extension files by default.
- Trusted workspace loads explicit extension file.
- Skills remain discoverable as text resources.
- `tiny-pi` remains small when no resources are enabled.

## Exit criteria

- Resource discovery no longer grows inside `Kernel`.
- Trust behavior is explicit.
- Existing skill behavior still works.
- Extension loading remains opt-in for executable code.

## Why this matters

A lean core needs extensibility, but extensibility must not mean “Kernel imports everything.” A resource loader gives tinyagent a Pi-like customization path without bloating the loop.
