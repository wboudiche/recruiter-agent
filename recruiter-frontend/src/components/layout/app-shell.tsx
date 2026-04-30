import { Link, Outlet } from "react-router-dom";
import { ThemeToggle } from "@/components/theme/theme-toggle";

export function AppShell() {
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b">
        <div className="container flex h-14 items-center justify-between">
          <Link to="/jobs" className="text-lg font-semibold">
            Recruiter Agent
          </Link>
          <nav className="flex items-center gap-4">
            <Link to="/jobs" className="text-sm hover:underline">Jobs</Link>
            <Link to="/settings" className="text-sm hover:underline">Settings</Link>
            <ThemeToggle />
          </nav>
        </div>
      </header>
      <main className="container flex-1 py-6">
        <Outlet />
      </main>
    </div>
  );
}
