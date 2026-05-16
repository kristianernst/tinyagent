# Architecture

FlowForge has four small modules:

- `models.py`: shared work item dataclasses.
- `parser.py`: backlog text parsing.
- `planner.py`: milestone selection.
- `reporting.py`: human-readable output.

The first version only produced a simple summary. The next version should keep
the module split but make planning behavior explicit and testable.
