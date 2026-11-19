import { beforeEach, expect, it, vi } from "vitest";
import { isValidElement, type ReactElement } from "react";

const h = vi.hoisted(() => ({ choice: null as unknown, storage: new Map<string, string>() }));
vi.mock("react", async load => ({ ...await load<typeof import("react")>(),
  useState: () => [h.choice, (value: unknown) => { h.choice = value; }], useId: () => "body"
}));
import { Section } from "../../src/ui/kit";
function nodes(value: unknown): ReactElement<any>[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (!isValidElement(value)) return [];
  const node = value as ReactElement<any>;
  return [node, ...nodes(node.props.children)];
}
function toggle(primary: boolean, title = "Selection") {
  return nodes(Section({ title, primary, children: "controls" })).find(n => n.type === "button")!;
}
beforeEach(() => {
  h.choice = null; h.storage.clear();
  vi.stubGlobal("window", { localStorage: {
    getItem: (key: string) => h.storage.get(key) ?? null,
    setItem: (key: string, value: string) => h.storage.set(key, value)
  } });
});
it.each(["Selection", "Library"])("%s follows a computed default until the user chooses", title => {
  expect(toggle(false, title).props["aria-expanded"]).toBe(false);
  expect(toggle(true, title).props["aria-expanded"]).toBe(true);
  toggle(true, title).props.onClick();
  expect(toggle(true, title).props["aria-expanded"]).toBe(false);
  expect(toggle(false, title).props["aria-expanded"]).toBe(false);
  h.choice = null; // Remount: the explicit close persists.
  expect(toggle(true, title).props["aria-expanded"]).toBe(false);
  toggle(false, title).props.onClick();
  expect(toggle(false, title).props["aria-expanded"]).toBe(true);
  h.choice = null;
  expect(toggle(false, title).props["aria-expanded"]).toBe(true);
});
it("renamed sections use their new default without migrating storage", () => {
  h.storage.set("rawibumi.section.Previous title", "0");
  expect(toggle(true, "New title").props["aria-expanded"]).toBe(true);
  expect(h.storage.size).toBe(1);
});
it("a user choice still works when storage is blocked", () => {
  vi.stubGlobal("window", { get localStorage() { throw new Error("blocked"); } });
  toggle(false).props.onClick();
  expect(toggle(false).props["aria-expanded"]).toBe(true);
});
