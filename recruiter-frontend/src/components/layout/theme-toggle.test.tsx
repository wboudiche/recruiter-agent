import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { THEME_STORAGE_KEY } from "@/hooks/use-theme";

import { ThemeToggle } from "./theme-toggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("light", "dark");
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("names the theme it will switch to, not the one in use", () => {
    render(<ThemeToggle />);

    expect(screen.getByRole("button", { name: /switch to light/i })).toBeInTheDocument();
  });

  it("switches the document to light and relabels itself", async () => {
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button", { name: /switch to light/i }));

    expect(document.documentElement.classList.contains("light")).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
    expect(screen.getByRole("button", { name: /switch to dark/i })).toBeInTheDocument();
  });
});
