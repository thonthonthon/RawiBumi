import { readFileSync } from "node:fs";
import { expect,it } from "vitest";
import css from "../../src/ui/tokens.css?raw";
import { reportToken } from "../../src/report/tokens";
it("resolves report colours from the canonical stylesheet",()=>{
 expect(css).toBe(readFileSync("src/ui/tokens.css","utf8"));
 expect(reportToken("role-panel-text")).toBe("#2B2F35");
});
