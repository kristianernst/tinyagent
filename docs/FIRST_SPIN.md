# M1.5 First Spin

Use this milestone to run Tinyagent on a disposable repo with a real model, then tune only from trace evidence.

Do not run the first spin on Tinyagent itself.

## Disposable Repo

```bash
rm -rf /tmp/tinyagent-spin
mkdir /tmp/tinyagent-spin
cd /tmp/tinyagent-spin
git init

cat > calc.py <<'PY'
def add(a, b):
    return a - b
PY

cat > test_calc.py <<'PY'
from calc import add


def test_add():
    assert add(2, 3) == 5
PY

git add .
git -c user.email=tinyagent@example.test -c user.name=tinyagent commit -m init
```

## Real-Model Run

Configure the OpenAI-compatible provider:

```bash
export TINYAGENT_MODEL_API_KEY=...
export TINYAGENT_MODEL_NAME=...
export TINYAGENT_MODEL_BASE_URL=https://api.openai.com/v1
```

Run from the Tinyagent repo:

```bash
uv run agentctl run "Fix the bug in calc.py. Run the tests and inspect the final diff." \
  --workspace /tmp/tinyagent-spin \
  --provider openai-compatible
```

## Trace Review

Inspect the generated run directory:

```text
events.jsonl
artifacts/context-0001.md
artifacts/model-request-logical-0001.json
artifacts/model-request-http-0001.json
artifacts/model-response-0001.json
artifacts/command-output-*.txt
summary.md
metrics.json
final.diff
```

Check whether the model understood the visible tools, used shell sanely, emitted valid `apply_patch`, reran tests, and left a minimal final diff.
