import type { FailureExplanation } from "../../state/reducer";
import type { Theme } from "../theme";
import { makeBox } from "../layout";
import { InfoPanelWidget } from "./InfoPanelWidget";
import { makePanelList } from "./panelStyle";

export class FailureWidget {
  readonly node: any;
  private summary: InfoPanelWidget;
  private select: any;

  constructor(private opentui: any, private ctx: any, private theme: Theme) {
    this.node = makeBox(opentui, ctx, { flexDirection: "column", flexGrow: 1 });
    this.summary = new InfoPanelWidget(opentui, ctx, theme, { compact: true });
    this.select = makePanelList(opentui, ctx, theme, {
      showDescription: true,
      minHeight: 4,
      height: 9,
      flexShrink: 0,
      marginTop: 1,
      maxRows: 5,
      maxTextWidth: 52,
    });
    this.node.add?.(this.summary.node);
    this.node.add?.(this.select);
  }

  update(failure: FailureExplanation | null): void {
    if (!failure) {
      this.summary.update({
        eyebrow: "failure review",
        rows: [
          {
          label: "status",
          value: "clear",
          detail: "no failed step in this run",
          tone: "success",
        },
      ],
      footer: "actions appear after a failed run",
      });
      if (this.select && "options" in this.select) this.select.options = [];
      return;
    }
    this.summary.update({
      eyebrow: "failure review",
      rows: [
        {
          label: "source",
          value: failure.source,
          detail: "stopped turn",
          tone: "danger",
        },
        {
          label: "last ok",
          value: stepValue(failure.lastSuccessfulEvent),
          detail: `${eventKind(failure.lastSuccessfulEvent)} · safe checkpoint`,
        },
        {
          label: "failed",
          value: stepValue(failure.failedEvent),
          detail: `${eventKind(failure.failedEvent)} · replay target`,
          tone: "warning",
        },
      ],
      footer: "recovery actions",
    });
    if (this.select && "options" in this.select) {
      this.select.options = failure.recoveryActions.map((action, index) => ({
        ...recoveryOption(action),
        value: String(index),
      }));
    }
  }
}

function recoveryOption(action: string): { name: string; rightMeta?: string; description: string } {
  const rewind = action.match(/\/rewind\s+(\d+)/);
  if (action.includes("/replay")) {
    return {
      name: "inspect failure",
      rightMeta: "/replay",
      description: "open replay",
    };
  }
  if (rewind) {
    return {
      name: "rewind before failure",
      rightMeta: `/rewind ${rewind[1]}`,
      description: `step ${rewind[1]}`,
    };
  }
  if (/retry/i.test(action)) {
    return {
      name: "retry compact prompt",
      rightMeta: "retry",
      description: "smaller bundle",
    };
  }
  return {
    name: action,
    description: "press Enter to copy hint",
  };
}

function stepValue(value: string): string {
  const seq = value.trim().match(/^(\d+)/)?.[1];
  return seq ? `step ${seq}` : value;
}

function eventKind(value: string): string {
  const type = value.trim().replace(/^\d+\s+/, "");
  if (type === "tool.execution.completed") return "tool completed";
  if (type === "model.call.failed") return "model failed";
  if (type === "model.call.started") return "model started";
  return type.replace(/\./g, " ");
}
