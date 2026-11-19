import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it, vi } from "vitest";
import "../../src/i18n";
vi.mock("../../src/client", () => ({ DEMO: true, engine: {}, exportAPI: {} }));
import { FreeCSVExport } from "../../src/results/ExportView";

it("disables server Free CSV in demo and explains the available HTML alternative", () => {
  const html = renderToStaticMarkup(createElement(FreeCSVExport, { projectId: "demo-project", runId: "demo-run" }));
  expect(html).toMatch(/<button[^>]*disabled/);
  expect(html).toContain("Server PDF and CSV downloads are unavailable in this demo.");
  expect(html).toContain("HTML report");
});
