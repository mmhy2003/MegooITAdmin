import { vi } from "vitest";

/** An IntersectionObserver the test drives by hand: it keeps its callback, its options and what it observes. */
export class FakeIntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];

  readonly callback: IntersectionObserverCallback;
  readonly options: IntersectionObserverInit | undefined;
  readonly observed = new Set<Element>();

  constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
    this.callback = callback;
    this.options = options;
    FakeIntersectionObserver.instances.push(this);
  }

  observe(element: Element): void {
    this.observed.add(element);
  }

  unobserve(element: Element): void {
    this.observed.delete(element);
  }

  disconnect(): void {
    this.observed.clear();
  }

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

/**
 * Put FakeIntersectionObserver in place of the global one. `show(ids)` reports the observed elements whose
 * data-server-id is in `ids` as intersecting and every other observed element as not.
 */
export function installIntersectionObserver(): { show(ids: string[]): void } {
  FakeIntersectionObserver.instances = [];
  vi.stubGlobal("IntersectionObserver", FakeIntersectionObserver);
  return {
    show(ids: string[]) {
      for (const observer of FakeIntersectionObserver.instances) {
        const entries = [...observer.observed].map(
          (target) =>
            ({ target, isIntersecting: ids.includes(target.getAttribute("data-server-id") ?? "") }) as IntersectionObserverEntry,
        );
        observer.callback(entries, observer as unknown as IntersectionObserver);
      }
    },
  };
}
