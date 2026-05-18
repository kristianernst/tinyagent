import { spinnerFrame } from "../design/spinners";
import { currentStatusLine } from "../state/selectors";
import type { AppState } from "../state/reducer";

export function renderStatusBar(state: AppState, tick = 0): string {
  const update = state.updatePanel.result?.available ? ` | update ${state.updatePanel.result.latest_version}` : "";
  return `${spinnerFrame(state.ui.spinner, tick)} ${currentStatusLine(state)}${update}`;
}
