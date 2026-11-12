import { z } from "zod";
import {
  AccuracySchema,
  AskRequestSchema,
  ErrorSchema,
  EvalSchema,
  EventSchemas,
  FaultsSchema,
  FeedsSchema,
  FeedXmlSchema,
  FolioSchema,
  HoldBodySchema,
  HoldSchema,
  HotelDetailSchema,
  HotelsSchema,
  MetaSchema,
  TaxesSchema,
  type AskEvent,
} from "./schema";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public retryAfter?: number,
  ) {
    super(message);
  }
}
async function checked(response: Response) {
  if (response.ok) return response;
  const parsed = ErrorSchema.safeParse(await response.json().catch(() => null));
  throw new ApiError(
    parsed.success ? parsed.data.error.message : `Request failed (${response.status}).`,
    response.status,
    parsed.success
      ? (parsed.data.error.retry_after_s ?? parsed.data.retry_after_s)
      : Number(response.headers.get("Retry-After")) || undefined,
  );
}
export async function get<T>(url: string, schema: z.ZodType<T>, signal?: AbortSignal): Promise<T> {
  const response = await checked(await fetch(url, { signal, cache: "no-store" }));
  const parsed = schema.safeParse(await response.json());
  if (!parsed.success)
    throw new Error(`The API response for ${url.split("?")[0]} does not match the published contract.`);
  return parsed.data;
}
export const api = {
  meta: (signal?: AbortSignal) => get("/api/meta", MetaSchema, signal),
  hotels: (query = "", signal?: AbortSignal) => get(`/api/hotels?${query}`, HotelsSchema, signal),
  hotel: (id: string, signal?: AbortSignal) =>
    get(`/api/hotels/${encodeURIComponent(id)}`, HotelDetailSchema, signal),
  quote: (query: string, signal?: AbortSignal) => get(`/api/quote?${query}`, FolioSchema, signal),
  accuracy: (query = "", signal?: AbortSignal) => get(`/api/accuracy?n=30&${query}`, AccuracySchema, signal),
  faults: (signal?: AbortSignal) => get("/api/faults", FaultsSchema, signal),
  feeds: (signal?: AbortSignal) => get("/api/feeds", FeedsSchema, signal),
  feed: async (filename: string) => {
    const response = await checked(await fetch(`/api/feeds/${encodeURIComponent(filename)}`));
    if (!response.headers.get("content-type")?.includes("xml"))
      throw new Error("Expected an XML feed download.");
    return FeedXmlSchema.parse(await response.text());
  },
  taxes: (signal?: AbortSignal) => get("/api/taxes", TaxesSchema, signal),
  eval: (signal?: AbortSignal) => get("/api/eval", EvalSchema, signal),
  hold: async (rate_id: string, hold_token: string) => {
    const response = await checked(
      await fetch("/api/holds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(HoldBodySchema.parse({ rate_id, hold_token, confirm: true })),
      }),
    );
    return HoldSchema.parse(await response.json());
  },
};

/** Streaming UTF-8 decoder; supports CRLF, comments, multiline data and split chunks. */
export async function* parseSSE(stream: ReadableStream<Uint8Array>): AsyncGenerator<AskEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  function parse(frame: string): AskEvent | null {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
    }
    if (!data.length) return null;
    if (!(event in EventSchemas)) throw new Error(`Unknown stream event: ${event}`);
    const schema = EventSchemas[event as keyof typeof EventSchemas];
    return { event, data: schema.parse(JSON.parse(data.join("\n"))) } as AskEvent;
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      let match: RegExpExecArray | null;
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        const frame = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        const parsed = parse(frame);
        if (parsed) yield parsed;
      }
      if (done) {
        if (buffer.trim()) {
          const parsed = parse(buffer);
          if (parsed) yield parsed;
        }
        break;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export async function ask(
  input: z.infer<typeof AskRequestSchema>,
  receive: (event: AskEvent) => void,
  signal?: AbortSignal,
) {
  const response = await checked(
    await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(AskRequestSchema.parse(input)),
      signal,
    }),
  );
  if (!response.body || !response.headers.get("content-type")?.includes("text/event-stream"))
    throw new Error("Expected an event stream from the API.");
  for await (const event of parseSSE(response.body)) receive(event);
}
