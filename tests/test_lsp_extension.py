from __future__ import annotations

from tinyagent.app.product import ProductHome
from tinyagent.app.server import ProductRuntimeController
from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ModelResponse, RunBudgets, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.extensions.lsp import (
    InMemoryLspClient,
    LspConfig,
    LspDiagnostic,
    LspExtension,
    LspLocation,
    LspManager,
    LspServerConfig,
    LspSymbol,
    load_lsp_config,
)
from tinyagent.extensions.lsp.context import LspSymbolsSource
from tinyagent.extensions.lsp.tools import LspDefinitionTool, LspDiagnosticsTool, LspReferencesTool, LspSymbolsTool


def test_lsp_tools_return_unavailable_when_disabled(tmp_path) -> None:
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_unavailable")
    result = LspSymbolsTool(LspManager()).run(ToolCall(name="lsp_symbols", args={"query": "Kernel"}), state)

    assert result.ok is False
    assert result.failure_kind == "unavailable"
    assert "LSP unavailable" in result.output


def test_lsp_tools_use_configured_fake_server_lazily(tmp_path) -> None:
    (tmp_path / "tiny.py").write_text("def dispatch():\n    dispatch()\n")
    client = InMemoryLspClient(
        symbols=[LspSymbol(name="dispatch", kind="function", path="tiny.py", line=1)],
        definitions={("tiny.py", 2, 5): [LspLocation(path="tiny.py", line=1, column=5)]},
        references={("tiny.py", 1, 5): [LspLocation(path="tiny.py", line=2, column=5)]},
        diagnostics=[LspDiagnostic(path="tiny.py", line=2, message="example diagnostic", severity="information")],
    )
    manager = LspManager(
        config=LspConfig(
            enabled=True,
            servers=(LspServerConfig(name="python", command=("pyright-langserver", "--stdio"), extensions=(".py",)),),
        ),
        clients={"python": client},
    )
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp")

    symbols = LspSymbolsTool(manager).run(ToolCall(name="lsp_symbols", args={"path": "tiny.py", "query": "dispatch"}), state)
    definition = LspDefinitionTool(manager).run(
        ToolCall(name="lsp_definition", args={"path": "tiny.py", "line": 2, "column": 5}),
        state,
    )
    references = LspReferencesTool(manager).run(
        ToolCall(name="lsp_references", args={"path": "tiny.py", "line": 1, "column": 5}),
        state,
    )
    diagnostics = LspDiagnosticsTool(manager).run(ToolCall(name="lsp_diagnostics", args={"path": "tiny.py"}), state)

    assert manager.started == ["python"]
    assert "dispatch" in symbols.output
    assert "tiny.py:1:5" in definition.output
    assert "tiny.py:2:5" in references.output
    assert "example diagnostic" in diagnostics.output
    assert [event.data["name"] for event in state.events if event.type == "extension.event" and event.data["extension"] == "lsp"] == [
        "lsp.symbols.listed",
        "lsp.definition.resolved",
        "lsp.references.resolved",
        "lsp.diagnostics.listed",
    ]


def test_lsp_context_source_search_and_read(tmp_path) -> None:
    manager = LspManager(
        config=LspConfig(enabled=True, servers=(LspServerConfig(name="python", command=("pyright",), extensions=(".py",)),)),
        clients={"python": InMemoryLspClient(symbols=[LspSymbol(name="dispatch", kind="function", path="tiny.py", line=3)])},
    )
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_context")
    state.context_registry = ContextRegistry([LspSymbolsSource(manager)])

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "dispatch", "source": "lsp_symbols"}), state)
    read = ContextReadTool().run(
        ToolCall(name="context_read", args={"ref": "lsp_symbols:symbol:tiny.py:3:dispatch"}),
        state,
    )

    assert searched.ok is True
    assert "lsp_symbols:symbol:tiny.py:3:dispatch" in searched.output
    assert read.ok is True
    assert "dispatch" in read.output


def test_lsp_policy_is_conservative_and_path_bounded(tmp_path) -> None:
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_policy")

    ask = LocalPolicy().evaluate(ToolCall(name="lsp_symbols", args={"path": "."}), state)
    denied = LocalPolicy().evaluate(ToolCall(name="lsp_symbols", args={"path": "../outside.py"}), state)

    assert ask.kind == "needs_approval"
    assert denied.kind == "deny"


def test_lsp_context_policy_uses_lsp_permission(tmp_path) -> None:
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_context_policy")

    combined = LocalPolicy().evaluate(ToolCall(name="context_search", args={"query": "dispatch"}), state)
    search = LocalPolicy().evaluate(ToolCall(name="context_search", args={"query": "dispatch", "source": "lsp_symbols"}), state)
    read = LocalPolicy().evaluate(ToolCall(name="context_read", args={"ref": "lsp_symbols:symbol:tiny.py:3:dispatch"}), state)

    assert combined.kind == "needs_approval"
    assert combined.permission == "lsp"
    assert search.kind == "needs_approval"
    assert search.permission == "lsp"
    assert read.kind == "needs_approval"
    assert read.permission == "lsp"


def test_lsp_extension_tools_are_visible_only_when_extension_is_enabled(tmp_path) -> None:
    manager = LspManager(
        config=LspConfig(enabled=True, servers=(LspServerConfig(name="python", command=("pyright",), extensions=(".py",)),)),
        clients={"python": InMemoryLspClient()},
    )
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        extensions=[LspExtension(manager)],
        budgets=RunBudgets(max_model_calls=1),
    ).run("lsp", workspace=tmp_path, run_id="run_lsp_kernel")

    context_built = next(event for event in state.events if event.type == "context.built")
    assert "lsp_symbols" in context_built.data["visible_tools"]
    assert "lsp_symbols" in state.context_registry.sources


def test_disabled_lsp_extension_registers_no_surface(tmp_path) -> None:
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        extensions=[LspExtension(LspManager(config=LspConfig(enabled=False)))],
        budgets=RunBudgets(max_model_calls=1),
    ).run("lsp", workspace=tmp_path, run_id="run_lsp_disabled")

    context_built = next(event for event in state.events if event.type == "context.built")
    assert "lsp_symbols" not in context_built.data["visible_tools"]
    assert "lsp_symbols" not in state.context_registry.sources


def test_lsp_workspace_symbols_query_all_clients(tmp_path) -> None:
    manager = LspManager(
        config=LspConfig(
            enabled=True,
            servers=(
                LspServerConfig(name="python", command=("pyright",), extensions=(".py",)),
                LspServerConfig(name="ts", command=("typescript-language-server", "--stdio"), extensions=(".ts",)),
            ),
        ),
        clients={
            "python": InMemoryLspClient(symbols=[LspSymbol(name="dispatch_py", kind="function", path="tiny.py", line=1)]),
            "ts": InMemoryLspClient(symbols=[LspSymbol(name="dispatch_ts", kind="function", path="tiny.ts", line=1)]),
        },
    )
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_multi")

    result = LspSymbolsTool(manager).run(ToolCall(name="lsp_symbols", args={"query": "dispatch"}), state)

    assert "dispatch_py" in result.output
    assert "dispatch_ts" in result.output


def test_lsp_filters_protected_and_external_result_paths(tmp_path) -> None:
    client = InMemoryLspClient(
        symbols=[
            LspSymbol(name="safe", kind="function", path="safe.py", line=1),
            LspSymbol(name="secret", kind="constant", path=".env", line=1),
        ],
        definitions={("safe.py", 1, 1): [LspLocation(path="../outside.py", line=1), LspLocation(path="safe.py", line=1)]},
        diagnostics=[
            LspDiagnostic(path=".tinyagent/runs/run_x/events.jsonl", line=1, message="hidden"),
            LspDiagnostic(path="safe.py", line=2, message="visible"),
        ],
    )
    manager = LspManager(
        config=LspConfig(enabled=True, servers=(LspServerConfig(name="python", command=("pyright",), extensions=(".py",)),)),
        clients={"python": client},
    )
    (tmp_path / "safe.py").write_text("safe = True\n")
    state = RunState.create("lsp", Workspace(tmp_path), run_id="run_lsp_filter")

    symbols = LspSymbolsTool(manager).run(ToolCall(name="lsp_symbols", args={"query": ""}), state)
    definition = LspDefinitionTool(manager).run(
        ToolCall(name="lsp_definition", args={"path": "safe.py", "line": 1, "column": 1}),
        state,
    )
    diagnostics = LspDiagnosticsTool(manager).run(ToolCall(name="lsp_diagnostics", args={}), state)

    assert "safe.py" in symbols.output
    assert ".env" not in symbols.output
    assert "../outside.py" not in definition.output
    assert ".tinyagent" not in diagnostics.output
    assert "visible" in diagnostics.output


def test_lsp_config_parser_and_product_status(tmp_path) -> None:
    home = ProductHome(tmp_path / "home")
    home.ensure()
    home.config_path.write_text(
        "[extensions.lsp]\n"
        "enabled = true\n"
        "[extensions.lsp.servers.python]\n"
        'command = ["pyright-langserver", "--stdio"]\n'
        'extensions = [".py"]\n'
        'permission = "allow"\n'
    )
    config = load_lsp_config(home.config_path)
    assert config.enabled is True
    assert config.servers[0].name == "python"

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    product = ProductRuntimeController(
        home=home,
        provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="done")]),
    )
    record = product.register_workspace(workspace)
    controller = product.controller_for_workspace(record["workspace_id"])

    assert controller.lsp_servers() == [
        {"name": "python", "enabled": True, "status": "configured", "extensions": [".py"], "permission": "allow"}
    ]


def test_lsp_config_merge_does_not_disable_when_workspace_has_no_lsp_table(tmp_path) -> None:
    home_config = tmp_path / "home.toml"
    workspace_config = tmp_path / "workspace.toml"
    home_config.write_text(
        "[extensions.lsp]\n"
        "enabled = true\n"
        "[extensions.lsp.servers.python]\n"
        'command = ["pyright"]\n'
        'extensions = [".py"]\n'
    )
    workspace_config.write_text("[mcp.github]\nenabled = false\n")

    config = load_lsp_config(home_config, workspace_config)

    assert config.enabled is True
    assert [server.name for server in config.servers] == ["python"]
