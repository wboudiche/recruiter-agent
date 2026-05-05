import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { useTheme } from "@/components/theme/theme-provider";
import {
  readRecentApps,
  useCommandPalette,
  type RecentApp,
} from "./command-palette-context";

interface JobItem {
  id: number;
  title: string;
}

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  section: string;
  run: () => void;
}

export function CommandPalette() {
  const { open, setOpen } = useCommandPalette();
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const [query, setQuery] = useState("");

  const jobs = useQuery({
    queryKey: queryKeys.jobs(),
    queryFn: () => api<JobItem[]>("/api/jobs"),
    enabled: open,  // only fetch when palette is open
  });

  const recents: RecentApp[] = open ? readRecentApps() : [];

  const items: PaletteItem[] = [
    ...(jobs.data ?? []).map<PaletteItem>((j) => ({
      id: `job:${j.id}`,
      label: j.title,
      section: "Jobs",
      run: () => { setOpen(false); navigate(`/jobs/${j.id}`); },
    })),
    ...recents.map<PaletteItem>((r) => ({
      id: `recent:${r.id}`,
      label: r.name,
      hint: "Recently viewed application",
      section: "Recent applications",
      run: () => { setOpen(false); navigate(`/applications/${r.id}`); },
    })),
    {
      id: "act:new-job",
      label: "New job",
      section: "Actions",
      run: () => { setOpen(false); navigate("/jobs/new"); },
    },
    {
      id: "act:settings",
      label: "Open settings",
      section: "Settings",
      run: () => { setOpen(false); navigate("/settings"); },
    },
    {
      id: "act:theme-light",
      label: "Switch to light theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("light"); },
    },
    {
      id: "act:theme-dark",
      label: "Switch to dark theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("dark"); },
    },
    {
      id: "act:theme-system",
      label: "Match system theme",
      section: "Theme",
      run: () => { setOpen(false); setTheme("system"); },
    },
  ];

  const filtered = query.trim()
    ? items.filter((i) => i.label.toLowerCase().includes(query.toLowerCase()))
    : items;

  const grouped = filtered.reduce<Record<string, PaletteItem[]>>((acc, item) => {
    (acc[item.section] ??= []).push(item);
    return acc;
  }, {});

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-lg p-0 overflow-hidden">
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <div className="border-b p-2">
          <Input
            autoFocus
            placeholder="Search…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="max-h-[60vh] overflow-y-auto p-2">
          {Object.entries(grouped).map(([section, list]) => (
            <div key={section} className="mb-2">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground px-2 mb-1">
                {section}
              </p>
              {list.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className="w-full text-left px-2 py-1.5 rounded text-sm hover:bg-muted"
                  onClick={item.run}
                >
                  {item.label}
                  {item.hint && (
                    <span className="text-xs text-muted-foreground ml-2">{item.hint}</span>
                  )}
                </button>
              ))}
            </div>
          ))}
          {filtered.length === 0 && (
            <p className="text-sm text-muted-foreground p-2">No matches.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
