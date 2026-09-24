import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { InterviewTemplateSheet } from "./interview-template-sheet";
import { ApiError } from "@/lib/api";
import {
  useInterviewTemplates,
  useSaveInterviewTemplate,
  type InterviewTemplate,
} from "@/hooks/use-interview-templates";

export function InterviewTemplatesTab() {
  const [showArchived, setShowArchived] = useState(false);
  const templates = useInterviewTemplates(showArchived);
  const archive = useSaveInterviewTemplate();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<InterviewTemplate | null>(null);

  function openNew() {
    setEditing(null);
    setSheetOpen(true);
  }

  function openEdit(t: InterviewTemplate) {
    setEditing(t);
    setSheetOpen(true);
  }

  function toggleActive(t: InterviewTemplate) {
    archive.mutate(
      { id: t.id, body: { is_active: !t.is_active } },
      {
        onError: (err) => {
          toast.error(err instanceof ApiError ? err.detail : "Couldn't update template");
        },
      },
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-medium">Interview templates</h3>
          <p className="text-xs text-muted-foreground">
            A template decides which questions a round starts from and
            whether probes are generated from scorecard gaps.
          </p>
        </div>
        <Button type="button" size="sm" onClick={openNew}>
          New template
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <input
          id="show-archived-templates"
          type="checkbox"
          className="h-4 w-4"
          checked={showArchived}
          onChange={(e) => setShowArchived(e.target.checked)}
        />
        <Label htmlFor="show-archived-templates" className="font-normal">
          Show archived
        </Label>
      </div>

      {templates.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading…</p>
      ) : (templates.data ?? []).length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No templates yet. Without one, every round is built from the job's
          own questions, as before.
        </p>
      ) : (
        <ul className="divide-y border rounded-md">
          {(templates.data ?? []).map((t) => (
            <li key={t.id} className="flex items-center justify-between gap-4 p-3">
              <div>
                <div className="font-medium">{t.name}</div>
                <div className="text-xs text-muted-foreground">
                  {t.probe_mode === "none" ? "No generated probes"
                    : t.probe_mode === "profile" ? "Probes from the candidate's history"
                    : "Probes from score gaps"}
                  {t.include_job_questions ? " · includes the job's own questions" : ""}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`Edit ${t.name}`}
                  onClick={() => openEdit(t)}
                >
                  Edit
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  aria-label={`${t.is_active ? "Archive" : "Unarchive"} ${t.name}`}
                  disabled={archive.isPending}
                  onClick={() => toggleActive(t)}
                >
                  {t.is_active ? "Archive" : "Unarchive"}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <InterviewTemplateSheet
        template={editing}
        open={sheetOpen}
        onOpenChange={setSheetOpen}
      />
    </div>
  );
}
