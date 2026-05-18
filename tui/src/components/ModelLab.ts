export function renderModelLab(provider: string, model = ""): string {
  return [`Provider: ${provider}`, `Model: ${model || "default"}`].join("\n");
}
