import { Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCommandPalette } from "./command-palette-context";

export function SearchTrigger() {
  const { setOpen } = useCommandPalette();
  return (
    <Button
      variant="ghost"
      size="sm"
      aria-label="Open command palette"
      onClick={() => setOpen(true)}
    >
      <Search className="h-4 w-4" />
    </Button>
  );
}
