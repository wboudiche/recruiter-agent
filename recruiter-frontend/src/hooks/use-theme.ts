import { useCallback, useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "recruiter-theme";

export const LIGHT_QUERY = "(prefers-color-scheme: light)";

/**
 * Reading localStorage THROWS rather than returning null when the browser
 * blocks site data (Safari private mode, "block all cookies"). Both helpers
 * below run on the render path, so an unguarded access takes down the whole
 * app rather than just the toggle.
 */
/**
 * Holds the choice for this session when storage is unavailable. Without it
 * the snapshot would re-read storage, miss the write that never landed, and
 * leave the button offering "switch to light" on an already-light page.
 */
let sessionTheme: Theme | null = null;

function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : sessionTheme;
  } catch {
    return sessionTheme;
  }
}

function writeStoredTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // The choice won't survive a reload, but it stays consistent for this
    // session — better than refusing to switch at all.
    sessionTheme = theme;
  }
}

/**
 * Resolve the active theme. An explicit stored choice always wins; with
 * nothing stored we follow the OS, and dark remains the fallback so the
 * app looks the way it always has when neither signal is present.
 */
export function resolveTheme(): Theme {
  return readStoredTheme() ?? (window.matchMedia(LIGHT_QUERY).matches ? "light" : "dark");
}

/**
 * Paint the theme onto <html>. The class drives every palette token (see
 * theme-palettes.css); `color-scheme` keeps native widgets — scrollbars,
 * date pickers, form controls — in step with it.
 */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.classList.remove("light", "dark");
  root.classList.add(theme);
  root.style.colorScheme = theme;
}

/**
 * Theme lives in localStorage rather than in React state: the header
 * toggle, the login page and the toast portal all read it at once, and a
 * per-component `useState` would let them drift apart. `resolveTheme` is
 * the only snapshot source, so a write to storage is what every consumer
 * re-reads — there is no second copy to keep in sync.
 */
const listeners = new Set<() => void>();

function subscribe(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  // An unset preference tracks the OS live; `resolveTheme` keeps ignoring
  // the query once an explicit choice is stored, so this stays harmless.
  const query = window.matchMedia(LIGHT_QUERY);
  query.addEventListener("change", onStoreChange);
  return () => {
    listeners.delete(onStoreChange);
    query.removeEventListener("change", onStoreChange);
  };
}

/** Record an explicit choice and paint it. */
export function setTheme(theme: Theme): void {
  writeStoredTheme(theme);
  applyTheme(theme);
  listeners.forEach((notify) => notify());
}

export function useTheme(): {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
} {
  const theme = useSyncExternalStore(subscribe, resolveTheme, () => "dark" as Theme);
  const toggleTheme = useCallback(() => {
    setTheme(resolveTheme() === "dark" ? "light" : "dark");
  }, []);
  return { theme, setTheme, toggleTheme };
}
