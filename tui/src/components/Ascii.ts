import { ascii } from "../design/ascii";

export function renderAscii(name: keyof typeof ascii): string {
  return ascii[name];
}
