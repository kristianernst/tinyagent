import type { RunEvent } from "../protocol/events";

export function event(seq: number, type: string, data: Record<string, unknown> = {}): RunEvent {
  return {
    id: `evt_${seq}`,
    seq,
    type,
    time: `2026-05-17T00:00:${String(seq).padStart(2, "0")}Z`,
    run_id: "run_fixture",
    turn_id: "turn_fixture",
    item_id: null,
    parent_item_id: null,
    source: "test",
    visibility: "user",
    durability: "event_log",
    data,
    artifact_refs: [],
    workspace_id: "default",
    conversation_id: "conv_fixture",
  };
}

export const basicRunFixture = [
  event(1, "run.started", { task: "say hi" }),
  event(2, "model.text.delta", { delta: "hi" }),
  event(3, "run.completed", { duration_seconds: 1 }),
];
