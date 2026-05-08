"""Model-free retrieval benchmark helpers."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tinyagent.core.index import RgWorkspaceIndex


@dataclass(frozen=True)
class RetrievalCase:
    id: str
    query: str
    expected_paths: tuple[str, ...] = ()
    expected_symbols: tuple[str, ...] = ()
    expected_line_ranges: tuple[dict[str, int | str], ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalCase:
        return cls(
            id=str(data["id"]),
            query=str(data["query"]),
            expected_paths=tuple(str(path) for path in data.get("expected_paths") or ()),
            expected_symbols=tuple(str(symbol) for symbol in data.get("expected_symbols") or ()),
            expected_line_ranges=tuple(dict(item) for item in data.get("expected_line_ranges") or () if isinstance(item, dict)),
        )


@dataclass(frozen=True)
class RetrievalHit:
    path: str
    symbol: str = ""
    line: int | None = None
    score: float = 0.0


@dataclass(frozen=True)
class RetrievalResult:
    case_id: str
    query: str
    backend: str
    latency_ms: float
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float
    precision_at_5: float
    recall_at_5: float
    result_count: int
    hits: tuple[RetrievalHit, ...] = field(default_factory=tuple)

    def to_json_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["hits"] = [asdict(hit) for hit in self.hits]
        return data


def load_retrieval_cases(path: Path) -> list[RetrievalCase]:
    raw = json.loads(path.expanduser().read_text())
    if isinstance(raw, dict):
        raw_cases = raw.get("cases") or []
    else:
        raw_cases = raw
    return [RetrievalCase.from_dict(item) for item in raw_cases if isinstance(item, dict)]


def evaluate_retrieval_case(
    case: RetrievalCase,
    hits: list[RetrievalHit],
    *,
    backend: str,
    started_at: float | None = None,
) -> RetrievalResult:
    latency_ms = (time.perf_counter() - started_at) * 1000 if started_at is not None else 0.0
    expected_count = max(_expected_item_count(case), 1)
    relevant_seen: set[tuple[object, ...]] = set()
    relevant_ranks: list[int] = []
    for index, hit in enumerate(hits, start=1):
        key = _relevance_key(case, hit)
        if key is None or key in relevant_seen:
            continue
        relevant_seen.add(key)
        relevant_ranks.append(index)
    first_rank = relevant_ranks[0] if relevant_ranks else 0
    top5 = hits[:5]
    relevant_top5 = len({key for hit in top5 if (key := _relevance_key(case, hit)) is not None})
    return RetrievalResult(
        case_id=case.id,
        query=case.query,
        backend=backend,
        latency_ms=latency_ms,
        hit_at_1=bool(first_rank and first_rank <= 1),
        hit_at_3=bool(first_rank and first_rank <= 3),
        hit_at_5=bool(first_rank and first_rank <= 5),
        reciprocal_rank=(1 / first_rank) if first_rank else 0.0,
        precision_at_5=relevant_top5 / max(len(top5), 1),
        recall_at_5=relevant_top5 / expected_count,
        result_count=len(hits),
        hits=tuple(hits),
    )


def run_rg_retrieval_benchmark(root: Path, cases: list[RetrievalCase], *, limit: int = 5) -> list[RetrievalResult]:
    index = RgWorkspaceIndex()
    results: list[RetrievalResult] = []
    for case in cases:
        started = time.perf_counter()
        index_hits = index.search(case.query, root=root, limit=limit)
        hits = [
            RetrievalHit(
                path=hit.path,
                line=hit.line_start,
                score=hit.score or 0.0,
            )
            for hit in index_hits
        ]
        results.append(evaluate_retrieval_case(case, hits, backend=index.name, started_at=started))
    return results


def check_retrieval_thresholds(results: list[RetrievalResult], threshold_path: Path) -> list[str]:
    config = json.loads(threshold_path.expanduser().read_text())
    summary = summarize_retrieval_results(results)
    failures: list[str] = []
    min_hit_at_5 = config.get("min_retrieval_hit_at_5")
    if min_hit_at_5 is not None and summary["hit_at_5"] < float(min_hit_at_5):
        failures.append(f"retrieval_hit_at_5 {summary['hit_at_5']:.3f} < {float(min_hit_at_5):.3f}")
    return failures


def summarize_retrieval_results(results: list[RetrievalResult]) -> dict[str, float]:
    total = max(len(results), 1)
    return {
        "hit_at_1": sum(1 for result in results if result.hit_at_1) / total,
        "hit_at_3": sum(1 for result in results if result.hit_at_3) / total,
        "hit_at_5": sum(1 for result in results if result.hit_at_5) / total,
        "mrr": sum(result.reciprocal_rank for result in results) / total,
        "precision_at_5": sum(result.precision_at_5 for result in results) / total,
        "recall_at_5": sum(result.recall_at_5 for result in results) / total,
        "latency_ms": sum(result.latency_ms for result in results) / total,
    }


def render_retrieval_report(results: list[RetrievalResult]) -> str:
    summary = summarize_retrieval_results(results)
    lines = [
        "# Retrieval Benchmark",
        "",
        f"cases: {len(results)}",
        f"hit_at_1: {summary['hit_at_1']:.3f}",
        f"hit_at_3: {summary['hit_at_3']:.3f}",
        f"hit_at_5: {summary['hit_at_5']:.3f}",
        f"mrr: {summary['mrr']:.3f}",
        f"precision_at_5: {summary['precision_at_5']:.3f}",
        f"recall_at_5: {summary['recall_at_5']:.3f}",
        "",
        "| Case | Backend | Hit@5 | MRR | Results |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for result in results:
        lines.append(
            f"| {result.case_id} | {result.backend} | {str(result.hit_at_5).lower()} | "
            f"{result.reciprocal_rank:.3f} | {result.result_count} |"
        )
    return "\n".join(lines) + "\n"


def _expected_item_count(case: RetrievalCase) -> int:
    return len(case.expected_line_ranges) or len(case.expected_symbols) or len(case.expected_paths)


def _relevance_key(case: RetrievalCase, hit: RetrievalHit) -> tuple[object, ...] | None:
    if case.expected_line_ranges:
        for item in case.expected_line_ranges:
            path = str(item.get("path") or "")
            start = int(item.get("start") or 0)
            end = int(item.get("end") or start)
            if hit.path == path and hit.line is not None and start <= hit.line <= end:
                return ("line_range", path, start, end)
        return None
    if case.expected_symbols:
        if hit.symbol and hit.symbol in case.expected_symbols:
            return ("symbol", hit.symbol)
        return None
    if hit.path in case.expected_paths:
        return ("path", hit.path)
    return None
