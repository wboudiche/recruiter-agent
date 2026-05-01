import { describe, expect, it, vi } from "vitest";
import { parseNdjsonStream } from "./ndjson";

function streamFrom(...chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c));
      controller.close();
    },
  });
}

describe("parseNdjsonStream", () => {
  it("parses one event per line", async () => {
    const stream = streamFrom('{"a":1}\n{"a":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { a: 2 }]);
  });

  it("handles a JSON object split across two chunks", async () => {
    const stream = streamFrom('{"a":', '1}\n{"b":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("yields trailing line without final newline", async () => {
    const stream = streamFrom('{"a":1}\n{"b":2}');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { b: 2 }]);
  });

  it("drops malformed lines with a warning", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const stream = streamFrom('{"ok":1}\nnot-json\n{"ok":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ ok: 1 }, { ok: 2 }]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it("ignores empty lines", async () => {
    const stream = streamFrom('{"a":1}\n\n{"a":2}\n');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }, { a: 2 }]);
  });
});
