import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { Slot } from "@/hooks/use-notify";

interface Props {
  slots: Slot[];
  onChange: (slots: Slot[]) => void;
}

function nowPlusHours(h: number): string {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + h);
  return d.toISOString().slice(0, 16);
}

function isoFromLocal(s: string): string {
  return new Date(s).toISOString();
}

export function StepSlots({ slots, onChange }: Props) {
  function addSlot() {
    const startLocal = nowPlusHours(24);
    const endLocal = nowPlusHours(25);
    onChange([
      ...slots,
      { start: isoFromLocal(startLocal), end: isoFromLocal(endLocal) },
    ]);
  }

  function updateSlot(
    index: number,
    key: "start" | "end",
    localValue: string,
  ) {
    const next = slots.slice();
    next[index] = { ...next[index]!, [key]: isoFromLocal(localValue) };
    onChange(next);
  }

  function removeSlot(index: number) {
    onChange(slots.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>Proposed time slots (your local timezone)</Label>
        <Button type="button" variant="outline" size="sm" onClick={addSlot}>
          <Plus className="h-4 w-4 mr-1" />
          Add slot
        </Button>
      </div>
      {slots.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Add at least one proposed time slot.
        </p>
      )}
      {slots.map((slot, index) => (
        <div
          key={index}
          className="grid grid-cols-[1fr_1fr_auto] gap-2 items-end"
        >
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">Start</Label>
            <Input
              type="datetime-local"
              value={slot.start.slice(0, 16)}
              onChange={(e) => updateSlot(index, "start", e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label className="text-xs text-muted-foreground">End</Label>
            <Input
              type="datetime-local"
              value={slot.end.slice(0, 16)}
              onChange={(e) => updateSlot(index, "end", e.target.value)}
            />
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => removeSlot(index)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
    </div>
  );
}
