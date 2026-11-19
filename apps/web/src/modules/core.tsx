import { ComponentsPanel } from "../panels/ComponentsPanel";
import { ElectricalPanel } from "../panels/ElectricalPanel";
import { LayoutPanel } from "../panels/LayoutPanel";
import { LossesGridPanel } from "../panels/LossesGridPanel";
import { useTranslation } from "react-i18next";
import { MeteoPanel } from "../panels/MeteoPanel";
import { ScenePanel } from "../panels/ScenePanel";
import { SimulatePanel } from "../panels/SimulatePanel";
import { SystemsPanel } from "../panels/SystemsPanel";
import { SitePanel } from "../panels/SitePanel";
import { lazy, Suspense } from "react";
import type { ModuleDef } from "./types";

// Results and export carry the chart libraries and the report builder: loaded when first opened (F7, ADR 0016).
const ResultsView = lazy(() => import("../results/ResultsView").then((m) => ({ default: m.ResultsView })));
const ExportView = lazy(() => import("../results/ExportView").then((m) => ({ default: m.ExportView })));
const Loading = () => <div className="results results--loading" aria-busy="true" />;

function StepIntro({ step }: { step: string }) {
  const { t } = useTranslation();
  return <p className="note">{t(`stepIntros.${step}`)}</p>;
}

/** The grid-connected PV workflow. */
export const coreModule: ModuleDef = {
  id: "core",
  order: 0,
  steps: [
    { id: "site", shortcut: "1", labelKey: "steps.site", layout: "workspace", render: () => <><StepIntro step="site" /><SitePanel /></> },
    { id: "components", shortcut: "2", labelKey: "steps.components", layout: "workspace", render: (ctx) => <><StepIntro step="components" /><ComponentsPanel onImport={() => ctx.openImport("components")} /></> },
    { id: "scene", shortcut: "3", labelKey: "steps.scene", layout: "workspace", render: (ctx) => <><StepIntro step="scene" /><ScenePanel onImport={() => ctx.openImport("geometry")} /></> },
    { id: "layout", shortcut: "4", labelKey: "steps.layout", layout: "workspace", render: () => <><StepIntro step="layout" /><LayoutPanel /></> },
    { id: "systems", shortcut: "5", labelKey: "steps.systems", layout: "workspace", render: () => <><StepIntro step="systems" /><SystemsPanel /></> },
    { id: "electrical", shortcut: "6", labelKey: "steps.electrical", layout: "workspace", render: () => <><StepIntro step="electrical" /><ElectricalPanel /></> },
    { id: "meteo", shortcut: "7", labelKey: "steps.meteo", layout: "workspace", render: (ctx) => <><StepIntro step="meteo" /><MeteoPanel onImport={() => ctx.openImport("meteo")} /></> },
    { id: "losses", shortcut: "8", labelKey: "steps.losses", layout: "workspace", render: () => <><StepIntro step="losses" /><LossesGridPanel /></> },
    { id: "simulate", shortcut: "9", labelKey: "steps.simulate", layout: "workspace", render: () => <><StepIntro step="simulate" /><SimulatePanel /></>, feature: "core.simulate" },
    { id: "results", shortcut: "0", labelKey: "steps.results", layout: "full", render: () => (
        <><StepIntro step="results" /><Suspense fallback={<Loading />}>
          <ResultsView />
        </Suspense></>
      ) },
    { id: "export", labelKey: "steps.export", layout: "full", render: () => (
        <><StepIntro step="export" /><Suspense fallback={<Loading />}>
          <ExportView />
        </Suspense></>
      ) }
  ]
};
