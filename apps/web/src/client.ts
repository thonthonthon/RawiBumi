import { httpAdapter, type EngineAdapter } from "./engine/adapter";
import { mockApi } from "./demo/mockApi";
import { exportAPI as persistedRunExportAPI } from "./engine/adapter";
export type { CSVExportSchema, RunTimeSeriesView } from "./engine/adapter";


/** True when running with `--mode demo` (in-browser mock engine, for UI review only). */
// `--mode demo` is enough on its own; .env.demo (VITE_RAWIBUMI_DEMO=1) is optional.
export const DEMO = import.meta.env.VITE_RAWIBUMI_DEMO === "1" || import.meta.env.MODE === "demo";


/**
 * The engine client used everywhere in the UI (see ./engine/adapter.ts).
 * No cast: the demo adapter must implement the full surface.
 */
export const engine: EngineAdapter = DEMO ? mockApi : httpAdapter;

/** Server-backed persisted-run exports; never derived from demo physics. */
export const exportAPI = persistedRunExportAPI;