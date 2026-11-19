#!/usr/bin/env node
// Generates src/generated/openapi.ts from the running FastAPI server's OpenAPI
// document. Start the API first (see README), then: npm run gen:openapi
// Override the URL with RAWIBUMI_OPENAPI_URL.
//
// openapi-typescript 7.13.0 declares a peer dependency on TypeScript 5, while
// this app pins TypeScript 7, so it runs through npx in isolation instead of
// being a devDependency.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const url = process.env.RAWIBUMI_OPENAPI_URL ?? "http://127.0.0.1:8000/openapi.json";
const out = path.join(root, "src/generated/openapi.ts");

const run = spawnSync("npx", ["--yes", "openapi-typescript@7.13.0", url, "--output", out], {
  cwd: root,
  stdio: "inherit",
  shell: process.platform === "win32"
});
process.exit(run.status ?? 1);
