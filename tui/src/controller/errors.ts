import type { AppState } from "../state/reducer";
import type { Store } from "../state/store";

export function appendError(store: Store, message: string, extra: Partial<AppState> = {}): void {
  const state = store.get();
  store.set({ ...state, ...extra, errors: [...state.errors, message] });
}

export async function safeClientAction(store: Store, action: () => Promise<unknown>): Promise<boolean> {
  try {
    await action();
    return true;
  } catch (error) {
    appendError(store, error instanceof Error ? error.message : String(error));
    return false;
  }
}
