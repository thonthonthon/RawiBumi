import { expect, it } from "vitest";
import { railSteps } from "../../src/modules/registry";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";

it("RB-MENU1 defines the exact rail order, EN/ID labels and shortcuts", () => {
  const expected = [
    ["site", "Project & site", "Proyek & lokasi", "1"],
    ["components", "Components", "Komponen", "2"],
    ["scene", "Scene", "Geometri", "3"],
    ["layout", "PV layout", "Tata letak PV", "4"],
    ["systems", "Systems", "Sistem", "5"],
    ["electrical", "Electrical", "Kelistrikan", "6"],
    ["meteo", "Weather", "Cuaca", "7"],
    ["losses", "Losses & grid", "Rugi-rugi & jaringan", "8"],
    ["simulate", "Simulate", "Simulasi", "9"],
    ["results", "Results", "Hasil", "0"],
    ["export", "Report & export", "Laporan & ekspor", undefined]
  ];
  expect(railSteps().map(step => {
    const key = step.labelKey.slice("steps.".length) as keyof typeof en.steps;
    return [step.id, en.steps[key], id.steps[key], step.shortcut];
  })).toEqual(expected);
});

it("every step starts with its translated one-line purpose", async () => {
  const { renderToStaticMarkup } = await import("react-dom/server");
  const { Children, isValidElement } = await import("react");
  const { default: i18n } = await import("../../src/i18n");
  try {
    for (const [language, messages] of [["en", en], ["id", id]] as const) {
      await i18n.changeLanguage(language);
      for (const step of railSteps()) {
        const panel = step.render({ openImport() {} });
        if (!isValidElement<{ children: import("react").ReactNode }>(panel)) throw new Error("Missing step panel");
        const intro = Children.toArray(panel.props.children)[0];
        expect(renderToStaticMarkup(intro)).toBe(`<p class="note">${messages.stepIntros[step.id]}</p>`);
      }
    }
  } finally {
    await i18n.changeLanguage("en");
  }
});
