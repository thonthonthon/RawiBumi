import { useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  createColumnHelper,
  createSortedRowModel,
  rowSortingFeature,
  sortFns,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { worstCheck, type LiveCheck } from "../engine/topology";
import { useActions, useUI } from "../state/store";
import { CheckGlyph, checksByString } from "./checks";

/** One row of the string table: engine topology plus the engine's live checks. */
export interface StringRow {
  id: string;
  inverter: string;
  mppt: number | null;
  modules: number;
  vmp: number | null;
  window: string;
  worst: LiveCheck["state"] | null;
  checks: LiveCheck[];
  fields: string;
  moduleIds: string[];
}

const RANK: Record<LiveCheck["state"], number> = {
  fail: 0,
  warn: 1,
  unavailable: 2,
  pass: 3,
};
const ROW_H = 28;

const features = tableFeatures({
  rowSortingFeature,
  sortedRowModel: createSortedRowModel(),
  sortFns: { alphanumeric: sortFns.alphanumeric, basic: sortFns.basic },
});
const col = createColumnHelper<typeof features, StringRow>();

/**
 * Bottom panel of the electrical step (B6): every string, sortable, virtualised for
 * thousands of rows. A row click selects the string's modules on the plan.
 */
export function StringTable() {
  const { t } = useTranslation();
  const { dispatch } = useActions();
  const view = useUI((s) => s.view);
  const selection = useUI((s) => s.selection);
  const scrollRef = useRef<HTMLDivElement>(null);

  const data = useMemo((): StringRow[] => {
    if (!view) return [];
    const checks = checksByString(view.topology_checks);
    const mppt = new Map<string, { inverter: string; index: number }>();
    for (const inv of view.bundle.electrical_design.inverter_instances)
      inv.mppt_instance_ids.forEach((m, i) =>
        mppt.set(m, { inverter: inv.name, index: i }),
      );
    const fieldOf = new Map(
      view.bundle.scene.module_instances.map((m) => [
        m.module_instance_id,
        m.pv_field_id,
      ]),
    );
    for (const tb of view.table_layout?.tables ?? [])
      for (let r = 0; r < tb.rows; r++)
        for (let c = 0; c < tb.columns; c++)
          fieldOf.set(`${tb.table_id}/${r}.${c}`, tb.pv_field_id);
    const fieldName = new Map(
      view.bundle.scene.pv_fields.map((f) => [f.pv_field_id, f.name]),
    );
    return view.bundle.electrical_design.strings.map((s) => {
      const at = s.target_mppt_instance_id
        ? mppt.get(s.target_mppt_instance_id)
        : undefined;
      const c = checks.get(s.string_id);
      const fields = [
        ...new Set(
          s.module_instance_ids
            .map((m) => fieldOf.get(m))
            .filter(Boolean) as string[],
        ),
      ].map((f) => fieldName.get(f) ?? f);
      return {
        id: s.string_id,
        inverter: at?.inverter ?? "",
        mppt: at ? at.index + 1 : null,
        modules: s.module_instance_ids.length,
        vmp: c?.vmp_v ?? null,
        window: c?.window_v ? `${c.window_v[0]}–${c.window_v[1]}` : "",
        worst: c ? worstCheck(c.checks) : null,
        checks: c?.checks ?? [],
        fields: fields.join(", "),
        moduleIds: s.module_instance_ids,
      };
    });
  }, [view]);

  const columns = useMemo(
    () =>
      col.columns([
        col.accessor("id", {
          header: t("stringTable.string"),
          sortFn: "alphanumeric",
          cell: (c) => <button type="button" className="linkbtn" aria-label={t("hardening.selectString", { id: c.getValue() })}
            onClick={(e) => { e.stopPropagation(); dispatch({ type: "select", ids: c.row.original.moduleIds }); }}>{c.getValue()}</button>,
        }),
        col.accessor("inverter", {
          header: t("stringTable.inverter"),
          cell: (c) =>
            c.getValue() || (
              <span className="sub">{t("electrical.unassigned")}</span>
            ),
        }),
        col.accessor("mppt", {
          header: "MPPT",
          sortFn: "basic",
          cell: (c) => c.getValue() ?? "—",
        }),
        col.accessor("modules", {
          header: t("stringTable.modules"),
          sortFn: "basic",
        }),
        col.accessor("vmp", {
          header: t("stringTable.vmp"),
          sortFn: "basic",
          cell: (c) => (c.getValue() === null ? "—" : c.getValue()!.toFixed(0)),
        }),
        col.accessor("window", { header: t("stringTable.window") }),
        col.accessor((r) => (r.worst ? RANK[r.worst] : 9), {
          id: "check",
          header: t("stringTable.check"),
          sortFn: "basic",
          cell: (c) => <CheckGlyph checks={c.row.original.checks} />,
        }),
        col.accessor("fields", { header: t("stringTable.fields") }),
      ]),
    [t, dispatch],
  );

  // Every column sorts ascending on its first click (numbers default to descending otherwise).
  const table = useTable({ features, columns, data, getRowId: (r) => r.id, sortDescFirst: false });
  const rows = table.getRowModel().rows;
  const virtual = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_H,
    overscan: 12,
  });
  const items = virtual.getVirtualItems();
  const padTop = items.length ? items[0].start : 0;
  const padBottom = items.length
    ? virtual.getTotalSize() - items[items.length - 1].end
    : 0;
  const sel = useMemo(() => new Set(selection), [selection]);

  return (
    <div
      className="stringtable"
      ref={scrollRef}
      role="region"
      aria-label={t("stringTable.title")}
      tabIndex={0}
    >
      <table className="tbl tbl--sticky" aria-rowcount={rows.length + 1}>
        <thead>
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => {
                const sorted = h.column.getIsSorted();
                return (
                  <th
                    key={h.id}
                    aria-sort={
                      sorted === "asc"
                        ? "ascending"
                        : sorted === "desc"
                          ? "descending"
                          : "none"
                    }
                    className={
                      ["modules", "vmp", "mppt"].includes(h.column.id)
                        ? "num"
                        : undefined
                    }
                  >
                    <button
                      type="button"
                      className="th-sort"
                      onClick={h.column.getToggleSortingHandler()}
                    >
                      <table.FlexRender header={h} />
                      <span aria-hidden="true">
                        {sorted === "asc"
                          ? " ▲"
                          : sorted === "desc"
                            ? " ▼"
                            : ""}
                      </span>
                    </button>
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {padTop > 0 && (
            <tr aria-hidden="true">
              <td
                colSpan={columns.length}
                style={{ height: padTop, padding: 0 }}
              />
            </tr>
          )}
          {items.map((vi) => {
            const row = rows[vi.index];
            const on =
              row.original.moduleIds.length > 0 &&
              row.original.moduleIds.every((m) => sel.has(m));
            return (
              <tr
                key={row.id}
                aria-rowindex={vi.index + 2}
                aria-selected={on}
                className={
                  on
                    ? "row--selected"
                    : row.original.worst === "fail"
                      ? "row--warn"
                      : undefined
                }
                style={{ height: ROW_H }}
                onClick={() =>
                  dispatch({ type: "select", ids: row.original.moduleIds })
                }
              >
                {row.getAllCells().map((c) => (
                  <td
                    key={c.id}
                    className={
                      ["modules", "vmp", "mppt"].includes(c.column.id)
                        ? "num"
                        : undefined
                    }
                  >
                    <table.FlexRender cell={c} />
                  </td>
                ))}
              </tr>
            );
          })}
          {padBottom > 0 && (
            <tr aria-hidden="true">
              <td
                colSpan={columns.length}
                style={{ height: padBottom, padding: 0 }}
              />
            </tr>
          )}
          {!rows.length && (
            <tr>
              <td colSpan={columns.length} className="sub">
                {t("stringTable.empty")}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
