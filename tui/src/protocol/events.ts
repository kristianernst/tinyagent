export type Visibility = "internal" | "debug" | "user" | "public";
export type Durability = "ephemeral" | "event_log" | "artifact_only";

export type RunEvent = {
  id: string;
  seq: number;
  type: string;
  time: string;
  run_id: string;
  turn_id: string | null;
  item_id: string | null;
  parent_item_id: string | null;
  source: string;
  visibility: Visibility;
  durability: Durability;
  data: Record<string, unknown>;
  artifact_refs: string[];
  workspace_id?: string;
  conversation_id?: string;
};

export type Workspace = {
  workspace_id: string;
  id?: string;
  root: string;
  name: string;
  kind?: string;
  trust?: string;
  default_provider?: string;
};

export type Conversation = {
  conversation_id: string;
  title: string;
  status: string;
  active_turn_id: string | null;
  created_at: string;
  updated_at: string;
  workspace: string;
  turn_count: number;
  last_run_id?: string;
  last_turn_status?: string;
};

export type ConversationTurn = {
  type: string;
  conversation_id?: string;
  turn_id?: string;
  run_id?: string;
  run_path?: string;
  status?: string;
  created_at?: string;
  completed_at?: string;
  user_message?: unknown;
  assistant_message?: unknown;
};

export type RunObject = {
  id: string;
  run_id: string;
  workspace_id: string;
  conversation_id: string;
  turn_id: string;
  status: string;
  task: string;
  created_at: string;
  updated_at: string;
  started_at: string;
  completed_at?: string | null;
  run_path: string;
  model: Record<string, unknown>;
  profile: string;
  workspace_mode: string;
  approval_mode: string;
  session_mode: SessionMode;
  approvals_reviewer: string;
  sandbox_mode: string;
  event_count: number;
  artifact_count: number;
  links: Record<string, string>;
};

export type ApprovalDecision = "approved" | "denied" | "cancelled" | "expired";
export type ApprovalMode = "never" | "on-request" | "yolo";
export type SessionMode = "normal" | "plan";

export type Approval = {
  approval_id: string;
  run_id: string;
  turn_id: string | null;
  step_id: string | null;
  action_kind: string;
  tool_name: string;
  cwd: string;
  args_preview: string;
  command: string | null;
  risk: "low" | "medium" | "high" | string;
};

export type Artifact = {
  path: string;
  kind: string;
  bytes: number;
  created_at?: string | Record<string, unknown>;
  safe_to_display: boolean;
};

export type GitFileStatus = {
  path: string;
  oldPath?: string;
  status: "added" | "modified" | "deleted" | "renamed" | "untracked" | "copied" | "typechange" | "unknown";
};

export type GitSnapshot = {
  isRepo: boolean;
  clean: boolean;
  branch?: string;
  ahead?: number;
  behind?: number;
  files: GitFileStatus[];
  diff: string;
  diffTruncated: boolean;
  omittedFiles?: number;
  error?: string;
};

export type StartRunRequest = {
  workspace_id?: string;
  task: string;
  run_id?: string;
  approval_mode?: ApprovalMode;
  approvals_reviewer?: string;
  profile?: string;
  conversation_id?: string;
  turn_id?: string;
  parent_turn_id?: string;
  session_mode?: SessionMode;
};

export type StartRunResponse = {
  run: RunObject;
  events_url: string;
};

export type EvalResult = {
  case_id: string;
  success: boolean;
  status: string;
  validation_ok?: boolean;
  model_call_count?: number;
  tool_call_count?: number;
  failure_reason?: string;
};

export type EvalRunResponse = {
  suite_path: string;
  output_dir: string;
  total: number;
  passed: number;
  report: string;
  results: EvalResult[];
};

export type SkillDraft = {
  draft_id: string;
  name: string;
  path: string;
  status: string;
  source_run_id: string;
  created_at: string;
};

export type UpdateStatus = {
  current_version: string;
  channel: string;
  install_kind: string;
  manifest_source: string;
  checked_at: string;
  latest_version: string;
  available: boolean;
  reason: string;
  platform: string;
  active_version: string;
  previous_version: string;
  artifact?: {
    platform: string;
    url: string;
    sha256: string;
    size?: number | null;
    kind: string;
    expected_files: string[];
  } | null;
};

export function isUserVisible(event: RunEvent): boolean {
  return event.visibility === "public" || event.visibility === "user";
}

export function eventText(event: RunEvent, key: string): string {
  const value = event.data?.[key];
  return typeof value === "string" ? value : "";
}
