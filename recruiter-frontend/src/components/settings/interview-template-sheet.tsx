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
  KIND_LABEL,
  KIND_SUMMARY,
  interviewKind,
  settingsForKind,
  useSaveInterviewTemplate,
  type InterviewKind,
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
    setEditingSettings(
      interviewKind({
        probe_mode: template?.probe_mode ?? "score_gaps",
        include_job_questions: template?.include_job_questions ?? true,
      }) === "custom",
    );
  }, [open, template]);

  // Derived, never stored: the radio reads back what the two settings say,
  // so the label can never drift from the behaviour. The exception is
  // Custom, which is a request to see the controls — settings that happen
  // to match a preset must not snap the radio back while editing them.
  const derived = interviewKind({
    probe_mode: probeMode, include_job_questions: includeJobQuestions,
  });
  const [editingSettings, setEditingSettings] = useState(false);
  const kind: InterviewKind = editingSettings ? "custom" : derived;

  function chooseKind(next: InterviewKind) {
    setEditingSettings(next === "custom");
    const settings = settingsForKind(next, {
      probe_mode: probeMode, include_job_questions: includeJobQuestions,
    });
    setProbeMode(settings.probe_mode);
    setIncludeJobQuestions(settings.include_job_questions);
  }

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
            A template decides what kind of interview a round runs and which
            questions it starts from.
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
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">What kind of interview is this?</legend>
            <div className="flex flex-wrap gap-2">
              {(["technical", "hr", "custom"] as InterviewKind[]).map((k) => (
                <label
                  key={k}
                  className="flex items-center gap-2 rounded border border-border px-3 py-2 text-sm"
                >
                  <input
                    type="radio"
                    name="template-kind"
                    className="h-4 w-4"
                    checked={kind === k}
                    onChange={() => chooseKind(k)}
                  />
                  {KIND_LABEL[k]}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">{KIND_SUMMARY[kind]}</p>
          </fieldset>

          {/* The two settings the kind stands for. A preset sets both, so
              they are only asked about when the answer is not implied. */}
          {kind === "custom" && (
            <>
              <div className="space-y-1">
                <Label htmlFor="template-probe-mode">Generated probes</Label>
                <Select value={probeMode} onValueChange={(v) => setProbeMode(v as ProbeMode)}>
                  <SelectTrigger id="template-probe-mode" aria-label="Generated probes">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="score_gaps">From the candidate's scorecard gaps</SelectItem>
                    <SelectItem value="profile">From the candidate's career history</SelectItem>
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
            </>
          )}

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
