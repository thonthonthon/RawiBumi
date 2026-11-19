#!/usr/bin/env node
// Anti-AI-design gate: runs impeccable's deterministic detector (pinned in
// devDependencies) on the source and fails on any finding that is not in
// quality/impeccable-baseline.json. Line numbers are ignored so unrelated
// edits do not break the gate. `--update` rewrites the baseline; do that only
// when a finding is fixed or deliberately accepted (say why in the PR).
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const BASELINE = path.join(root, "quality/impeccable-baseline.json");
const update = process.argv.includes("--update");
const bin = path.join(root, "node_modules/.bin", process.platform === "win32" ? "impeccable.cmd" : "impeccable");

const run = spawnSync(bin, ["detect", "--json", "--no-advisory", "src", "index.html"], {
  cwd: root,
  encoding: "utf8",
  shell: process.platform === "win32",
  maxBuffer: 64 * 1024 * 1024
});
if (run.error) throw run.error;
if (![0, 2].includes(run.status)) {
  console.error(run.stderr || `impeccable exited with ${run.status}`);
  process.exit(1);
}

const findings = JSON.parse(run.stdout || "[]").map((f) => ({
  antipattern: f.antipattern,
  file: path.relative(root, f.file ?? "").split(path.sep).join("/"),
  snippet: (f.snippet ?? "").trim()
}));
const key = (f) => `${f.antipattern}|${f.file}|${f.snippet}`;

if (update) {
  fs.mkdirSync(path.dirname(BASELINE), { recursive: true });
  fs.writeFileSync(BASELINE, JSON.stringify({ tool: "impeccable@4.7.0", findings }, null, 2) + "\n");
  console.log(`Baseline written: ${findings.length} accepted finding(s).`);
  process.exit(0);
}

const accepted = new Set((fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")).findings : []).map(key));
const fresh = findings.filter((f) => !accepted.has(key(f)));
const fixed = [...accepted].filter((k) => !findings.some((f) => key(f) === k));

if (fixed.length) console.log(`Fixed since baseline (run npm run quality -- --update): ${fixed.length}`);
if (fresh.length) {
  console.error("New design findings:");
  for (const f of fresh) console.error(`  ${f.file}  ${f.antipattern}  ${f.snippet}`);
  process.exit(1);
}
console.log(`Design gate OK: ${findings.length} finding(s), all in the baseline.`);
