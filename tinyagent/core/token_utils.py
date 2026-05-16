"""Small approximate token-budget helpers."""

from __future__ import annotations

TOKEN_ESTIMATE_DIVISOR = 4
TRUNCATION_MARKER = "\n[truncated]\n"


def estimate_tokens(text: str) -> int:
    size = len(text)
    if size <= 0:
        return 0
    return (size + TOKEN_ESTIMATE_DIVISOR - 1) // TOKEN_ESTIMATE_DIVISOR


def token_budget_to_text_limit(token_budget: int) -> int:
    return max(0, token_budget * TOKEN_ESTIMATE_DIVISOR)


def fits_token_budget(text: str, token_budget: int) -> bool:
    return estimate_tokens(text) <= max(token_budget, 0)


def clip_text_to_token_budget(text: str, token_budget: int) -> str:
    limit = token_budget_to_text_limit(token_budget)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARKER):
        return text[:limit]
    available = limit - len(TRUNCATION_MARKER)
    head = available // 2
    tail = available - head
    return text[:head] + TRUNCATION_MARKER + text[-tail:]
