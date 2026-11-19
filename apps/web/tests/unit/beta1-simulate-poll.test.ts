import { afterEach, expect, it, vi } from "vitest";
import { api } from "../../src/api";
import { ApiError } from "../../src/types";

// BETA1: a run that outlasts the server's wait answers 202 with a job; the client polls until the run record (or the
// run's own error) arrives, so Run behaves as before behind a proxy's per-request limit.
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

it("polls a 202 job to the run record", async () => {
  vi.useFakeTimers();
  const calls: string[] = [];
  const replies = [json(202, { job_id: "j1", status: "running" }), json(202, { job_id: "j1", status: "running" }),
    json(200, { simulation_run_id: "run-1", status: "completed" })];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => { calls.push(`${init?.method ?? "GET"} ${url}`); return replies.shift()!; }));
  const run = api.simulate("p 1");
  await vi.advanceTimersByTimeAsync(4100);
  await expect(run).resolves.toMatchObject({ simulation_run_id: "run-1" });
  expect(calls).toEqual(["POST /api/projects/p%201/simulate", "GET /api/projects/p%201/simulate/jobs/j1", "GET /api/projects/p%201/simulate/jobs/j1"]);
});

it("a direct 200 returns at once, and a failed job raises the run's error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(200, { simulation_run_id: "run-2", status: "completed" })));
  await expect(api.simulate("p")).resolves.toMatchObject({ simulation_run_id: "run-2" });
  vi.useFakeTimers();
  const replies = [json(202, { job_id: "j2", status: "running" }), json(422, { detail: "simulation execution preflight failed: reason" })];
  vi.stubGlobal("fetch", vi.fn(async () => replies.shift()!));
  const run = api.simulate("p");
  const caught = run.catch((e) => e);
  await vi.advanceTimersByTimeAsync(2100);
  const error = await caught;
  expect(error).toBeInstanceOf(ApiError);
  expect((error as ApiError).status).toBe(422);
});
