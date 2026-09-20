import { act, render, renderHook, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY, applyTheme, resolveTheme, useTheme } from "./use-theme";

/**
 * The global setup stubs matchMedia with a permanently `matches: false`
 * object. These tests need to drive the query both ways, so each one
 * installs its own stub over the top.
 */
function stubPrefersLight(prefersLight: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query.includes("light") ? prefersLight : !prefersLight,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

/**
 * A matchMedia stub whose result can be flipped after the fact, so a test
 * can simulate the user changing their OS appearance while the app runs.
 */
function stubLiveMediaQuery(initialPrefersLight: boolean) {
  const handlers = new Set<(event: MediaQueryListEvent) => void>();
  let prefersLight = initialPrefersLight;
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    get matches() {
      return query.includes("light") ? prefersLight : !prefersLight;
    },
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: (_: string, handler: (event: MediaQueryListEvent) => void) =>
      handlers.add(handler),
    removeEventListener: (_: string, handler: (event: MediaQueryListEvent) => void) =>
      handlers.delete(handler),
    dispatchEvent: vi.fn(),
  }));
  return {
    flipTo(next: boolean) {
      prefersLight = next;
      handlers.forEach((handler) => handler({ matches: next } as MediaQueryListEvent));
    },
  };
}

describe("resolveTheme", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns the stored choice, ignoring the system preference", () => {
    stubPrefersLight(true);
    window.localStorage.setItem(THEME_STORAGE_KEY, "dark");

    expect(resolveTheme()).toBe("dark");
  });

  it("falls back to the system preference when nothing is stored", () => {
    stubPrefersLight(true);

    expect(resolveTheme()).toBe("light");
  });
});

describe("applyTheme", () => {
  afterEach(() => {
    document.documentElement.classList.remove("light", "dark");
    document.documentElement.style.removeProperty("color-scheme");
  });

  it("swaps the theme class on the document element", () => {
    document.documentElement.classList.add("dark");

    applyTheme("light");

    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

describe("useTheme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("light", "dark");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("toggling flips the theme, paints it, and remembers the choice", () => {
    stubPrefersLight(false);
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");

    act(() => result.current.toggleTheme());

    expect(result.current.theme).toBe("light");
    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("keeps every consumer in step when one of them toggles", async () => {
    stubPrefersLight(false);
    function Readout({ label }: { label: string }) {
      const { theme } = useTheme();
      return <span>{`${label}:${theme}`}</span>;
    }
    function Toggle() {
      const { toggleTheme } = useTheme();
      return <button onClick={toggleTheme}>flip</button>;
    }
    render(
      <>
        <Readout label="a" />
        <Readout label="b" />
        <Toggle />
      </>,
    );

    await userEvent.click(screen.getByRole("button", { name: "flip" }));

    expect(screen.getByText("a:light")).toBeInTheDocument();
    expect(screen.getByText("b:light")).toBeInTheDocument();
  });
});

describe("useTheme and the OS preference", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("light", "dark");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("follows the OS when the user has never picked a theme", () => {
    const media = stubLiveMediaQuery(false);
    const { result } = renderHook(() => useTheme());
    expect(result.current.theme).toBe("dark");

    act(() => media.flipTo(true));

    expect(result.current.theme).toBe("light");
  });

  it("ignores the OS once the user has picked a theme", () => {
    const media = stubLiveMediaQuery(false);
    const { result } = renderHook(() => useTheme());
    act(() => result.current.setTheme("dark"));

    act(() => media.flipTo(true));

    expect(result.current.theme).toBe("dark");
  });
});

describe("when the browser denies storage access", () => {
  /**
   * Safari's private mode and "block all cookies" make localStorage throw on
   * access rather than return null. `resolveTheme` runs inside
   * `getSnapshot`, so an unguarded throw takes down the whole render — not
   * just the toggle.
   */
  const realStorage = Object.getOwnPropertyDescriptor(window, "localStorage")!;

  beforeEach(() => {
    stubPrefersLight(false);
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("The operation is insecure.", "SecurityError");
      },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "localStorage", realStorage);
    vi.restoreAllMocks();
  });

  it("falls back to dark instead of throwing", () => {
    expect(() => resolveTheme()).not.toThrow();
    expect(resolveTheme()).toBe("dark");
  });

  it("still paints a toggle even though the choice cannot be saved", () => {
    const { result } = renderHook(() => useTheme());

    act(() => result.current.toggleTheme());

    expect(document.documentElement.classList.contains("light")).toBe(true);
  });

  it("reports the switched theme, so the control does not contradict the page", () => {
    const { result } = renderHook(() => useTheme());
    const before = result.current.theme;

    act(() => result.current.toggleTheme());

    // Without an in-memory fallback the snapshot re-reads storage, misses the
    // write that never landed, and the button goes on offering "switch to
    // light" while the page is already light. Asserted as a flip rather than
    // a fixed value: the fallback deliberately outlives a single hook.
    expect(result.current.theme).toBe(before === "dark" ? "light" : "dark");
    expect(document.documentElement.classList.contains(result.current.theme)).toBe(true);
  });
});
