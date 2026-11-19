# Phase 6.9B closure: explicit browser execution

The browser can explicitly launch the validated detailed electrical-shading
path and view its persisted attribution results. This change is orchestration
and presentation only. Phase 6.9A physical kernels, U/N/B/S/C/T kernels,
attribution-energy aggregation, downstream PCC physics and legacy dispatch
are unchanged. No commit was made.

## Controls and request

Simulate defaults to **Existing geometry execution (legacy)**. The engineer can
select **Detailed electrical shading · level_2_bypass_substring** and choose
`fail_closed` (default) or `explicit_lower_fidelity`. Controls are disabled while
an operation is in progress; detailed execution is unavailable in demo mode.
Changing a choice invalidates the displayed readiness and requests fresh
backend preflight. Committed project-view changes also refresh preflight,
including pinned asset/selection changes without a project revision increment.
Stale readiness responses cannot enable the new selection.

Legacy browser requests retain their existing `{}` body. Bodyless requests also
retain the same endpoint behavior. The detailed POST envelope is:

```json
{
  "electrical_shading_configuration": {
    "requested_fidelity": "level_2_bypass_substring",
    "fallback_policy": "fail_closed"
  }
}
```

`explicit_lower_fidelity` is sent only when selected by the engineer. Unknown
request fields, unsupported requested levels and invalid policies are rejected
by the API. The backend adds these two engineering choices to the existing
ElectricalShadingConfiguration contract for the supported runtime. It retains
the browser study's existing models, losses, timestep, geometry settings and
output configuration. The project-held module selections, topology, executable
parameterization, evidence and source assets are frozen into the canonical
revision store; the launch does not rewrite them. The canonical dispatcher
requires their fidelity/policy to match the request. No frontend runtime-support
or scientific-capability computation is introduced.

## Readiness and fallback

GET `/api/projects/{project_id}/execution-readiness` remains unchanged without
query parameters. Detailed preflight uses `requested_fidelity` and
`fallback_policy` query parameters matching the launch. The backend creates a
private coherent electrical snapshot, checks engineering validation, freezes
detailed inputs and invokes the existing detailed dispatch resolver without
numerical execution or persistence.

The backend reports `ready_detailed`, `blocked_detailed_inputs`,
`unsupported_configuration`, or `explicit_fallback_available`. Legacy readiness
retains its existing execution class. Findings are displayed verbatim, including
engineering rule IDs and actionable messages. Missing weather has its existing
weather-revision finding. These are preflight results: interval-dependent
numerical/downstream support still remains authoritative at execution.

Launch rechecks preflight server-side. A blocked request returns 422 without
executing or persisting a legacy run. Integrity/schema/selection-policy mismatch
failures cannot fall back. The explicit lower-fidelity policy can permit the
existing canonical fallback only when legacy readiness also passes. Actual
fallback identity and reason come from the canonical dispatcher and persisted
package, never from frontend inference.

## End-to-end and reopen

Project → select detailed execution → backend preflight → POST study → frozen
canonical SimulationRun → GET `/runs/{run_id}/result` → verified project view →
Results → Detailed Electrical Shading.

Successful launch selects the newly completed run in Results even if an older
run was selected earlier. Execution identity is shown independently of energy
summary availability: requested/resolved fidelity, fallback policy, whether
fallback occurred and backend reason. The attribution section uses the existing
persisted energy summary and period tables. Legacy runs have no fabricated
detailed section. A fallback run can show execution identity with no attribution
summary.

Reload/reopen retrieves the saved project and verified package fields. It does
not POST another study or recompute attribution. The read-only result endpoint
continues to reject package tampering. Diagnostic artifacts remain opt-in;
the browser launch does not enable them and presentation does not fetch curves.

## Files changed

- `apps/api/server.py`: optional strict detailed launch envelope and readiness query.
- `apps/api/study.py`: backend detailed preflight, existing electrical contract,
  frozen selection plumbing into the unchanged validated canonical dispatcher.
- `apps/web/src/api.ts`: optional launch/readiness request and persisted result read.
- `apps/web/src/types.ts`: launch envelope and persisted fallback identity types.
- `apps/web/src/panels/SimulatePanel.tsx`: explicit execution/policy controls,
  backend readiness, persisted-result read and completed-run selection.
- `apps/web/src/results/DetailedElectricalShading.tsx`: independent execution identity display.
- `apps/web/src/results/ResultsView.tsx`: identity including fallback without summary.
- `apps/web/tests/detailed-launch.mjs`: actual Chromium production UI/API workflow.
- `tests/browser_phase69b_server.py`: isolated controlled browser fixture server.
- `tests/unit/test_phase69b_browser_launch.py`: real HTTP launch, dispatch,
  blocking, fallback, dark rendering, reopen and tamper checks.
- `docs/phase69b-browser-closure.md`: closure checkpoint.

## Validation

Validation completed on 2026-10-04:

- Frontend typecheck: passed (`npm run typecheck --prefix apps/web`).
- Frontend production build: passed (`npm run build --prefix apps/web`);
  the existing large-bundle warning remains.
- Actual Chromium production browser/API workflow: passed, including legacy,
  blocked, detailed dark, detailed daylight, attribution navigation, persisted
  reload/reopen and explicit fallback.
- Focused browser-launch API tests: **6 passed in 7.83 seconds**.
- Relevant Phase 6.9A/6.9B, result exposure, loss-energy, inverter and canonical
  persistence regressions: **148 passed in 2528.32 seconds**.
- Complete Python suite: **835 passed in 2782.76 seconds**.
- No failures or skips in the final Python suites; each retains one existing
  Starlette dependency deprecation warning.
- `git diff --check`: passed. No commit was made.

Final logs: `/tmp/rawibumi-closure-typecheck.log`,
`/tmp/rawibumi-closure-build.log`, `/tmp/rawibumi-closure-browser-final.log`,
`/tmp/rawibumi-closure-focused-final.log`, `/tmp/rawibumi-closure-relevant.log`
and `/tmp/rawibumi-closure-full.log`. Earlier sandbox-stalled, exploratory and
interrupted attempts are excluded from these final results. Controlled local
browser servers were stopped after verification.

Chromium uses the production build and a real local FastAPI fixture server.
The browser tests assert unchanged legacy request/default, no detailed result
on legacy runs, blocked detailed launch, exact detailed payload, real detailed
dark execution, attribution navigation, exact persisted identity after reopen
and reload, no extra simulation requests, result endpoint equality and explicit
fallback display. An additional daylight run verifies positive energy, detailed
`pcc_complete` identity, applicable attribution coverage and diagnostics remaining
disabled. No browser physics responses are mocked. API tests also forbid
simulation and energy aggregation during reopen and reject tampered packages.
Existing result-exposure tests retain frontend no-recomputation checks.

The browser runner accepts a JSON file with `origin`, `legacy`, `detailed`,
`blocked` and `fallback` project IDs, plus an optional `daylight` project ID. Start its controlled server with
`.venv/bin/python -m tests.browser_phase69b_server`, then run
`node apps/web/tests/detailed-launch.mjs /tmp/rawibumi-closure-browser.json`
with Playwright/Chromium available. `RAWIBUMI_PLAYWRIGHT_MODULE` can point to an
external Playwright installation. Temporary browser tools/libraries used for
this checkpoint live under `/tmp` and are not project dependencies.

## Remaining Phase 6.9 limitations

The existing detailed fixed-tilt domain, sampled-MPP precision, bounded reverse
bias support, evidence-bound module quality, module-temperature assumptions and
tracker/current-limit limitations remain. Preflight cannot guarantee all
interval-dependent support. Detailed input authoring/import remains in the
existing project contracts; launch controls do not synthesize missing evidence.
Requested policy must agree with already frozen engineering selections.
Coverage describes simulated observations, not calendar completeness.
Historical packages without energy summaries cannot display attribution energy.
There is no per-MPPT energy breakdown, arbitrary period splitting, annual
optimization, annual acceleration or PCC counterfactual attribution.
