import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme } from "@/hooks/use-theme";

/**
 * Header control for the light/dark palette. The label names the theme the
 * click will move you TO — "Switch to light theme" while dark is showing —
 * because a control named after the current state reads as a status readout
 * and leaves people guessing what the button does.
 */
export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const next = theme === "dark" ? "light" : "dark";

  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={toggleTheme}
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  );
}
