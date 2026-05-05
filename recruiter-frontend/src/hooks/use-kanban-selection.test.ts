import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useKanbanSelection } from "./use-kanban-selection";

describe("useKanbanSelection", () => {
  it("starts empty", () => {
    const { result } = renderHook(() => useKanbanSelection());
    expect(result.current.selected.size).toBe(0);
  });

  it("toggle adds and removes", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(true);
    act(() => result.current.toggle(1));
    expect(result.current.selected.has(1)).toBe(false);
  });

  it("selectMany adds all (idempotent)", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    expect(result.current.selected.size).toBe(3);
    act(() => result.current.selectMany([2, 3, 4]));
    expect(result.current.selected.size).toBe(4);
  });

  it("clear empties", () => {
    const { result } = renderHook(() => useKanbanSelection());
    act(() => result.current.selectMany([1, 2, 3]));
    act(() => result.current.clear());
    expect(result.current.selected.size).toBe(0);
  });
});
