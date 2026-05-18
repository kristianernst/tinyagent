import { ascii } from "../../design/ascii";
import type { Theme } from "../theme";
import { makeBox, makeText } from "../layout";

export function buildSplash(opentui: any, ctx: any, theme: Theme): any {
  const box = makeBox(opentui, ctx, {
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    paddingY: 1,
    backgroundColor: theme.background,
    flexShrink: 0,
  });
  box.add(
    makeText(opentui, ctx, {
      content: ascii.logo,
      fg: theme.accent,
    }),
  );
  box.add(
    makeText(opentui, ctx, {
      content: "Type to chat. /help for commands. Ctrl+K palette. Ctrl+R rail.",
      fg: theme.textMuted,
    }),
  );
  return box;
}
