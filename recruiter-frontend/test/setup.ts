import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom doesn't implement matchMedia; stub for ThemeProvider and similar consumers.
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

// jsdom doesn't implement EventSource either. A minimal stub keeps useSSE happy.
class StubEventSource {
  url: string;
  readyState = 1;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  constructor(url: string) {
    this.url = url;
  }
  addEventListener() {}
  removeEventListener() {}
  close() {
    this.readyState = 2;
  }
  dispatchEvent() {
    return true;
  }
}
// @ts-expect-error -- assigning a stub to the global for jsdom tests.
globalThis.EventSource = StubEventSource;

// jsdom doesn't implement scrollIntoView; stub for ChatPanel auto-scroll and similar.
Element.prototype.scrollIntoView = vi.fn();
