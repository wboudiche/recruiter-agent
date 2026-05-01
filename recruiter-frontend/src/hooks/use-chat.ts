import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import { parseNdjsonStream } from "@/lib/ndjson";
import { queryKeys } from "@/lib/query-keys";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export type ChatRow = {
  id: number;
  application_id: number;
  role: "user" | "assistant" | "tool";
  content: string | null;
  tool_calls: { id: string; name: string; arguments: Record<string, unknown> }[] | null;
  tool_call_id: string | null;
  tool_name: string | null;
  tool_result: Record<string, unknown> | null;
  created_at: string;
};

type StreamEvent =
  | { type: "message"; role: "user" | "assistant"; id: number; content: string }
  | { type: "tool_call_start"; id: string; name: string; arguments: Record<string, unknown> }
  | { type: "tool_call_result"; id: string; name: string; result: Record<string, unknown> }
  | { type: "message_delta"; text: string }
  | { type: "message_done"; id: number }
  | { type: "error"; detail: string; phase: string };

export function useChat(applicationId: number) {
  const qc = useQueryClient();
  const [isStreaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const history = useQuery({
    queryKey: queryKeys.chat(applicationId),
    queryFn: () => api<ChatRow[]>(`/api/applications/${applicationId}/chat`),
  });

  async function sendMessage(message: string): Promise<void> {
    setError(null);
    setStreaming(true);

    // We mutate the canonical history cache directly as events arrive — one
    // source of truth, no separate `draft` array. On `finally` we
    // invalidate, which refetches from the server and replaces the
    // optimistic rows with their canonical (positive-id) counterparts.
    // Synthetic-id rows for events the server doesn't surface (tool_call_start,
    // message_delta) get replaced by the real assistant/tool rows that
    // appear when the canonical history reloads.
    let nextSyntheticId = -1;
    const key = queryKeys.chat(applicationId);
    function appendOptimistic(row: ChatRow) {
      qc.setQueryData<ChatRow[]>(key, (prev) => [...(prev ?? []), row]);
    }
    const now = () => new Date().toISOString();

    try {
      const response = await fetch(
        `${BASE_URL}/api/applications/${applicationId}/chat`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ message }),
        },
      );
      if (!response.ok || !response.body) {
        throw new ApiError(response.status, await response.text());
      }

      for await (const ev of parseNdjsonStream<StreamEvent>(response.body)) {
        switch (ev.type) {
          case "message":
            appendOptimistic({
              id: ev.id, application_id: applicationId, role: ev.role,
              content: ev.content, tool_calls: null, tool_call_id: null,
              tool_name: null, tool_result: null, created_at: now(),
            });
            break;
          case "tool_call_start":
            appendOptimistic({
              id: nextSyntheticId--, application_id: applicationId, role: "assistant",
              content: null,
              tool_calls: [{ id: ev.id, name: ev.name, arguments: ev.arguments }],
              tool_call_id: null, tool_name: null, tool_result: null, created_at: now(),
            });
            break;
          case "tool_call_result":
            appendOptimistic({
              id: nextSyntheticId--, application_id: applicationId, role: "tool",
              content: null, tool_calls: null,
              tool_call_id: ev.id, tool_name: ev.name, tool_result: ev.result,
              created_at: now(),
            });
            break;
          case "message_delta":
            appendOptimistic({
              id: nextSyntheticId--, application_id: applicationId, role: "assistant",
              content: ev.text, tool_calls: null, tool_call_id: null,
              tool_name: null, tool_result: null, created_at: now(),
            });
            break;
          case "message_done":
            // No-op — invalidation in `finally` swaps the optimistic
            // rows for canonical server-side rows.
            break;
          case "error":
            setError(ev.detail);
            return;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "stream failed");
    } finally {
      setStreaming(false);
      qc.invalidateQueries({ queryKey: key });
    }
  }

  const undo = useMutation({
    mutationFn: (token: string) =>
      api(`/api/applications/${applicationId}/undo`, {
        method: "POST",
        json: { undo_token: token },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.application(applicationId) });
      qc.invalidateQueries({ queryKey: queryKeys.chat(applicationId) });
    },
  });

  const messages: ChatRow[] = history.data ?? [];
  return { messages, sendMessage, isStreaming, error, undo: undo.mutate };
}
