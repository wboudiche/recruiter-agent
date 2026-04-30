import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { api, ApiError } from "./api";

const server = setupServer();

describe("api", () => {
  beforeEach(() => server.listen({ onUnhandledRequest: "error" }));
  afterEach(() => {
    server.resetHandlers();
    server.close();
  });

  it("returns parsed JSON on 200", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs", () =>
        HttpResponse.json([{ id: 1, title: "Backend" }]),
      ),
    );
    const data = await api<unknown>("/api/jobs");
    expect(data).toEqual([{ id: 1, title: "Backend" }]);
  });

  it("throws ApiError on 4xx with detail", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs/9999", () =>
        HttpResponse.json({ detail: "job not found" }, { status: 404 }),
      ),
    );
    await expect(api("/api/jobs/9999")).rejects.toMatchObject({
      status: 404,
      detail: "job not found",
    });
  });

  it("ApiError instanceof check works", async () => {
    server.use(
      http.get("http://localhost:8000/api/jobs/9999", () =>
        HttpResponse.json({ detail: "nope" }, { status: 404 }),
      ),
    );
    try {
      await api("/api/jobs/9999");
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
    }
  });
});
