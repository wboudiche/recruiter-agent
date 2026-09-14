import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UserRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCurrentUser } from "@/hooks/use-current-user";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export function UserChip() {
  const qc = useQueryClient();
  const me = useCurrentUser();
  const logout = useMutation({
    mutationFn: () => api("/api/auth/logout", { method: "POST" }),
    onSuccess: () => {
      qc.removeQueries({ queryKey: queryKeys.currentUser() });
      window.location.href = "/";
    },
  });

  if (!me.data) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="shrink-0 text-sm"
          // Below `sm` the email is the widest thing in the header and
          // would push the nav off-screen, so the trigger is icon-only
          // there; the name stays exposed to assistive tech and the
          // menu still shows who is signed in.
          aria-label={me.data.email}
        >
          <UserRound className="h-4 w-4 sm:hidden" aria-hidden />
          <span className="hidden sm:inline">{me.data.email}</span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuItem
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
        >
          {logout.isPending ? "Signing out…" : "Sign out"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
