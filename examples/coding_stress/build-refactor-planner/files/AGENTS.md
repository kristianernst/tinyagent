# Agent Instructions

- Keep this repo dependency-free; use only the Python standard library.
- Preserve the `src/flowforge` package layout.
- Prefer focused edits in the existing modules before adding new abstractions.
- Use `search_code`, `context_search`, and `read_file` for repo inspection.
  Reserve shell for verification and final git diff.
- Run `python3 -m unittest discover -s tests` and `python3 scripts/validate.py`.
- Inspect `git diff` before the final answer when git is available.
