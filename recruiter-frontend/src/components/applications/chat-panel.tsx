import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ChatRow, useChat } from "@/hooks/use-chat";

interface Props {
  applicationId: number;
}

export function ChatPanel({ applicationId }: Props) {
  const { messages, sendMessage, isStreaming, error, undo } = useChat(applicationId);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Track whether the user is reading at the bottom; if they scrolled up,
  // don't auto-scroll on new messages — that would yank them away from
  // the part of the conversation they're currently reading.
  const pinnedRef = useRef(true);
  useEffect(() => {
    if (!pinnedRef.current) return;
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length, isStreaming]);

  function handleScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    // 40px slack so micro-scroll-jitter doesn't unpin.
    pinnedRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 40;
  }

  async function onSend() {
    const text = input.trim();
    if (!text || isStreaming) return;
    setInput("");
    await sendMessage(text);
  }

  return (
    <div className="flex flex-col h-full bg-card border-l">
      <div className="px-4 py-2 border-b font-medium">Chat</div>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-3 space-y-3"
      >
        {messages.length === 0 && (
          <p className="text-sm text-muted-foreground">Ask anything about this candidate.</p>
        )}
        {messages.map((m) => (
          <MessageRow key={m.id} row={m} onUndo={(t) => undo(t)} />
        ))}
        {isStreaming && (
          <p className="text-xs text-muted-foreground animate-pulse">Thinking…</p>
        )}
        {error && (
          <p className="text-xs text-red-600 border border-red-300 rounded p-2 bg-red-50">
            {error}
          </p>
        )}
        <div ref={bottomRef} />
      </div>
      <div className="p-3 border-t flex gap-2">
        <Textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask anything…"
          disabled={isStreaming}
          rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
        />
        <Button onClick={onSend} disabled={isStreaming || !input.trim()}>
          Send
        </Button>
      </div>
    </div>
  );
}

function MessageRow({ row, onUndo }: { row: ChatRow; onUndo: (token: string) => void }) {
  if (row.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="bg-primary text-primary-foreground rounded-lg px-3 py-2 max-w-[85%] whitespace-pre-wrap">
          {row.content}
        </div>
      </div>
    );
  }
  if (row.role === "assistant" && !row.tool_calls) {
    return (
      <div className="prose prose-sm max-w-none dark:prose-invert">
        <ReactMarkdown>{row.content || ""}</ReactMarkdown>
      </div>
    );
  }
  if (row.role === "assistant" && row.tool_calls) {
    return (
      <div className="space-y-1">
        {row.content && (
          <div className="prose prose-sm max-w-none dark:prose-invert">
            <ReactMarkdown>{row.content}</ReactMarkdown>
          </div>
        )}
        {row.tool_calls.map((tc) => (
          <Card key={tc.id} className="p-2 text-xs text-muted-foreground bg-muted/40">
            <code>{tc.name}({JSON.stringify(tc.arguments)})</code>
          </Card>
        ))}
      </div>
    );
  }
  if (row.role === "tool") {
    return <ToolResultCard row={row} onUndo={onUndo} />;
  }
  return null;
}

function ToolResultCard({ row, onUndo }: { row: ChatRow; onUndo: (token: string) => void }) {
  const [open, setOpen] = useState(false);
  const isAction =
    row.tool_name === "validate_application" || row.tool_name === "reject_application";
  const undoToken =
    isAction && row.tool_result && typeof row.tool_result["undo_token"] === "string"
      ? (row.tool_result["undo_token"] as string)
      : null;

  return (
    <Card className="p-2 text-xs space-y-1 border-l-2 border-l-primary/40">
      <button
        type="button"
        className="text-left w-full font-mono text-muted-foreground hover:text-foreground"
        onClick={() => setOpen((o) => !o)}
      >
        ↳ {row.tool_name} {open ? "▼" : "▶"}
      </button>
      {open && (
        <pre className="overflow-x-auto bg-background rounded p-2">
          {JSON.stringify(row.tool_result, null, 2)}
        </pre>
      )}
      {undoToken && (
        <Button size="sm" variant="outline" onClick={() => onUndo(undoToken)}>
          Undo
        </Button>
      )}
    </Card>
  );
}
