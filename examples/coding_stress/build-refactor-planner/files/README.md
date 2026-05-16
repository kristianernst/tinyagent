# FlowForge

FlowForge is a tiny milestone planning CLI for release teams.

Current command:

```bash
python3 -m flowforge.cli summary data/backlog.txt
```

The backlog format is a pipe-delimited text file. Each non-comment line starts
with a work item key and title, followed by key-value fields.
