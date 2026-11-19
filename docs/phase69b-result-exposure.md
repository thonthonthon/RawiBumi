# Phase 6.9B increment 3: persisted result exposure

The browser/API presentation reads completed run packages. Phase 6.9A physical
execution, U/N/B/S/C/T kernels, attribution-energy aggregation, actual loss
ledgers and frozen legacy shading field meanings are unchanged. No commit,
annual acceleration, annual extrapolation or PCC counterfactual propagation is
included.

## API and persistence

The existing browser SimulationRun record, POST simulate response, GET runs
response and project view can include optional `detailed_electrical_shading`:

- `package_manifest_sha256`: completed package identity bound to saved runs.
- `execution_identity`: persisted requested/resolved fidelity, runtime status,
  fallback/failure information, limitations and execution hashes.
- `selected_mppt_result`, `dc_attribution_result`, `attribution_energy_result`:
  artifact name, availability status, model ID where recorded, SHA-256 and
  unavailable reason codes.
- `attribution_energy_summary`: the exact persisted
  DetailedDCAttributionEnergySummary payload, including model/version identities,
  run/daily/monthly periods, channel coverage/reasons, scope and interval audit.
- `diagnostic_artifacts`: separate availability and references only; no curves.

GET `/api/projects/{project_id}/runs/{run_id}/result` also exposes an existing
canonical package directly without launching or altering execution. It requires
an existing project and verifies package completion and identity before returning
results. This increment does not add a new detailed execution request or change
the browser's existing Phase-5 launch envelope.

Project/run reads hydrate from verified packages, replacing cached presentation
fields with persisted authority. Reopening retains exact values and rejects a
tampered package. Detailed cached records without their package fail closed.
Historical legacy records predating packages retain their response shape;
bodyless simulation requests remain unchanged. Detailed historical packages
without an energy-summary reference return null summary rather than zeros.

The backend validates attribution/energy records during persistence and performs
full scientific package verification at completion. Both paths remain unchanged. The API read boundary verifies completion,
manifested bytes, compact payload/reference hashes, execution and source identity,
interval-ledger equality and agreement with the existing compact observed total.
These are comparisons of stored values, with no integration, energy aggregation
or counterfactual execution. Cached run references must match package hashes on
reopening. Hash verification establishes consistency, not external authentication.
Normal presentation reads compact JSON only; diagnostic files are hashed as bytes
without loading their curve JSON. References are names/hashes, not automatic
download links.

## Results presentation

A compact engineering table is separate from production charts and the actual
loss waterfall. It appears only when a persisted attribution-energy summary
exists, including runs with valid DC attribution but no actual energy summary.
Execution status also appears independently of attribution availability.

Four explicit accounting rows distinguish geometric shading, explanatory detailed
DC attribution, downstream DC/inverter losses and actual PCC/energy results.
There is no combined DC/PCC total or second subtraction from production.

A selector lists only the backend's run-total, daily and monthly periods, using
persisted period keys and observed timestamps. No JavaScript month grouping,
missing-month filling, integration, attribution calculation, extrapolation or
annual performance claim is performed.

Each of six channels shows completeness, observed signed energy, available versus
applicable simulated seconds, fraction, not-applicable/unavailable duration and
unavailable reason codes. Complete means complete attribution over applicable
observed simulation coverage, not a whole calendar month or year. Partial values
are explicitly observed subtotals. Unavailable and not-applicable rows show no
known energy. Dark duration never appears as failed applicable coverage.

Positive values are labelled reduction; negative values are labelled recovery,
including bypass interaction. Nonzero values below 0.001 Wh display as signed
`<0.001 Wh`, with the full raw value in the cell tooltip/data attribute and raw
persisted summary disclosure. Larger magnitudes use Wh/kWh. Numeric presentation
does not mutate underlying results.

Collapsible disclosures show model/version, compact references/hashes,
limitations/failures, optional diagnostic references and raw persisted summary.
The page does not fetch or render IV curves, offer automatic recommendations or
modify engineering selections.

## Verification

Focused coverage exercises actual React server rendering and verified API
packages: signed reduction/recovery, tiny values, all completeness states,
dark periods, reason codes, exact daily/monthly/run values, unchanged raw inputs,
absence of client integration, actual-energy isolation, opt-in diagnostic
references, saved/reopened project equality, tamper rejection and legacy absence.
Browser automation is not installed in this environment; rendered HTML examples
are written to `/tmp/rawibumi-inc3-{signed,partial,unavailable,dark}.html`.

Validation completed on 2026-10-04:

- Frontend typecheck: passed (`npm run typecheck --prefix apps/web`).
- Frontend build: passed (`npm run build --prefix apps/web`); existing large-bundle warning remains.
- Final focused API/rendering/energy tests: **14 passed in 190.95 seconds**.
- Relevant Phase 6.9A/6.9B, loss-energy and inverter regressions: **125 passed in 2359.67 seconds**.
- Complete Python suite: **829 passed in 2489.36 seconds**, no failures or skips.
- Python suites retain one existing Starlette dependency deprecation warning.
- `git diff --check`: passed. No commit was made.

The API tests forbid the counterfactual entry point, energy aggregator,
`_assemble`, `_from_source` and the full scientific package verifier during
presentation. Tampered energy remains rejected after refreshing the outer
manifest. Saved completion hashes also bind optional diagnostic bytes.
Legacy absent/null fields and bodyless requests remain compatible.

Logs: `/tmp/rawibumi-phase69b-inc3-typecheck.log`,
`/tmp/rawibumi-phase69b-inc3-build.log`,
`/tmp/rawibumi-phase69b-inc3-focused-final.log`,
`/tmp/rawibumi-phase69b-inc3-relevant.log`, and
`/tmp/rawibumi-phase69b-inc3-full.log`. Earlier sandbox-stalled attempts are
excluded from these final results. Prior checkpoint logs were preserved.

## Remaining limitations

The existing detailed physical domain, sampled-MPP precision, bounded reverse
bias support, module-temperature assumptions and tracker limitations remain.
Coverage describes simulated observations, not calendar completeness. Reporting
remains aggregated over applicable MPPT scopes. There is no per-MPPT energy
breakdown, arbitrary period splitting, PCC counterfactual attribution or annual
optimization. Historical packages lacking attribution energy cannot show the
energy section. Existing browser launch behavior remains Phase 5; this work
exposes persisted detailed execution rather than adding engineering controls.


## Changed files

- `apps/api/detailed_results.py`: display-only package integrity and compact result projection.
- `apps/api/study.py`: optional result exposure, run hydration and persisted-result reads.
- `apps/api/service.py`: project-view result hydration after reopening.
- `apps/api/server.py`: read-only persisted run-result endpoint.
- `apps/web/src/types.ts`: optional detailed result/coverage contracts.
- `apps/web/src/results/DetailedElectricalShading.tsx`: signed values, coverage, periods and disclosures.
- `apps/web/src/results/ResultsView.tsx`: separate result section and accounting boundaries.
- `apps/web/tests/detailed-results.mjs`: actual React rendering assertions.
- `tests/unit/test_phase69b_result_exposure.py`: verified API, persistence, tamper, legacy and rendering tests.
- `docs/phase69b-result-exposure.md`: implementation and validation checkpoint.
