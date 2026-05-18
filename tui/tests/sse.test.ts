import { expect, test } from "bun:test";
import { parseSseBlock, parseSseChunk } from "../src/backend/sse";

test("parses SSE data blocks", () => {
  const event = parseSseBlock('id: 1\nevent: run.started\ndata: {"id":"evt_1","seq":1,"type":"run.started","time":"","run_id":"run","turn_id":null,"item_id":null,"parent_item_id":null,"source":"test","visibility":"user","durability":"event_log","data":{},"artifact_refs":[]}\n');
  expect(event?.type).toBe("run.started");
  expect(event?.seq).toBe(1);
});

test("keeps partial SSE chunks buffered", () => {
  const parsed = parseSseChunk('data: {"id":"evt_1","seq":1');
  expect(parsed.events).toEqual([]);
  expect(parsed.rest).toContain("evt_1");
});
