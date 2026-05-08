from __future__ import annotations

import ast
import json

from tinyagent.evals.retrieval import (
    RetrievalCase,
    RetrievalHit,
    check_retrieval_thresholds,
    evaluate_retrieval_case,
    load_retrieval_cases,
    render_retrieval_report,
    run_rg_retrieval_benchmark,
    summarize_retrieval_results,
)


def test_retrieval_metrics_rank_expected_paths(tmp_path) -> None:
    case = RetrievalCase(id="find-dispatch", query="where dispatch happens", expected_paths=("tinyagent/core/kernel.py",))

    result = evaluate_retrieval_case(
        case,
        [
            RetrievalHit(path="tinyagent/core/tools.py"),
            RetrievalHit(path="tinyagent/core/kernel.py", symbol="Kernel._dispatch_tool_call"),
        ],
        backend="rg",
    )

    assert result.hit_at_1 is False
    assert result.hit_at_3 is True
    assert result.hit_at_5 is True
    assert result.reciprocal_rank == 0.5
    assert result.precision_at_5 == 0.5
    assert result.recall_at_5 == 1.0

    summary = summarize_retrieval_results([result])
    report = render_retrieval_report([result])
    assert summary["mrr"] == 0.5
    assert "hit_at_5: 1.000" in report


def test_retrieval_metrics_use_symbol_and_line_relevance(tmp_path) -> None:
    symbol_case = RetrievalCase(id="symbol", query="dispatch", expected_paths=("a.py",), expected_symbols=("target",))
    line_case = RetrievalCase(
        id="line",
        query="needle",
        expected_paths=("a.py",),
        expected_line_ranges=({"path": "a.py", "start": 10, "end": 12},),
    )

    symbol = evaluate_retrieval_case(
        symbol_case,
        [RetrievalHit(path="a.py", symbol="wrong"), RetrievalHit(path="a.py", symbol="target")],
        backend="fake",
    )
    line = evaluate_retrieval_case(
        line_case,
        [
            RetrievalHit(path="a.py", line=1),
            RetrievalHit(path="a.py", line=10),
            RetrievalHit(path="a.py", line=11),
        ],
        backend="fake",
    )

    assert symbol.hit_at_1 is False
    assert symbol.hit_at_3 is True
    assert line.hit_at_1 is False
    assert line.hit_at_3 is True
    assert line.recall_at_5 == 1.0


def test_rg_retrieval_benchmark_searches_workspace_and_thresholds(tmp_path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "dispatch.py").write_text("def dispatch_tool_call():\n    return 'needle'\n")
    cases = [
        RetrievalCase(
            id="find-dispatch",
            query="dispatch_tool_call",
            expected_paths=("pkg/dispatch.py",),
            expected_line_ranges=({"path": "pkg/dispatch.py", "start": 1, "end": 1},),
        )
    ]
    thresholds = tmp_path / "thresholds.json"
    thresholds.write_text('{"min_retrieval_hit_at_5": 1.0}\n')

    results = run_rg_retrieval_benchmark(tmp_path, cases)

    assert results[0].hit_at_1 is True
    assert check_retrieval_thresholds(results, thresholds) == []


def test_retrieval_cases_load_from_json(tmp_path) -> None:
    path = tmp_path / "retrieval.json"
    path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "find-tool-dispatch",
                        "query": "where does dispatch happen",
                        "expected_paths": ["tinyagent/core/kernel.py"],
                        "expected_symbols": ["Kernel._dispatch_tool_call"],
                    }
                ]
            }
        )
    )

    [case] = load_retrieval_cases(path)

    assert case.id == "find-tool-dispatch"
    assert case.expected_paths == ("tinyagent/core/kernel.py",)
    assert case.expected_symbols == ("Kernel._dispatch_tool_call",)


def test_core_does_not_import_evals() -> None:
    core_root = __import__("pathlib").Path(__file__).resolve().parents[1] / "tinyagent" / "core"
    offenders: list[str] = []
    for path in core_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            relative = False
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
                if node.level:
                    relative = True
                    names.extend(alias.name for alias in node.names)
            else:
                continue
            if any(
                name in {"evals", "tinyagent.evals"} or name.startswith("tinyagent.evals.") or (relative and name.startswith("evals"))
                for name in names
            ):
                offenders.append(path.relative_to(core_root.parents[1]).as_posix())

    assert offenders == []
