from __future__ import annotations

from tinyagent.app.product import ProductHome
from tinyagent.app.server import ProductRuntimeController
from tinyagent.core.context_sources import ContextReadTool, ContextRegistry, ContextSearchTool
from tinyagent.core.kernel import Kernel
from tinyagent.core.models import FakeModelProvider
from tinyagent.core.policy import LocalPolicy, PolicyConfig, PolicyRule
from tinyagent.core.profiles import ApexCoderProfile
from tinyagent.core.state import ModelResponse, RunBudgets, RunState, ToolCall, Workspace
from tinyagent.core.tools import default_tools
from tinyagent.extensions.mcp import InMemoryMcpClient, McpConfig, McpExtension, McpResult, McpToolInfo
from tinyagent.extensions.mcp.context import McpToolCatalogueSource
from tinyagent.extensions.mcp.tools import McpCallTool, McpLoadToolTool, McpSearchToolsTool
from tinyagent.runtime.server import RunController, RuntimeConfig


def test_mcp_config_parses_deferred_server() -> None:
    config = McpConfig.from_dict(
        {
            "mcp": {
                "github": {
                    "enabled": True,
                    "type": "stdio",
                    "command": ["github-mcp-server"],
                    "exposure": "deferred",
                    "permission": "ask",
                }
            }
        }
    )

    server = config.servers[0]
    assert server.name == "github"
    assert server.command == ("github-mcp-server",)
    assert server.exposure == "deferred"


def test_mcp_deferred_search_load_and_call_large_result(tmp_path) -> None:
    tool = McpToolInfo(
        server="github",
        name="search_issues",
        description="Search GitHub issues",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        permission="ask",
    )
    client = InMemoryMcpClient(
        tools=[tool],
        tool_results={"search_issues": McpResult(content="issue\n" * 10_000)},
    )
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp")
    clients = {"github": client}

    searched = McpSearchToolsTool(clients).run(ToolCall(name="mcp_search_tools", args={"query": "issues"}), state)
    loaded = McpLoadToolTool(clients).run(ToolCall(name="mcp_load_tool", args={"server": "github", "tool": "search_issues"}), state)
    called = McpCallTool(clients).run(
        ToolCall(
            name="mcp_call",
            args={"server": "github", "tool": "search_issues", "arguments": {"query": "repo:owner/repo"}},
        ),
        state,
    )

    assert searched.ok is True
    assert "github.search_issues" in searched.output
    assert loaded.ok is True
    assert "schema" in loaded.output
    assert called.ok is True
    assert called.truncated is True
    assert called.data["context_ref"].startswith("contextfs:context/mcp_call/")
    assert (state.output_dir / called.artifact_path).exists()
    assert [event.data["name"] for event in state.events if event.type == "extension.event" and event.data["extension"] == "mcp"] == [
        "mcp.tools.searched",
        "mcp.tool.loaded",
        "mcp.tool.called",
    ]


def test_mcp_context_source_search_and_read(tmp_path) -> None:
    client = InMemoryMcpClient(
        tools=[
            McpToolInfo(
                server="linear",
                name="search_issues",
                description="Search Linear issues",
                input_schema={"type": "object"},
            )
        ]
    )
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_context")
    state.context_registry = ContextRegistry([McpToolCatalogueSource({"linear": client})])

    searched = ContextSearchTool().run(ToolCall(name="context_search", args={"query": "Linear", "source": "mcp_tools"}), state)
    read = ContextReadTool().run(
        ToolCall(name="context_read", args={"ref": "mcp_tools:mcp-tool:linear/search_issues"}),
        state,
    )

    assert searched.ok is True
    assert "mcp_tools:mcp-tool:linear/search_issues" in searched.output
    assert read.ok is True
    assert "linear.search_issues" in read.output
    event = next(event for event in state.events if event.type == "context.search.completed")
    assert event.data["refs"] == ["mcp_tools:mcp-tool:linear/search_issues"]
    assert "results" not in event.data


def test_mcp_policy_defaults_to_approval_and_network_guard(tmp_path) -> None:
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_policy")
    search = LocalPolicy().evaluate(ToolCall(name="mcp_search_tools", args={"query": "issues"}), state)
    call = LocalPolicy().evaluate(
        ToolCall(name="mcp_call", args={"server": "github", "tool": "create_issue", "arguments": {}}),
        state,
    )
    allowed_mcp_config = PolicyConfig(rules=(PolicyRule("mcp_tool", "github.create_issue", "allow"),))
    network_blocked = LocalPolicy(config=allowed_mcp_config).evaluate(
        ToolCall(name="mcp_call", args={"server": "github", "tool": "create_issue", "arguments": {}}),
        state,
    )
    denied_config = PolicyConfig(rules=(PolicyRule("mcp_tool", "github.create_issue", "deny"),))
    denied = LocalPolicy(config=denied_config).evaluate(
        ToolCall(name="mcp_call", args={"server": "github", "tool": "create_issue", "arguments": {}}),
        state,
    )

    assert search.kind == "needs_approval"
    assert call.kind == "needs_approval"
    assert network_blocked.kind == "deny"
    assert network_blocked.permission == "network"
    assert denied.kind == "deny"


def test_mcp_context_source_uses_mcp_policy(tmp_path) -> None:
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_context_policy")
    denied_config = PolicyConfig(
        rules=(
            PolicyRule("mcp_server", "*", "deny"),
            PolicyRule("context_search", "*", "allow"),
            PolicyRule("context_read", "mcp_tools:*", "allow"),
        )
    )
    policy = LocalPolicy(config=denied_config)

    search = policy.evaluate(ToolCall(name="context_search", args={"query": "issues", "source": "mcp_tools"}), state)
    read = policy.evaluate(ToolCall(name="context_read", args={"ref": "mcp_tools:mcp-tool:github/search_issues"}), state)

    assert search.kind == "deny"
    assert search.permission == "mcp_server"
    assert read.kind == "deny"
    assert read.permission == "mcp_server"


def test_mcp_hidden_tools_cannot_load_call_or_context_read(tmp_path) -> None:
    hidden = McpToolInfo(server="github", name="secret_tool", description="hidden", exposure="hidden")
    client = InMemoryMcpClient(tools=[hidden], tool_results={"secret_tool": McpResult(content="called")})
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_hidden")
    clients = {"github": client}

    searched = McpSearchToolsTool(clients).run(ToolCall(name="mcp_search_tools", args={"query": "hidden"}), state)
    loaded = McpLoadToolTool(clients).run(ToolCall(name="mcp_load_tool", args={"server": "github", "tool": "secret_tool"}), state)
    called = McpCallTool(clients).run(
        ToolCall(name="mcp_call", args={"server": "github", "tool": "secret_tool", "arguments": {}}),
        state,
    )
    state.context_registry = ContextRegistry([McpToolCatalogueSource(clients)])
    read = ContextReadTool().run(ToolCall(name="context_read", args={"ref": "mcp_tools:mcp-tool:github/secret_tool"}), state)

    assert "No MCP tools found" in searched.output
    assert loaded.ok is False
    assert called.ok is False
    assert read.ok is False


def test_mcp_structured_result_is_preserved(tmp_path) -> None:
    tool = McpToolInfo(server="github", name="search_issues", description="Search GitHub issues")
    client = InMemoryMcpClient(
        tools=[tool],
        tool_results={"search_issues": McpResult(content="", structured_content={"issues": [{"title": "Bug"}]})},
    )
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_structured")

    result = McpCallTool({"github": client}).run(
        ToolCall(name="mcp_call", args={"server": "github", "tool": "search_issues", "arguments": {}}),
        state,
    )

    assert result.ok is True
    assert '"issues"' in result.output
    assert "Bug" in result.output


def test_mcp_large_loaded_schema_gets_context_artifact(tmp_path) -> None:
    schema = {"type": "object", "description": "x" * 20_000}
    tool = McpToolInfo(server="github", name="large_tool", description="Large schema", input_schema=schema)
    state = RunState.create("mcp", Workspace(tmp_path), run_id="run_mcp_large_schema")

    result = McpLoadToolTool({"github": InMemoryMcpClient(tools=[tool])}).run(
        ToolCall(name="mcp_load_tool", args={"server": "github", "tool": "large_tool"}),
        state,
    )

    assert result.ok is True
    assert result.truncated is True
    assert result.data["context_ref"].startswith("contextfs:context/mcp_load_tool/")
    assert result.artifact_path
    assert (state.output_dir / result.artifact_path).exists()


def test_mcp_extension_adds_tools_and_context_source_to_default_kernel(tmp_path) -> None:
    client = InMemoryMcpClient(
        tools=[McpToolInfo(server="github", name="search_issues", description="Search GitHub issues")]
    )
    state = Kernel(
        model=FakeModelProvider([ModelResponse(content="done")]),
        profile=ApexCoderProfile(),
        tools=default_tools(),
        policy=LocalPolicy(),
        extensions=[McpExtension({"github": client})],
        budgets=RunBudgets(max_model_calls=1),
    ).run("mcp", workspace=tmp_path, run_id="run_mcp_kernel")

    context_built = next(event for event in state.events if event.type == "context.built")
    assert "mcp_search_tools" in context_built.data["visible_tools"]
    assert "mcp_tools" in state.context_registry.sources


def test_run_controller_reports_mcp_status(tmp_path) -> None:
    client = InMemoryMcpClient(
        tools=[McpToolInfo(server="github", name="search_issues")],
    )
    controller = RunController(
        RuntimeConfig(
            workspace=tmp_path,
            run_root=tmp_path / "runs",
            provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="done")]),
            mcp_clients={"github": client},
        )
    )

    assert controller.mcp_servers() == [
        {"name": "github", "enabled": True, "status": "ready", "tool_count": 1, "resource_count": 0, "error": ""}
    ]


def test_product_runtime_reports_configured_mcp_server_without_client(tmp_path) -> None:
    home = ProductHome(tmp_path / "home")
    home.ensure()
    home.config_path.write_text('[mcp.github]\nenabled = true\ntype = "stdio"\ncommand = ["github-mcp-server"]\n')
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    product = ProductRuntimeController(
        home=home,
        provider_factory=lambda _task: FakeModelProvider([ModelResponse(content="done")]),
    )
    record = product.register_workspace(workspace)

    controller = product.controller_for_workspace(record["workspace_id"])

    assert controller.mcp_servers() == [
        {"name": "github", "enabled": True, "status": "configured", "tool_count": 0, "resource_count": 0, "error": ""}
    ]
