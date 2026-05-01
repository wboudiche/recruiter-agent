/**
 * Async generator that parses a `ReadableStream<Uint8Array>` of NDJSON
 * (one JSON object per line, `\n`-terminated) into typed events.
 *
 * Behavior:
 * - Handles JSON objects split across chunk boundaries (UTF-8 safe via
 *   `TextDecoder({ stream: true })`).
 * - Yields a final trailing line even when the stream ends without `\n`.
 * - Empty lines are skipped.
 * - Malformed JSON lines are SILENTLY DROPPED with `console.warn`. The
 *   consumer never sees an exception from this iterator. If you need
 *   error visibility upstream, parse line-by-line yourself.
 */
export async function* parseNdjsonStream<T = unknown>(
  stream: ReadableStream<Uint8Array>,
): AsyncIterable<T> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (value) buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      try {
        yield JSON.parse(line) as T;
      } catch (err) {
        console.warn("ndjson: dropping malformed line", { line, err });
      }
    }
    if (done) {
      const tail = buf.trim();
      if (tail) {
        try {
          yield JSON.parse(tail) as T;
        } catch (err) {
          console.warn("ndjson: dropping malformed trailing line", { tail, err });
        }
      }
      return;
    }
  }
}
