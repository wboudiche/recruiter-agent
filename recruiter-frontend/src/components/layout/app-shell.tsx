import { Link, Outlet } from "react-router-dom";
import { UserChip } from "@/components/auth/user-chip";
import { CommandPaletteProvider } from "@/components/command-palette/command-palette-context";
import { CommandPalette } from "@/components/command-palette/command-palette";
import { SearchTrigger } from "@/components/command-palette/search-trigger";

export function AppShell() {
  return (
    <CommandPaletteProvider>
      <div className="geist-theme min-h-screen flex flex-col">
        <header className="sticky top-0 z-40 border-b border-border/60 bg-background/70 backdrop-blur-md">
          <div className="mx-auto flex h-16 max-w-[1800px] items-center justify-between px-6 md:px-10">
            <Link to="/jobs" className="ed-wordmark group">
              <span className="font-serif italic text-[18px] text-foreground">
                Recruiter
              </span>
              <span className="mx-2 text-[hsl(var(--ed-amber))] transition-transform duration-300 group-hover:rotate-180 inline-block">
                ·
              </span>
              <span className="font-sans text-[10px] uppercase tracking-[0.34em] text-muted-foreground">
                Agent
              </span>
            </Link>
            <nav className="flex items-center gap-6">
              <NavLink to="/jobs">Jobs</NavLink>
              <NavLink to="/settings">Settings</NavLink>
              <div className="mx-1 h-4 w-px bg-border" />
              <SearchTrigger />
              <UserChip />
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1800px] flex-1 px-6 py-10 md:px-10">
          <Outlet />
        </main>
        <CommandPalette />
      </div>
    </CommandPaletteProvider>
  );
}

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="relative font-sans text-[11px] font-medium uppercase tracking-[0.28em] text-muted-foreground transition-colors hover:text-foreground after:absolute after:left-0 after:-bottom-1 after:h-px after:w-0 after:bg-[hsl(var(--ed-amber))] after:transition-all hover:after:w-full"
    >
      {children}
    </Link>
  );
}
