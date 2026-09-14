import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook } from "@testing-library/react";
import { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { handleServerEvent, useSSE } from "./sse";
import { queryKeys } from "./query-keys";

// A minimal EventSource stand-in that actually routes named events the way
// a browser does — only listeners registered for that exact event name (or
// "message", for unnamed events) get called. This is what real usage goes
// through; calling handleServerEvent directly bypasses it entirely and
// can't catch a missing addEventListener registration.
class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, Array<(event: MessageEvent) => void>> = {};
  closed = false;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners[type] = (this.listeners[type] ?? []).filter((l) => l !== listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    for (const listener of this.listeners[type] ?? []) listener(event);
  }
}

describe("handleServerEvent", () => {
  it("invalidates interviewKit query for interview_kit events", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "interview_kit" as const,
      application_id: 42,
      status: "ready" as const,
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.interviewKit(42),
    });
    expect(spy).toHaveBeenCalledTimes(4);
  });

  it("also invalidates interviewers, application, and jobs for interview_kit events", () => {
    // A sheet submit can add/remove an interviewer's row or move the stage,
    // so the interviewers panel, the detail header, and the kanban all need
    // a refetch alongside the kit itself.
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "interview_kit" as const,
      application_id: 42,
      status: "ready" as const,
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.interviewers(42),
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.application(42),
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["jobs"],
      exact: false,
    });
  });

  it("invalidates jobApplications but not the jobs prefix when job_id is set and stage_changed is false", () => {
    // The backend now tells us which job's board is affected and whether
    // the stage actually moved. When it didn't, only that job's application
    // list needs a refetch — invalidating the whole ["jobs"] prefix would
    // refetch every mounted kanban board for nothing.
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "interview_kit" as const,
      application_id: 42,
      job_id: 8,
      status: "ready" as const,
      stage_changed: false,
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.jobApplications(8) });
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ["jobs"], exact: false });
  });

  it("invalidates the jobs prefix when stage_changed is true", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "interview_kit" as const,
      application_id: 42,
      job_id: 8,
      status: "ready" as const,
      stage_changed: true,
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.jobApplications(8) });
    expect(spy).toHaveBeenCalledWith({ queryKey: ["jobs"], exact: false });
  });

  it("invalidates application, jobs, and candidates for stage events", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "stage" as const,
      application_id: 42,
      stage: "interview_scheduled",
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.application(42),
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["jobs"],
      exact: false,
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["candidates"],
      exact: false,
    });
    expect(spy).toHaveBeenCalledTimes(3);
  });

  it("invalidates application, jobs, and candidates for error events", () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    const payload = {
      type: "error" as const,
      application_id: 42,
      phase: "chat",
      error: "something went wrong",
    };
    handleServerEvent(payload, qc);
    expect(spy).toHaveBeenCalledWith({
      queryKey: queryKeys.application(42),
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["jobs"],
      exact: false,
    });
    expect(spy).toHaveBeenCalledWith({
      queryKey: ["candidates"],
      exact: false,
    });
    expect(spy).toHaveBeenCalledTimes(3);
  });
});

describe("useSSE (wire-level)", () => {
  const realEventSource = globalThis.EventSource;

  afterEach(() => {
    globalThis.EventSource = realEventSource;
    MockEventSource.instances = [];
  });

  function mountSSE(qc: QueryClient) {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    return renderHook(() => useSSE(), { wrapper });
  }

  it("routes a named interview_kit SSE event to the invalidation handler", () => {
    // @ts-expect-error - test stub, not a full EventSource implementation
    globalThis.EventSource = MockEventSource;
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    mountSSE(qc);

    const source = MockEventSource.instances[0];
    expect(source).toBeDefined();
    source.emit("interview_kit", {
      type: "interview_kit", application_id: 42, status: "ready",
    });

    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.interviewKit(42) });
  });

  it("routes a named stage SSE event to the invalidation handler", () => {
    // @ts-expect-error - test stub, not a full EventSource implementation
    globalThis.EventSource = MockEventSource;
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, "invalidateQueries");
    mountSSE(qc);

    const source = MockEventSource.instances[0];
    source.emit("stage", {
      type: "stage", application_id: 42, stage: "interview_scheduled",
    });

    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.application(42) });
  });
});
