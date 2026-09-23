import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { TrackRead } from "@/hooks/use-interview-kit";
import { useInterviewers, useUserDirectory } from "@/hooks/use-interviewers";
import { ApiError } from "@/lib/api";

interface Props {
  applicationId: number;
  canWrite: boolean;
  /** The live round's tracks. With two or more, the panel is shown and
   *  edited per track; otherwise exactly as before tracks. */
  tracks?: TrackRead[];
}

export function InterviewersPicker({ applicationId, canWrite, tracks = [] }: Props) {
  const {
    interviewers, isLoading: interviewersLoading, isError: interviewersError, setInterviewers,
  } = useInterviewers(applicationId);
  // The track whose panel the dialog edits: undefined = closed; null = the
  // whole panel of a one-track round (no ?track= sent).
  const [editing, setEditing] = useState<string | null | undefined>(undefined);
  const open = editing !== undefined;
  const perTrack = tracks.length > 1;
  const labelOf = (track: string | undefined) => {
    const t = tracks.find((x) => x.track === track);
    return t ? (t.template_name ?? "No template") : (track ?? "");
  };
  // One track per person per round: someone on another track is shown but
  // cannot be ticked here.
  const onOtherTrack = (userId: number) =>
    editing ? interviewers.find((i) => i.user_id === userId && i.track !== editing) : undefined;
  const [filter, setFilter] = useState("");
  const [checked, setChecked] = useState<number[]>([]);
  const directory = useUserDirectory(open);

  function openDialog(track: string | null) {
    setChecked(interviewers.filter((i) => track === null || i.track === track).map((i) => i.user_id));
    setFilter("");
    setEditing(track);
  }

  const visible = (directory.data ?? []).filter((u) => {
    const q = filter.trim().toLowerCase();
    return !q || u.email.toLowerCase().includes(q) || (u.name ?? "").toLowerCase().includes(q);
  });

  // An interviewer already on the panel whose account no longer shows up in
  // the directory (deactivated) would otherwise be un-removable: they'd
  // never appear as a row to untick. Surface them from `interviewers`
  // itself, not the directory, so they can still be unassigned. Only do
  // this once the directory has actually loaded — when it errored,
  // `directory.data` is `undefined` and every current assignee would
  // otherwise be misread as "not in the directory" and rendered
  // "(inactive)".
  const directoryIds = new Set((directory.data ?? []).map((u) => u.id));
  const inactiveAssigned = directory.data !== undefined
    ? interviewers.filter((i) => !directoryIds.has(i.user_id) && (!editing || i.track === editing))
    : [];

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs font-mono uppercase tracking-wider text-muted-foreground">
        interviewers:
      </span>
      {!interviewersLoading && interviewersError && (
        <span className="text-sm text-muted-foreground">Couldn't load interviewers</span>
      )}
      {!interviewersLoading && !interviewersError && interviewers.length === 0 && (
        <span className="text-sm text-muted-foreground">none</span>
      )}
      {!perTrack && interviewers.map((i) => (
        <span
          key={i.user_id}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs"
        >
          {i.name ?? i.email}
          {i.submitted_at && <span aria-label="submitted" className="text-success">✓</span>}
        </span>
      ))}
      {!perTrack && canWrite && (
        <Button
          variant="outline"
          size="sm"
          className="h-auto px-2 py-1 text-xs"
          onClick={() => openDialog(null)}
          disabled={interviewersLoading || interviewersError}
        >
          Assign
        </Button>
      )}
      {perTrack && tracks.map((t) => (
        <div key={t.track} className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">{labelOf(t.track)}:</span>
          {interviewers.filter((i) => i.track === t.track).map((i) => (
            <span key={i.user_id}
              className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-xs">
              {i.name ?? i.email}
              {i.submitted_at && <span aria-label="submitted" className="text-success">✓</span>}
            </span>
          ))}
          {canWrite && (
            <Button variant="outline" size="sm" className="h-auto px-2 py-1 text-xs"
              aria-label={`Assign interviewers to ${labelOf(t.track)}`}
              onClick={() => openDialog(t.track)}
              disabled={interviewersLoading || interviewersError}>
              Assign
            </Button>
          )}
        </div>
      ))}
      <Dialog open={open} onOpenChange={(o) => { if (!o) setEditing(undefined); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {editing ? `Assign interviewers — ${labelOf(editing)}` : "Assign interviewers"}
            </DialogTitle>
          </DialogHeader>
          <Input
            placeholder="Search by name or email"
            aria-label="Search users"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          {directory.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading users…</p>
          ) : directory.isError ? (
            <p className="text-sm text-muted-foreground">Couldn't load users</p>
          ) : visible.length === 0 && inactiveAssigned.length === 0 ? (
            <p className="text-sm text-muted-foreground">No users match.</p>
          ) : (
            <ul className="max-h-72 space-y-1 overflow-y-auto">
              {visible.map((u) => {
                const label = u.name ? `${u.name} (${u.email})` : u.email;
                const other = onOtherTrack(u.id);
                return (
                  <li key={u.id}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        aria-label={label}
                        checked={checked.includes(u.id)}
                        disabled={!!other}
                        onChange={(e) =>
                          setChecked((ids) =>
                            e.target.checked ? [...ids, u.id] : ids.filter((x) => x !== u.id))}
                      />
                      {label}
                      {other && (
                        <span className="text-muted-foreground"> (on {labelOf(other.track)})</span>
                      )}
                    </label>
                  </li>
                );
              })}
              {inactiveAssigned.map((i) => {
                const label = i.name ?? i.email;
                const other = onOtherTrack(i.user_id);
                return (
                  <li key={`inactive-${i.user_id}`}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        aria-label={label}
                        checked={checked.includes(i.user_id)}
                        disabled={!!other}
                        onChange={(e) =>
                          setChecked((ids) =>
                            e.target.checked ? [...ids, i.user_id] : ids.filter((x) => x !== i.user_id))}
                      />
                      {label} <span className="text-muted-foreground">(inactive)</span>
                      {other && (
                        <span className="text-muted-foreground"> (on {labelOf(other.track)})</span>
                      )}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(undefined)}>Cancel</Button>
            <Button
              disabled={setInterviewers.isPending || directory.isError}
              onClick={() =>
                setInterviewers.mutate(editing ? { userIds: checked, track: editing } : checked, {
                  onSuccess: () => setEditing(undefined),
                  onError: (err) =>
                    toast.error(err instanceof ApiError ? err.detail : "Couldn't save interviewers"),
                })}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
