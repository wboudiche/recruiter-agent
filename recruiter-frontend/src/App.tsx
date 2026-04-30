import { ThemeProvider } from "@/components/theme/theme-provider";
import { ThemeToggle } from "@/components/theme/theme-toggle";

export default function App() {
  return (
    <ThemeProvider>
      <div data-testid="app-root" className="min-h-screen p-4">
        <header className="flex justify-between">
          <h1 className="text-xl font-semibold">Recruiter Agent</h1>
          <ThemeToggle />
        </header>
      </div>
    </ThemeProvider>
  );
}
