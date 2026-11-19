import { api } from "./api";
import { mockApi } from "./demo/mockApi";


/** True when running with `--mode demo` (in-browser mock engine, for UI review only). */
export const DEMO = import.meta.env.VITE_RAWIBUMI_DEMO === "1";


/** The engine client used everywhere in the UI. Same surface as ./api. */
export const engine: typeof api = DEMO ? (mockApi as unknown as typeof api) : api;