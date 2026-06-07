// Renders the real TUI shell against opentui's TestRenderer and dumps
// captured frames to disk as plain text. The harness mounts every widget the
// production path uses (chrome bar, transcript, composer, picker, approval)
// and drives it through realistic state transitions so we can verify the
// design system visually without an interactive terminal.
//
// Usage:
//   bun scripts/visual-check.ts               # dumps to .tui-snapshots/
//   bun scripts/visual-check.ts --print       # also prints to stdout
//
// Output: one .txt per scene, each is the literal character grid the user
// would see. ANSI color escapes are stripped (only glyph + layout fidelity
// matters here; color is verified by reading the source).

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createTestRenderer } from "@opentui/core/testing";

import { mountApp } from "../src/ui/mount";
import { Store } from "../src/state/store";
import { emptyState, type AppState, type SessionState } from "../src/state/reducer";
import type { Approval, RunEvent } from "../src/protocol/events";

type Scene = {
  name: string;
  state: AppState;
  viewport?: { width: number; height: number };
  // Optional post-mount mutation (e.g. open the picker) before the capture.
  prepare?: (mount: ReturnType<typeof mountApp>) => void | Promise<void>;
  // Optional mutation after the normal refresh, useful for pointer states that
  // should not be recomputed by mount.refresh().
  afterRefresh?: (mount: ReturnType<typeof mountApp>) => void | Promise<void>;
};

const WIDTH = 120;
const HEIGHT = 38;
const OUT_DIR = join(import.meta.dir, "..", ".tui-snapshots");

async function main() {
  const wantsStdout = process.argv.includes("--print");
  mkdirSync(OUT_DIR, { recursive: true });

  const scenes: Scene[] = [
    sceneIdle(),
    sceneStreaming(),
    sceneToolsResolving(),
    sceneRootPaperSize(),
    scenePickerSlash(),
    scenePickerAt(),
    sceneApprovalModal(),
    sceneCtxWarning(),
    sceneCtxDanger(),
    sceneChromeTransientOverflow(),
    sceneSessionsOverlay(),
    sceneCompactPicker(),
    sceneDensityThreshold99(),
    sceneDensityThreshold100(),
    sceneChromeBranchHover(),
    sceneHistorySearch(),
    sceneContextMenu(),
    sceneContextOverlay(),
    sceneUsageOverlay(),
    sceneDiffOverlay(),
    sceneReplayOverlay(),
    sceneEvalOverlay(),
    sceneSkillsOverlay(),
    sceneUpdateOverlay(),
    sceneReviewOverlay(),
    sceneSettingsOverlay(),
    sceneExtensionsOverlay(),
    sceneHelpOverlay(),
    sceneModelOverlay(),
    sceneHeadlessOverlay(),
    sceneAcpOverlay(),
    sceneThemeOverlay(),
    sceneDebugOverlay(),
    scenePickerSkill(),
    sceneCommandPalette(),
    scenePickerNoMatch(),
    sceneCompactSessionsOverlay(),
    scenePickerHover(),
    sceneTranscriptInteraction(),
    sceneComposerHintClick(),
    sceneComposerUnfocused(),
    scenePickerAtNoMatch(),
    scenePickerSkillNoMatch(),
    sceneActivityOverlay(),
    sceneActivityEmptyOverlay(),
  ];

  for (const scene of scenes) {
    const { renderer, renderOnce, captureCharFrame } = await createTestRenderer({
      width: scene.viewport?.width ?? WIDTH,
      height: scene.viewport?.height ?? HEIGHT,
      targetFps: 30,
      gatherStats: false,
    });

    // Build a RendererHost facade matching the production interactive shape
    // but backed by the TestRenderer instance.
    const host: any = {
      kind: "interactive",
      ctx: renderer,
      root: renderer.root,
      width: scene.viewport?.width ?? WIDTH,
      height: scene.viewport?.height ?? HEIGHT,
      requestRender: () => renderer.requestRender?.(),
      focus: (r: any) => renderer.focusRenderable?.(r),
      blur: (r: any) => renderer.blurRenderable?.(r),
      stop: () => {},
      on: () => {},
      off: () => {},
      opentui: await import("@opentui/core"),
    };

    const store = new Store(scene.state);
    const mount = mountApp(host, store);
    await scene.prepare?.(mount);
    mount.refresh();
    await scene.afterRefresh?.(mount);
    await renderOnce();
    const rawFrame = captureCharFrame();
    const frame = normalizeSnapshot(rawFrame);
    const out = join(OUT_DIR, `${scene.name}.txt`);
    writeFileSync(out, frame);
    if (wantsStdout) {
      console.log(`\n══════ ${scene.name} ──────────────────────────────────────────────`);
      console.log(frame);
    }
    validateScene(scene.name, rawFrame, scene.viewport?.width ?? WIDTH);
    mount.destroy();
    try {
      (renderer as any).destroy?.();
    } catch {}
  }
  console.log(`✓ ${scenes.length} scenes captured → ${OUT_DIR}`);
}

function normalizeSnapshot(frame: string): string {
  return frame.replace(/\u00a0/g, " ");
}

function validateScene(name: string, rawFrame: string, expectedWidth: number): void {
  const frame = normalizeSnapshot(rawFrame);
  const has = (needle: string) => frame.includes(needle);
  const fail = (message: string): never => {
    throw new Error(`${name}: ${message}`);
  };

  for (const [index, line] of frame.split("\n").entries()) {
    const width = Array.from(line).length;
    if (width > expectedWidth) fail(`line ${index + 1} exceeds viewport width (${width} > ${expectedWidth})`);
  }

  const bannedGlyph = frame.match(/[■░▒▓█]/u)?.[0];
  if (bannedGlyph) fail(`uses Paper-banned glyph ${bannedGlyph}`);

  if (has("thought ·")) fail("reasoning headers should not expose implementation block counts");
  if (has("— brand")) fail("normal chrome should not expose theme-token names");
  if (has("● ● ●")) fail("live chrome should not duplicate native terminal window controls");

  if (name === "06-approval-modal") {
    if (!has("⦗ approve ⦘")) fail("chrome must expose approval through the phase pill");
    if (has("approve queued")) fail("approval phase must not duplicate approve queued as a transient");
    if (!has("› fix the streaming jitte…")) fail("modal backdrop should preserve a dimmed prompt summary like Paper");
    if (!has("⠙ shell rm -rf node_modul…")) fail("modal backdrop should preserve a dimmed blocked-tool summary like Paper");
    if (!has("We should clean the loc…")) fail("modal backdrop should preserve a dimmed assistant summary like Paper");
    if (has("ask, plan") || has("skills  ⌜esc⌟ cancel turn")) fail("modal backdrop leaked composer chrome");
    if (has("$ rm -rf node_modules")) fail("approval command should render without a shell prompt prefix");
    if (!has("requested by: agent · turn 7")) fail("approval modal should show the Paper requester metadata row");
    if (!has("⌜a⌟ allow for session")) fail("approval modal should expose the session-scope affordance copy");
    if (!has("┏━") || !has("━┓") || !has("┗━") || !has("━┛")) fail("approval modal should use Paper heavy corner glyphs");
    if (!has("⌜e⌟ edit command")) fail("approval modal should show the Paper edit-command copy");
    if (!has("esc dismisses")) fail("approval modal should use Paper dismiss copy");
  }

  if (name === "10-compact-picker-80") {
    if (!has("⎇ …")) fail("compact chrome should collapse branch to ⎇ …");
    if (has("ctx ▱")) fail("compact chrome should collapse ctx meter to percentage text");
    if (!has("⌜⏎⌟ run")) fail("compact slash picker should keep command-run hint copy");
  }

  if (name === "42-density-threshold-99") {
    if (has("ctx ▱")) fail("99-column chrome should stay in compact density below the Paper threshold");
    if (!has("⌜⏎⌟ send") || !has("⌜/⌟ cmds")) fail("99-column composer should use compact footer copy below the Paper threshold");
  }

  if (name === "43-density-threshold-100") {
    if (!has("ctx ▱")) fail("100-column chrome should leave compact density at the Paper threshold");
    if (!has("⌜enter⌟ send") || !has("⌜/⌟ commands")) fail("100-column composer should use wide footer copy at the Paper threshold");
  }

  if (name === "03-tools-inline-resolve") {
    if (has("learning⠹")) fail("chrome spinner should sit in its own lane, not attach to the branch");
    if (!has("ws : tinyagent") || !has("model : gpt-5")) fail("root chrome should use the Paper label spacing for workspace and model");
    if (!has("ta-review-gated-learning")) fail("Paper-width root chrome should preserve the full branch name");
    if (!has("20:48 · just now")) fail("root transcript should show the prompt timestamp lane");
    if (!has("⦗ streaming ⦘")) fail("root chrome should expose streaming as the phase pill");
    if (!has("⦗ approve queued ⦘")) fail("queued approvals should stay in chrome while the root transcript remains visible");
    if (frame.indexOf("⦗ streaming ⦘") > frame.indexOf("⦗ approve queued ⦘"))
      fail("phase pill should render before queued approval, matching the Paper chrome order");
    if (!has("ctx ▰▱▱▱▱ 24%")) fail("root chrome should match the Paper context percentage for the resolving scene");
    if (has("24% — brand")) fail("normal ctx chrome should not leak the theme token label");
    if (!has("implement the new design tokens")) fail("root composer should show the Paper draft prompt");
    if (frame.indexOf("⌜esc⌟ cancel turn") < frame.indexOf("⌜$⌟ skills") + 20)
      fail("composer footer should keep cancel turn in the right-side lane");
    if (!has("thought for 4s")) fail("root transcript should show Paper-style elapsed reasoning copy");
    if (has("thought · 1 block")) fail("root transcript should not expose reasoning implementation block counts");
    if (!has("The reflow happens because we replace assistant.content")) fail("active streaming reasoning should match the Paper root body copy");
    if (!has("⌜r⌟ collapse")) fail("active streaming reasoning should advertise collapse, not expand");
    for (const needle of ["0.4s", "0.2s", "running…"]) {
      if (!has(needle)) fail(`tool rows should show right-side meta ${needle}`);
    }
    if (!has("└ Transcript.ts:160") || !has("└ markdown.ts:42")) fail("short completed tool output should expand inline like the Paper root");
    if (has("3 hits · 2 lines")) fail("short completed tool output should not collapse behind a line-count hint");
    if (!has("PATCH  src/ui/widgets/Transcript.ts")) fail("root transcript should show the inline patch preview");
    if (!has("+3  −1")) fail("inline patch preview should expose added/removed counts with Paper minus typography");
    if (has("+3  -1")) fail("inline patch preview should not use ASCII hyphen for removed counts");
    const patchLine = frame.split("\n").find((line) => line.includes("PATCH  src/ui/widgets/Transcript.ts")) ?? "";
    if (patchLine.indexOf("+3  −1") - patchLine.indexOf("PATCH  ") < 70)
      fail("inline patch preview should reserve a right-aligned action/count lane");
    if (!has("⌜⏎⌟ apply") || !has("⌜d⌟ diff")) fail("inline patch preview should show apply and diff actions");
    if (!has("card.assistant.content = next")) fail("inline patch preview should include changed code");
    if (!has("Once that lands the per-chunk reflow disappears")) fail("assistant follow-up should render below the inline patch preview");
    if (frame.indexOf("PATCH  src/ui/widgets/Transcript.ts") > frame.indexOf("Once that lands the per-chunk reflow disappears"))
      fail("assistant follow-up should come after the inline patch preview, matching Paper");
    if (has("allow once") || has("risk: high")) fail("queued approval should not open the blocking modal before approval phase");
  }

  if (name === "44-root-paper-size") {
    if (!has("◆ tinyagent") || !has("ws : tinyagent") || !has("model : gpt-5"))
      fail("Paper-sized root should keep product, workspace, and model identity in the chrome");
    if (!has("⦗ streaming ⦘") || !has("⦗ approve queued ⦘")) fail("Paper-sized root should preserve phase and queued approval chrome");
    if (!has("ctx ▰▱▱▱▱ 24%")) fail("Paper-sized root should use the full ctx meter at 110 columns");
    if (!has("implement the new design tokens")) fail("Paper-sized root should keep the composer draft visible");
    if (!has("⌜enter⌟ send") || !has("⌜/⌟ commands") || !has("⌜esc⌟ cancel turn"))
      fail("Paper-sized root should keep the wide composer footer lanes");
    if (!has("PATCH  src/ui/widgets/Transcript.ts")) fail("Paper-sized root should keep the inline patch preview visible");
    if (has("allow once") || has("risk: high")) fail("Paper-sized root queued approval should stay in chrome, not open the modal");
  }

  if (name === "07-ctx-warning") {
    if (!has("82% — warning")) fail("warning ctx scene should label the 80-95 threshold");
    if (has("⦗ compact ⦘")) fail("warning ctx scene should not show the compact transient before danger threshold");
  }

  if (name === "08-ctx-danger") {
    if (!has("96% — danger")) fail("danger ctx scene should label the 95+ threshold");
    if (!has("⦗ compact ⦘")) fail("danger ctx scene should show the compact transient");
    if (!has("ws : tinyagent") || !has("model : gpt-5"))
      fail("danger ctx chrome should preserve Paper identity labels at 120 columns");
  }

  if (["01-idle", "02-streaming", "03-tools-inline-resolve", "04-picker-slash"].includes(name)) {
    if (!has("⌜esc⌟ cancel turn")) fail("composer footer should match the Paper root footer copy");
    if (!has("⌜enter⌟ send") || !has("⌜⇧enter⌟ newline")) fail("composer footer should use the Paper root key labels for send and newline");
    if (has("⌜↑↓⌟ history")) fail("composer footer should not advertise history in the root footer");
    if (has("╭─ ask, plan") || has("╭─ implement")) fail("composer prompt should sit inside the input lane, not in the top border");
  }

  if (name === "10-compact-picker-80" || name === "40-chrome-branch-hover-80") {
    if (!has("⌜⏎⌟ send")) fail("compact composer footer should keep symbolic send copy to avoid clipping");
    if (has("⌜↑↓⌟ history")) fail("composer footer should not advertise history in the root footer");
  }

  if (name === "01-idle") {
    if (!has("⎇ ta-") || has("⎇ …")) fail("idle chrome should keep a compact branch cue before collapsing to ellipsis");
  }

  if (name === "11-history-search") {
    if (!has("history · over")) fail("history search should fold the typed filter into the picker header");
    if (has("query  over")) fail("history search should not render a form-like query row");
    if (!has("› review the overlay state")) fail("history search should keep the selected command in the row lane");
    if (!has("type to filter") || has("⌜type⌟")) fail("history search should not style free-text filtering as a keycap");
    if (!has("type to filter   ⌜^R⌟ next   ⌜⏎⌟ use   ⌜esc⌟ cancel") || has("type to filter · ⌜^R⌟ next · ⌜⏎⌟ use · ⌜esc⌟ cancel"))
      fail("history search footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ close") || has("⌜esc⌟ collapse")) fail("history search should use Paper cancel copy");
  }

  if (name === "04-picker-slash") {
    if (!/commands\s+\d+ \/ \d+/.test(frame)) fail("slash picker should show selected/total count, not match count");
    if (!has("5 / 19")) fail("slash picker should use the curated Paper command catalog size");
    for (const needle of ["/diff", "show git diff", "/diff-stat", "show diff summary", "› /replay", "replay current run", "/sessions", "list sessions", "/skills", "open skill forge"]) {
      if (!has(needle)) fail(`slash picker should mirror the Paper command window for ${needle}`);
    }
    for (const stale of ["/compact-mode", "/usage", "/rewind", "/fork"]) {
      if (has(stale)) fail(`slash picker should not drift from the Paper command window with ${stale}`);
    }
    if (has("Replay cinema") || has("Usage panel") || has("Fork from event")) fail("slash picker should not use feature-name command titles");
    if (has("commands matching")) fail("slash picker header should stay mode-only like Paper");
    if (!has("replay current run") || !frame.split("\n").some((line) => line.includes("› /replay") && line.includes("↵")))
      fail("selected slash command should keep the Paper right-side enter cue");
    if (frame.split("\n").some((line) => line.includes("› /diff") || line.includes("› /diff-stat") || line.includes("› /sessions") || line.includes("› /skills")))
      fail("slash picker should reserve the marker lane without drawing chevrons on inactive rows");
    if (!has("⌜⏎⌟ run")) fail("slash mention picker should say enter runs the command");
    if (has("⌜⏎⌟ insert")) fail("slash mention picker should not say enter inserts command text");
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ run   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ run · ⌜esc⌟ cancel"))
      fail("slash picker footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ collapse")) fail("slash picker should use Paper cancel copy");
  }

  if (name === "05-picker-at-file") {
    for (const needle of ["files matching tra", "4", "src/ui/widgets/Transcript.ts", "12kb", "tests/ui/transcript.test.ts", "4kb", "docs/TRANSCRIPT.md", "2kb", "— recent —", "README.md", "3kb"]) {
      if (!has(needle)) fail(`file picker should keep multi-row match context for ${needle}`);
    }
    const lines = frame.split("\n");
    const recentLine = lines.findIndex((line) => line.includes("— recent —"));
    if (recentLine <= 0 || !lines[recentLine - 1]?.includes("─")) fail("file picker should divide matched files from the recent row like Paper");
    if (lines.some((line) => line.includes("› tests/ui/transcript.test.ts") || line.includes("› docs/TRANSCRIPT.md") || line.includes("› README.md")))
      fail("file picker should only draw the chevron for the selected file row");
    if (!has("⌜⏎⌟ insert")) fail("file picker should say enter inserts the mention");
    if (has("⌜⏎⌟ run")) fail("file picker should not say enter runs a file");
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ insert   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ insert · ⌜esc⌟ cancel"))
      fail("file picker footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ collapse")) fail("file picker should use Paper cancel copy");
  }

  if (name === "12-context-menu") {
    for (const needle of ["▍ Copy last reply", "assistant text", "Copy conversation", "all turns", "Stop run", "cancel run"]) {
      if (!has(needle)) fail(`context menu should keep compact action metadata: ${needle}`);
    }
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ choose   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ choose · ⌜esc⌟ cancel"))
      fail("context menu footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ collapse") || has("⌜esc⌟ close")) fail("context menu should use Paper cancel copy like transient popovers");
    if (has("\n    │   Copy assistant text") || has("\n    │   Copy all turns") || has("\n    │   Cancel active run"))
      fail("context menu should not render action descriptions as second-line rows");
  }

  if (name === "29-picker-skill") {
    if (!/skills\s+\d+ \/ \d+/.test(frame)) fail("skill picker should show selected/total count");
    if (!has("3 / 11")) fail("skill picker should mirror the Paper compact row count");
    for (const needle of ["› verify", "review", "loop"]) {
      if (!has(needle)) fail(`skill picker missing Paper-style row ${needle}`);
    }
    if (has("› review") || has("› loop")) fail("skill picker should only draw the chevron for the selected row");
    if (has("visual-check") || has("paper-review")) fail("skill picker should keep the Paper skill window to three visible rows");
    if (has("› $verify") || has("$review") || has("$loop")) fail("skill picker rows should not duplicate the trigger prefix");
    if (has("skills matching")) fail("skill picker header should stay mode-only like Paper");
    if (!has("⌜⏎⌟ insert")) fail("skill picker should say enter inserts the mention");
    if (has("⌜⏎⌟ run")) fail("skill picker should not say enter runs a skill");
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ insert   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ insert · ⌜esc⌟ cancel"))
      fail("skill picker footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ collapse")) fail("skill picker should use Paper cancel copy");
  }

  if (name === "35-composer-hint-skills-click") {
    for (const needle of ["capture TUI scenes", "compare terminal against Paper"]) {
      if (!has(needle)) fail(`skill picker should keep compact skill descriptions: ${needle}`);
    }
    if (!has("▸⌜$⌟ skills") || has("⌜$⌟▸skills")) fail("composer hint hover should use a fixed marker lane before the keycap");
    if (has("Capture OpenTUI scenes before calling UI work d…") || has("Compare the terminal surface against the Paper …"))
      fail("skill picker should not clip long skill prose in the row lane");
    if (!has("⌜⏎⌟ insert")) fail("composer skill picker should say enter inserts the mention");
    if (has("⌜⏎⌟ run")) fail("composer skill picker should not say enter runs a skill");
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ insert   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ insert · ⌜esc⌟ cancel"))
      fail("composer skill picker footer should use Paper spacing without dot separators");
    if (!has("⌜esc⌟ cancel") || has("⌜esc⌟ collapse")) fail("composer skill picker should use Paper cancel copy");
  }

  if (name === "36-composer-unfocused-placeholder") {
    if (!has("The composer should go quiet")) fail("unfocused composer scene should keep the transcript context visible");
    if (has("press / to start")) fail("unfocused composer input should stay quiet, not show instructional placeholder copy");
    if (has("ask, plan")) fail("unfocused composer should not show the focused placeholder");
  }

  if (name === "09-sessions-overlay" || name === "32-compact-sessions-overlay-80") {
    if (!has("sessions  ⦗ 12 ⦘")) fail("sessions overlay header missing");
    if (has("ask, plan") || has("skills  ⌜")) fail("right-side overlay should cover composer chrome");
    if (!has("▍ design tokens · TUI") || !has("active")) fail("sessions overlay should show the active row with an accent lane and status");
    if (name === "09-sessions-overlay" && !has("gpt-5 · 14 turns · 4.2k tok · 2m ago"))
      fail("sessions overlay should show Paper-style selected session metadata");
    if (name === "32-compact-sessions-overlay-80" && (!has("gpt-5 · 14 turns · 4.2k tok") || has("·c4.2k") || has("tok · 2m ago")))
      fail("compact sessions overlay should keep selected metadata on one readable row");
    if (!has("review-gated learning") || !has("gpt-5 · 27 turns · 11.4k tok"))
      fail("sessions overlay should show Paper-style model/turn/token metadata");
    if (!has("permission profiles v1") || !has("haiku-4.5 · 6 turns")) fail("sessions overlay should preserve mixed model metadata");
    if (!has("⌜↑↓⌟ nav") || !has("⌜⏎⌟ open") || !has("⌜n⌟ new"))
      fail("sessions overlay footer should keep navigation, open, and new controls visible");
    if (frame.split("\n").some((line) => line.includes("⌜↑↓⌟ nav") && line.includes("⌜esc⌟ close")))
      fail("sessions overlay footer should not duplicate the header close action");
  }

  if (name === "13-context-overlay") {
    for (const needle of ["workspace      tinyagent", "~/work/dev/tinyagent", "files          7", "file mentions"]) {
      if (!has(needle)) fail(`context overlay should keep workspace summary compact: ${needle}`);
    }
    for (const needle of ["▍ tui/src/ui/widgets/Rail.ts", "tui/src/ui/widgets/ContextWidget.ts", "modified", "tui/src/ui/widgets/panelStyle.ts", "added"]) {
      if (!has(needle)) fail(`context overlay should keep file status in readable row lanes: ${needle}`);
    }
    if (has("M tui/src/ui/widgets/ContextWidget.ts") || has("A tui/src/ui/widgets/panelStyle.ts"))
      fail("context overlay should not bake git status into the file path lane");
    if (has("/Users/k/work/dev/tinyagent") || has("workspace mention index")) fail("context overlay should not expose raw local roots or implementation labels");
    if (has("Git status stays in the first file lane.")) fail("context overlay should not show implementation guidance as footer copy");
  }

  if (name === "14-usage-overlay") {
    for (const needle of ["48,212 in · 9,408 out", "5,238 tok/call avg", "latency        18.7s", "end to end"]) {
      if (!has(needle)) fail(`usage overlay should show stateful metrics instead of explanatory prose: ${needle}`);
    }
    if (has("18,740 ms") || has("seconds end to end") || has("input plus output for the active session") || has("completed model invocations") || has("Bars compare input and output within this run."))
      fail("usage overlay should not show low-value explanatory prose");
  }

  if (name === "17-eval-overlay") {
    if (!has("▍ slash-picker") || !has("passed")) fail("eval overlay should keep case status in the right metadata lane");
    if (!has("compact-80col") || !has("failed")) fail("eval overlay should expose failed cases without status prefixes in the title");
    if (has("✓ slash-picker") || has("✗ compact-80col")) fail("eval overlay should not bake status glyphs into the title lane");
    if (!has("suite          evals/tui-overlay.yaml") || !has("snapshot gate"))
      fail("eval overlay should describe the selected suite as a visual gate, not command documentation");
    if (!has("output         eval artifacts") || !has(".tinyagent/evals/overlay-20260525"))
      fail("eval overlay should keep output paths in the readable detail lane");
    if (has("output         .tinyagent/evals/overlay-20260…")) fail("eval overlay should not clip output paths in the value lane");
    if (!has("needs review · compact-80col · footer clipped"))
      fail("eval overlay should summarize failed state in the footer");
    if (has("next step ·") || has("overlay visual eval") || has("needs review:") || has("tinyagent eval run evals/tui-overlay.yaml") || has("run /eval <suite-path>") || has("suite path"))
      fail("eval overlay should not render raw report prose");
  }

  if (name === "16-replay-overlay") {
    for (const needle of ["run            overlay refactor", "saved trace", "timeline       5 steps", "fork           workspace copy", "temporary workspace"]) {
      if (!has(needle)) fail(`replay overlay should keep timeline metadata in product-facing lanes: ${needle}`);
    }
    if (has("Run: run_overlay_refactor") || has("Fork: /private/tmp/tinyagent/fork-0004") || has("/private/tmp/tinyagent/fork-0004"))
      fail("replay overlay should not lead with raw run ids or absolute fork paths");
    if (has("run_overlay_refactor") || has("fork 0004") || has("0004"))
      fail("replay overlay should keep raw run ids and zero-padded event numbers out of the visible sheet");
    if (!has("▍ tool completed") || !has("read · output captured") || !has("step 4"))
      fail("replay overlay should select the cursor event with one active marker and readable event detail");
    if (has("> step 4") || has("▍   step 1")) fail("replay overlay should not render competing cursor and selection markers");
    for (const needle of ["selected step", "step           4", "tool           read", "output         RailWidget mounts the overlay shell."]) {
      if (!has(needle)) fail(`replay overlay should render selected step data in lanes: ${needle}`);
    }
    for (const needle of ["turn preview", "phase          streaming", "1 turn · 1 tool · 5.7ms replay", "assistant      response preview", "The panel surfaces now share one language."]) {
      if (!has(needle)) fail(`replay overlay should render projected state as product-facing rows: ${needle}`);
    }
    if (has("event detail") || has("event          ") || has("run state") || has("event data") || has('"tool":') || has('"output":') || has("{") || has("}"))
      fail("replay overlay should not render selected event payload as raw JSON");
    if (has("run.started") || has("model.reasoning.completed") || has("tool.execution.started") || has("tool.execution.completed") || has("model.text.delta"))
      fail("replay overlay should not render raw protocol event names in visible lanes");
    if (has("projection") || has("projected ") || has("internals")) fail("replay overlay should not expose implementation projection copy");
  }

  if (name === "23-help-overlay") {
    if (!/▍ \/new\s+start new session/.test(frame)) fail("command map should use single-row command/action lanes");
    if (has("\n                                        │     start new session")) fail("command map should not render command actions as second-line descriptions");
    for (const hidden of ["/always-approve", "/approve", "/deny", "/compact-mode", "/rewind", "/fork"]) {
      if (has(hidden)) fail(`command map should keep compatibility command out of the Paper catalog: ${hidden}`);
    }
    if (!has("/help") || !has("show commands")) fail("command map should show the full curated Paper catalog");
    if (has("+1 more")) fail("command map should not hide commands behind overflow while the overlay has room");
    if (!has("/usage") || !has("show token usage")) fail("command map should preserve curated usage overlay command");
    if (has(" · agent") || has(" · backend")) fail("command map should not expose command implementation metadata");
    if (!has("commands")) fail("command help should use the same plain label as the picker");
    if (has("command map")) fail("command help should not expose internal command-map wording");
    for (const stale of ["Session browser", "Context graph", "Model switcher", "Replay cinema", "Diff forge", "Skill forge", "Eval lab"]) {
      if (has(stale)) fail(`command map should not use feature-name command copy: ${stale}`);
    }
  }

  if (name === "30-command-palette") {
    if (!has("1 / 19")) fail("command palette should use the curated Paper command catalog size");
    if (!has("/diff-stat")) fail("command palette should keep multi-word slash command labels readable");
    if (has("/diff-sta…")) fail("command palette should not clip slash command labels in the primary lane");
    if (has("/always-approve") || has("/approve") || has("/deny")) fail("command palette should keep approval actions out of the curated picker");
    if (!has("⌜⏎⌟ run")) fail("command palette should say enter runs the selected command");
    if (has("⌜⏎⌟ insert")) fail("command palette should not use mention-insert copy");
    if (!frame.split("\n").some((line) => line.includes("› /new") && line.includes("↵")))
      fail("command palette selected row should keep the Paper right-side enter cue");
    if (frame.split("\n").some((line) => line.includes("› /context") || line.includes("› /diff") || line.includes("› /diff-stat") || line.includes("› /replay") || line.includes("› /sessions")))
      fail("command palette should reserve the marker lane without drawing chevrons on inactive rows");
    if (!has("⌜↑↓⌟ move   ⌜⏎⌟ run   ⌜esc⌟ cancel") || has("⌜↑↓⌟ move · ⌜⏎⌟ run · ⌜esc⌟ cancel"))
      fail("command palette should use Paper cancel copy for Escape");
    for (const needle of ["start new session", "list sessions", "show context", "show model state"]) {
      if (!has(needle)) fail(`command palette should use Paper-style action copy: ${needle}`);
    }
    for (const stale of ["Session browser", "Context graph", "Model switcher"]) {
      if (has(stale)) fail(`command palette should not use feature-name command copy: ${stale}`);
    }
  }

  if (name === "25-headless-overlay") {
    for (const needle of ["run            start task", "stream         watch progress", "replay         review run", "draft skill    capture pattern", "usage          17324 tok · 5 calls", "bridge         connect clients", "same trace · cli parity"]) {
      if (!has(needle)) fail(`headless panel should use semantic row labels: ${needle}`);
    }
    for (const needle of [
      'tinyagent run "<prompt>"',
      'tinyagent run "<prompt>" --stream text',
      "tinyagent replay <run-id>",
      "fork           from step 42",
      "tinyagent fork <run-path> --at 42",
      "tinyagent skills draft-from-run <run-path>",
      "tinyagent agent stdio --protocol tinyagent",
    ]) {
      if (!has(needle)) fail(`headless panel should keep compact command templates readable: ${needle}`);
    }
    if (has("tinyagent run \"bring the panel surface in line with the P…") || has("/Users/k/work/dev/tinyagent/.tinyagent/run…"))
      fail("headless panel should not clip active prompt text or absolute run paths");
    if (has("tinyagent replay run_overlay_refactor") || has("from event 42"))
      fail("headless panel should use placeholder replay targets and step language");
    if (has("run json") || has("usage json") || has("json event log") || has("jsonl events") || has("run            tinyagent run"))
      fail("headless panel should not place wire-format copy in primary lanes");
    if (has("--output-format json") || has("--stream jsonl") || has("--debug") || has("jq .usage"))
      fail("headless panel should keep machine/debug formats out of the visible sheet");
    if (!has("saved with run summary")) fail("headless usage row should describe where usage lives without a jq recipe");
    if (has("draft skill    from run")) fail("headless draft-skill row should use trace language");
    if (has("stdio          protocol bridge") || has("agent          bridge mode")) fail("headless bridge row should not expose protocol or implementation wording in primary lanes");
    if (has("project run")) fail("headless replay row should not expose projection vocabulary");
  }

  if (name === "15-diff-overlay") {
    for (const needle of ["diff summary", "files          2 changed files", "Rail.ts · panelStyle.ts", "changes        +4 −1", "unified · full patch"]) {
      if (!has(needle)) fail(`diff overlay should give patch content a compact summary lane: ${needle}`);
    }
    if (has("changes        +4 -1")) fail("diff overlay should not use ASCII hyphen for removed counts");
    if (!has("backgroundColor: theme.surfaceOverlay")) fail("diff overlay should still render the selected diff content");
    if (has("PATCH  tui/src/ui/widgets/Rail.ts")) fail("diff overlay should suppress the transcript inline patch preview underneath");
    if (has("Files:") || has("Changed files:")) fail("diff overlay should not use prose headings for patch metadata");
  }

  if (name === "26-acp-overlay") {
    if (!has("acp bridge")) fail("ACP panel should use the compact bridge eyebrow");
    if (!has("bridge         live session") || !has("app-connected turn stream"))
      fail("ACP panel should keep bridge state product-facing");
    if (!has("command        app bridge")) fail("ACP panel should use a short semantic command value");
    if (!has("tinyagent agent stdio --protocol acp")) fail("ACP panel should keep the concrete command in the detail lane");
    if (has("command        tinyagent agent stdio --protoc")) fail("ACP panel should not clip command text in the value lane");
    if (has("transport      stdio json-rpc") || has("protocol stdout · stderr logs") || has("stdio json-rpc") || has("stderr logs"))
      fail("ACP panel should not expose transport/protocol log wording");
    for (const needle of ["start          open session", "create conversation", "prompt         stream turn", "send user prompt", "cancel         stop run", "return control", "approval       resolve tool", "allow or deny", "same trace · app parity"]) {
      if (!has(needle)) fail(`ACP panel should keep action rows readable: ${needle}`);
    }
    if (has("session.start") || has("session.prompt") || has("session.cancel") || has("approval.resolve"))
      fail("ACP panel should not expose protocol method names in visible rows");
    if (has("allocates") || has("notifications") || has("diagnostics") || has("observable"))
      fail("ACP panel should not read like protocol documentation");
  }

  if (name === "20-review-overlay") {
    for (const needle of ["source         model", "stopped turn", "last ok        step 14", "tool completed · safe checkpoint", "failed         step 15", "model failed · replay target", "inspect failure", "/replay", "rewind before failure", "/rewind 14", "retry compact prompt"]) {
      if (!has(needle)) fail(`failure review should expose readable recovery action: ${needle}`);
    }
    if (has("tool.execution.completed") || has("model.call.failed") || has("event 14") || has("event 15"))
      fail("failure review should not expose raw event type names in summary lanes");
    if (
      has("subsystem that reported") ||
      has("failure source") ||
      has("failure boundary") ||
      has("event to inspect") ||
      has("raw failed event") ||
      has("retry smaller prompt") ||
      has("project before failure")
    )
      fail("failure review should not read like explanatory documentation");
  }

  if (name === "22-extensions-overlay") {
    for (const needle of ["▍ mcp", "3 servers", "servers: filesystem, linear, paper", "2 servers", "app hooks", "off", "lifecycle hooks"]) {
      if (!has(needle)) fail(`extensions overlay should expose readable metadata: ${needle}`);
    }
    if (has("▤") || has("⌘") || has("✦")) fail("extensions overlay should not use ad hoc non-whitelisted kind glyphs");
    if (has("mcp · 3 servers") || has("lsp · 2 servers") || has("hook · off") || has("mcp · enabled") || has("product_runtime") || has("product runtime") || has("runtime hooks") || has("Model Context Protocol") || has("Experimental product") || has("Product runtime hooks") || has("local agent runti…"))
      fail("extensions overlay should not clip implementation prose in primary lanes");
  }

  if (name === "18-skills-overlay") {
    if (!has("▍ overlay-review") || !has("draft")) fail("skill forge should keep draft status in the right metadata lane");
    if (!has("visual-check") || !has("ready")) fail("skill forge should expose ready drafts in the right metadata lane");
    if (!has("draft          overlay-review") || !has("skills/overlay-review/SKILL.md"))
      fail("skill forge should show draft names and paths instead of raw draft ids");
    if (!has("skills/overlay-review/SKILL.md · overlay refactor"))
      fail("skill forge should keep draft path/source metadata readable");
    for (const needle of ["draft preview", "purpose       TUI overlay panel changes", "draft intent", "step 1        inspect Paper", "1 of 3", "step 3        capture snapshots", "3 of 3"]) {
      if (!has(needle)) fail(`skill forge should render draft markdown as compact lanes: ${needle}`);
    }
    if (has("selected       overlay-review") || has("selected draft")) fail("skill forge should not expose selection-state labels in the visible panel");
    if (has("draft    overlay-review") || has("ready    visual-check")) fail("skill forge should not align rows with padded title text");
    if (has("draft_overlay_review · run_overlay_refact…") || has("# overlay-review") || has("- inspect Paper") || has("from skill file") || has("workflow") || has("show skills/overlay-review/SKILL.md"))
      fail("skill forge should not render raw draft ids or markdown prose in primary lanes");
  }

  if (name === "19-update-overlay") {
    if (!has("ws : tinyagent") || !has("model : gpt-5"))
      fail("update chrome should drop branch before Paper identity labels");
    if (!has("source         alpha feed") || !has("checked release service"))
      fail("update panel should keep release source in a readable product lane");
    if (has("manifest       alpha remote") || has("https://updates.tinyagent.dev/alpha.json") || has("updates.tinyagent.dev") || has("alpha.json"))
      fail("update panel should not expose manifest wording or release feed URLs");
    if (!has("last           checked") || !has("2026-05-25 18:40"))
      fail("update panel should describe the last action as state, not command documentation");
    if (!has("ready to apply · rollback available")) fail("update panel should expose update state in the footer");
    if (has("/update check") || has("/update apply") || has("last local update command"))
      fail("update panel should not read like slash-command documentation");
  }

  if (name === "21-settings-overlay") {
    if (!has("semantic layer only · widgets unchanged")) fail("settings overlay should keep theme copy principle-facing");
    if (!has("spinner        braille") || !has("frame-based motion"))
      fail("settings overlay should explain the spinner as a motion primitive");
    for (const needle of ["reasoning      folded", "reasoning folded", "diff view      split", "split patch view", "mouse          on", "mouse and keyboard aligned"]) {
      if (!has(needle)) fail(`settings overlay should describe current state instead of option lists: ${needle}`);
    }
    if (!has("changes not written to disk")) fail("settings overlay should expose dirty state without command prose");
    if (has("paper-dark · paper-light") || has("spinner        braille\n                                        │     braille") || has("off · on") || has("unified · split") || has("high-contrast") || has("options:") || has("run /settings save") || has("/settings set <key> <value>"))
      fail("settings overlay should not read like command documentation");
  }

  if (name === "24-model-overlay") {
    for (const needle of ["model state", "provider       openai", "next turn", "model          gpt-5", "generation model", "approval       on-request", "tool gates", "session        normal", "reasoning folded"]) {
      if (!has(needle)) fail(`model overlay should keep model-state copy compact: ${needle}`);
    }
    if (
      has("runtime") ||
      has("selected model") ||
      has("active id") ||
      has("configured runtime for the next model call") ||
      has("openai-compatible model name passed to the provider") ||
      has("Launch config picks provider") ||
      has("active model id") ||
      has("shell and workspace tools") ||
      has("reasoning collapsed until requested") ||
      has("reasoning expanded in transcript")
    )
      fail("model overlay should not show implementation explanation copy");
  }

  if (name === "28-debug-overlay") {
    if (!has("ws : tinyagent") || !has("model : gpt-5"))
      fail("debug chrome should drop branch before Paper identity labels");
    if (has("Developer surface projected from AppState.") || has("debug view mirrors the event projection"))
      fail("debug overlay should not show implementation-note prose");
    if (has("⦗ / ⦘") || has("/always-approve") || has("› /new"))
      fail("debug overlay should cover stale command palette state");
    if (has("palette open")) fail("debug overlay should not expose covered palette state");
    for (const needle of ["approval on-request · plan session", "next turn", "theme          paper-dark", "semantic layer only · widgets unchanged", "activity       3 steps", "latest step 88 · 1 turn", "replay         0 steps", "0.0 ms timeline", "surface        debug overlay", "right sheet · diff unified", "reasoning      folded", "transcript fold"]) {
      if (!has(needle)) fail(`debug overlay should keep compact state copy: ${needle}`);
    }
    if (has("events        ") || has("last seq") || has("0 events") || has("0.0 ms replay") || has("debug rail") || has("right overlay") || has("transcript state") || has("overlay        open") || has("palette closed") || has("ms projection") || has("event projection") || has("theme paper-dark · panel debug") || has("paper-dark · debug panel") || has("approval on-request · session plan") || has("reasoning      collapsed"))
      fail("debug overlay should not read like implementation projection copy");
  }

  if (name === "31-picker-no-match" || name === "37-picker-at-no-match" || name === "38-picker-skill-no-match") {
    if (!has("no matches · ⌜esc⌟ cancel")) fail("empty picker should collapse to one non-selectable Paper cancel label");
    if (has("no matches · ⌜esc⌟ collapse")) fail("empty picker should not use collapse copy");
    if (has("(no match)") || has("›no match") || has("▸no match")) fail("empty picker must not render a selectable row");
  }

  if (name === "33-picker-hover-distinct") {
    if (!has("› /new")) fail("keyboard selection marker missing");
    if (!has("▸ /context")) fail("mouse hover marker missing");
  }

  if (name === "39-chrome-transient-overflow") {
    for (const needle of ["⦗ compact ⦘", "⦗ approve queued ⦘", "⦗ +2 ⦘", "⦗ failed ⦘"]) {
      if (!has(needle)) fail(`transient overflow scene missing ${needle}`);
    }
    if (!has("gpt-5")) fail("overflow chrome should preserve the model identity lane");
    if (has("ws : tinyagent    ⦗ failed")) fail("overflow chrome should not drop model while preserving workspace prose");
    if (has("update 0.4.2") || has("⦗ plan ⦘")) fail("overflow should hide concrete pills after the first two");
    if (!has("ask, plan") || !has("⌜esc⌟ cancel turn")) fail("queued approval should not cover the composer before approval phase");
    if (has("allow once") || has("risk: high")) fail("queued approval overflow should not render the blocking modal");
  }

  if (name === "27-theme-overlay") {
    const lines = frame.split("\n");
    if (!has("same widgets · different semantic tokens")) fail("theme panel should explain semantic-token previews");
    for (const needle of ["PAPER-DARK", "PAPER-LIGHT", "MONO"]) {
      if (!has(needle)) fail(`theme panel missing ${needle} preview`);
    }
    for (const needle of ["default", "bright environments", "screen recording · demos · CI snapshots"]) {
      if (!has(needle)) fail(`theme panel missing Paper subtitle ${needle}`);
    }
    for (const needle of ["thought for 2s", "edit Transcript.ts · +3 −1", "⠙ shell bun test", "implement design tokens"]) {
      if (!has(needle)) fail(`theme panel should mirror Paper preview row ${needle}`);
    }
    if (has("▍ PAPER-DARK") || has("▍ PAPER-LIGHT") || has("▍ MONO")) fail("theme panel should use Paper color/border treatment, not list-row markers");
    if (has("edit Transcript.ts · +3 -1")) fail("theme panel should not use ASCII hyphen for removed counts");
    if (has("⠋ shell bun test")) fail("theme panel should use the same static running frame as the Paper preview");
    const monoLine = lines.findIndex((line) => line.includes("MONO"));
    const monoInputLine = lines.findIndex((line, index) => index > monoLine && line.includes("implement design tokens"));
    const footerLine = lines.findIndex((line) => line.includes("semantic layer only · widgets unchanged"));
    if (monoLine < 0 || monoInputLine < 0 || footerLine < 0 || monoInputLine > footerLine)
      fail("theme panel should fit the MONO preview before the footer");
    if (lines.some((line, index) => line.includes("│  │ ─") && lines[index + 1]?.includes("│  │ ─")))
      fail("theme panel divider should not wrap inside preview cards");
    if (!has("semantic layer only · widgets unchanged")) fail("theme panel footer should state the Paper semantic-layer principle");
    if (has("cycle: paper-dark · paper-light · mono") || has("high-contrast in settings"))
      fail("theme panel footer should not read like settings documentation");
  }

  if (name === "40-chrome-branch-hover-80") {
    if (!has("⎇ ta-r…ing")) fail("hovered compact branch should expand to a truncated branch name");
    if (has("⎇ …")) fail("hovered branch should not remain fully collapsed");
  }

  if (name === "41-activity-overlay") {
    for (const needle of ["activity", "2 tool calls", "session mode", "mode          plan", "write tools locked"]) {
      if (!has(needle)) fail(`activity overlay should expose compact plan state: ${needle}`);
    }
    if (!frame.split("\n").some((line) => line.includes("▍ ✓ read") && line.includes("Paper activity reference")))
      fail("activity overlay should keep selected tool input in the row metadata lane");
    if (!frame.split("\n").some((line) => line.includes("⠋ patch") && line.includes("PlanBoardWidget copy")))
      fail("activity overlay should keep running tool input in the row metadata lane");
    for (const stale of ["│     Paper activity reference", "│     PlanBoardWidget copy"]) {
      if (has(stale)) fail(`activity overlay should not render tool input as a second-line description: ${stale.trim()}`);
    }
    if (!has("⠙ patch") || !has("⠋ patch activity panel")) fail("activity overlay should render readable plan-step action labels");
    if (has("⠹ patch")) fail("activity overlay should not advance live spinners faster than the Paper beat cadence");
    if (has("plan.ste") || has("plan.step")) fail("activity overlay should not expose clipped or dotted internal tool ids");
    if ((frame.match(/⦗ plan ⦘/g) ?? []).length !== 1) fail("activity overlay should not duplicate the plan pill");
    for (const stale of ["PLAN MODE ACTIVE", "Build mode", "/build exits plan", "/plan enters planning", "Plan mode active", "Plan mode inactive"]) {
      if (has(stale)) fail(`activity overlay should not show stale mode prose: ${stale}`);
    }
  }

  if (name === "45-activity-empty-overlay") {
    for (const needle of ["activity", "activity clear", "tool calls", "status        quiet", "waiting for agent actions", "session mode", "mode          plan", "write tools locked"]) {
      if (!has(needle)) fail(`empty activity overlay should stay quiet and product-facing: ${needle}`);
    }
    if (has("tool calls · none yet") || has("tool calls · none selected") || has("none selected") || has("none yet"))
      fail("empty activity overlay should not expose blunt empty-selection copy");
    const lines = frame.split("\n");
    const waitingLine = lines.findIndex((line) => line.includes("waiting for agent actions"));
    const modeLine = lines.findIndex((line) => line.includes("session mode"));
    if (waitingLine < 0 || modeLine < 0 || modeLine - waitingLine > 4)
      fail("empty activity overlay should collapse the quiet tool state before session mode");
  }
}

// ── Scene builders ─────────────────────────────────────────────────────────

function baseState(): AppState {
  const s = emptyState();
  s.workspaces = [{ workspace_id: "ws1", root: "/Users/k/work/dev/tinyagent", name: "tinyagent" }];
  s.activeWorkspaceId = "ws1";
  s.model = "gpt-5";
  s.provider = "openai";
  s.workspaceFiles = [
    "src/ui/widgets/Transcript.ts",
    "src/ui/widgets/Composer.ts",
    "src/ui/widgets/ChromeBar.ts",
    "tests/ui/transcript.test.ts",
    "docs/TRANSCRIPT.md",
    "src/design/tokens.ts",
    "docs/TUI.md",
    "README.md",
  ];
  s.workspaceFileMetadata = {
    "src/ui/widgets/Transcript.ts": { bytes: 12 * 1024, mtimeMs: 30 },
    "tests/ui/transcript.test.ts": { bytes: 4 * 1024, mtimeMs: 20 },
    "docs/TRANSCRIPT.md": { bytes: 2 * 1024, mtimeMs: 10 },
    "README.md": { bytes: 3 * 1024, mtimeMs: 100 },
  };
  s.activeSession = {
    runId: "run-1",
    conversationId: "conv-1",
    turns: [],
    pendingApproval: null,
    pendingApprovalToolName: null,
    diff: null,
    git: { branch: "ta-review-gated-learning" } as any,
    usage: { inputTokens: 0, outputTokens: 0, totalTokens: 0, modelCalls: 0, latencyMs: 0 },
  } as SessionState;
  return s;
}

function sceneIdle(): Scene {
  const state = baseState();
  return { name: "01-idle", state };
}

function sceneStreaming(): Scene {
  const state = baseState();
  state.phase = "streaming";
  state.activeSession!.turns = [
    {
      id: "t1",
      user: "fix the streaming jitter in Transcript so phase changes don't reflow the whole pane",
      assistant:
        "We can keep the existing transcript card and mutate the assistant node's content in place. The markdown renderer already supports in-place updates via the streaming flag, so we never re-mount when phase doesn't change.\n\nOnce that lands the per-chunk reflow disappears and the spinner can co-exist with the caret.",
      reasoning: [{ id: "r1", text: "The reflow happens because we replace assistant.content on every chunk.", completed: true }],
      tools: [],
      phase: "streaming",
      startedAt: "20:48",
      completedAt: undefined,
    },
  ];
  state.activeSession!.usage.totalTokens = 1400;
  return { name: "02-streaming", state };
}

function sceneToolsResolving(): Scene {
  const state = baseState();
  state.phase = "streaming";
  state.activeSession!.turns = [
    {
      id: "t1",
      user: "fix the streaming jitter in Transcript so phase changes don't reflow the whole pane",
      assistant:
        "We can keep the existing transcript card and mutate the assistant node in place. Here is the patch:\n\nOnce that lands the per-chunk reflow disappears and the spinner can co-exist with the caret. We should also coalesce bursty chunks at motion.stream.gate so we never queue redundant paints.",
      reasoning: [
        {
          id: "r1",
          text: "The reflow happens because we replace assistant.content on every chunk, which re-mounts the markdown node. The renderer should mutate the existing node's content prop instead — markdown.ts already supports in-place updates via the streaming flag.",
          completed: true,
          startedAt: "2026-05-25T20:48:00.000Z",
          completedAt: "2026-05-25T20:48:04.000Z",
        },
      ],
      tools: [
        {
          id: "tc1",
          tool: "read",
          label: "read",
          argsSummary: "src/ui/widgets/Transcript.ts · 250 lines",
          status: "done",
          output: "",
          startedAt: "2026-05-25T20:48:00.000Z",
          completedAt: "2026-05-25T20:48:00.400Z",
        },
        {
          id: "tc2",
          tool: "search",
          label: "search",
          argsSummary: '"card.lastAssistant" in src/ · 3 hits',
          status: "done",
          output: "Transcript.ts:160 — card.assistant.content = next;\nmarkdown.ts:42 — streaming: turn.phase === \"streaming\"",
          startedAt: "2026-05-25T20:48:00.400Z",
          completedAt: "2026-05-25T20:48:00.600Z",
        },
        {
          id: "tc3",
          tool: "edit",
          label: "edit",
          argsSummary: "src/ui/widgets/Transcript.ts",
          status: "running",
          output: "",
          startedAt: "2026-05-25T20:48:00.600Z",
        },
      ],
      phase: "streaming",
      startedAt: "20:48",
    },
  ];
  state.activeSession!.diff = {
    paths: ["src/ui/widgets/Transcript.ts"],
    truncated: false,
    text: [
      "diff --git a/src/ui/widgets/Transcript.ts b/src/ui/widgets/Transcript.ts",
      "@@ -158,7 +158,9 @@ function applyChunk(card, next) {",
      " function applyChunk(card, next) {",
      "+  if (next !== card.lastAssistant) {",
      "+    card.assistant.content = next;",
      "+    card.lastAssistant = next;",
      "-    card.assistant = rebuild(next);",
      "   }",
      " }",
    ].join("\n"),
  };
  state.activeSession!.pendingApproval = {
    approval_id: "approval_queued",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "npm test -- --watch",
    args_preview: "npm test -- --watch",
  };
  state.activeSession!.usage.totalTokens = 30_720;
  return {
    name: "03-tools-inline-resolve",
    state,
    viewport: { width: 160, height: HEIGHT },
    prepare: (mount) => {
      mount.composer.setValue("implement the new design tokens");
    },
  };
}

function sceneRootPaperSize(): Scene {
  return {
    ...sceneToolsResolving(),
    name: "44-root-paper-size",
    viewport: { width: 110, height: 36 },
  };
}

function scenePickerSlash(): Scene {
  const state = baseState();
  return {
    name: "04-picker-slash",
    state,
    prepare: (mount) => {
      mount.composer.setValue("/rep");
      mount.composer.focus();
    },
  };
}

function scenePickerAt(): Scene {
  const state = baseState();
  return {
    name: "05-picker-at-file",
    state,
    prepare: (mount) => {
      mount.composer.setValue("summarize @tra");
      mount.composer.focus();
    },
  };
}

function scenePickerSkill(): Scene {
  const state = baseState();
  state.skills = [
    {
      name: "verify",
      path: "skills/verify/SKILL.md",
      description: "run app, observe",
    },
    {
      name: "review",
      path: "skills/review/SKILL.md",
      description: "review the diff",
    },
    {
      name: "loop",
      path: "skills/loop/SKILL.md",
      description: "run on interval",
    },
    {
      name: "visual-check",
      path: "skills/visual-check/SKILL.md",
      description: "capture snapshots",
    },
    {
      name: "paper-review",
      path: "skills/paper-review/SKILL.md",
      description: "compare against Paper",
    },
    {
      name: "fix-ci",
      path: "skills/fix-ci/SKILL.md",
      description: "debug checks",
    },
    {
      name: "ship",
      path: "skills/ship/SKILL.md",
      description: "prepare a PR",
    },
    {
      name: "smoke",
      path: "skills/smoke/SKILL.md",
      description: "quickly verify",
    },
    {
      name: "docs",
      path: "skills/docs/SKILL.md",
      description: "write docs",
    },
    {
      name: "perf",
      path: "skills/perf/SKILL.md",
      description: "profile latency",
    },
    {
      name: "release",
      path: "skills/release/SKILL.md",
      description: "release notes",
    },
  ];
  return {
    name: "29-picker-skill",
    state,
    prepare: (mount) => {
      mount.composer.setValue("Save $ver");
      mount.composer.focus();
    },
  };
}

function sceneCommandPalette(): Scene {
  const state = baseState();
  return {
    name: "30-command-palette",
    state,
    prepare: (mount) => {
      mount.palette.show();
    },
  };
}

function scenePickerNoMatch(): Scene {
  const state = baseState();
  return {
    name: "31-picker-no-match",
    state,
    prepare: (mount) => {
      mount.composer.setValue("/zzzz");
      mount.composer.focus();
    },
  };
}

function scenePickerAtNoMatch(): Scene {
  const state = baseState();
  return {
    name: "37-picker-at-no-match",
    state,
    prepare: (mount) => {
      mount.composer.setValue("summarize @zzzz");
      mount.composer.focus();
    },
  };
}

function scenePickerSkillNoMatch(): Scene {
  const state = baseState();
  state.skills = [
    {
      name: "visual-check",
      path: "skills/visual-check/SKILL.md",
      description: "Capture OpenTUI scenes before calling UI work done",
    },
  ];
  return {
    name: "38-picker-skill-no-match",
    state,
    prepare: (mount) => {
      mount.composer.setValue("run $zzzz");
      mount.composer.focus();
    },
  };
}

function scenePickerHover(): Scene {
  const state = baseState();
  return {
    name: "33-picker-hover-distinct",
    state,
    prepare: (mount) => {
      mount.composer.setValue("/");
      mount.composer.focus();
    },
    afterRefresh: (mount) => {
      (mount.mentionMenu as any).setHoverIndex?.(1);
    },
  };
}

function sceneTranscriptInteraction(): Scene {
  const state = baseState();
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "inspect transcript interactivity",
      assistant: "The transcript keeps output quiet until the row is expanded.",
      reasoning: [{ id: "r1", text: "The clickable header should reveal this reasoning without turning the whole transcript into cards.", completed: true }],
      tools: [
        {
          id: "tc1",
          tool: "read",
          label: "read",
          argsSummary: "tui/src/ui/widgets/Transcript.ts · 340 lines",
          status: "done",
          output: "Transcript.ts:140 — reasoning header\nTranscript.ts:260 — tool output row",
          startedAt: "20:48",
          completedAt: "20:48",
        },
        {
          id: "tc2",
          tool: "search",
          label: "search",
          argsSummary: '"clickable" in DESIGN_TOKENS.md · 4 hits',
          status: "done",
          output: "DESIGN_TOKENS.md:666 — hover state\nDESIGN_TOKENS.md:678 — Transcript turn header\nDESIGN_TOKENS.md:679 — Tool call rows",
          startedAt: "20:49",
          completedAt: "20:49",
        },
      ],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:50",
    },
  ];
  return {
    name: "34-transcript-clickable-rows",
    state,
    afterRefresh: (mount) => {
      mount.transcript.setReasoningExpanded("t1", true);
      mount.transcript.setToolExpanded("tc2", true);
      mount.transcript.setHoveredTool("tc2");
    },
  };
}

function sceneComposerHintClick(): Scene {
  const state = baseState();
  state.skills = [
    {
      name: "visual-check",
      path: "skills/visual-check/SKILL.md",
      description: "Capture OpenTUI scenes before calling UI work done",
    },
    {
      name: "paper-review",
      path: "skills/paper-review/SKILL.md",
      description: "Compare the terminal surface against the Paper artboard",
    },
  ];
  return {
    name: "35-composer-hint-skills-click",
    state,
    prepare: (mount) => {
      mount.composer.setValue("implement design tokens");
      mount.composer.activateHint("$");
    },
    afterRefresh: (mount) => {
      mount.composer.setHoveredHintAction("$");
    },
  };
}

function sceneComposerUnfocused(): Scene {
  const state = baseState();
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "check composer focus treatment",
      assistant: "The composer should go quiet when focus moves back to the transcript.",
      reasoning: [],
      tools: [],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:49",
    },
  ];
  return {
    name: "36-composer-unfocused-placeholder",
    state,
    prepare: (mount) => {
      mount.focus.focusById("transcript");
    },
  };
}

function sceneApprovalModal(): Scene {
  const state = baseState();
  state.phase = "approval";
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "fix the streaming jitter in Transcript",
      assistant: "We should clean the local install, but the command needs explicit approval first.",
      reasoning: [{ id: "r1", text: "The shell command is destructive and must block on a modal.", completed: true }],
      tools: [
        { id: "tc1", tool: "shell", label: "shell", argsSummary: "rm -rf node_modules", status: "blocked", output: "", startedAt: "20:48" },
      ],
      phase: "approval",
      startedAt: "20:48",
    },
  ];
  const approval: Approval = {
    approval_id: "ap1",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "rm -rf node_modules",
    args_preview: "rm -rf node_modules",
    cwd: "/Users/kristian/work/dev/tinyagent",
    turn_id: "turn 7",
  } as any;
  state.activeSession!.pendingApproval = approval;
  return { name: "06-approval-modal", state };
}

function sceneCtxWarning(): Scene {
  const state = baseState();
  state.activeSession!.usage.totalTokens = Math.round(128_000 * 0.82); // 82%
  return { name: "07-ctx-warning", state };
}

function sceneCtxDanger(): Scene {
  const state = baseState();
  state.activeSession!.usage.totalTokens = Math.round(128_000 * 0.96); // 96%
  return { name: "08-ctx-danger", state };
}

function sceneChromeTransientOverflow(): Scene {
  const state = baseState();
  state.phase = "failed";
  state.sessionMode = "plan";
  state.activeSession!.usage.totalTokens = 128_000;
  state.activeSession!.pendingApproval = {
    approval_id: "approval_overflow",
    tool_name: "shell",
    action_kind: "run-command",
    risk: "high",
    command: "rm -rf node_modules",
    args_preview: "rm -rf node_modules",
  };
  state.updatePanel = {
    status: "ready",
    lastAction: "auto-check",
    error: "",
    result: {
      current_version: "0.4.1",
      latest_version: "0.4.2",
      channel: "alpha",
      install_kind: "standalone",
      manifest_source: "test",
      checked_at: "",
      available: true,
      reason: "new alpha build available",
      platform: "darwin-arm64",
      active_version: "0.4.1",
      previous_version: "",
      artifact: null,
    },
  };
  return { name: "39-chrome-transient-overflow", state };
}

function sceneSessionsOverlay(): Scene {
  const state = baseState();
  state.ui.activePanel = "sessions";
  state.sessions = [
    {
      conversation_id: "conv_design_tokens",
      title: "design tokens · TUI",
      status: "active",
      active_turn_id: null,
      created_at: "2026-05-25T18:41:00Z",
      updated_at: "2m ago",
      workspace: "tinyagent",
      turn_count: 14,
      model: "gpt-5",
      tokens: 4200,
      last_run_id: "run_design",
      last_turn_status: "done",
    } as any,
    {
      conversation_id: "conv_review_gated",
      title: "review-gated learning",
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-25T17:12:00Z",
      updated_at: "2h ago",
      workspace: "tinyagent",
      turn_count: 27,
      model: "gpt-5",
      tokens: 11_400,
      last_run_id: "run_review",
      last_turn_status: "done",
    } as any,
    {
      conversation_id: "conv_sdk_lifecycle",
      title: "SDK lifecycle surface",
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-24T12:10:00Z",
      updated_at: "1d ago",
      workspace: "tinyagent",
      turn_count: 9,
      model: "gpt-5",
      tokens: 2100,
    } as any,
    {
      conversation_id: "conv_workspace_snapshot",
      title: "workspace snapshot ext",
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-24T09:05:00Z",
      updated_at: "1d ago",
      workspace: "tinyagent",
      turn_count: 15,
      model: "gpt-5",
    } as any,
    {
      conversation_id: "conv_permission_profiles",
      title: "permission profiles v1",
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-23T14:10:00Z",
      updated_at: "2d ago",
      workspace: "tinyagent",
      turn_count: 6,
      model: "haiku-4.5",
    } as any,
    {
      conversation_id: "conv_allowed_tools",
      title: "allowed tool boundary",
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-22T10:00:00Z",
      updated_at: "3d ago",
      workspace: "tinyagent",
      turn_count: 22,
      model: "gpt-5",
    } as any,
    ...Array.from({ length: 6 }, (_, index) => ({
      conversation_id: `conv_archive_${index}`,
      title: `archive session ${index + 1}`,
      status: "done",
      active_turn_id: null,
      created_at: "2026-05-20T10:00:00Z",
      updated_at: `${index + 4}d ago`,
      workspace: "tinyagent",
      turn_count: 3 + index,
      model: "gpt-5",
    })) as any,
  ];
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "the slash-command list was getting buggy; merging menus",
      assistant:
        "All three widgets now consume the same picker surface. The command list, file mentions, and skill mentions share one compact overlay with consistent keyboard behavior.",
      reasoning: [{ id: "r1", text: "The Paper reference shows the session panel sliding over an intact transcript.", completed: true }],
      tools: [
        { id: "tc1", tool: "read", label: "read", argsSummary: "src/ui/widgets/Picker.ts · 180 lines", status: "done", output: "", startedAt: "20:48", completedAt: "20:48" },
        { id: "tc2", tool: "search", label: "search", argsSummary: '"menu" in src/ui · 14 hits', status: "done", output: "", startedAt: "20:49", completedAt: "20:49" },
      ],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:50",
    },
  ];
  return { name: "09-sessions-overlay", state };
}

function sceneCompactPicker(): Scene {
  const state = baseState();
  return {
    name: "10-compact-picker-80",
    state,
    viewport: { width: 80, height: 24 },
    prepare: (mount) => {
      mount.composer.setValue("/rep");
      mount.composer.focus();
    },
  };
}

function sceneDensityThreshold99(): Scene {
  const state = baseState();
  return {
    name: "42-density-threshold-99",
    state,
    viewport: { width: 99, height: 24 },
  };
}

function sceneDensityThreshold100(): Scene {
  const state = baseState();
  return {
    name: "43-density-threshold-100",
    state,
    viewport: { width: 100, height: 24 },
  };
}

function sceneChromeBranchHover(): Scene {
  const state = baseState();
  return {
    name: "40-chrome-branch-hover-80",
    state,
    viewport: { width: 80, height: 24 },
    afterRefresh: (mount) => {
      const chrome = mount.chromeBar as any;
      chrome.setHoveredLeftAction?.("diff");
    },
  };
}

function sceneActivityOverlay(): Scene {
  const state = baseOverlayState("activity");
  state.sessionMode = "plan";
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "review activity overlay",
      assistant: "The activity panel keeps tool calls and session mode in the same compact state language.",
      reasoning: [],
      tools: [
        { id: "tc1", tool: "read", label: "read", argsSummary: "Paper activity reference", status: "done", output: "", startedAt: "20:48", completedAt: "20:48" },
        { id: "tc2", tool: "plan.step", label: "patch activity panel", argsSummary: "PlanBoardWidget copy", status: "running", output: "", startedAt: "20:49" },
      ],
      phase: "thinking",
      startedAt: "20:48",
      completedAt: "",
    },
  ];
  return { name: "41-activity-overlay", state };
}

function sceneActivityEmptyOverlay(): Scene {
  const state = baseOverlayState("activity");
  state.sessionMode = "plan";
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "wait for the next step",
      assistant: "The activity surface should stay quiet until a tool call appears.",
      reasoning: [],
      tools: [],
      phase: "thinking",
      startedAt: "20:48",
      completedAt: "",
    },
  ];
  return { name: "45-activity-empty-overlay", state };
}

function sceneCompactSessionsOverlay(): Scene {
  const state = sceneSessionsOverlay().state;
  return {
    name: "32-compact-sessions-overlay-80",
    state,
    viewport: { width: 80, height: 24 },
  };
}

function sceneHistorySearch(): Scene {
  const state = baseState();
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "review the overlay state",
      assistant: "The compact overlays now share one frame language.",
      reasoning: [],
      tools: [],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:49",
    },
  ];
  return {
    name: "11-history-search",
    state,
    prepare: (mount) => {
      mount.historySearch.open(
        [
          "fix the streaming jitter in Transcript",
          "review the overlay state",
          "summarize @src/ui/widgets/Transcript.ts",
        ],
        () => {},
      );
      for (const ch of "over") mount.historySearch.appendChar(ch);
    },
  };
}

function sceneContextMenu(): Scene {
  const state = baseState();
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "copy the last answer",
      assistant: "The context menu should feel like the same compact Paper popover as the rest of the shell.",
      reasoning: [],
      tools: [],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:49",
    },
  ];
  return {
    name: "12-context-menu",
    state,
    prepare: (mount) => {
      mount.contextMenu.showAt(
        4,
        5,
        [
          { label: "Copy last reply", description: "Copy assistant text", value: "copy-last" },
          { label: "Copy conversation", description: "Copy all turns", value: "copy-conv" },
          { label: "Stop run", description: "Cancel active run", value: "stop-run" },
        ],
        () => {},
      );
    },
  };
}

function sceneContextOverlay(): Scene {
  const state = baseOverlayState("context");
  state.workspaceFiles = [
    "tui/src/ui/widgets/Rail.ts",
    "tui/src/ui/widgets/ContextWidget.ts",
    "tui/src/ui/widgets/ReplayWidget.ts",
    "tui/src/ui/widgets/panelStyle.ts",
    "tui/scripts/visual-check.ts",
    "docs/TUI.md",
    "README.md",
  ];
  state.activeSession!.git = {
    isRepo: true,
    clean: false,
    branch: "tui-paper-overlay",
    ahead: 2,
    behind: 0,
    files: [
      { path: "tui/src/ui/widgets/ContextWidget.ts", status: "modified" },
      { path: "tui/src/ui/widgets/panelStyle.ts", status: "added" },
      { path: "tui/scripts/visual-check.ts", status: "modified" },
    ],
    diff: "",
    diffTruncated: false,
  };
  return { name: "13-context-overlay", state };
}

function sceneUsageOverlay(): Scene {
  const state = baseOverlayState("usage");
  state.activeSession!.usage = {
    inputTokens: 48_212,
    outputTokens: 9_408,
    totalTokens: 57_620,
    modelCalls: 11,
    latencyMs: 18_740,
  };
  return { name: "14-usage-overlay", state };
}

function sceneDiffOverlay(): Scene {
  const state = baseOverlayState("diff");
  state.activeSession!.diff = {
    paths: ["tui/src/ui/widgets/Rail.ts", "tui/src/ui/widgets/panelStyle.ts"],
    truncated: false,
    text: [
      "diff --git a/tui/src/ui/widgets/Rail.ts b/tui/src/ui/widgets/Rail.ts",
      "--- a/tui/src/ui/widgets/Rail.ts",
      "+++ b/tui/src/ui/widgets/Rail.ts",
      "@@ -83,2 +83,2 @@",
      "-      backgroundColor: theme.surface,",
      "+      backgroundColor: theme.surfaceOverlay,",
      "       border: [\"left\"],",
      "diff --git a/tui/src/ui/widgets/panelStyle.ts b/tui/src/ui/widgets/panelStyle.ts",
      "new file mode 100644",
      "--- /dev/null",
      "+++ b/tui/src/ui/widgets/panelStyle.ts",
      "@@ -0,0 +1,3 @@",
      "+export function makePanelList(opentui, ctx, theme, options = {}) {",
      "+  return { backgroundColor: theme.surfaceOverlay, ...options };",
      "+}",
    ].join("\n"),
  };
  return { name: "15-diff-overlay", state };
}

function sceneReplayOverlay(): Scene {
  const state = baseOverlayState("replay");
  const events = [
    makeEvent(1, "run.started", { task: "align overlay panels with Paper" }),
    makeEvent(2, "model.reasoning.completed", { reason: "The right sheet is the stable frame." }),
    makeEvent(3, "tool.execution.started", { tool: "read", args: { path: "tui/src/ui/widgets/Rail.ts" } }),
    makeEvent(4, "tool.execution.completed", { tool: "read", output: "RailWidget mounts the overlay shell." }),
    makeEvent(5, "model.text.delta", { delta: "The panel surfaces now share one language." }),
  ];
  state.replay = {
    runId: "run_overlay_refactor",
    events,
    cursorSeq: 4,
    rawEvent: events[3],
    projected: {
      phase: "streaming",
      lastSeq: 4,
      turns: 1,
      tools: 1,
      assistantPreview: "The panel surfaces now share one language.",
    },
    forkDir: "/private/tmp/tinyagent/fork-0004",
    replayMs: 5.7,
  };
  return { name: "16-replay-overlay", state };
}

function sceneEvalOverlay(): Scene {
  const state = baseOverlayState("eval");
  state.evalLab = {
    status: "completed",
    suitePath: "evals/tui-overlay.yaml",
    outputDir: ".tinyagent/evals/overlay-20260525",
    command: "tinyagent eval run evals/tui-overlay.yaml",
    error: "",
    results: [
      { case_id: "slash-picker", success: true, status: "passed", model_call_count: 1, tool_call_count: 0 },
      { case_id: "approval-modal", success: true, status: "passed", model_call_count: 1, tool_call_count: 1 },
      { case_id: "sessions-overlay", success: true, status: "passed", model_call_count: 2, tool_call_count: 2 },
      { case_id: "compact-80col", success: false, status: "failed", failure_reason: "footer clipped at 80 columns" },
    ],
    report: [
      "overlay visual eval",
      "passed: 3 / 4",
      "needs review: compact-80col footer clipping",
      "",
      "next step · tighten footer hint spacing before release",
    ].join("\n"),
  };
  return { name: "17-eval-overlay", state };
}

function sceneSkillsOverlay(): Scene {
  const state = baseOverlayState("skills");
  state.skillForge = {
    status: "ready",
    selectedDraftId: "draft_overlay_review",
    lastAction: "show draft_overlay_review",
    error: "",
    drafts: [
      {
        draft_id: "draft_overlay_review",
        name: "overlay-review",
        path: "skills/overlay-review/SKILL.md",
        status: "draft",
        source_run_id: "run_overlay_refactor",
        created_at: "2026-05-25T18:45:00Z",
      },
      {
        draft_id: "draft_visual_check",
        name: "visual-check",
        path: "skills/visual-check/SKILL.md",
        status: "ready",
        source_run_id: "run_snapshots",
        created_at: "2026-05-25T18:10:00Z",
      },
    ],
    markdown: [
      "# overlay-review",
      "",
      "For TUI overlay panel changes.",
      "",
      "- inspect Paper",
      "- update a focused surface",
      "- capture snapshots before calling the work done",
    ].join("\n"),
  };
  return { name: "18-skills-overlay", state };
}

function sceneUpdateOverlay(): Scene {
  const state = baseOverlayState("update");
  state.updatePanel = {
    status: "ready",
    lastAction: "check",
    error: "",
    result: {
      current_version: "0.4.1",
      channel: "alpha",
      install_kind: "uv-tool",
      manifest_source: "https://updates.tinyagent.dev/alpha.json",
      checked_at: "2026-05-25T18:40:00Z",
      latest_version: "0.4.2",
      available: true,
      reason: "new alpha build available",
      platform: "darwin-arm64",
      active_version: "0.4.1",
      previous_version: "0.4.0",
      artifact: null,
    },
  };
  return { name: "19-update-overlay", state };
}

function sceneReviewOverlay(): Scene {
  const state = baseOverlayState("review");
  state.failure = {
    source: "model",
    lastSuccessfulEvent: "14 tool.execution.completed",
    failedEvent: "15 model.call.failed",
    recoveryActions: [
      "Inspect raw failed event with /replay.",
      "Project state before failure with /rewind 14.",
      "Retry with a smaller prompt bundle.",
    ],
  };
  return { name: "20-review-overlay", state };
}

function sceneSettingsOverlay(): Scene {
  const state = baseOverlayState("settings");
  state.settings = {
    theme: "paper-dark",
    spinner: "braille",
    showReasoning: false,
    diffView: "split",
    mouseCapture: true,
    rightRail: false,
    dirty: true,
  };
  return { name: "21-settings-overlay", state };
}

function sceneExtensionsOverlay(): Scene {
  const state = baseOverlayState("extensions");
  state.extensions = [
    {
      name: "mcp",
      kind: "mcp",
      servers: ["filesystem", "linear", "paper"],
      enabled: true,
      description: "Connected tool servers available to the local agent runtime.",
    },
    {
      name: "lsp",
      kind: "lsp",
      servers: ["typescript", "python"],
      enabled: true,
      description: "Language servers used for hover, symbols, and diagnostics.",
    },
    {
      name: "product_runtime",
      kind: "feature",
      enabled: false,
      description: "Product runtime hooks.",
    },
  ];
  return { name: "22-extensions-overlay", state };
}

function sceneHelpOverlay(): Scene {
  const state = baseOverlayState("help");
  return { name: "23-help-overlay", state };
}

function sceneModelOverlay(): Scene {
  const state = baseOverlayState("model");
  state.provider = "openai";
  state.model = "gpt-5";
  return { name: "24-model-overlay", state };
}

function sceneHeadlessOverlay(): Scene {
  const state = baseOverlayState("headless");
  state.activeSession!.runId = "run_overlay_refactor";
  state.activeSession!.runPath = "/Users/k/work/dev/tinyagent/.tinyagent/runs/run_overlay_refactor";
  state.activeSession!.lastSeq = 42;
  state.activeSession!.usage = {
    inputTokens: 14_220,
    outputTokens: 3_104,
    totalTokens: 17_324,
    modelCalls: 5,
    latencyMs: 9_220,
  };
  return { name: "25-headless-overlay", state };
}

function sceneAcpOverlay(): Scene {
  const state = baseOverlayState("acp");
  return { name: "26-acp-overlay", state };
}

function sceneThemeOverlay(): Scene {
  const state = baseOverlayState("theme");
  state.ui.theme = "paper-dark";
  state.ui.spinner = "braille";
  return { name: "27-theme-overlay", state };
}

function sceneDebugOverlay(): Scene {
  const state = baseOverlayState("debug");
  state.phase = "streaming";
  state.approvalMode = "on-request";
  state.sessionMode = "plan";
  state.ui.paletteOpen = true;
  state.activeSession!.lastSeq = 88;
  state.activeSession!.eventsBySeq = new Map([
    [86, makeEvent(86, "tool.execution.started", { tool: "read" })],
    [87, makeEvent(87, "tool.execution.completed", { tool: "read" })],
    [88, makeEvent(88, "model.text.delta", { delta: "ok" })],
  ]);
  return { name: "28-debug-overlay", state };
}

function baseOverlayState(panel: string): AppState {
  const state = baseState();
  state.ui.activePanel = panel;
  state.activeSession!.usage.totalTokens = 32_400;
  state.activeSession!.turns = [
    {
      id: "t1",
      runId: "run-1",
      user: "bring the panel surface in line with the Paper TUI reference",
      assistant:
        "The main shell stays one column. Panels slide over the transcript from the right and keep the same compact terminal rhythm.",
      reasoning: [{ id: "r1", text: "The sheet should cover, not split, the conversation.", completed: true }],
      tools: [
        { id: "tc1", tool: "read", label: "read", argsSummary: "Paper overlay reference", status: "done", output: "", startedAt: "20:48", completedAt: "20:48" },
        { id: "tc2", tool: "edit", label: "edit", argsSummary: "panel widgets", status: "done", output: "", startedAt: "20:49", completedAt: "20:50" },
      ],
      phase: "done",
      startedAt: "20:48",
      completedAt: "20:50",
    },
  ];
  return state;
}

function makeEvent(seq: number, type: string, data: Record<string, unknown>): RunEvent {
  return {
    id: `evt_${seq}`,
    seq,
    type,
    time: `2026-05-25T18:4${seq}:00Z`,
    run_id: "run_overlay_refactor",
    turn_id: "turn_1",
    item_id: `item_${seq}`,
    parent_item_id: null,
    source: "agent",
    visibility: "public",
    durability: "event_log",
    data,
    artifact_refs: [],
    workspace_id: "ws1",
    conversation_id: "conv-1",
  };
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
