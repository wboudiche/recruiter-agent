import { Button } from "@/components/ui/button";

export type Density = "comfortable" | "compact";

interface Props {
  value: Density;
  onChange: (density: Density) => void;
}

export function KanbanDensityToggle({ value, onChange }: Props) {
  return (
    <div className="inline-flex gap-1">
      <Button
        type="button"
        variant={value === "comfortable" ? "default" : "outline"}
        size="sm"
        aria-pressed={value === "comfortable"}
        onClick={() => onChange("comfortable")}
      >
        Comfortable
      </Button>
      <Button
        type="button"
        variant={value === "compact" ? "default" : "outline"}
        size="sm"
        aria-pressed={value === "compact"}
        onClick={() => onChange("compact")}
      >
        Compact
      </Button>
    </div>
  );
}
