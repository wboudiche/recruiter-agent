import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Lock, Unlock } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { api, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { JobRead } from "@/hooks/use-jobs";
import { EditJobDetailsSheet } from "./edit-job-details-sheet";

interface Props {
  job: JobRead;
}

/**
 * Manage menu on the job-detail header. Lives next to the Criteria
 * button. Two actions today: Edit title/description, Close/Reopen.
 *
 * Both go through the same PATCH /api/jobs/{id} endpoint the
 * criteria sheet already uses; we just invalidate the job + jobs
 * queries on success so the kanban header reflects the new state.
 */
export function JobActionsMenu({ job }: Props) {
  const qc = useQueryClient();
  const [editOpen, setEditOpen] = useState(false);

  const toggleStatus = useMutation({
    mutationFn: () =>
      api<JobRead>(`/api/jobs/${job.id}`, {
        method: "PATCH",
        json: { status: job.status === "open" ? "closed" : "open" },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.job(job.id) });
      qc.invalidateQueries({ queryKey: queryKeys.jobs() });
      toast.success(job.status === "open" ? "Job closed" : "Job reopened");
    },
    onError: (err) => {
      toast.error(err instanceof ApiError ? err.detail : "Couldn't update job");
    },
  });

  const isOpen = job.status === "open";

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            aria-label="Manage job"
            className="px-2"
          >
            <MoreHorizontal className="h-4 w-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-[180px]">
          <DropdownMenuItem onSelect={() => setEditOpen(true)}>
            <Pencil className="h-4 w-4 mr-2" />
            Edit details
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => toggleStatus.mutate()}
            disabled={toggleStatus.isPending}
          >
            {isOpen ? (
              <>
                <Lock className="h-4 w-4 mr-2" />
                Close job
              </>
            ) : (
              <>
                <Unlock className="h-4 w-4 mr-2" />
                Reopen job
              </>
            )}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <EditJobDetailsSheet
        job={job}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
    </>
  );
}
