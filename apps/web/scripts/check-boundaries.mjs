#!/usr/bin/env node
// Architecture checks that a type checker cannot express.
//   1. Only src/api.ts may call fetch(); screens go through `engine` (src/client.ts).
//   2. Only src/engine/adapter.ts may import ./api directly.
//   3. Hard-coded colours (hex, rgb(), hsl()) may not increase (ratchet; 0 since F1).
// Run `npm run check:boundaries`. `--update` rewrites the colour baseline after
// a deliberate reduction.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = path.join(root, "src");
const BASELINE = path.join(root, "quality/colour-baseline.json");
const update = process.argv.includes("--update");

const FETCH_ALLOWED = new Set(["src/api.ts"]);
const API_IMPORT_ALLOWED = new Set(["src/engine/adapter.ts"]);
const COLOUR_EXEMPT = [/^src\/ui\/tokens\.css$/, /^src\/ui\/palette\.ts$/, /^src\/generated\//];
// Hex colours and rgb()/hsl() functions. palette.ts converts tokens and is exempt.
const HEX = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\(/g;

function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const full = path.join(dir, e.name);
    return e.isDirectory() ? walk(full) : [full];
  });
}

const problems = [];
const colours = {};
for (const file of walk(SRC)) {
  const rel = path.relative(root, file).split(path.sep).join("/");
  if (!/\.(tsx?|css)$/.test(rel)) continue;
  const text = fs.readFileSync(file, "utf8");
  if (/\.(tsx?)$/.test(rel)) {
    if (!FETCH_ALLOWED.has(rel) && /\bfetch\s*\(/.test(text))
      problems.push(`${rel}: calls fetch(); use \`engine\` from src/client.ts`);
    if (!API_IMPORT_ALLOWED.has(rel) && /from\s+["'](\.\.?\/)+api["']/.test(text))
      problems.push(`${rel}: imports ./api directly; use \`engine\` from src/client.ts`);
  }
  if (!COLOUR_EXEMPT.some((r) => r.test(rel))) {
    const n = (text.replace(/\/\*[\s\S]*?\*\//g, "").match(HEX) ?? []).length;
    if (n) colours[rel] = n;
  }
}

const baseline = fs.existsSync(BASELINE) ? JSON.parse(fs.readFileSync(BASELINE, "utf8")) : { files: {} };
if (update) {
  fs.mkdirSync(path.dirname(BASELINE), { recursive: true });
  fs.writeFileSync(BASELINE, JSON.stringify({ note: "Hard-coded colour count per file. May only go down; 0 since F1 (all colours come from tokens).", files: colours }, null, 2) + "\n");
  console.log(`Colour baseline written: ${Object.values(colours).reduce((a, b) => a + b, 0)} literals in ${Object.keys(colours).length} files.`);
} else {
  for (const [rel, n] of Object.entries(colours)) {
    const allowed = baseline.files[rel] ?? 0;
    if (n > allowed) problems.push(`${rel}: ${n} hard-coded colours (baseline ${allowed}); use --rb-* tokens from src/ui/tokens.css`);
  }
}

if (problems.length) {
  console.error(problems.join("\n"));
  process.exit(1);
}
const total = Object.values(colours).reduce((a, b) => a + b, 0);
console.log(`Boundaries OK. Hard-coded colours: ${total} (must not grow).`);
