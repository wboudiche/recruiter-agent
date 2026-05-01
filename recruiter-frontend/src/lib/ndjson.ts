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
