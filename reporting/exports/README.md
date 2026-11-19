# Numerical CSV export (Phase 7, self-hosted Free)

`GET /api/projects/{project_id}/runs/{run_id}/exports/schema` returns the fields
verified as exportable for a registered completed run. `POST` to the same path
without `/schema` accepts exactly:

```json
{"format":"csv","resolution":"hourly","level":"project","columns":["pcc_power_w"]}
```

The response is `application/zip`, with `timeseries.csv` followed by
`export-manifest.json`. Unknown request properties, duplicate/empty column lists,
unsupported options, and unavailable column IDs are rejected. Timestamp and
interval duration are always included; output columns follow persisted dataset
order, regardless of selection order. Unknown projects return 404; unknown runs,
invalid source packages, and unsupported selections return descriptive 422 errors.

## Source and verification

The project store validates project IDs. The study service requires the run ID
in that project's saved run list and resolves it under that project's run storage,
with containment and symlink checks. Only `completed` and
`completed_with_warnings` runs are eligible.

The reader reuses `engine.simulation.artifacts.verify_run_package` and canonical
output-schema validation, not a replacement package verifier. The existing
completion manifest binds `simulation-run.json`, `reproducibility-manifest.json`,
and `timeseries.parquet` by byte hash/size. Export additionally checks the saved
input hash (and saved package digest when present), run/package identities,
ResultDatasetReference URI containment, byte hash/size, ordered columns and counts,
and the canonical `dataframe_logical_sha256` of the decoded dataset. Both embedded
and persisted reproducibility manifests must agree with the dataset identity.
The Parquet reader consumes the exact byte snapshot checked against those hashes.
No simulation, chart reconstruction, interpolation, resampling, annualization, or
source-directory writes occur. The existing canonical verifier may perform its
normal scientific consistency checks for detailed artifacts.

PyArrow is already declared in `requirements-validation.txt` (`pyarrow>=18,<23`);
pandas is already used throughout the engine and provided through the existing
pvlib dependency. `apps/api/requirements.txt` contains only the HTTP stack. The
existing installation must include both manifests, as for simulation persistence.
No dependency changes are required by this feature.

## Scientific surface

Fields are an explicit subset of `build_standard_timeseries` in
`engine/simulation/artifacts.py`, filtered by actual persisted column availability.
The schema supplies source IDs, labels and units. It does not derive units from
names or expose arbitrary additional Parquet fields.

- `timestamp`: interval start, serialized with `Timestamp.isoformat()` and its
  stored timezone offset; `interval_seconds`: interval duration in seconds.
- GHI, DNI, DHI, beam/sky/ground/global POA, unshaded global POA and effective
  irradiance: W/m², as stored. Detailed runs may contain only a subset; their
  POA/effective irradiance and cell temperature use the engine's module surface
  area weighting, recorded in the source model manifest.
- Ambient, module and cell temperature: °C; wind speed: m/s.
- Gross DC: raw array MPP power; net DC: array virtual MPP power after DC wiring;
  inverter input: DC to converter; inverter output: net inverter AC; PCC: the
  existing net inverter AC identity boundary. All power is W, never relabeled kW.
  Load, zero-export curtailment, AC wiring and transformer losses are not implied
  by the PCC boundary (`engine/losses/ledger.py`).
- Interval energy: stored PCC energy in Wh.

Hourly eligibility requires nonempty timezone-aware timestamp data, every stored
interval equal to 3600 seconds, strictly increasing unique timestamps at exactly
one-hour cadence, and agreeing simulation/working-resolution metadata. A single
row is eligible only when its stored duration and source resolution are hourly.
Native weather resolution can differ and is reported without transforming rows.
Timezone metadata must agree with stored offsets at each instant (Parquet may
restore a fixed offset under an equivalent timezone name). Exported timestamps
are never localized or converted, including at offset changes. Unsupported resolutions
are rejected, not converted. Per-inverter, per-MPPT/string, load, curtailment, and
other fields outside the explicit allowlist are unavailable.

## S15: Parquet and the full deliverable

The request may add `formats` (`["csv"]`, `["parquet"]` or both; default `["csv"]`)
and `deliverable` (default false). **Without them the ZIP is byte-for-byte the CSV
export above.** Parquet (`timeseries.parquet`, zstd) holds the same selected
columns, in the same order, with the stored timestamps. With `deliverable: true`
the ZIP also carries:

- `monthly.csv`: one row per site-local month, with energy (kWh), unshaded POA and
  GHI irradiation (kWh/m²), specific yield and PR, plus one `loss_<channel>_kwh`
  column per staged-ledger channel whose hourly column is stored. Months come from
  the engine's own `aggregate_interval_quantities`. Energy and every loss channel
  are reconciled against the run's `summary-result.json` (1e-6 relative); a
  mismatch refuses the export.
- `summary-result.json`, `design-validation-report.json` and
  `validation-findings.json`, byte copies from the verified package;
- `run-record.json`: the project's saved run record, including the launch
  `readiness_warnings`.

The manifest then adds `formats`, `files` (path, SHA-256, byte size and
description per file) and `deliverable` (the monthly columns and units, kWp and
PR bases, loss channels, and the readiness warnings, or "not recorded for this
run"). The file is `RawiBumi_results_bundle.zip`.

`GET /api/projects/{id}/runs/{run_id}/timeseries` serves the same monthly table
plus site-local day × 24-hour matrices: AC power (kW), POA, GHI, and cell and
ambient temperature. It uses the same verified loader and refusals.

## Serialization and provenance

The UTF-8 CSV uses source column IDs, comma delimiters, standard CSV quoting and
LF line endings. Numeric values use 17 significant decimal digits, with integers
preserved exactly. Missing numeric values (null/NaN) produce empty CSV fields,
never zero. Infinite values and missing timestamps/durations are rejected.
Current canonical standard-result construction rejects nonfinite measurements;
the reader's explicit missing-value rule also covers verified persisted nullable
numeric columns. No measurements are synthesized to fill them.

The manifest records project/run IDs, source byte and logical hashes, package
digest, row count, selected columns/units, timestamp semantics/timezone,
source interval and weather resolutions, revision IDs, component/model manifests,
engine version and detailed execution identity where available. It contains no
wall-clock generation time. ZIP entries use fixed order, date, permissions and
uncompressed storage, so identical requests against the same immutable source
produce identical CSV, manifest and ZIP bytes. The internal canonical dataset reference retains its local file URI for
source verification, but the downloadable manifest omits that URI.
The export manifest instead records source hashes, CSV SHA-256 and byte size.
Relocating immutable packages still requires their references to be valid. Exports are built in memory; this phase
does not add streaming or claim annual/live-memory qualification.

## Entitlements and launch boundary

The screen uses the existing `can("core.export.csv-basic")` self-hosted Free
entitlement. The API has no server-side identity or hosted entitlement enforcement.
A frontend gate is not security. **Phase 8 must enforce hosted Guest denial
server-side before public launch.** This Phase 7 task does not implement or claim
that hosted restriction, and introduces no identity headers, cookies or login.
The numerical screen calls the real export API; demo chart data is never exported.
Its dedicated persisted-run HTTP transport is exposed through `src/client.ts`,
preserving the screen import boundary without adding fake numerical data
to `EngineAdapter` or the demo engine. Hosted authorization remains Phase 8.

## Authored verification (not executed in this implementation pass)

- `tests/unit/test_phase7_csv_export.py`: bounded synthetic persisted packages,
  numerical parity, intervals/offsets, deterministic ZIP content, malformed
  requests, containment, corruption/reference failures and source immutability.
- `apps/web/tests/unit/export-api.test.ts`: ZIP blobs and API error messages.
- `apps/web/tests/e2e/export-download.spec.ts`: schema-driven UI states, selection,
  retries and browser downloads using mocked routes in the existing demo shell.

No tests, builds, API servers, simulations, annual resource tests or live-memory
qualification were run in the implementation pass. An independent gate must
execute the authored tests and the existing applicable regression checks.

## Verified full report PDF (RPT2b-2)

`BrowserStudyService.native_pdf_document` authorizes registered completed runs by project/run identity,
re-verifies their immutable package, summary, reproducibility and dataset, and obtains `report_snapshot`.
The design fingerprint must match the run; an earlier design is refused. No export re-simulates,
resamples, annualises or writes project/run data. The retired B1 display projection is no longer used.

The browser and the Node bundle use the same `report/render.ts::renderReport` and template. Charts share
ECharts SSR and the pure parser of `ui/tokens.css`; the SLD is the same React component as the workstation.
Content parity means identical text, values, sections and chart series, not SVG layout coordinates or IDs.
The cover says **Results computed / Hasil dihitung** using the recorded completion time in the site's timezone.
Partial runs say **simulated period**; annual Pxx, annual specific yield and annual eligibility checks are
not applicable. Energy/monthly/ledger reconciliation and other integrity checks still block errors.
The existing 365-day annual behavior stays intact; recorded leap years are supported without annualisation.

### Delivery and deployment

- `GET /api/reporting/native-pdf/capability` retains exactly `{enabled,format:"pdf",text_based:true,locales:["en","id"]}`.
- `POST /api/projects/{project_id}/runs/{run_id}/exports/native-pdf` accepts only `locale` (en/id, default en) and
  optional `plan_figure_png` (PNG data URL). No client snapshot, HTML, worker path or data is accepted.
- The existing GET endpoint remains a compatibility alias with no figure. Both return an application/pdf attachment
  named `RawiBumi_verified_report.pdf`, no-store/nosniff, and the existing fixed sanitized failure statuses.
- The deployment gate is unchanged: Community self-hosted only; an explicit `RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED=1`
  enables it, other explicit values disable it; without the flag it follows the configured absolute existing
  `RAWIBUMI_PDF_NODE`, `RAWIBUMI_PDF_RUNTIME_ROOT`, `RAWIBUMI_PDF_CHROMIUM_EXECUTABLE` paths. Hosted editions stay off.
  The gate is checked before request body/locale validation. Capability does not certify runtime health or provide
  user authentication. Existing externally enforced authorization and resource/admission controls remain necessary.

The figure is illustrative, drawn by the browser and unverified, labelled in both locales. Python checks PNG
signature, strict base64, <=4 MiB and <=4096 by 4096, Pillow verify then reload, no animation, complete chunks and
no trailing/polyglot bytes. Fresh RGBA pixel re-encoding strips metadata; only those bytes reach Node. Without
it, the plan chapter explicitly says **Plan figure not supplied**. No raster-report renderer is restored.

### Build and isolation

`cd apps/web && npm run build` builds the web app then the CommonJS Node-target report library at
`dist/report-render/report-render.cjs`. Provision that artifact beneath `RAWIBUMI_PDF_RUNTIME_ROOT` alongside
pinned Playwright 1.64.1 and its matching Chromium; no package download/runtime fallback occurs during export.
The Node entry imports no store, demo, imagery, panes, UI-kit or browser storage; fonts/tokens/report CSS are
embedded at build time. The worker checks the bundle resolves inside its runtime root.

Python verifies the snapshot SHA over `canonical_json_bytes` excluding `snapshot_sha256`; it passes that exact
JSON text plus digest. Node hashes the original UTF-8 bytes, never a JS reserialization, before parsing/rendering.
Integers beyond ±(2^53−1) are refused, including integer source columns before conversion to native-series floats.

Chromium still requires its sandbox, JavaScript off, offline mode, service workers blocked and downloads off.
Every resource request is aborted and makes rendering fail. All required font/image/SVG resources are inline.
No shell invocation, arbitrary navigation, source-file access, pageRanges or content truncation is introduced.
The private worker cwd/home/tmp, scrubbed environment, process-group/descendant cleanup, bounded streams,
35-second worker / 40-second parent deadlines and 128 MiB Node heap remain. The sampled worker-tree
RSS/PSS guard is calibrated and operator-configurable as documented below.

Admission bounds (fail closed, no truncation):

| Bound | Value / basis |
|---|---|
| Snapshot serialized bytes | 32 MiB |
| Snapshot list | 528,064 entries: 527,040 minute leap-year intervals + 1,024 headroom |
| Snapshot string | 2,048 characters: 2,000-character address + 48 headroom |
| Object keys | 128, unchanged |
| Depth | 32, accommodating the nested verified design and model records |
| Nodes | 4,000,000, including both native timestamp and power arrays plus design metadata |
| Conservative tree accounting | 160 MiB, including six-byte escaped timestamp characters and scalar overhead |
| Worker wire input | 48 MiB, covering snapshot JSON-string escaping and a 4 MiB PNG encoded in base64 |
| PDF output | 126 pages and 8 MiB, including protected output |
| Worker diagnostics | 4,096 bytes |

The sampled process guards are retained, not a substitute for OS/cgroup/container enforcement.

### Verification

The former report-contract suite now tests verified snapshot/source binding; the native suites cover digest,
full/partial/localized content, HTML escaping, process/isolation limits, protection, watermark geometry and HTTP
compatibility. New `test_rb_rpt2b2_*`, `rpt2b2-*.test.ts` and `rpt2b2-pdf.spec.ts` cover the shared renderer,
PNG boundary, native series, immutable sources, byte hashing and screen/CSV/PDF content parity. Run with the
explicit PDF runtime environment and temporary test stores, plus `npm run verify`, demo Playwright and the
formal live harness. Missing integration prerequisites fail rather than silently skipping.

## Protected Free / Community native PDF

Every native PDF is protected inside `render_native_pdf` after Chromium rendering.
It opens without a password, uses AES-256 revision 6, and has a fresh owner password
from `secrets` per file. That password is never persisted or logged. High-quality
printing and accessibility extraction are allowed; copying, modification,
annotations, form filling and document assembly are disabled. These permissions
are deterrents, not DRM; the printed run/data hashes remain the integrity checks.
Protection failures use the existing sanitized error path and never return the
unprotected render. The 8 MiB limit also applies to the protected bytes.

The fixed worker payload carries `watermark: "free_community"`. Native text in a
reserved top-margin band identifies every page as a Free / Community report.
Production totals and monthly values use Reference Production / Produksi Referensi.
The protection policy and deployment gate are unchanged. Content comes from the
verified snapshot and shared full-report renderer described above. The browser HTML
download remains independent of PDF service availability.

### Results production-label audit (RPT2a)

These labels use **Reference Production** / **Produksi Referensi**; their values,
units and existing before/after-zero-export qualifications are unchanged.

| Results presentation | Previous label (en) | Updated label (en; id uses Produksi Referensi) |
|---|---|---|
| Annual energy KPI, monthly legend, waterfall endpoint | AC energy | Reference Production (`results.referenceProduction`, Results-only) |
| Period energy KPI and its chart labels | AC energy over the simulated period | Reference Production over the simulated period (`results.kpiPeriodEnergy`) |
| Inverter production-energy column | AC (kWh) | Reference Production (kWh) |
| PCC boundary | Actual PCC energy | Reference Production at the PCC (`results.bPcc`) |
| Monthly quantity selector | Production | Reference Production (`results.mProduction`) |
| Monthly source note | From the run's monthly energy… | Reference Production from the run's monthly energy… (`results.productionNote`) |
| Delivered-energy series | Delivered after zero export | Reference Production after zero export (`results.delivered`) |
| AC heatmap series | AC after zero export | Reference Production after zero export (`results.hAc`) |
| Daily before/after series | AC before/after zero export | Reference Production before/after zero export (`results.acBefore`, `results.acAfter`) |
| Stored-engine daily power series | AC power | Reference Production (AC power) (`results.referenceProductionPower`, Results-only) |

Other candidates retain their existing meaning: specific yield, PR, capacity
factor and peak power name derived metrics; Plant total and Inverter subtotal
identify aggregate rows; chart accessibility names describe the quantity and
chart type. Loss/reference-energy lines, irradiance, cell temperature, load,
coverage notes, warnings, and the annual Pxx quantiles are unchanged. Shared
`results.kpiEnergy` and `s15.acPower` remain unchanged, preserving the separate
browser HTML report.

### Amendment 5: scale measurements with the former 768-MiB guard

Annual verified synthetic source packages were bound to designs from the existing USE5 runtime,
Project and electrical-session builders, with loss/Pxx sections, watermark and illustrative PNG.
These are report-layout measurements, not predictions of plant production. The runtime design has
100 modules, 10 MPPTs and 5 orientation classes. The 990-kWp design has 1,800 modules, 6 inverters
and 100 strings; the 5.5-MWp fixture has 10,000 modules, 31 inverters and 556 strings. The latter two
use a clearly synthetic 150-kW, six-MPPT inverter definition, with three inputs per MPPT.

| Design | Locale | Pages | Protected bytes | Export seconds |
|---|---|---:|---:|---:|
| USE5 runtime | en | 8 | 288,348 | 1.077 |
| USE5 runtime | id | 8 | 288,189 | 1.051 |
| 990 kWp | en | 17 | 594,165 | 2.388 |
| 990 kWp | id | 17 | 593,933 | 2.521 |
| 10,000 modules (one completed run) | en | 63 | 2,141,774 | 34.365 |
| 10,000 modules (quiet serial rerun) | en | refused | — | 8.863 |
| 10,000 modules | id | refused | — | 9.032 |

Times include Python snapshot admission, Node rendering, Chromium and protection. Measurement
used a temporary worker copy with only the page cap removed; all other guards remained active.
The production page cap is twice the largest successfully measured document: 2 × 63 = 126.
The existing 8-MiB byte cap exceeds twice the largest measured output and remains unchanged.

**Historical Amendment 5 result:** quiet serial runs exceeded the former 768-MiB aggregate PSS
guard (776.0 MiB en; 771.8 MiB id). The Amendment 6 calibration below supersedes that memory
limit; page/byte caps, deadlines, sandbox and output completeness remain unchanged.
The separate 200,000-module browser benchmark is a renderer-only stress fixture without a
canonical electrical design or recorded run; it is not a verified report measurement.

In demo mode Vite has no API proxy, even when RAWIBUMI_API is set. Default server-export schema
and capability probes therefore fail closed at the UI origin; the UI explains that server PDF/CSV
downloads are unavailable and offers the HTML report. Free CSV is disabled before making a request.
The demo report snapshot remains supplied by mockApi. Explicit browser-route transport mocks in
tests can still exercise the server-export UI without an API process.

### Amendment 6: calibrated memory policy

The 10,000-module / 31-inverter / 556-string annual fixture was profiled three times per locale,
with all content, including the illustrative PNG, watermark and populated losses/Pxx. A measurement-only
2-GiB ceiling allowed the previous 768-MiB refusal to be measured; no sandbox, Node-heap, timeout or
output guard was bypassed. An independent process sampled PSS at 25-ms intervals, separating Node
from Chromium descendants and the Python process during pikepdf protection and page inspection.
All six reports had 63 pages.

| Locale / run | Node render / all (MiB) | Chromium (MiB) | Python during pikepdf (MiB) | Simultaneous whole-export peak (MiB) |
|---|---:|---:|---:|---:|
| en / 1 | 217.01 / 240.25 | 580.94 | 241.79 | 1029.66 |
| en / 2 | 216.88 / 240.35 | 579.60 | 259.87 | 1055.73 |
| en / 3 | 215.29 / 242.70 | 574.78 | 276.14 | 1104.70 |
| id / 1 | 216.04 / 239.81 | 580.63 | 276.02 | 1073.04 |
| id / 2 | 216.61 / 239.92 | 578.30 | 292.46 | 1086.75 |
| id / 3 | 217.07 / 240.44 | 576.18 | 293.47 | 1086.45 |

The per-process/stage peaks do not occur simultaneously and must not be added. Python figures
include the process baseline and retained allocator memory, not just incremental pikepdf allocations.
The highest simultaneous total includes Python during snapshot admission/worker communication as
well as Node and Chromium: **1,158,359,040 bytes (1,104.70 MiB)**.

The default guard is **1,737,538,560 bytes (1,657.05 MiB)** =
`max(768 MiB, ceil(1,158,359,040 × 1.5))`, below 2 GiB. The existing sampled guard
continues to monitor the worker process tree; its calibration conservatively includes the observed
Python parent peak too. It is not a new OS allocation barrier or a limit on the entire API process.

Operators may set `RAWIBUMI_PDF_MEMORY_LIMIT_MIB` to an integer **768 through 2048**, inclusive.
Unset uses the calibrated default. Empty, signed, fractional, exponent, whitespace-padded, non-ASCII
or out-of-range values fail closed before a worker starts. The budget is parsed once per worker call,
with the same RSS screening and confirming PSS measurement. The 128-MiB Node heap remains separate.
Lower operator budgets can deliberately refuse large reports. The 8-MiB byte cap and 126-page cap stay.

The real production default (no measurement worker or memory override) was then verified **3/3 en and
3/3 id**: all six files were 63 pages, 2,141,774 bytes en / 2,142,582 bytes id, protected with R6.
The complete PDF/security suites passed 362 tests, and formal `parallel check-a` passed all 73 live
tests at the default eight workers. No timeout or output-cap changes were required.
