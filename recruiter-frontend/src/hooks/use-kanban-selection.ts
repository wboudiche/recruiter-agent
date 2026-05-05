import { useCallback, useState } from "react";

export interface SelectionApi {
  selected: Set<number>;
  toggle: (id: number) => void;
  selectMany: (ids: number[]) => void;
  clear: () => void;
}

export function useKanbanSelection(): SelectionApi {
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const toggle = useCallback((id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const selectMany = useCallback((ids: number[]) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) next.add(id);
      return next;
    });
  }, []);

  const clear = useCallback(() => setSelected(new Set()), []);

  return { selected, toggle, selectMany, clear };
}
