import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import { handleServerEvent } from "./sse";
import { queryKeys } from "./query-keys";

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
    expect(spy).toHaveBeenCalledTimes(1);
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
