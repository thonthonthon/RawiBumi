import { useEffect, useState } from "react";
import { DEMO } from "../client";

/** USE-D7: synthetic test components stay out of pickers unless the viewer turns them on (per-viewer preference). */
const KEY = "rawibumi.showTestComponents";
const EVENT = "rawibumi:test-components";

function read(): boolean {
  try {
    const stored = window.localStorage.getItem(KEY);
    // The demo has only synthetic components, so it shows them unless the viewer turned them off.
    return stored === null ? DEMO : stored === "1";
  } catch {
    return DEMO;
  }
}

export function useShowTestComponents(): [boolean, (show: boolean) => void] {
  const [show, setShow] = useState(read);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const sync = () => setShow(read());
    window.addEventListener(EVENT, sync);
    return () => window.removeEventListener(EVENT, sync);
  }, []);
  const update = (next: boolean) => {
    try {
      window.localStorage.setItem(KEY, next ? "1" : "0");
    } catch {
      // Storage can be unavailable (private window); the choice then lasts this page view.
    }
    setShow(next);
    if (typeof window !== "undefined") window.dispatchEvent(new Event(EVENT));
  };
  return [show, update];
}

/** Pickable components: no superseded revisions, no synthetic ones unless shown; the current choice always stays. */
export function pickable<T extends { revision_id: string; synthetic_reference: boolean; superseded_by?: string }>(
  items: T[], showTest: boolean, keep?: string
): T[] {
  return items.filter((c) => c.revision_id === keep || (!c.superseded_by && (showTest || !c.synthetic_reference)));
}
