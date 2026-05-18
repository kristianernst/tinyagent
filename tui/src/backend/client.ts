import type {
  Approval,
  ApprovalDecision,
  Artifact,
  Conversation,
  ConversationTurn,
  EvalRunResponse,
  GitSnapshot,
  RunEvent,
  RunObject,
  SkillDraft,
  StartRunRequest,
  StartRunResponse,
  UpdateStatus,
  Workspace,
} from "../protocol/events";
import { readSse } from "./sse";

export class TinyAgentClient {
  readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async health(): Promise<{ healthy: boolean; schema_version: number; version: string }> {
    return this.json("GET", "/v1/health");
  }

  async listWorkspaces(): Promise<Workspace[]> {
    return (await this.json<{ items: Workspace[] }>("GET", "/v1/workspaces")).items ?? [];
  }

  async workspaceFiles(workspaceId: string): Promise<string[]> {
    const body = await this.json<{ files: string[] }>("GET", `/v1/workspaces/${encodeURIComponent(workspaceId)}/files`);
    return Array.isArray(body.files) ? body.files : [];
  }

  async gitStatus(workspaceId: string): Promise<GitSnapshot> {
    return this.json("GET", `/v1/workspaces/${encodeURIComponent(workspaceId)}/git/status`);
  }

  async listConversations(workspaceId?: string): Promise<Conversation[]> {
    const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return (await this.json<{ items: Conversation[] }>("GET", `/v1/conversations${query}`)).items ?? [];
  }

  async conversationTurns(conversationId: string, workspaceId?: string): Promise<ConversationTurn[]> {
    const query = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : "";
    return (await this.json<{ items: ConversationTurn[] }>("GET", `/v1/conversations/${encodeURIComponent(conversationId)}/turns${query}`))
      .items ?? [];
  }

  async startRun(request: StartRunRequest): Promise<StartRunResponse> {
    return this.json("POST", "/v1/runs", request);
  }

  async getRun(runId: string, workspaceId?: string): Promise<RunObject> {
    return (await this.json<{ run: RunObject }>("GET", `/v1/runs/${encodeURIComponent(runId)}${query({ workspace_id: workspaceId })}`)).run;
  }

  async events(runId: string, workspaceId?: string, afterSeq = 0): Promise<RunEvent[]> {
    const params: Record<string, string | number | undefined> = { workspace_id: workspaceId };
    if (afterSeq > 0) params.after_seq = afterSeq;
    return (await this.json<{ items: RunEvent[] }>("GET", `/v1/runs/${encodeURIComponent(runId)}/events.jsonl${query(params)}`)).items ?? [];
  }

  streamEvents(
    runId: string,
    onEvent: (event: RunEvent) => void,
    opts: { workspaceId?: string; afterSeq?: number; signal?: AbortSignal } = {},
  ): Promise<void> {
    const params: Record<string, string | number | undefined> = { workspace_id: opts.workspaceId };
    if (opts.afterSeq && opts.afterSeq > 0) params.after_seq = opts.afterSeq;
    return fetch(`${this.baseUrl}/v1/runs/${encodeURIComponent(runId)}/events${query(params)}`, {
      headers: { Accept: "text/event-stream" },
      signal: opts.signal,
    }).then((response) => {
      if (!response.ok) throw new Error(`streamEvents failed: ${response.status}`);
      return readSse(response, onEvent, opts.signal);
    });
  }

  async approvals(runId: string, workspaceId?: string): Promise<Approval[]> {
    return (await this.json<{ items: Approval[] }>("GET", `/v1/runs/${encodeURIComponent(runId)}/approvals${query({ workspace_id: workspaceId })}`))
      .items ?? [];
  }

  async resolveApproval(
    runId: string,
    approvalId: string,
    decision: ApprovalDecision,
    opts: { workspaceId?: string; scope?: "once" | "run" | null; reason?: string } = {},
  ): Promise<boolean> {
    const body = await this.json<{ resolved: boolean }>(
      "POST",
      `/v1/runs/${encodeURIComponent(runId)}/approvals/${encodeURIComponent(approvalId)}/resolve${query({ workspace_id: opts.workspaceId })}`,
      { decision, scope: opts.scope ?? "once", reason: opts.reason ?? "tui_resolved" },
    );
    return Boolean(body.resolved);
  }

  async cancel(runId: string, workspaceId?: string, reason = "tui_cancelled"): Promise<boolean> {
    const body = await this.json<{ cancelled: boolean }>(
      "POST",
      `/v1/runs/${encodeURIComponent(runId)}/cancel${query({ workspace_id: workspaceId })}`,
      { reason },
    );
    return Boolean(body.cancelled);
  }

  async artifacts(runId: string, workspaceId?: string): Promise<Artifact[]> {
    return (await this.json<{ items: Artifact[] }>("GET", `/v1/runs/${encodeURIComponent(runId)}/artifacts${query({ workspace_id: workspaceId })}`))
      .items ?? [];
  }

  async forkRun(runId: string, at: string, workspaceId?: string): Promise<{ fork_dir: string }> {
    return this.json("POST", `/v1/runs/${encodeURIComponent(runId)}/fork${query({ workspace_id: workspaceId })}`, { at });
  }

  async runEvalSuite(
    suitePath: string,
    opts: { workspaceId?: string; approvalMode?: string; sessionMode?: string; profile?: string } = {},
  ): Promise<EvalRunResponse> {
    return this.json("POST", `/v1/evals${query({ workspace_id: opts.workspaceId })}`, {
      workspace_id: opts.workspaceId,
      suite_path: suitePath,
      approval_mode: opts.approvalMode,
      session_mode: opts.sessionMode,
      profile: opts.profile,
    });
  }

  async listSkillDrafts(workspaceId?: string): Promise<SkillDraft[]> {
    return (await this.json<{ items: SkillDraft[] }>("GET", `/v1/skills/drafts${query({ workspace_id: workspaceId })}`)).items ?? [];
  }

  async createSkillDraft(runId: string, workspaceId?: string): Promise<SkillDraft> {
    return (await this.json<{ draft: SkillDraft }>("POST", `/v1/skills/drafts${query({ workspace_id: workspaceId })}`, { workspace_id: workspaceId, run_id: runId })).draft;
  }

  async showSkillDraft(draftId: string, workspaceId?: string): Promise<{ draft_id: string; markdown: string }> {
    return this.json("GET", `/v1/skills/drafts/${encodeURIComponent(draftId)}${query({ workspace_id: workspaceId })}`);
  }

  async installSkillDraft(draftId: string, workspaceId?: string): Promise<{ draft_id: string; path: string }> {
    return this.json("POST", `/v1/skills/drafts/${encodeURIComponent(draftId)}/install${query({ workspace_id: workspaceId })}`, {
      workspace_id: workspaceId,
    });
  }

  async rejectSkillDraft(draftId: string, workspaceId?: string): Promise<{ draft_id: string; path: string }> {
    return this.json("POST", `/v1/skills/drafts/${encodeURIComponent(draftId)}/reject${query({ workspace_id: workspaceId })}`, {
      workspace_id: workspaceId,
    });
  }

  async updateStatus(): Promise<UpdateStatus> {
    return this.json("GET", "/v1/update");
  }

  async listExtensions(workspaceId?: string): Promise<Array<Record<string, unknown>>> {
    const body = await this.json<{ items?: Array<Record<string, unknown>> }>(
      "GET",
      `/v1/extensions${query({ workspace_id: workspaceId })}`,
    );
    return body.items ?? [];
  }

  async checkUpdate(opts: { channel?: string; manifestSource?: string } = {}): Promise<UpdateStatus> {
    return this.json("POST", "/v1/update/check", { channel: opts.channel, manifest_source: opts.manifestSource });
  }

  async applyUpdate(opts: { channel?: string; manifestSource?: string } = {}): Promise<UpdateStatus> {
    return this.json("POST", "/v1/update/apply", { channel: opts.channel, manifest_source: opts.manifestSource });
  }

  async rollbackUpdate(): Promise<UpdateStatus> {
    return this.json("POST", "/v1/update/rollback", {});
  }

  private async json<T>(method: string, path: string, body?: unknown): Promise<T> {
    const response = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`);
    return (await response.json()) as T;
  }
}

function query(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : "";
}
