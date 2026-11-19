import { expect, test } from "@playwright/test";
import fs from "node:fs";

interface PerfHook { modules: number; frames(): number; lastFrameMs(): number; pickBench(n: number): { mean: number; max: number; hits: number } }
for (const count of [100_000, 200_000]) test(`${count} synthetic modules: indexed picking and measured interactive frames`, async ({ page }, info) => {
  const errors: string[] = []; page.on("pageerror", (e) => errors.push(e.message));
  await page.route("https://nominatim.openstreetmap.org/**", (r) => r.abort());
  const started = Date.now();
  await page.goto(`/?synthetic=${count}&perf`); await page.locator(".start__row").first().click();
  await page.keyboard.press("Alt+6"); await page.keyboard.press("Alt+Backslash");
  await page.waitForFunction((n) => {
    const p = (window as unknown as { __rawibumiPerf?: PerfHook }).__rawibumiPerf;
    return p?.modules === n && p.frames() > 0;
  }, count);
  const readyMs = Date.now() - started;
  const metrics = await page.evaluate(async () => {
    const perf = (window as unknown as { __rawibumiPerf: PerfHook }).__rawibumiPerf;
    const el = document.querySelector<HTMLCanvasElement>(".plan__canvas")!;
    const rect = el.getBoundingClientRect();
    perf.pickBench(50); // warm the picking path before timing it
    const picks = perf.pickBench(1000);
    const start = performance.now(), frames = perf.frames();
    let ticks = 0;
    const frameMs: number[] = [];
    await new Promise<void>((resolve) => {
      const step = () => {
        if (performance.now() - start > 3000) return resolve();
        el.dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, clientX: rect.x + rect.width / 2, clientY: rect.y + rect.height / 2, deltaY: ticks++ % 2 ? 2 : -2 }));
        frameMs.push(perf.lastFrameMs()); requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
    const elapsedMs = performance.now() - start;
    const gl = document.querySelectorAll<HTMLCanvasElement>(".plan__layer")[1].getContext("webgl2")!;
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return { modules: perf.modules, picks, submittedFrames: perf.frames() - frames, elapsedMs,
      fps: (perf.frames() - frames) * 1000 / elapsedMs, maxSubmitMs: Math.max(...frameMs),
      gpu: ext ? String(gl.getParameter(ext.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER)), userAgent: navigator.userAgent };
  });
  const canvas = page.locator(".plan__canvas");
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down({ button: "middle" });
  const pan = await page.evaluate(async () => {
    const perf = (window as unknown as { __rawibumiPerf: PerfHook }).__rawibumiPerf;
    const el = document.querySelector<HTMLCanvasElement>(".plan__canvas")!, rect = el.getBoundingClientRect();
    const start = performance.now(), frames = perf.frames(); let ticks = 0;
    await new Promise<void>((resolve) => {
      const move = () => {
        if (performance.now() - start > 3000) return resolve();
        el.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, pointerId: 1, pointerType: "mouse", buttons: 4,
          clientX: rect.x + rect.width / 2 + Math.sin(ticks++ / 12) * 60, clientY: rect.y + rect.height / 2 }));
        requestAnimationFrame(move);
      }; requestAnimationFrame(move);
    });
    const elapsedMs = performance.now() - start;
    return { submittedFrames: perf.frames() - frames, elapsedMs, fps: (perf.frames() - frames) * 1000 / elapsedMs };
  });
  await page.mouse.up({ button: "middle" });
  const record = { ...metrics, pan, readyMs, errors, method: "3 seconds each of wheel zoom and middle-button drag at requestAnimationFrame cadence; fps counts rendered submissions, not idle frames or GPU timer samples. Synthetic renderer only, no engine fill or payload claim." };
  fs.mkdirSync("../../evidence", { recursive: true });
  fs.writeFileSync(`../../evidence/f8-scale-${count}.json`, JSON.stringify(record, null, 2) + "\n");
  await info.attach("scale measurements", { body: JSON.stringify(record, null, 2), contentType: "application/json" });
  expect(metrics.modules).toBe(count); expect(metrics.picks.hits).toBeGreaterThan(0);
  expect(metrics.picks.max).toBeLessThan(16); expect(metrics.submittedFrames).toBeGreaterThan(0);
  expect(metrics.fps).toBeGreaterThanOrEqual(30); expect(pan.fps).toBeGreaterThanOrEqual(30);
  expect(errors).toEqual([]);
});
