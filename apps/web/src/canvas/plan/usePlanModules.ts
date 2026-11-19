import { useMemo } from "react";
import { DEMO } from "../../client";
import { useUI, type ModuleShape } from "../../state/store";
import { syntheticCount, syntheticModules } from "./synthetic";

const requested = typeof window !== "undefined" && DEMO ? syntheticCount(window.location.search) : null;
let cache: ModuleShape[] | null = null;

/**
 * Modules shown by the plan and 3D views: the project's, or in demo builds
 * with `?synthetic=N`, a synthetic layout for the performance check.
 */
export function usePlanModules(): { modules: ModuleShape[]; synthetic: boolean } {
  const stateModules = useUI((s) => s.modules);
  return useMemo(() => {
    if (!requested) return { modules: stateModules, synthetic: false };
    cache ??= syntheticModules(requested);
    return { modules: cache, synthetic: true };
  }, [stateModules]);
}
