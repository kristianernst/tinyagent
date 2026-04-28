"""Small cancellation primitives for the local harness."""

from __future__ import annotations

import threading
from dataclasses import dataclass


class RunCancelled(RuntimeError):
    """Raised at harness boundaries when a run has been cancelled."""


@dataclass
class CancelToken:
    reason: str | None = None
    escalated: bool = False
    signal_count: int = 0

    def __post_init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self, reason: str = "cancelled", *, escalate: bool = False) -> None:
        self.reason = reason
        self.escalated = self.escalated or escalate
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.cancelled:
            raise RunCancelled(self.reason or "cancelled")
