import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { engine } from "../client";
import type { TopologyCommand } from "../engine/topology";
import { centroid, pointInPolygon, type Vec2 } from "../geometry";
import { engineCommand } from "../state/history";
import { useActions, useUI, type ModuleShape } from "../state/store";
import type { ProjectView } from "../types";

/** All MPPTs in inverter order, for the [ ] and 1–9 target keys. */
export function allMppts(view: ProjectView | null): Array<{ id: string; inverterId: string; inverterName: string; index: number }> {
  if (!view) return [];
  return view.bundle.electrical_design.inverter_instances.flatMap((inv) =>
    inv.mppt_instance_ids.map((id, index) => ({ id, inverterId: inv.inverter_instance_id, inverterName: inv.name, index }))
  );
}

/**
 * The electrical tools of the plan (B6): String path (S), Assign brush (A),
 * Lasso (L), Split (X), Join (J), Reverse (R), Move module (M) and Swap modules (W), plus the MPPT target keys.
 * Each finished gesture is one engine topology command and one undo step.
 */
export function useElectricalTools(modules: readonly ModuleShape[]) {
  const { t } = useTranslation();
  const { dispatch, toast } = useActions();
  const s = useUI((st) => ({ tool: st.tool, view: st.view, target: st.target, selection: st.selection, step: st.step }));
  const [path, setPath] = useState<string[]>([]);
  // One Enter hint per path (USE1 E6), not one per click.
  const hinted = useRef(false);
  useEffect(() => { if (!path.length) hinted.current = false; }, [path.length]);
  const [painting, setPainting] = useState(false);
  const [brush, setBrush] = useState<string[]>([]);
  const [lasso, setLasso] = useState<Vec2[]>([]);
  const [joinFirst, setJoinFirst] = useState<string | null>(null);
  /** S14a: the module picked by the first click of Move module or Swap modules. */
  const [picked, setPicked] = useState<string | null>(null);
  const pid = s.view?.bundle.project.project_id ?? "";
  // A pick belongs to the tool that made it.
  useEffect(() => setPicked(null), [s.tool]);

  const stringOf = useMemo(() => new Map(modules.filter((m) => m.stringId).map((m) => [m.id, m.stringId!])), [modules]);
  const stringModules = useMemo(() => new Map((s.view?.bundle.electrical_design.strings ?? []).map((x) => [x.string_id, x.module_instance_ids])), [s.view]);
  const centres = useMemo(() => new Map(modules.map((m) => [m.id, centroid(m.polygon)] as const)), [modules]);
  const mppts = useMemo(() => allMppts(s.view), [s.view]);

  const run = useCallback((label: string, command: TopologyCommand) => engineCommand(label, () => engine.topologyCommand(pid, command, s.view ?? undefined)), [pid, s.view]);

  const reset = useCallback(() => {
    setPath([]);
    setPainting(false);
    setBrush([]);
    setLasso([]);
    setJoinFirst(null);
    setPicked(null);
  }, []);

  const addToPath = (id: string) => {
    if (path.includes(id)) return;
    if (stringOf.has(id)) {
      toast("info", t("electrical.alreadyStrung", { string: stringOf.get(id) }));
      return;
    }
    setPath((p) => (p.includes(id) ? p : [...p, id]));
  };

  /**
   * Move module: the picked module takes the clicked module's place in that string, the rest shifting on
   * (Shift+click: just after it). Delete takes the picked module out of its string.
   */
  const moveTo = (id: string, target: string, after: boolean) => {
    const to = stringOf.get(target)!;
    const rest = (stringModules.get(to) ?? []).filter((m) => m !== id);
    const index = rest.indexOf(target) + (after ? 1 : 0);
    void run(t("electrical.movingModule"), { command_type: "move_module", parameters: { module_instance_id: id, to_string_id: to, index } });
  };

  /** Pointer down on the plan; returns true when the tool used it. */
  const down = (w: Vec2, moduleId: string | null, shift = false): boolean => {
    switch (s.tool) {
      case "string_path":
        if (!moduleId) return false;
        addToPath(moduleId);
        setPainting(true);
        return true;
      case "assign": {
        if (!s.target) {
          toast("info", t("electrical.pickTarget"));
          return true;
        }
        const sid = moduleId ? stringOf.get(moduleId) : undefined;
        if (moduleId && !sid) toast("info", t("electrical.notStrung"));
        setBrush(sid ? [sid] : []);
        setPainting(true);
        return true;
      }
      case "lasso":
        setLasso([w]);
        return true;
      case "split": {
        const sid = moduleId ? stringOf.get(moduleId) : undefined;
        if (!sid) return !!moduleId;
        void run(t("electrical.splitting"), { command_type: "split_string", parameters: { string_id: sid, after_module_instance_id: moduleId! } });
        return true;
      }
      case "join": {
        const sid = moduleId ? stringOf.get(moduleId) : undefined;
        if (!sid) return !!moduleId;
        if (!joinFirst) setJoinFirst(sid);
        else if (joinFirst === sid) setJoinFirst(null);
        else {
          const first = joinFirst;
          setJoinFirst(null);
          void run(t("electrical.joining"), { command_type: "join_strings", parameters: { first_string_id: first, second_string_id: sid } });
        }
        return true;
      }
      case "reverse": {
        const sid = moduleId ? stringOf.get(moduleId) : undefined;
        if (!sid) return !!moduleId;
        void run(t("electrical.reversing"), { command_type: "reverse_string", parameters: { string_id: sid } });
        return true;
      }
      case "move_module":
      case "swap_modules": {
        if (!moduleId) return false;
        if (!stringOf.has(moduleId)) {
          toast("info", t("electrical.notStrung"));
          return true;
        }
        if (!picked || picked === moduleId) {
          setPicked(picked === moduleId ? null : moduleId);
          return true;
        }
        const first = picked;
        setPicked(null);
        if (s.tool === "move_module") moveTo(first, moduleId, shift);
        else void run(t("electrical.swappingModules"), { command_type: "swap_modules", parameters: { first_module_instance_id: first, second_module_instance_id: moduleId } });
        return true;
      }
      default:
        return false;
    }
  };

  const move = (w: Vec2, moduleId: string | null, scale: number) => {
    if (s.tool === "string_path" && painting && moduleId) addToPath(moduleId);
    else if (s.tool === "assign" && painting && moduleId) {
      const sid = stringOf.get(moduleId);
      if (sid) setBrush((b) => (b.includes(sid) ? b : [...b, sid]));
    } else if (s.tool === "lasso" && lasso.length) {
      const last = lasso[lasso.length - 1];
      if (Math.hypot(w[0] - last[0], w[1] - last[1]) * scale > 3) setLasso((l) => [...l, w]);
    }
  };

  const up = () => {
    if (s.tool === "string_path") {
      setPainting(false);
      // USE1 (E6): a path is only a draft until Enter; say so, with its length.
      if (painting && path.length && !hinted.current) {
        hinted.current = true;
        toast("info", t("use1.pathHint", { count: path.length }));
      }
    }
    else if (s.tool === "assign") {
      setPainting(false);
      if (brush.length && s.target) void run(t("electrical.assigning"), { command_type: "assign_strings_to_mppt", parameters: { string_ids: brush, mppt_instance_id: s.target } });
      setBrush([]);
    } else if (s.tool === "lasso") {
      if (lasso.length > 2) {
        const ids = modules.filter((m) => pointInPolygon(centres.get(m.id)!, lasso)).map((m) => m.id);
        dispatch({ type: "select", ids });
      }
      setLasso([]);
    }
  };

  const setTargetIndex = (i: number) => {
    const m = mppts[i];
    if (m) dispatch({ type: "setTarget", target: m.id });
  };

  /** Keys while the electrical step is active; returns true when used. */
  const key = (ev: KeyboardEvent): boolean => {
    if (s.step !== "electrical") return false;
    if (ev.key === "[" || ev.key === "]") {
      if (!mppts.length) return true;
      const at = mppts.findIndex((m) => m.id === s.target);
      const next = at < 0 ? 0 : (at + (ev.key === "]" ? 1 : -1) + mppts.length) % mppts.length;
      setTargetIndex(next);
      return true;
    }
    if (/^[1-9]$/.test(ev.key) && mppts.length) {
      const cur = mppts.find((m) => m.id === s.target) ?? mppts[0];
      const inInverter = mppts.filter((m) => m.inverterId === cur.inverterId);
      const m = inInverter[Number(ev.key) - 1];
      if (m) dispatch({ type: "setTarget", target: m.id });
      return true;
    }
    if (s.tool === "string_path") {
      if (ev.key === "Enter" && path.length) {
        const ids = path;
        setPath([]);
        void run(t("electrical.creatingString"), { command_type: "create_string", parameters: { module_instance_ids: ids, mppt_instance_id: s.target } });
        return true;
      }
      if (ev.key === "Backspace" && path.length) {
        setPath((p) => p.slice(0, -1));
        return true;
      }
    }
    if (s.tool === "move_module" && picked && (ev.key === "Delete" || ev.key === "Backspace")) {
      const id = picked;
      setPicked(null);
      void run(t("electrical.unstringingModule"), { command_type: "move_module", parameters: { module_instance_id: id, to_string_id: null, index: null } });
      return true;
    }
    if (ev.key === "Escape" && (path.length || joinFirst || picked || lasso.length || brush.length)) {
      reset();
      return true;
    }
    return false;
  };

  const selectedStrings = useMemo(() => new Set(s.selection.map((id) => stringOf.get(id)).filter(Boolean) as string[]), [s.selection, stringOf]);
  const highlighted = useMemo(() => new Set([...selectedStrings, ...brush, ...(joinFirst ? [joinFirst] : [])]), [selectedStrings, brush, joinFirst]);

  return { down, move, up, key, reset, path, lasso, highlighted, centres, stringOf, mppts, joinFirst, picked };
}
