# Implementation Brief

Build the next FlowForge vertical slice. The current repo is intentionally
incomplete and spread across several files. The target tests describe the
public behavior, but the requirements below are the source of truth.

## Product Behavior

FlowForge should parse a pipe-delimited backlog and produce a dependency-aware
milestone plan.

Backlog line shape:

```text
KEY | Title | owner=name | status=todo | points=3 | priority=2 | depends=A,B | tags=api,ux
```

Rules:

- Ignore blank lines and lines starting with `#`.
- Required fields are key and title.
- `owner` defaults to `unassigned`.
- `status` must be one of `todo`, `doing`, `done`, or `blocked`.
- `points` defaults to `1` and must parse as an integer.
- `priority` defaults to `5`; lower numbers are scheduled earlier.
- `depends` and `tags` are comma-separated lists. Empty values should become
  empty tuples.
- Parser errors should include the line number and enough detail to fix the
  backlog.

Planning rules:

- `done` items count as completed dependencies and are not scheduled.
- `blocked` items are reported under blocked work and are not scheduled.
- `todo` and `doing` items can be scheduled when all dependencies are completed
  or scheduled in an earlier wave.
- Build waves until no more items can be scheduled.
- Within each wave, schedule lower priority first, then smaller point values,
  then key.
- Capacity is per owner per wave. The default is 8 points per owner. The CLI
  accepts repeated `--capacity owner=points` overrides.
- Items that cannot be scheduled because dependencies are still missing should
  be reported as blocked with a reason.

Public APIs expected by the tests:

- `flowforge.parser.parse_backlog(text: str) -> list[WorkItem]`
- `flowforge.planner.plan_milestone(items, capacity_by_owner=None) -> MilestonePlan`
- `flowforge.reporting.render_markdown(plan: MilestonePlan) -> str`
- `flowforge.reporting.render_json(plan: MilestonePlan) -> str`

The exact dataclass shape is up to you, but the tests expect:

- `WorkItem.key`, `title`, `owner`, `status`, `points`, `priority`,
  `depends_on`, and `tags`.
- `MilestonePlan.waves`, `blocked`, and `done`.
- Each wave exposes `index`, `items`, and `remaining_capacity`.

## CLI Behavior

Keep the module runnable as `python3 -m flowforge.cli`.

Required commands:

- `summary BACKLOG`: print counts by status and total points.
- `plan BACKLOG --format markdown|json [--capacity owner=points]...`: print the
  milestone plan to stdout.
- `export BACKLOG --format markdown|json --out PATH [--capacity owner=points]...`:
  write the rendered plan to a file, creating parent directories as needed.

## Documentation

Update `README.md` so it mentions the new `plan` and `export` commands.
Update `docs/architecture.md` so it names the dependency-aware planner.

## Verification

Run:

```bash
python3 -m unittest discover -s tests
python3 scripts/validate.py
```

Then inspect the final diff.
