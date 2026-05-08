"""Permissive Agent Skills-compatible SKILL.md parser."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SKILL_MARKDOWN_BYTES = 256 * 1024
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)*$")


@dataclass(frozen=True)
class ParsedSkill:
    name: str
    description: str
    tags: tuple[str, ...]
    markdown: str
    truncated: bool
    token_estimate: int
    warnings: tuple[str, ...]


def parse_skill_file(path: Path, *, fallback_name: str) -> ParsedSkill:
    with path.open("rb") as file:
        data = file.read(MAX_SKILL_MARKDOWN_BYTES + 1)
    truncated = len(data) > MAX_SKILL_MARKDOWN_BYTES
    if truncated:
        data = data[:MAX_SKILL_MARKDOWN_BYTES]
    return parse_skill_markdown(data.decode(errors="replace"), fallback_name=fallback_name, truncated=truncated)


def parse_skill_markdown(markdown: str, *, fallback_name: str, truncated: bool = False) -> ParsedSkill:
    frontmatter, body = _split_frontmatter(markdown)
    warnings: list[str] = []
    metadata = _parse_frontmatter(frontmatter) if frontmatter else {}
    if not frontmatter:
        warnings.append("missing frontmatter")

    name = str(metadata.get("name") or "").strip()
    if not name:
        name = fallback_name
        warnings.append("missing name; derived from folder")
    name = _normalize_skill_name(name)

    description = str(metadata.get("description") or "").strip()
    if not description:
        description = _first_paragraph(body)
        warnings.append("missing description; derived from first paragraph")
    if not description:
        description = "No description provided."

    tags = _string_tuple(metadata.get("tags"))
    if truncated:
        warnings.append(f"SKILL.md truncated at {MAX_SKILL_MARKDOWN_BYTES} bytes")
    return ParsedSkill(
        name=name,
        description=description,
        tags=tags,
        markdown=markdown,
        truncated=truncated,
        token_estimate=max(1, len(markdown) // 4),
        warnings=tuple(warnings),
    )


def _split_frontmatter(markdown: str) -> tuple[str, str]:
    if not markdown.startswith("---\n"):
        return "", markdown
    end = markdown.find("\n---", 4)
    if end == -1:
        return "", markdown
    after = end + len("\n---")
    if after < len(markdown) and markdown[after] == "\r":
        after += 1
    if after < len(markdown) and markdown[after] == "\n":
        after += 1
    return markdown[4:end], markdown[after:]


def _parse_frontmatter(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list: list[str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list is not None and stripped.startswith("- "):
            current_list.append(_strip_quotes(stripped[2:].strip()))
            continue
        current_list = None
        if ":" not in stripped:
            continue
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        value = raw_value.strip()
        if value == "":
            if key == "tags":
                data[key] = []
                current_list = data[key]
            else:
                data[key] = {}
            continue
        if value == "[]":
            data[key] = []
            continue
        if value.startswith("[") and value.endswith("]"):
            data[key] = [_strip_quotes(item.strip()) for item in value[1:-1].split(",") if item.strip()]
            continue
        if value in {"|", ">"}:
            data[key] = ""
            continue
        data[key] = _strip_quotes(value)
        if key == "tags" and isinstance(data[key], list):
            current_list = data[key]
    return data


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_skill_name(value: str) -> str:
    name = value.strip().replace("\\", "/")
    if name.startswith("/") or name.endswith("/") or ".." in name.split("/"):
        raise ValueError(f"Invalid skill name: {value}")
    if not SKILL_NAME_PATTERN.fullmatch(name):
        cleaned = re.sub(r"[^A-Za-z0-9_.-/]+", "-", name).strip("-._/")
        cleaned = re.sub(r"/+", "/", cleaned)
        if not cleaned or not SKILL_NAME_PATTERN.fullmatch(cleaned):
            raise ValueError(f"Invalid skill name: {value}")
        return cleaned
    return name


def _first_paragraph(markdown: str) -> str:
    lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith("#"):
            continue
        lines.append(line)
    return " ".join(lines)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()
