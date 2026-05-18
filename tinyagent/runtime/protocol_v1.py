"""Shared v1 protocol response helpers."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from tinyagent import __version__

SCHEMA_VERSION = 1

V1_RUN_START_KEYS = frozenset(
    {
        "workspace_id",
        "task",
        "run_id",
        "approval_mode",
        "approvals_reviewer",
        "session_mode",
        "profile",
        "conversation_id",
        "turn_id",
        "parent_turn_id",
    }
)


def health_response(*, version: str = __version__) -> dict[str, object]:
    return {"healthy": True, "version": version, "schema_version": SCHEMA_VERSION}


def error_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, object]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": f"req_{uuid4().hex}",
        }
    }


def run_links(run_id: str, *, workspace_id: str | None = None) -> dict[str, str]:
    query = f"?workspace_id={workspace_id}" if workspace_id else ""
    return {
        "events": f"/v1/runs/{run_id}/events{query}",
        "artifacts": f"/v1/runs/{run_id}/artifacts{query}",
    }


def run_object(summary: dict[str, Any], *, workspace_id: str | None = None) -> dict[str, Any]:
    run_id = str(summary.get("run_id") or summary.get("id") or "")
    return {
        "id": run_id,
        "run_id": run_id,
        "workspace_id": workspace_id or summary.get("workspace_id") or "",
        "conversation_id": summary.get("conversation_id") or "",
        "turn_id": summary.get("turn_id") or "",
        "status": summary.get("status") or "unknown",
        "task": summary.get("task") or "",
        "created_at": summary.get("started_at") or summary.get("created_at") or "",
        "updated_at": summary.get("completed_at") or summary.get("updated_at") or "",
        "started_at": summary.get("started_at") or "",
        "completed_at": summary.get("completed_at"),
        "run_path": summary.get("run_path") or "",
        "model": summary.get("model") or summary.get("model_spec") or {},
        "profile": summary.get("profile") or "",
        "workspace_mode": summary.get("workspace_mode") or "",
        "approval_mode": summary.get("approval_mode") or "",
        "session_mode": summary.get("session_mode") or "normal",
        "approvals_reviewer": summary.get("approvals_reviewer") or "",
        "sandbox_mode": summary.get("sandbox_mode") or "",
        "event_count": summary.get("event_count") or 0,
        "artifact_count": summary.get("artifact_count") or 0,
        "links": run_links(run_id, workspace_id=workspace_id),
    }


def openapi_spec(*, product: bool = False) -> dict[str, Any]:
    paths: dict[str, Any] = {
        "/v1/health": {"get": {"summary": "Health check", "responses": _response("Health")}},
        "/v1/workspaces": {
            "get": {"summary": "List workspaces", "responses": _response("WorkspaceList")},
            "post": {"summary": "Register workspace", "responses": _response("WorkspaceResponse")},
        },
        "/v1/workspaces/{workspace_id}/files": {
            "get": {
                "summary": "List workspace files visible to the TUI",
                "parameters": [_path_param("workspace_id")],
                "responses": _response("WorkspaceFiles"),
            }
        },
        "/v1/workspaces/{workspace_id}/git/status": {
            "get": {
                "summary": "Get git branch, dirty files, and bounded diff for a workspace",
                "parameters": [_path_param("workspace_id")],
                "responses": _response("GitSnapshot"),
            }
        },
        "/v1/conversations": {
            "get": {
                "summary": "List conversations for a workspace",
                "parameters": [_workspace_param(required=False)],
                "responses": _response("ConversationList"),
            }
        },
        "/v1/conversations/{conversation_id}/turns": {
            "get": {
                "summary": "List turns for a conversation",
                "parameters": [_path_param("conversation_id"), _workspace_param(required=False)],
                "responses": _response("ConversationTurnList"),
            }
        },
        "/v1/runs": {
            "get": {"summary": "List runs", "responses": _response("RunList")},
            "post": {
                "summary": "Start run",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/StartRunRequest"}}},
                },
                "responses": _response("RunStartResponse", status="202"),
            },
        },
        "/v1/runs/{run_id}": {"get": {"summary": "Get run", "responses": _response("RunResponse")}},
        "/v1/runs/{run_id}/events": {
            "get": {
                "summary": "Stream run events",
                "parameters": [_path_param("run_id"), _workspace_param(required=False), _after_seq_param()],
                "responses": {
                    "200": {
                        "description": "SSE event stream",
                        "content": {
                            "text/event-stream": {
                                "schema": {"type": "string"},
                                "x-itemSchema": {"$ref": "#/components/schemas/Event"},
                            }
                        },
                    },
                    **_error_responses(),
                },
            }
        },
        "/v1/runs/{run_id}/events.jsonl": {
            "get": {
                "summary": "List run events after a sequence",
                "parameters": [_path_param("run_id"), _workspace_param(required=False), _after_seq_param()],
                "responses": _response("EventList"),
            }
        },
        "/v1/runs/{run_id}/artifacts": {
            "get": {
                "summary": "List public run artifacts",
                "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                "responses": _response("ArtifactList"),
            }
        },
        "/v1/runs/{run_id}/artifacts/{path}": {
            "get": {
                "summary": "Fetch public run artifact",
                "parameters": [_path_param("run_id"), _path_param("path"), _workspace_param(required=False)],
                "responses": {
                    "200": {
                        "description": "Artifact bytes",
                        "content": {
                            "application/octet-stream": {
                                "schema": {"type": "string", "format": "binary"},
                            },
                        },
                    },
                    **_error_responses(),
                },
            }
        },
        "/v1/runs/{run_id}/approvals": {
            "get": {
                "summary": "List pending run approvals",
                "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                "responses": _response("ApprovalList"),
            }
        },
        "/v1/runs/{run_id}/cancel": {
            "post": {
                "summary": "Cancel active run",
                "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                "responses": _response("CancelResponse"),
            }
        },
        "/v1/runs/{run_id}/fork": {
            "post": {
                "summary": "Create fork metadata from a run event",
                "parameters": [_path_param("run_id"), _workspace_param(required=False)],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/RunForkRequest"}}},
                },
                "responses": _response("RunForkResponse", status="201"),
            }
        },
        "/v1/runs/{run_id}/approvals/{approval_id}/resolve": {
            "post": {
                "summary": "Resolve pending approval",
                "parameters": [_path_param("run_id"), _path_param("approval_id"), _workspace_param(required=False)],
                "responses": _response("ApprovalResolutionResponse"),
            }
        },
        "/v1/evals": {
            "post": {
                "summary": "Run an eval suite for a workspace",
                "parameters": [_workspace_param(required=False)],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/EvalRunRequest"}}},
                },
                "responses": _response("EvalRunResponse", status="201"),
            }
        },
        "/v1/skills/drafts": {
            "get": {
                "summary": "List reviewable skill drafts",
                "parameters": [_workspace_param(required=False)],
                "responses": _response("SkillDraftList"),
            },
            "post": {
                "summary": "Draft a skill from a completed run",
                "parameters": [_workspace_param(required=False)],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/SkillDraftRequest"}}},
                },
                "responses": _response("SkillDraftResponse", status="201"),
            },
        },
        "/v1/skills/drafts/{draft_id}": {
            "get": {
                "summary": "Show a skill draft",
                "parameters": [_path_param("draft_id"), _workspace_param(required=False)],
                "responses": _response("SkillDraftMarkdown"),
            }
        },
        "/v1/skills/drafts/{draft_id}/install": {
            "post": {
                "summary": "Install a reviewed skill draft",
                "parameters": [_path_param("draft_id"), _workspace_param(required=False)],
                "responses": _response("SkillDraftActionResponse", status="201"),
            }
        },
        "/v1/skills/drafts/{draft_id}/reject": {
            "post": {
                "summary": "Reject a skill draft",
                "parameters": [_path_param("draft_id"), _workspace_param(required=False)],
                "responses": _response("SkillDraftActionResponse", status="201"),
            }
        },
    }
    if product:
        paths.update(
            {
                "/v1/update": {"get": {"summary": "Show update status", "responses": _response("UpdateStatus")}},
                "/v1/update/check": {
                    "post": {
                        "summary": "Check the configured release channel for updates",
                        "requestBody": {
                            "required": False,
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UpdateRequest"}}},
                        },
                        "responses": _response("UpdateStatus"),
                    }
                },
                "/v1/update/apply": {
                    "post": {
                        "summary": "Apply a verified standalone update",
                        "requestBody": {
                            "required": False,
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/UpdateRequest"}}},
                        },
                        "responses": _response("UpdateStatus"),
                    }
                },
                "/v1/update/rollback": {
                    "post": {"summary": "Rollback to the previous standalone version", "responses": _response("UpdateStatus")}
                },
            }
        )
    schemas = _schemas()
    if product:
        schemas.update(_update_schemas())
    return {
        "openapi": "3.1.0",
        "info": {"title": "tinyagent app protocol", "version": __version__},
        "paths": paths,
        "components": {"schemas": schemas},
    }


def _schemas() -> dict[str, Any]:
    return {
                "Health": _object(
                    {
                        "healthy": {"type": "boolean"},
                        "version": {"type": "string"},
                        "schema_version": {"type": "integer"},
                    }
                ),
                "Workspace": _object(
                    {
                        "workspace_id": {"type": "string"},
                        "id": {"type": "string"},
                        "root": {"type": "string"},
                        "name": {"type": "string"},
                    }
                ),
                "WorkspaceList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Workspace"}}}),
                "WorkspaceResponse": _object({"workspace": {"$ref": "#/components/schemas/Workspace"}}),
                "WorkspaceFiles": _object({"files": {"type": "array", "items": {"type": "string"}}}),
                "GitFileStatus": _object(
                    {
                        "path": {"type": "string"},
                        "oldPath": {"type": "string"},
                        "status": {"type": "string"},
                    }
                ),
                "GitSnapshot": _object(
                    {
                        "isRepo": {"type": "boolean"},
                        "clean": {"type": "boolean"},
                        "branch": {"type": "string"},
                        "ahead": {"type": "integer"},
                        "behind": {"type": "integer"},
                        "files": {"type": "array", "items": {"$ref": "#/components/schemas/GitFileStatus"}},
                        "diff": {"type": "string"},
                        "diffTruncated": {"type": "boolean"},
                        "omittedFiles": {"type": "integer"},
                    }
                ),
                "Conversation": _object(
                    {
                        "conversation_id": {"type": "string"},
                        "title": {"type": "string"},
                        "status": {"type": "string"},
                        "active_turn_id": {"type": ["string", "null"]},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                        "workspace": {"type": "string"},
                        "turn_count": {"type": "integer"},
                        "last_run_id": {"type": "string"},
                        "last_turn_status": {"type": "string"},
                    }
                ),
                "ConversationTurn": _object(
                    {
                        "type": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "turn_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "run_path": {"type": "string"},
                        "created_at": {"type": "string"},
                        "completed_at": {"type": "string"},
                        "status": {"type": "string"},
                    }
                ),
                "ConversationList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Conversation"}}}),
                "ConversationTurnList": _object(
                    {
                        "conversation_id": {"type": "string"},
                        "items": {"type": "array", "items": {"$ref": "#/components/schemas/ConversationTurn"}},
                    }
                ),
                "StartRunRequest": _object(
                    {
                        "workspace_id": {"type": "string"},
                        "task": {"type": "string"},
                        "run_id": {"type": "string"},
                        "approval_mode": {"type": "string"},
                        "session_mode": {"type": "string"},
                        "approvals_reviewer": {"type": "string"},
                        "profile": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "turn_id": {"type": "string"},
                        "parent_turn_id": {"type": "string"},
                    }
                ),
                "Run": _object(
                    {
                        "id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "workspace_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "turn_id": {"type": "string"},
                        "status": {"type": "string"},
                        "task": {"type": "string"},
                        "created_at": {"type": "string"},
                        "updated_at": {"type": "string"},
                        "started_at": {"type": "string"},
                        "completed_at": {"type": ["string", "null"]},
                        "run_path": {"type": "string"},
                        "model": {"type": "object"},
                        "profile": {"type": "string"},
                        "workspace_mode": {"type": "string"},
                        "approval_mode": {"type": "string"},
                        "session_mode": {"type": "string"},
                        "approvals_reviewer": {"type": "string"},
                        "sandbox_mode": {"type": "string"},
                        "event_count": {"type": "integer"},
                        "artifact_count": {"type": "integer"},
                        "links": {"type": "object", "additionalProperties": {"type": "string"}},
                    }
                ),
                "RunList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Run"}}}),
                "RunResponse": _object({"run": {"$ref": "#/components/schemas/Run"}}),
                "RunStartResponse": _object({"run": {"$ref": "#/components/schemas/Run"}, "events_url": {"type": "string"}}),
                "Event": _object(
                    {
                        "id": {"type": "string"},
                        "seq": {"type": "integer"},
                        "type": {"type": "string"},
                        "run_id": {"type": "string"},
                        "turn_id": {"type": ["string", "null"]},
                        "item_id": {"type": ["string", "null"]},
                        "parent_item_id": {"type": ["string", "null"]},
                        "source": {"type": "string"},
                        "visibility": {"type": "string"},
                        "durability": {"type": "string"},
                        "time": {"type": "string"},
                        "data": {"type": "object"},
                        "artifact_refs": {"type": "array", "items": {"type": "string"}},
                        "workspace_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                    }
                ),
                "EventList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Event"}}}),
                "Artifact": _object(
                    {
                        "path": {"type": "string"},
                        "kind": {"type": "string"},
                        "bytes": {"type": "integer"},
                        "created_at": {"type": ["string", "object"]},
                        "safe_to_display": {"type": "boolean"},
                    }
                ),
                "ArtifactList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Artifact"}}}),
                "Approval": _object(
                    {
                        "approval_id": {"type": "string"},
                        "run_id": {"type": "string"},
                        "turn_id": {"type": ["string", "null"]},
                        "step_id": {"type": ["string", "null"]},
                        "action_kind": {"type": "string"},
                        "tool_name": {"type": "string"},
                        "cwd": {"type": "string"},
                        "args_preview": {"type": "string"},
                        "command": {"type": ["string", "null"]},
                        "risk": {"type": "string"},
                    }
                ),
                "ApprovalList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/Approval"}}}),
                "ApprovalResolutionResponse": _object({"resolved": {"type": "boolean"}}),
                "CancelResponse": _object({"cancelled": {"type": "boolean"}}),
                "RunForkRequest": _object({"at": {"type": "string"}}, required=["at"]),
                "RunForkResponse": _object({"fork_dir": {"type": "string"}}),
                "EvalRunRequest": _object(
                    {
                        "workspace_id": {"type": "string"},
                        "suite_path": {"type": "string"},
                        "output_dir": {"type": "string"},
                        "approval_mode": {"type": "string"},
                        "session_mode": {"type": "string"},
                        "approvals_reviewer": {"type": "string"},
                        "profile": {"type": "string"},
                    }
                ),
                "EvalResult": _object(
                    {
                        "case_id": {"type": "string"},
                        "success": {"type": "boolean"},
                        "status": {"type": "string"},
                        "validation_ok": {"type": "boolean"},
                        "model_call_count": {"type": "integer"},
                        "tool_call_count": {"type": "integer"},
                        "failure_reason": {"type": "string"},
                    }
                ),
                "EvalRunResponse": _object(
                    {
                        "suite_path": {"type": "string"},
                        "output_dir": {"type": "string"},
                        "total": {"type": "integer"},
                        "passed": {"type": "integer"},
                        "report": {"type": "string"},
                        "results": {"type": "array", "items": {"$ref": "#/components/schemas/EvalResult"}},
                    }
                ),
                "SkillDraft": _object(
                    {
                        "draft_id": {"type": "string"},
                        "name": {"type": "string"},
                        "path": {"type": "string"},
                        "status": {"type": "string"},
                        "source_run_id": {"type": "string"},
                        "created_at": {"type": "string"},
                    }
                ),
                "SkillDraftList": _object({"items": {"type": "array", "items": {"$ref": "#/components/schemas/SkillDraft"}}}),
                "SkillDraftRequest": _object({"workspace_id": {"type": "string"}, "run_id": {"type": "string"}}),
                "SkillDraftResponse": _object({"draft": {"$ref": "#/components/schemas/SkillDraft"}}),
                "SkillDraftMarkdown": _object({"draft_id": {"type": "string"}, "markdown": {"type": "string"}}),
                "SkillDraftActionResponse": _object({"draft_id": {"type": "string"}, "path": {"type": "string"}}),
                "ErrorResponse": _object(
                    {
                        "error": _object(
                            {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                                "details": {"type": "object"},
                                "request_id": {"type": "string"},
                            }
                        )
                    }
                ),
    }


def _update_schemas() -> dict[str, Any]:
    return {
        "UpdateArtifact": _object(
            {
                "platform": {"type": "string"},
                "url": {"type": "string"},
                "sha256": {"type": "string"},
                "size": {"type": ["integer", "null"]},
                "kind": {"type": "string"},
                "expected_files": {"type": "array", "items": {"type": "string"}},
            }
        ),
        "UpdateStatus": _object(
            {
                "current_version": {"type": "string"},
                "channel": {"type": "string"},
                "install_kind": {"type": "string"},
                "manifest_source": {"type": "string"},
                "checked_at": {"type": "string"},
                "latest_version": {"type": "string"},
                "available": {"type": "boolean"},
                "reason": {"type": "string"},
                "platform": {"type": "string"},
                "artifact": {"anyOf": [{"$ref": "#/components/schemas/UpdateArtifact"}, {"type": "null"}]},
                "active_version": {"type": "string"},
                "previous_version": {"type": "string"},
            }
        ),
        "UpdateRequest": _object({"channel": {"type": "string"}, "manifest_source": {"type": "string"}, "manifest": {"type": "string"}}),
    }


def _object(properties: dict[str, Any], *, required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": True}
    if required:
        schema["required"] = required
    return schema


def _response(schema: str, *, status: str = "200") -> dict[str, Any]:
    return {
        status: {
            "description": schema,
            "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{schema}"}}},
        },
        **_error_responses(),
    }


def _error_responses() -> dict[str, Any]:
    error = {"description": "Error", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorResponse"}}}}
    return {"400": error, "403": error, "404": error}


def _path_param(name: str) -> dict[str, Any]:
    return {"name": name, "in": "path", "required": True, "schema": {"type": "string"}}


def _workspace_param(*, required: bool) -> dict[str, Any]:
    return {"name": "workspace_id", "in": "query", "required": required, "schema": {"type": "string"}}


def _after_seq_param() -> dict[str, Any]:
    return {"name": "after_seq", "in": "query", "schema": {"type": "integer"}}
