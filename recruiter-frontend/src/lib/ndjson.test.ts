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

  it("handles a UTF-8 multi-byte char split across chunks", async () => {
    // "é" encodes as 0xC3 0xA9. Split between the two bytes — only
    // TextDecoder({ stream: true }) handles this correctly.
    const bytes = new TextEncoder().encode('{"x":"é"}\n');
    const split = bytes.findIndex((b) => b === 0xa9);
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(bytes.slice(0, split));
        c.enqueue(bytes.slice(split));
        c.close();
      },
    });
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ x: "é" }]);
  });

  it("warns on malformed trailing line without final newline", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const stream = streamFrom('{"a":1}\nnope-not-json');
    const events: unknown[] = [];
    for await (const ev of parseNdjsonStream(stream)) events.push(ev);
    expect(events).toEqual([{ a: 1 }]);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
