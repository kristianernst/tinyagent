export type Focusable = {
  id: string;
  focus: () => void;
  blur: () => void;
};

export class FocusStack {
  private stack: Focusable[] = [];
  private cycle: Focusable[] = [];
  private current = 0;
  private switching = false;

  push(focusable: Focusable): void {
    if (this.stack.includes(focusable)) return;
    if (this.stack.length) this.peek()?.blur();
    this.stack.push(focusable);
    focusable.focus();
  }

  pop(focusable?: Focusable): void {
    if (focusable && this.peek()?.id !== focusable.id) {
      this.stack = this.stack.filter((item) => item.id !== focusable.id);
      return;
    }
    const removed = this.stack.pop();
    removed?.blur();
    if (this.stack.length) {
      this.peek()?.focus();
    } else {
      this.cycle[this.current]?.focus();
    }
  }

  peek(): Focusable | null {
    return this.stack[this.stack.length - 1] ?? null;
  }

  registerCycle(cycle: Focusable[]): void {
    this.cycle = cycle;
    if (!cycle.length) return;
    this.current = 0;
    cycle[0].focus();
  }

  cycleNext(): void {
    if (!this.cycle.length || this.switching) return;
    this.switching = true;
    try {
      this.cycle[this.current]?.blur();
      this.current = (this.current + 1) % this.cycle.length;
      this.cycle[this.current]?.focus();
    } finally {
      this.switching = false;
    }
  }

  cyclePrevious(): void {
    if (!this.cycle.length || this.switching) return;
    this.switching = true;
    try {
      this.cycle[this.current]?.blur();
      this.current = (this.current - 1 + this.cycle.length) % this.cycle.length;
      this.cycle[this.current]?.focus();
    } finally {
      this.switching = false;
    }
  }

  focusById(id: string): boolean {
    const index = this.cycle.findIndex((item) => item.id === id);
    if (index < 0) return false;
    if (this.current === index) return true;
    if (this.switching) return true;
    this.switching = true;
    try {
      this.cycle[this.current]?.blur();
      this.current = index;
      this.cycle[this.current]?.focus();
    } finally {
      this.switching = false;
    }
    return true;
  }

  currentId(): string | null {
    return this.cycle[this.current]?.id ?? this.peek()?.id ?? null;
  }
}
