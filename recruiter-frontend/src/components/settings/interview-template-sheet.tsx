import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { QuestionListEditor, type EditableQuestion } from "@/components/interview/question-list-editor";
import { ApiError } from "@/lib/api";
import {
  useSaveInterviewTemplate,
  type InterviewTemplate,
  type ProbeMode,
} from "@/hooks/use-interview-templates";

interface Props {
  template?: InterviewTemplate | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function InterviewTemplateSheet({ template, open, onOpenChange }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [probeMode, setProbeMode] = useState<ProbeMode>("score_gaps");
  const [includeJobQuestions, setIncludeJobQuestions] = useState(true);
  const [rows, setRows] = useState<EditableQuestion[]>([]);

  // Reset the working copy from the template whenever the sheet opens —
  // matching a new template (no `template`) starts with the backend's own
  // defaults, so opening "New template" always looks the same.
  useEffect(() => {
    if (!open) return;
    setName(template?.name ?? "");
    setDescription(template?.description ?? "");
    setProbeMode(template?.probe_mode ?? "score_gaps");
    setIncludeJobQuestions(template?.include_job_questions ?? true);
    setRows(template?.questions ?? []);
  }, [open, template]);

  const save = useSaveInterviewTemplate();

  function handleSave() {
    save.mutate(
      {
        id: template?.id,
        body: {
          name: name.trim(),
          description: description || null,
          probe_mode: probeMode,
          include_job_questions: includeJobQuestions,
          questions: rows.filter((r) => r.text.trim()),
        },
      },
      {
        onSuccess: () => onOpenChange(false),
        onError: (err) => {
          toast.error(err instanceof ApiError ? err.detail : "Couldn't save template");
        },
      },
    );
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-xl flex flex-col">
        <SheetHeader>
          <SheetTitle>{template ? "Edit template" : "New template"}</SheetTitle>
          <SheetDescription>
            A template decides which questions a round starts from, and
            where its generated questions come from — the candidate's
            scorecard gaps, their career history, or nowhere at all.
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto space-y-4 py-4">
          <div className="space-y-1">
            <Label htmlFor="template-name">Name</Label>
            <Input
              id="template-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="template-description">Description</Label>
            <Textarea
              id="template-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div className="space-y-1">
            <Label htmlFor="template-probe-mode">Generated probes</Label>
            <Select value={probeMode} onValueChange={(v) => setProbeMode(v as ProbeMode)}>
              <SelectTrigger id="template-probe-mode" aria-label="Generated probes">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="score_gaps">From score gaps (technical)</SelectItem>
                <SelectItem value="profile">From the candidate's history (RH)</SelectItem>
                <SelectItem value="none">None — curated questions only</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="template-include-job-questions"
              type="checkbox"
              className="h-4 w-4"
              checked={includeJobQuestions}
              onChange={(e) => setIncludeJobQuestions(e.target.checked)}
            />
            <Label htmlFor="template-include-job-questions" className="font-normal">
              Include the job's own questions
            </Label>
          </div>

          <QuestionListEditor
            rows={rows}
            onChange={setRows}
            canWrite
            labelPrefix="Template question"
            idPrefix="template-question"
            emptyMessage={<>No questions yet. Use <em>Add question</em> to start.</>}
          />
        </div>

        <div className="border-t pt-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={save.isPending}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={save.isPending || !name.trim()}
          >
            {save.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}
