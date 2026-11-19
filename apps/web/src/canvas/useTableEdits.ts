import { useCallback } from "react";
import { engine } from "../client";
import { slotOf, type TableEditCommand, type TableRecord } from "../engine/layout";
import type { Vec2 } from "../geometry";
import { engineCommand } from "../state/history";
import { useUI } from "../state/store";

/** Tables of a table-level layout that hold any of the given module ids. */
export function tablesOfModules(ids: readonly string[], tables: readonly TableRecord[]): TableRecord[] {
  const wanted = new Set(ids.map((id) => slotOf(id)?.tableId).filter(Boolean) as string[]);
  return tables.filter((t) => wanted.has(t.table_id));
}

/**
 * Table edits (B5): each is one engine command, pins the tables it touches and is
 * one undo step. Commands go per field, as the engine route is per field.
 */
export function useTableEdits() {
  const projectId = useUI((s) => s.view?.bundle.project.project_id ?? null);
  const tables = useUI((s) => s.view?.table_layout?.tables ?? null);

  const perField = useCallback(
    async (label: string, ids: readonly string[], make: (fieldTableIds: string[], fieldId: string) => TableEditCommand) => {
      if (!projectId || !tables) return;
      const byField = new Map<string, string[]>();
      for (const t of tables.filter((x) => ids.includes(x.table_id))) byField.set(t.pv_field_id, [...(byField.get(t.pv_field_id) ?? []), t.table_id]);
      for (const [fieldId, own] of byField) await engineCommand(label, () => engine.editTables(projectId, fieldId, make(own, fieldId)));
    },
    [projectId, tables]
  );

  const moveTables = useCallback(
    (ids: readonly string[], d: Vec2) => perField("Moving tables", ids, (table_ids) => ({ kind: "move_tables", table_ids, dx_m: d[0], dy_m: d[1] })),
    [perField]
  );
  const deleteTables = useCallback((ids: readonly string[]) => perField("Deleting tables", ids, (table_ids) => ({ kind: "delete_tables", table_ids })), [perField]);
  const unpinTables = useCallback((ids: readonly string[]) => perField("Unpinning tables", ids, (table_ids) => ({ kind: "unpin_tables", table_ids })), [perField]);
  const deleteModules = useCallback(
    async (moduleIds: readonly string[]) => {
      if (!projectId || !tables) return;
      const byField = new Map<string, string[]>();
      for (const id of moduleIds) {
        const s = slotOf(id);
        const t = s && tables.find((x) => x.table_id === s.tableId);
        if (t) byField.set(t.pv_field_id, [...(byField.get(t.pv_field_id) ?? []), id]);
      }
      for (const [fieldId, own] of byField)
        await engineCommand("Deleting modules", () => engine.editTables(projectId, fieldId, { kind: "delete_modules", module_instance_ids: own }));
    },
    [projectId, tables]
  );

  return { moveTables, deleteTables, unpinTables, deleteModules };
}
