/**
 * EngineAdapter: the only door between the UI and the RawiBumi engine.
 *
 * - Screens import `engine` from ../client.ts and never call `fetch` themselves.
 * - The HTTP implementation (../api.ts) is the reference surface.
 * - The demo implementation (../demo/mockApi.ts) must implement every method,
 *   checked at compile time with `satisfies EngineAdapter`. A method the demo
 *   cannot honour rejects with DemoUnavailableError instead of being absent.
 * - Phase 7.0 switches domains from the mock to HTTP; screens do not change.
 *
 * See docs/adr/0005-engine-adapter-boundary.md.
 */
import { api } from "../api";
export { exportAPI } from "../api";
export type { CSVExportSchema, RunTimeSeriesView } from "../api";

export type EngineAdapter = typeof api;
export type EngineMethod = keyof EngineAdapter;

export const httpAdapter: EngineAdapter = api;

/** Raised by the demo adapter for engine capabilities it does not imitate. */
export class DemoUnavailableError extends Error {
  readonly method: string;
  constructor(method: string) {
    super(`"${method}" needs the RawiBumi engine and is not available in demo mode.`);
    this.name = "DemoUnavailableError";
    this.method = method;
  }
}
