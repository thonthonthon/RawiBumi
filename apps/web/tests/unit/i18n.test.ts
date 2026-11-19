import { describe, expect, it } from "vitest";
import { en } from "../../src/i18n/en";
import { id } from "../../src/i18n/id";

type Tree = { [k: string]: string | Tree };
function flatten(t: Tree, prefix = ""): Record<string, string> {
  return Object.entries(t).reduce<Record<string, string>>((acc, [k, v]) => {
    const key = prefix ? `${prefix}.${k}` : k;
    return typeof v === "string" ? { ...acc, [key]: v } : { ...acc, ...flatten(v, key) };
  }, {});
}
const placeholders = (s: string) => [...s.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort();

describe("translations", () => {
  const E = flatten(en as unknown as Tree);
  const I = flatten(id as unknown as Tree);

  it("Bahasa Indonesia has exactly the English keys", () => {
    expect(Object.keys(I).sort()).toEqual(Object.keys(E).sort());
  });

  it("no string is empty", () => {
    expect(Object.entries({ ...E, ...I }).filter(([, v]) => !v.trim())).toEqual([]);
  });

  it("placeholders match between languages", () => {
    const mismatched = Object.keys(E).filter((k) => placeholders(E[k]).join() !== placeholders(I[k]).join());
    expect(mismatched).toEqual([]);
  });

  it("English labels use sentence case (no Title Case Words)", () => {
    const titleCase = Object.entries(flatten((en as unknown as Tree).steps as Tree)).filter(([, v]) => /^[A-Z][a-z]+ [A-Z][a-z]/.test(v));
    expect(titleCase).toEqual([]);
  });
});
