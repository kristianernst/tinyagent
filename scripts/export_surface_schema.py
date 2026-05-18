"""Export the public surface protocol schema for the TypeScript TUI."""

from __future__ import annotations

import json

from tinyagent.runtime.protocol_v1 import SCHEMA_VERSION, openapi_spec


def main() -> int:
    spec = openapi_spec(product=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "openapi": spec["openapi"],
        "components": spec["components"],
        "paths": spec["paths"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
