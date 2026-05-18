import type { RunEvent } from "../protocol/events";
import { emptyState, reduceEvent, type AppState } from "./reducer";

export type Listener = (state: AppState) => void;

export class Store {
  private state: AppState;
  private listeners = new Set<Listener>();

  constructor(initial: AppState = emptyState()) {
    this.state = initial;
  }

  get(): AppState {
    return this.state;
  }

  set(next: AppState): void {
    this.state = next;
    for (const listener of this.listeners) listener(next);
  }

  event(event: RunEvent): void {
    this.set(reduceEvent(this.state, event));
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
