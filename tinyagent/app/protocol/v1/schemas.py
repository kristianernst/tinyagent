"""Compatibility imports for the shared v1 protocol schema helpers."""

from tinyagent.runtime.protocol_v1 import (
    SCHEMA_VERSION,
    V1_RUN_START_KEYS,
    error_response,
    health_response,
    openapi_spec,
    run_links,
    run_object,
)

__all__ = [
    "SCHEMA_VERSION",
    "V1_RUN_START_KEYS",
    "error_response",
    "health_response",
    "openapi_spec",
    "run_links",
    "run_object",
]
