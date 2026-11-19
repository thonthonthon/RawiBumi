import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  // Vite serves public assets at /fonts; Node SSR needs an absolute filesystem path (also on Windows).
  resolve: { alias: { "/fonts": fileURLToPath(new URL("./public/fonts", import.meta.url)) } },
  test: {
    css: { include: [/tokens\.css/] },
    include: ["tests/unit/**/*.test.ts"],
    environment: "node"
  }
});
