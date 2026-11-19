import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button as RacButton, ListLayout, Tree, TreeItem, TreeItemContent, Virtualizer, type Key } from "react-aria-components";
import { worstCheck } from "../engine/topology";
import { useForm, useStore } from "../state/store";
import { mpptColor } from "../ui/palette";
import { CheckGlyph, checksByString, VoltageBar } from "./checks";
import { notationOfInverter } from "./sync";

const UNASSIGNED = "__unassigned";

/**
 * Electrical tree (B6): inverter → MPPT → string, read from the engine's topology view.
 * - An MPPT row is the target of the Assign brush and of new strings: activating it sets the target
 *   (the same as [ ] and 1–9 on the plan).
 * - A string row selects its modules on the plan.
 * - Each MPPT shows a voltage bar and each string its worst live check (engine values).
 * The tree, the plan and the notation all read the same engine topology, so they cannot drift.
 */
export function TopologyTree() {
  const { t } = useTranslation();
  const { state, dispatch } = useStore();
  const v = state.view!;
  const checks = useMemo(() => checksByString(v.topology_checks), [v.topology_checks]);
  const modulesOf = useMemo(() => new Map(v.bundle.electrical_design.strings.map((s) => [s.string_id, s.module_instance_ids])), [v]);
  const [collapsed, setCollapsed] = useForm<string[]>("elec.treeCollapsed", []);

  const allKeys = useMemo(
    () => [...v.topology_view.inverters.flatMap((inv) => [inv.inverter_instance_id, ...inv.mppts.map((m) => m.mppt_instance_id)]), UNASSIGNED],
    [v.topology_view]
  );
  const expandedKeys = useMemo(() => new Set(allKeys.filter((k) => !collapsed.includes(k))), [allKeys, collapsed]);
  const rowCount = v.topology_view.inverters.reduce((n, inv) => n + 1 + (expandedKeys.has(inv.inverter_instance_id)
    ? inv.mppts.reduce((m, mppt) => m + 1 + (expandedKeys.has(mppt.mppt_instance_id) ? mppt.strings.length : 0), 0) : 0), 0)
    + (v.topology_view.unassigned_strings.length ? 1 + (expandedKeys.has(UNASSIGNED) ? v.topology_view.unassigned_strings.length : 0) : 0);
  const selectedStrings = useMemo(() => {
    const sel = new Set(state.selection);
    return new Set(v.bundle.electrical_design.strings.filter((s) => s.module_instance_ids.length && s.module_instance_ids.every((m) => sel.has(m))).map((s) => s.string_id));
  }, [state.selection, v]);

  const stringRow = (s: { string_id: string; name: string; module_count: number }) => {
    const c = checks.get(s.string_id);
    return (
      <TreeItem
        key={s.string_id}
        id={s.string_id}
        textValue={`${s.name}, ${t("electrical.modules", { count: s.module_count })}${c ? `, ${t(`checks.state_${worstCheck(c.checks)}`)}` : ""}`}
        onAction={() => dispatch({ type: "select", ids: modulesOf.get(s.string_id) ?? [] })}
        className={selectedStrings.has(s.string_id) ? "etree__item etree__item--selected" : "etree__item"}
      >
        <TreeItemContent>
          <span className="etree__row etree__row--string">
            <span className="etree__name">{s.name}</span>
            <span className="etree__meta">{t("electrical.modules", { count: s.module_count })}</span>
            {c?.vmp_v != null && <span className="etree__meta">{c.vmp_v.toFixed(0)} V</span>}
            <CheckGlyph checks={c?.checks} />
          </span>
        </TreeItemContent>
      </TreeItem>
    );
  };

  const tree = (
    <Tree
      aria-label={t("electrical.treeLabel")}
      className="etree"
      style={rowCount > 200 ? { height: 320, overflow: "auto" } : undefined}
      selectionMode="none"
      expandedKeys={expandedKeys}
      onExpandedChange={(keys: Set<Key>) => setCollapsed(allKeys.filter((k) => !keys.has(k)))}
      renderEmptyState={() => <p className="sub">{t("electrical.treeEmpty")}</p>}
    >
      {v.topology_view.inverters.map((inv) => (
        <TreeItem key={inv.inverter_instance_id} id={inv.inverter_instance_id} textValue={`${inv.name} ${notationOfInverter(inv)}`} className="etree__item">
          <TreeItemContent>
            {({ isExpanded }) => (
              <span className="etree__row etree__row--inverter">
                <RacButton slot="chevron" className="etree__chevron" aria-label={isExpanded ? t("electrical.collapse") : t("electrical.expand")}>
                  {isExpanded ? "▾" : "▸"}
                </RacButton>
                <span className="etree__name">{inv.name}</span>
                <code className="etree__notation">{notationOfInverter(inv) || t("electrical.noNotation")}</code>
              </span>
            )}
          </TreeItemContent>
          {inv.mppts.map((m) => {
            const strs = m.strings.map((s) => checks.get(s.string_id)).filter(Boolean) as NonNullable<ReturnType<typeof checks.get>>[];
            const isTarget = state.target === m.mppt_instance_id;
            return (
              <TreeItem
                key={m.mppt_instance_id}
                id={m.mppt_instance_id}
                textValue={`${inv.name} MPPT ${m.index}${isTarget ? `, ${t("electrical.target")}` : ""}`}
                onAction={() => dispatch({ type: "setTarget", target: m.mppt_instance_id })}
                className={isTarget ? "etree__item etree__item--target" : "etree__item"}
              >
                <TreeItemContent>
                  {({ isExpanded, hasChildItems }) => (
                    <span className="etree__row etree__row--mppt">
                      {hasChildItems ? (
                        <RacButton slot="chevron" className="etree__chevron" aria-label={isExpanded ? t("electrical.collapse") : t("electrical.expand")}>
                          {isExpanded ? "▾" : "▸"}
                        </RacButton>
                      ) : (
                        <span className="etree__chevron" aria-hidden="true" />
                      )}
                      <span className="etree__swatch" style={{ background: mpptColor(m.index - 1) }} aria-hidden="true" />
                      <span className="etree__name">MPPT {m.index}</span>
                      {isTarget && <span className="tag tag--target">{t("electrical.target")}</span>}
                      <span className="etree__meta">{t("electrical.strings", { count: m.strings.length })}</span>
                      <VoltageBar strings={strs} basis={v.topology_checks?.basis ?? ""} />
                    </span>
                  )}
                </TreeItemContent>
                {m.strings.map(stringRow)}
              </TreeItem>
            );
          })}
        </TreeItem>
      ))}
      {v.topology_view.unassigned_strings.length > 0 && (
        <TreeItem id={UNASSIGNED} textValue={t("electrical.unassigned")} className="etree__item">
          <TreeItemContent>
            {({ isExpanded }) => (
              <span className="etree__row etree__row--inverter">
                <RacButton slot="chevron" className="etree__chevron" aria-label={isExpanded ? t("electrical.collapse") : t("electrical.expand")}>
                  {isExpanded ? "▾" : "▸"}
                </RacButton>
                <span className="etree__name">{t("electrical.unassigned")}</span>
                <span className="etree__meta">{t("electrical.strings", { count: v.topology_view.unassigned_strings.length })}</span>
              </span>
            )}
          </TreeItemContent>
          {v.topology_view.unassigned_strings.map(stringRow)}
        </TreeItem>
      )}
    </Tree>
  );
  return rowCount > 200 ? <Virtualizer layout={ListLayout} layoutOptions={{ rowHeight: 32 }}>{tree}</Virtualizer> : tree;
}
