import { ContextMenu } from "../ui/ContextMenu";
import { ViewControls } from "./ViewControls";
import { presetCamera, selectedRoof, type GeometryView, type CameraFrame } from "./viewPresets";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  BufferGeometry,
  DirectionalLight,
  Float32BufferAttribute,
  LineBasicMaterial,
  LineLoop,
  Object3D,
  GridHelper,
  HemisphereLight,
  LinearSRGBColorSpace,
  PerspectiveCamera,
  OrthographicCamera,
  Scene,
  WebGLRenderer
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { TransformControls } from "three/addons/controls/TransformControls.js";
import { engine } from "../client";
import { isExplicitField, isGeneratedField, type ExactSceneGeometry } from "../types";
import { bounds, planeZ, type Vec2 } from "../geometry";
import { useEntityEdits } from "./useEntityEdits";
import { useUI } from "../state/store";
import { NotWired } from "../ui/kit";
import { moduleLooks, tokenColor } from "./gl/colors";
import { ModuleMesh, moduleMaterial } from "./gl/modules";
import { webglAvailable } from "./gl/planRenderer";
import { buildMassing, buildExactGeometry, disposeGroup, moduleHeights } from "./gl/scene3d";
import { usePlanModules } from "./plan/usePlanModules";
import { unionBox } from "./plan/viewport";
import type { Group } from "three";

/**
 * Geometry presets: orthographic side/face cameras and a perspective orbit camera over the scene as
 * the UI holds it. Read-only, and labelled as a preview: module footprints sit
 * at roof height without tilt until the engine's 3D scene is wired (Phase 7).
 * Z is up; X east, Y north, as in the plan.
 */
export function View3D({ preset = "isometric", onCameraFrame }: {
  preset?: Exclude<GeometryView, "plan">;
  onCameraFrame?: (frame: CameraFrame) => void;
} = {}) {
  const { t } = useTranslation();
  const state = useUI((s) => ({ step: s.step, selection: s.selection, view: s.view, entities: s.entities, planViewport: s.planViewport, cameraFrame: s.cameraFrame }));
  const { modules: planModules } = usePlanModules();
  const explicitFields = useMemo(() => new Set((state.view?.bundle.scene.pv_fields ?? []).filter(isExplicitField).map(f => f.pv_field_id)), [state.view]);
  const modules = useMemo(() => planModules.filter(m => !explicitFields.has(m.fieldId)), [planModules, explicitFields]);
  const needsExact = explicitFields.size > 0 || !!state.view?.bundle.scene.obstacles.some(o => o.obstacle_type === "imported_mesh");
  const [loadedGeometry, setExact] = useState<ExactSceneGeometry | null>(null);
  const [geometryError, setGeometryError] = useState<string | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number } | null>(null);
  const projectId = state.view?.bundle.project.project_id;
  const sceneHash = state.view?.identity.scene_hash;
  const sceneRevision = state.view?.bundle.scene.revision_id;
  const exact = loadedGeometry?.source_scene_hash === sceneHash && loadedGeometry?.source_scene_revision_id === sceneRevision ? loadedGeometry : null;
  useEffect(() => {
    setExact(null); setGeometryError(null);
    if (!needsExact || !projectId) return;
    const controller = new AbortController();
    engine.sceneGeometry3d(projectId, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.source_scene_hash !== sceneHash || data.source_scene_revision_id !== sceneRevision) {
        setGeometryError(t("mesh1.changed")); return;
      }
      setExact(data);
    }).catch(error => { if (!controller.signal.aborted) setGeometryError(String(error instanceof Error ? error.message : error)); });
    return () => controller.abort();
  }, [needsExact, projectId, sceneHash, sceneRevision, t]);
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const three = useRef<{ renderer: WebGLRenderer; camera: PerspectiveCamera | OrthographicCamera; controls: OrbitControls; scene: Scene; render: () => void } | null>(null);
  const spanRef = useRef(30);
  const frameRef = useRef(state.cameraFrame);
  const [failed, setFailed] = useState(false);
  const homed = useRef<string | null>(null);
  const electrical = state.step === "electrical";
  const selected = useMemo(() => new Set(state.selection), [state.selection]);

  const surfaceOfField = useMemo(
    () =>
      new Map(
        (state.view?.bundle.scene.pv_fields ?? []).filter(isGeneratedField).map((f) => [
          f.pv_field_id,
          {
            supportSurfaceId: f.support_surface_id,
            tiltDeg: f.tilt_deg,
            azimuthDeg: f.azimuth_deg,
            mountingHeightM: state.view?.table_layout?.requests[f.pv_field_id]?.mounting_height_m
          }
        ])
      ),
    [state.view]
  );

  // Renderer, camera, controls, lights and ground: once.
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    if (!webglAvailable()) {
      setFailed(true);
      return;
    }
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({ canvas, antialias: true });
    } catch {
      setFailed(true);
      return;
    }
    renderer.outputColorSpace = LinearSRGBColorSpace;
    renderer.setClearColor(tokenColor("role-stage-bg"));
    const scene = new Scene();
    const { camera } = presetCamera(preset, { centre: [0, 0, 0], span: 30 }, 1, selectedRoof(state.entities, state.selection));
    const controls = new OrbitControls(camera, canvas);
    controls.enableDamping = false;
    controls.enableRotate = preset === "isometric";
    if (preset === "isometric") controls.maxPolarAngle = Math.PI / 2 - 0.02;
    controls.listenToKeyEvents(canvas);
    scene.add(new HemisphereLight(tokenColor("color-chalk-100"), tokenColor("color-graphite-850"), 3));
    const sun = new DirectionalLight(tokenColor("color-chalk-100"), 2.5);
    sun.position.set(-0.6, -1, 1.6);
    scene.add(sun);
    let frame = 0;
    const render = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        renderer.render(scene, camera);
      });
    };
    controls.addEventListener("change", render);
    controls.addEventListener("end", () => {
      const aspect = wrap.clientWidth / Math.max(1, wrap.clientHeight);
      const span = camera instanceof OrthographicCamera
        ? (camera.top - camera.bottom) * Math.min(aspect, 1) / camera.zoom
        : camera.position.distanceTo(controls.target) / 1.25;
      onCameraFrame?.({ centre: controls.target.toArray(), span });
    });
    const resize = () => {
      const w = wrap.clientWidth;
      const h = wrap.clientHeight;
      renderer.setPixelRatio(window.devicePixelRatio || 1);
      renderer.setSize(w, h, false);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      const aspect = w / Math.max(1, h);
      if (camera instanceof PerspectiveCamera) camera.aspect = aspect;
      else {
        const halfH = spanRef.current / 2 / Math.min(aspect, 1);
        camera.left = -halfH * aspect; camera.right = halfH * aspect;
        camera.top = halfH; camera.bottom = -halfH;
      }
      camera.updateProjectionMatrix();
      render();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    resize();
    three.current = { renderer, camera, controls, scene, render };
    return () => {
      ro.disconnect();
      cancelAnimationFrame(frame);
      controls.dispose();
      renderer.dispose();
      three.current = null;
      homed.current = null;
    };
  }, []);

  // Bounds of everything shown, for the ground grid and the home view.
  const box = useMemo(() => {
    const vis = state.entities.filter((e) => !e.hidden).map((e) => e.polygon);
    let mb = null;
    if (modules.length) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (const m of modules)
        for (const [x, y] of m.polygon) {
          if (x < minX) minX = x;
          if (y < minY) minY = y;
          if (x > maxX) maxX = x;
          if (y > maxY) maxY = y;
        }
      mb = { minX, minY, maxX, maxY };
    }
    let combined = unionBox(vis.length ? bounds(vis) : null, mb);
    if (exact?.bounds_3d) {
      const {min_xyz: lo, max_xyz: hi} = exact.bounds_3d;
      combined = unionBox(combined, {minX: lo[0], minY: lo[1], maxX: hi[0], maxY: hi[1]});
    }
    return combined ?? { minX: -15, minY: -10, maxX: 15, maxY: 10 };
  }, [state.entities, modules, exact]);

  const home = useCallback(() => {
    const th = three.current;
    if (!th) return;
    const heights = state.entities.filter(e => !e.hidden).flatMap(e => e.polygon.flatMap(p => {
      const z = planeZ(e.polygon, e.plane, p) ?? 0;
      return [z, z + (e.kind === "obstacle" ? e.height_m : 0)];
    }));
    const vertical = exact?.bounds_3d;
    const loZ = Math.min(0, ...heights, vertical?.min_xyz[2] ?? 0);
    const hiZ = Math.max(0, ...heights, vertical?.max_xyz[2] ?? 0);
    const region = state.planViewport;
    const aspect = (wrapRef.current?.clientWidth ?? 800) / Math.max(1, wrapRef.current?.clientHeight ?? 600);
    const width = region ? region.size.w / region.view.scale : box.maxX - box.minX;
    const height = region ? region.size.h / region.view.scale : box.maxY - box.minY;
    const frame = frameRef.current ?? {
      centre: [region?.view.cx ?? (box.minX + box.maxX) / 2, region?.view.cy ?? (box.minY + box.maxY) / 2, (loZ + hiZ) / 2] as [number, number, number],
      span: Math.max(width / aspect, height, (hiZ - loZ) * 1.15, 10) * Math.min(aspect, 1)
    };
    const roof = selectedRoof(state.entities, state.selection);
    if (preset === "face" && !roof) return;
    const next = presetCamera(preset, frame, aspect, roof);
    spanRef.current = frame.span;
    if (th.camera instanceof PerspectiveCamera && next.camera instanceof PerspectiveCamera) th.camera.copy(next.camera);
    if (th.camera instanceof OrthographicCamera && next.camera instanceof OrthographicCamera) {
      th.camera.copy(next.camera);
      spanRef.current = (next.camera.top - next.camera.bottom) * Math.min(aspect, 1);
    }
    th.controls.target.copy(next.target);
    th.controls.update();
    th.render();
  }, [box, exact, preset, state.entities, state.selection, state.planViewport]);

  // Massing and ground: rebuilt when entities change.
  useEffect(() => {
    const th = three.current;
    if (!th) return;
    const massing = buildMassing(state.entities);
    const span = Math.max(box.maxX - box.minX, box.maxY - box.minY, 20);
    const size = Math.ceil((span * 1.6) / 10) * 10;
    const grid = new GridHelper(size, Math.min(200, size / (size > 400 ? 50 : 5)), tokenColor("role-stage-grid"), tokenColor("role-stage-grid"));
    grid.rotation.x = Math.PI / 2;
    grid.position.set((box.minX + box.maxX) / 2, (box.minY + box.maxY) / 2, -0.01);
    th.scene.add(massing, grid);
    th.render();
    return () => {
      th.scene.remove(massing, grid);
      disposeGroup(massing);
      grid.geometry.dispose();
      (grid.material as { dispose: () => void }).dispose();
    };
  }, [state.entities, box]);

  useEffect(() => {
    const th = three.current;
    if (!th || !exact) return;
    let group: Group;
    try { group = buildExactGeometry(exact, explicitFields); }
    catch (error) { setGeometryError(String(error instanceof Error ? error.message : error)); return; }
    th.scene.add(group); th.render();
    return () => { th.scene.remove(group); disposeGroup(group); th.render(); };
  }, [exact, explicitFields]);

  // Modules: rebuilt when the layout changes, recoloured on step or selection change.
  const moduleRef = useRef<{ mesh: ModuleMesh; group: Group; material: ReturnType<typeof moduleMaterial> } | null>(null);
  useEffect(() => {
    const th = three.current;
    if (!th || !modules.length) return;
    const material = moduleMaterial();
    material.uniforms.uEdge.value = 1;
    material.uniforms.uDpr.value = window.devicePixelRatio || 1;
    material.uniforms.uHatchColor.value = tokenColor("role-stage-muted");
    material.uniforms.uSelColor.value = tokenColor("role-selection");
    material.uniforms.uHatchBg.value = tokenColor("role-stage-surface");
    const mesh = new ModuleMesh(modules, material, moduleHeights(state.entities, surfaceOfField));
    th.scene.add(mesh.group);
    moduleRef.current = { mesh, group: mesh.group, material };
    return () => {
      th.scene.remove(mesh.group);
      mesh.dispose();
      material.dispose();
      moduleRef.current = null;
    };
  }, [modules, state.entities, surfaceOfField]);

  useEffect(() => {
    const th = three.current;
    const m = moduleRef.current;
    if (!th || !m) return;
    const look = moduleLooks(electrical);
    m.material.uniforms.uEdgeColor.value = tokenColor("role-stage-module");
    m.material.uniforms.uEdgeOwnHue.value = electrical ? 1 : 0;
    m.mesh.setLooks((x) => look(x, selected.has(x.id)));
    th.render();
  }, [electrical, selected, modules, state.entities, surfaceOfField]);

  // Gizmo on the selected entity: drag the arrows to move it (X, Y) or raise and lower it (Z).
  // Typed equivalents are in the inspector (ΔX, ΔY, elevation).
  const { commitMove, raise } = useEntityEdits();
  const target = state.entities.find((e) => state.selection.includes(e.id) && !e.hidden) ?? null;
  const editRef = useRef({ commitMove, raise });
  editRef.current = { commitMove, raise };
  useEffect(() => {
    const th = three.current;
    const canvas = canvasRef.current;
    if (!th || !canvas || !target) return;
    const zOf = (p: Vec2) => planeZ(target.polygon, target.plane, p) ?? 0;
    const top = Math.max(...target.polygon.map(zOf)) + (target.kind === "obstacle" ? target.height_m : 0);
    const b = bounds([target.polygon]);
    const centre: Vec2 = [(b.minX + b.maxX) / 2, (b.minY + b.maxY) / 2];
    const proxy = new Object3D();
    proxy.position.set(centre[0], centre[1], top);
    // The selection outline rides on the proxy, so it follows the drag.
    const outline = new LineLoop(
      new BufferGeometry().setAttribute("position", new Float32BufferAttribute(target.polygon.flatMap(([x, y]) => [x - centre[0], y - centre[1], 0.02]), 3)),
      new LineBasicMaterial({ color: tokenColor("role-selection") })
    );
    proxy.add(outline);
    th.scene.add(proxy);
    const gizmo = new TransformControls(th.camera, canvas);
    gizmo.setMode("translate");
    gizmo.setSpace("world");
    gizmo.setSize(0.8);
    gizmo.enabled = !target.locked;
    gizmo.attach(proxy);
    const helper = gizmo.getHelper();
    th.scene.add(helper);
    const start = proxy.position.clone();
    gizmo.addEventListener("change", th.render);
    gizmo.addEventListener("dragging-changed", async (ev) => {
      th.controls.enabled = !ev.value;
      if (ev.value) return;
      const d = proxy.position.clone().sub(start);
      proxy.position.copy(start);
      th.render();
      if (Math.abs(d.x) > 1e-6 || Math.abs(d.y) > 1e-6) {
        const moved = await editRef.current.commitMove(target, [d.x, d.y]);
        if (target.source === "engine" && !moved) return;
      }
      if (Math.abs(d.z) > 1e-6) await editRef.current.raise(target, d.z);
    });
    th.render();
    return () => {
      gizmo.detach();
      gizmo.dispose();
      th.scene.remove(helper, proxy);
      outline.geometry.dispose();
      (outline.material as LineBasicMaterial).dispose();
      th.controls.enabled = true;
      th.render();
    };
  }, [target]);

  // Home view on first show and when the project changes.
  useEffect(() => {
    const key = `${state.view?.bundle.project.project_id ?? ""}:${modules.length}:${exact?.source_scene_hash ?? ""}:${preset === "face" ? selectedRoof(state.entities, state.selection)?.id : ""}`;
    if (homed.current === key) return;
    homed.current = key;
    home();
  }, [state.view, modules.length, home]);

  return (
    <div className="view3d" ref={wrapRef} onContextMenu={e => {
      e.preventDefault();
      const rect = e.currentTarget.getBoundingClientRect();
      setMenu({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    }}>
      {menu && <ContextMenu items={[]} at={menu}
        box={{ w: wrapRef.current?.clientWidth ?? 800, h: wrapRef.current?.clientHeight ?? 600 }}
        label={t("stage.views")} onSelect={() => {}} onClose={restore => { setMenu(null); if (restore) canvasRef.current?.focus(); }}
        submenu={{ label: t("stage.view"), content: close => <ViewControls menu onClose={() => { close(); setMenu(null); canvasRef.current?.focus(); }} /> }} /> }
      <canvas ref={canvasRef} className="view3d__canvas" tabIndex={0} aria-label={t("view3d.ariaLabel")} />
      <div className="view3d__bar">
        <span className="view3d__tag">{t("view3d.preview")}</span>
        <NotWired id="view3d" compact />
        <span className="view3d__note">{t("view3d.previewNote")}</span>
        <button type="button" className="btn btn--sm btn--stage" onClick={home}>
          {t("view3d.reset")}
        </button>
      </div>
      {needsExact && <p className="view3d__note" role={geometryError ? "alert" : "status"}>
        {geometryError ? t("mesh1.error", {message: geometryError}) : exact ? t("mesh1.readOnly") : t("mesh1.loading")}
      </p>}
      {failed && (
        <p className="plan__nogl" role="alert">
          {t("plan.noWebgl")}
        </p>
      )}
    </div>
  );
}
