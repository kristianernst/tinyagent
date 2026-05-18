export type ComposerState = {
  value: string;
  history: string[];
};

export function emptyComposer(): ComposerState {
  return { value: "", history: [] };
}

export function renderComposer(value: string): string {
  return `> ${value}`;
}
