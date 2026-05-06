"""Shared product/runtime identifier validation."""

from __future__ import annotations

import re

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


def validate_run_id(run_id: str) -> None:
    if not run_id or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError(f"invalid run_id: {run_id}")
