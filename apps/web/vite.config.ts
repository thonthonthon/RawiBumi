import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

export default defineConfig(({ mode }) => mode === "report" ? {
  resolve: { conditions: ["node"], alias: { "/fonts": fileURLToPath(new URL("./public/fonts", import.meta.url)) } },
  ssr: { noExternal: true, target: "node" },
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: { ssr: true, target: "node22", outDir: "dist/report-render", emptyOutDir: true,
    lib: { entry: "src/report/entry.ts", formats: ["cjs"], fileName: () => "report-render.cjs" },
    rolldownOptions: { platform: "node", output: { entryFileNames: "report-render.cjs" } } }
} : {
  plugins: [react()],
  server: {
    port: 5173,
    proxy: mode === "demo" ? undefined : {
      "/api": process.env.RAWIBUMI_API ?? "http://127.0.0.1:8000"
    }
  },
  build: {
    target: "es2022"
  },
  // Results and export are lazy chunks (ADR 0016): pre-bundle their libraries at start-up,
  // so the dev server does not discover them on first open and reload the page.
  optimizeDeps: {
    include: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers", "uplot", "react-dom/server"]
  }
});
