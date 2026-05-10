import { Briefcase, Settings as SettingsIcon, Sparkles } from "lucide-react";
import { Link, Outlet } from "react-router-dom";
import { ThemeToggle } from "@/components/theme/theme-toggle";
import { UserChip } from "@/components/auth/user-chip";
import { CommandPaletteProvider } from "@/components/command-palette/command-palette-context";
import { CommandPalette } from "@/components/command-palette/command-palette";
import { SearchTrigger } from "@/components/command-palette/search-trigger";

export function AppShell() {
  return (
    <CommandPaletteProvider>
      <div className="geist-theme min-h-screen flex flex-col">
        <header className="border-b border-border/60 backdrop-blur-sm sticky top-0 z-40 bg-background/80">
          <div className="container flex h-14 items-center justify-between">
            <Link
              to="/jobs"
              className="flex items-center gap-2 text-lg font-semibold"
            >
              <span className="grid h-7 w-7 place-items-center rounded-md bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white">
                <Sparkles className="h-4 w-4" />
              </span>
              Recruiter Agent
            </Link>
            <nav className="flex items-center gap-1">
              <NavLink to="/jobs" icon={<Briefcase className="h-4 w-4" />}>
                Jobs
              </NavLink>
              <NavLink to="/settings" icon={<SettingsIcon className="h-4 w-4" />}>
                Settings
              </NavLink>
              <div className="mx-2 h-5 w-px bg-border" />
              <SearchTrigger />
              <UserChip />
              <ThemeToggle />
            </nav>
          </div>
        </header>
        <main className="container flex-1 py-6">
          <Outlet />
        </main>
        <CommandPalette />
      </div>
    </CommandPaletteProvider>
  );
}

function NavLink({
  to,
  icon,
  children,
}: {
  to: string;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground transition-colors"
    >
      {icon}
      {children}
    </Link>
  );
}
