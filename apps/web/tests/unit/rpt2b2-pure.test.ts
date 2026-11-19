import { readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { expect, it } from "vitest";

it("keeps the shared report's pure dependency chain free of browser state and storage", () => {
  const root = resolve("src");
  const visited = new Set<string>();
  const visit = (file: string) => {
    if (visited.has(file)) return;
    visited.add(file);
    const code = readFileSync(file, "utf8");
    expect(file).not.toMatch(/\/(state|demo|imagery|panes)\/|\/ui\/kit|\/site\//);
    expect(code.replace(/\/\*[\s\S]*?\*\//g, "")).not.toMatch(/\b(?:window|document|localStorage|sessionStorage)\s*[.[]/);
    const imports = [...code.matchAll(/(?:import|export)\s+(?!type\b)[^;]*?from\s+["']([^"']+)["']/g), ...code.matchAll(/\bimport\s*\(\s*["']([^"']+)["']\s*\)(?!\s*\.[A-Z])/g), ...code.matchAll(/^\s*import\s*["']([^"']+)["']/gm)];
    for (const match of imports) {
      const path = match[1];
      if (!path.startsWith(".") || path.includes("?")) continue;
      const target = [".ts", ".tsx", "/index.ts", "/index.tsx"].map(ext => resolve(dirname(file), path + ext)).find(existsSync);
      if (target) visit(target);
    }
  };
  visit(resolve(root, "report/pureSld.tsx"));
  visit(resolve(root, "report/presentation.ts"));
  visit(resolve(root, "report/render.ts"));
});
