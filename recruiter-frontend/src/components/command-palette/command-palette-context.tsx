import { createContext, useContext, useEffect, useMemo, useState } from "react";

interface CommandPaletteApi {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

const Ctx = createContext<CommandPaletteApi | null>(null);

export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const value = useMemo<CommandPaletteApi>(
    () => ({ open, setOpen, toggle: () => setOpen((o) => !o) }),
    [open],
  );

  // Global Cmd+K / Ctrl+K binding (accept either modifier so it works on
  // Mac and on other platforms regardless of navigator.platform reporting).
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCommandPalette(): CommandPaletteApi {
  const v = useContext(Ctx);
  if (!v) throw new Error("useCommandPalette must be inside <CommandPaletteProvider>");
  return v;
}

const RECENT_KEY = "recent.applications";

export interface RecentApp {
  id: number;
  name: string;
  ts: number;
}

export function pushRecentApp(entry: RecentApp): void {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    const list: RecentApp[] = raw ? JSON.parse(raw) : [];
    const next = [entry, ...list.filter((e) => e.id !== entry.id)].slice(0, 10);
    localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    /* ignore localStorage errors (private mode etc.) */
  }
}

export function readRecentApps(): RecentApp[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}
