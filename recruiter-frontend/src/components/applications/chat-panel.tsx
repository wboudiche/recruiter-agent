import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ChatRow, useChat } from "@/hooks/use-chat";
import { SearchResultCard, type SearchResult } from "./search-result-card";

interface Props {
  applicationId: number;
  jobId: number;
  /** False for viewers. Chat itself stays fully usable for a viewer (the
   *  server allowlists it) — this only withholds the two write-y bits
   *  that ride inside tool-result rows: reversing a validate/reject via
   *  Undo, and adding a search result as a candidate. Everything else in
   *  the transcript (including what those tools reported) stays visible. */
  canWrite?: boolean;
}

export function ChatPanel({ applicationId, jobId, canWrite = false }: Props) {
  const { messages, sendMessage, isStreaming, error, undo, searchResults } = useChat(applicationId);
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
          <MessageRow
            key={m.id}
            row={m}
            onUndo={(t) => undo(t)}
            searchResults={searchResults}
            jobId={jobId}
            canWrite={canWrite}
          />
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

/** Assistant replies are LLM markdown, and the agent leans on the full GFM
 *  vocabulary — pipe tables for score breakdowns, bullets for strengths and
 *  gaps, inline code for tool and command names.
 *
 *  Two things have to be supplied here. react-markdown parses CommonMark
 *  only, which has no table syntax, so remark-gfm is what turns a pipe block
 *  into a real <table> instead of a paragraph of literal `| a | b |` text.
 *  And every element needs explicit classes: Tailwind preflight strips
 *  bullets, heading sizes and quote indents, and the `prose` classes that
 *  used to sit on the callers generated nothing — @tailwindcss/typography
 *  isn't installed, and its `dark:prose-invert` could never have matched
 *  anyway, since the theme is dark through :root variables rather than a
 *  .dark class. Styling against the app's own tokens keeps chat replies in
 *  the editorial palette instead of importing a second type system. */
function Markdown({ children }: { children: string }) {
  return (
    <div className="text-sm leading-relaxed">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: (props) => <p className="[&:not(:first-child)]:mt-2" {...props} />,
          /* `!` throughout: geist-theme styles `.geist-theme h1/h2/h3` as the
             page-title display face (italic Fraunces, up to 3.25rem), and that
             selector outranks a bare utility class. Unqualified, an agent's
             `## ` sub-heading rendered at the same scale as the candidate's
             name in a 340px-wide column. */
          h1: (props) => (
            <h1
              className="mt-3 mb-1 !font-sans !text-sm !font-semibold !not-italic !tracking-normal first:mt-0"
              {...props}
            />
          ),
          h2: (props) => (
            <h2
              className="mt-3 mb-1 !font-sans !text-sm !font-semibold !not-italic !tracking-normal first:mt-0"
              {...props}
            />
          ),
          h3: (props) => (
            <h3
              className="mt-3 mb-1 !font-sans !text-xs !font-semibold !not-italic !uppercase !tracking-wide !text-muted-foreground first:mt-0"
              {...props}
            />
          ),
          ul: (props) => (
            <ul
              className="my-2 list-disc space-y-1 pl-5 marker:text-muted-foreground"
              {...props}
            />
          ),
          ol: (props) => (
            <ol
              className="my-2 list-decimal space-y-1 pl-5 marker:text-muted-foreground"
              {...props}
            />
          ),
          a: (props) => (
            <a
              className="underline underline-offset-2 decoration-border hover:decoration-foreground"
              {...props}
            />
          ),
          blockquote: (props) => (
            <blockquote
              className="my-2 border-l-2 border-border pl-3 italic text-muted-foreground"
              {...props}
            />
          ),
          hr: (props) => <hr className="my-3 border-border" {...props} />,
          /* Inline code only — the `pre` override neutralises these classes
             for fenced blocks, which react-markdown nests as <pre><code>. */
          code: (props) => (
            <code
              className="rounded bg-muted/60 px-1 py-0.5 font-mono text-[0.85em]"
              {...props}
            />
          ),
          pre: (props) => (
            <pre
              className="my-2 overflow-x-auto rounded border border-border bg-muted/40 p-2 text-xs [&_code]:bg-transparent [&_code]:p-0"
              {...props}
            />
          ),
          table: (props) => (
            <div className="my-2 overflow-x-auto">
              <table className="w-full border-collapse text-xs" {...props} />
            </div>
          ),
          th: (props) => (
            <th
              className="border border-border bg-muted/40 px-2 py-1 text-left font-medium"
              {...props}
            />
          ),
          td: (props) => (
            <td className="border border-border px-2 py-1 align-top" {...props} />
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

function MessageRow({
  row, onUndo, searchResults, jobId, canWrite,
}: {
  row: ChatRow;
  onUndo: (token: string) => void;
  searchResults: Record<string, SearchResult[]>;
  jobId: number;
  canWrite: boolean;
}) {
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
      <Markdown>{row.content || ""}</Markdown>
    );
  }
  if (row.role === "assistant" && row.tool_calls) {
    return (
      <div className="space-y-1">
        {row.content && (
          <Markdown>{row.content}</Markdown>
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
    const cards = row.tool_call_id ? searchResults[row.tool_call_id] : undefined;
    return (
      <div className="space-y-2">
        <ToolResultCard row={row} onUndo={onUndo} canWrite={canWrite} />
        {cards && cards.length > 0 && (
          <div className="space-y-2 pl-4 border-l border-l-primary/30">
            {cards.map((c) => (
              <SearchResultCard key={c.url} result={c} jobId={jobId} canWrite={canWrite} />
            ))}
          </div>
        )}
      </div>
    );
  }
  return null;
}

function ToolResultCard({
  row, onUndo, canWrite,
}: {
  row: ChatRow;
  onUndo: (token: string) => void;
  canWrite: boolean;
}) {
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
      {undoToken && canWrite && (
        <Button size="sm" variant="outline" onClick={() => onUndo(undoToken)}>
          Undo
        </Button>
      )}
    </Card>
  );
}
