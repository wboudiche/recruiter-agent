import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
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

describe("api 401 handling", () => {
  let originalLocation: PropertyDescriptor | undefined;

  beforeEach(() => {
    originalLocation = Object.getOwnPropertyDescriptor(window, "location");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    if (originalLocation) {
      Object.defineProperty(window, "location", originalLocation);
    }
  });

  it("redirects to /api/auth/login on 401", async () => {
    const fetchMock = vi.fn(async () =>
      new Response("unauth", { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      value: {
        pathname: "/jobs",
        search: "?x=1",
        get href() {
          return "";
        },
        set href(v: string) {
          hrefSetter(v);
        },
      },
      writable: true,
      configurable: true,
    });

    await expect(api("/api/jobs")).rejects.toThrow();
    expect(hrefSetter).toHaveBeenCalledTimes(1);
    const target = hrefSetter.mock.calls[0][0] as string;
    expect(target).toContain("/api/auth/login");
    expect(target).toContain("next=" + encodeURIComponent("/jobs?x=1"));
  });
});
