import { expect, test } from "bun:test";
import { parseServerUrl } from "../src/backend/spawn";

test("parses machine-readable server startup URL", () => {
  expect(parseServerUrl('{"host":"127.0.0.1","port":51741,"url":"http://127.0.0.1:51741"}\n', "127.0.0.1")).toBe(
    "http://127.0.0.1:51741",
  );
});

test("keeps legacy human server startup parsing as a fallback", () => {
  expect(parseServerUrl("serving tinyagent runtime on http://127.0.0.1:51742\n", "127.0.0.1")).toBe(
    "http://127.0.0.1:51742",
  );
});

