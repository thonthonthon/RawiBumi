import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { pickable } from "./testComponents";

/** USE3: brand, readiness and text filters over catalog components; the current choice always stays listed. */
export type ComponentStatus = "all" | "ready" | "layout_only";

interface Filterable {
  revision_id: string;
  manufacturer: string;
  model: string;
  synthetic_reference: boolean;
  superseded_by?: string;
  simulation_ready?: boolean;
}

export interface ComponentFilterState {
  brand: string;
  status: ComponentStatus;
  query: string;
}

export const NO_FILTER: ComponentFilterState = { brand: "", status: "all", query: "" };

export function filterComponents<T extends Filterable>(items: T[], filter: ComponentFilterState, showTest: boolean, keep?: string): T[] {
  const query = filter.query.trim().toLowerCase();
  return pickable(items, showTest, keep).filter((c) => c.revision_id === keep || (
    (!filter.brand || c.manufacturer === filter.brand)
    && (filter.status === "all" || (filter.status === "ready" ? c.simulation_ready !== false : c.simulation_ready === false))
    && (!query || `${c.manufacturer} ${c.model} ${c.revision_id}`.toLowerCase().includes(query))));
}

export function brandsOf(items: Filterable[], showTest: boolean): string[] {
  return [...new Set(pickable(items, showTest).map((c) => c.manufacturer))].sort((a, b) => a.localeCompare(b));
}

export function useComponentFilter() {
  return useState<ComponentFilterState>(NO_FILTER);
}

/** The filter controls: Brand, optionally Status, and a search box. */
export function ComponentFilterBar({ items, filter, onChange, showTest, withStatus = false }: {
  items: Filterable[]; filter: ComponentFilterState; onChange: (f: ComponentFilterState) => void; showTest: boolean; withStatus?: boolean;
}) {
  const { t } = useTranslation();
  const brands = useMemo(() => brandsOf(items, showTest), [items, showTest]);
  return (
    <div className="row wrap component-filter" data-component-filter>
      <select className="input" aria-label={t("use3.brand")} value={filter.brand} onChange={(e) => onChange({ ...filter, brand: e.target.value })}>
        <option value="">{t("use3.allBrands")}</option>
        {brands.map((b) => <option key={b} value={b}>{b}</option>)}
      </select>
      {withStatus && (
        <select className="input" aria-label={t("use3.status")} value={filter.status} onChange={(e) => onChange({ ...filter, status: e.target.value as ComponentStatus })}>
          <option value="all">{t("use3.allStatuses")}</option>
          <option value="ready">{t("s12a.ready")}</option>
          <option value="layout_only">{t("s12a.layoutOnly")}</option>
        </select>
      )}
      <input className="input" type="search" aria-label={t("use3.search")} placeholder={t("use3.searchPlaceholder")} value={filter.query}
        onChange={(e) => onChange({ ...filter, query: e.target.value })} />
    </div>
  );
}
