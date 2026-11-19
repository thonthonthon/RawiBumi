# ADR 0026 — Phase 3.8E canonical simulation orchestration and immutable run package

Status: accepted  
Date: 2026-09-23

## Context

The Phase-3 numerical kernel is now sufficiently mature for the current
unshaded fixed-tilt scope, but the application contract was still lower level
than the architecture specifications.

Before Phase 3.8E, a complete numerical run was invoked with an
`UnshadedFixedTiltConfiguration` carrying direct module and inverter
dictionaries plus topology values.

That was numerically useful but did not satisfy the platform contract:

```text
ProjectRevision + SimulationConfiguration
        ↓
canonical validation
        ↓
revision resolution
        ↓
model resolution
        ↓
simulation
        ↓
SimulationRun + result reference + SummaryResult
```

The Canonical Data Model specification also defines SimulationRun as an
immutable execution record and requires large time-series results to live in
columnar storage rather than inside ordinary JSON.

## Decision

### 1. Canonical application entry point

Phase 3.8E adds:

```text
run_canonical_simulation(...)
```

with inputs:

```text
ProjectRevision
SimulationConfiguration
CanonicalRevisionStore
simulation_run_id
engine_version
output_directory
```

The lower-level unshaded runner remains the numerical backend and is not
redefined as the product API.

### 2. Standalone ProjectRevision schema

The existing Project schema embeds a project-revision object for project
serialization.

Phase 3.8E additionally defines:

```text
project-revision.schema.json
```

as the standalone execution-input contract.

The embedded Project v0.1 shape is not silently migrated in this phase.

### 3. Revision store

The synchronous V1 adapter receives an explicit immutable-revision lookup
surface:

```text
scene revisions
electrical revisions
weather revisions
component revisions
```

All simulation-relevant references are resolved by revision ID before physics.

A missing or identity-mismatched required revision becomes a canonical
`blocking_error` ValidationFinding.

### 4. Current execution scope remains explicit

Phase 3.8E does not pretend that the existing numerical kernel supports every
canonical design.

The current executable scope is:

```text
fixed_tilt_unshaded_homogeneous_single_inverter.v0.1
```

It requires:

- exactly one enabled inverter instance;
- one module component revision across connected strings;
- identical modules per string;
- one common tilt/azimuth for connected module instances;
- one support-surface albedo, or an explicit/defaulted single albedo;
- normal string polarity;
- a consistent StringCircuit → MPPTInstance mapping;
- unshaded beam and diffuse methods.

Unsupported mixed-orientation, mixed-module, multi-inverter, shaded, or other
non-representable canonical designs are blocked.

They are not flattened into a synthetic equivalent system.

### 5. Component model resolution is part of the run

The existing Phase-1 component resolver is now executed by the canonical
orchestrator.

The run persists:

```text
SimulationModelResolution
SimulationAssumption[]
resolver warnings
```

Explicit module/inverter requests remain authoritative.

For the current kernel, successful component resolution is necessary but not
always sufficient: a lower-fidelity component model may be valid in the model
registry while still not being numerically implemented by the current
unshaded kernel. That situation is blocked explicitly as
`resolved_but_not_executable` behavior rather than silently substituted.

### 6. Weather validation gate

The canonical execution path applies:

```text
Phase-2 base weather QC
+
Phase-3.8D solar-aware QC
```

using the same working weather cadence and SolarPositionResult semantics as
simulation.

The Canonical Data Model states that only `blocking_error` prevents
simulation.

Therefore Phase 3.8E preserves individual weather finding severities and adds
a separate canonical blocking finding:

```text
SIMULATION_WEATHER_QC_FAILED
```

when the WeatherQCReport status is failed.

This keeps the original QC evidence while making the simulation gate explicit.

Warnings remain executable and are persisted.

### 7. SimulationConfiguration → runtime adapter

The adapter resolves canonical project state into
`UnshadedFixedTiltConfiguration`.

Geometry/electrical values are derived from canonical scene/electrical
revisions:

```text
PVField tilt/azimuth
support-surface albedo
module revision
inverter revision
modules per string
string IDs
MPPT assignments
```

The runtime no longer expects an application caller to supply these as
unversioned direct dictionaries.

### 8. Thermal coefficients remain explicit

The current thermal runtime requires:

```text
u_c_w_m2k
u_v_w_m2k_per_ms
```

Phase 3.8E requires them in:

```text
SimulationConfiguration.numerical_options.thermal
```

No hidden thermal-coefficient default is introduced.

### 9. Loss defaults remain visible

If the following optional values are absent:

```text
module_mismatch_loss_fraction
string_mismatch_loss_fraction
dc_array_resistance_ohm
```

the current V1 adapter uses zero and emits SimulationAssumption records.

PAN-derived module-quality behavior remains controlled by the canonical module
definition unless explicitly overridden.

### 10. Output configuration is explicit

Phase 3.8E supports:

```text
standard_timeseries = true
format = parquet
```

The current adapter fails closed for unsupported output formats instead of
quietly writing something else.

### 11. Standard time-series result

A standard persisted result is projected from the detailed engine output.

It includes the canonical execution interval and the available standard
fields for:

- time;
- solar geometry;
- weather;
- POA;
- IAM/effective irradiance;
- thermal state;
- DC/loss state;
- inverter state;
- PCC power;
- interval energy.

The detailed in-memory result remains available to the synchronous worker, but
the durable standard result is stored as compressed Parquet.

### 12. Content-addressed result reference

`ResultDatasetReference v0.1` records:

```text
format
URI
media type
byte size
Parquet file SHA-256
logical-content SHA-256
row count
column count
columns
timestamp convention
Parquet engine/version
```

The logical-content hash is intentionally separate from the Parquet byte hash
so numerical reproducibility is not defined by one specific columnar encoder
version.

### 13. SummaryResult

Phase 3.8E defines and persists `SummaryResult v0.1`.

It distinguishes executed-period energy from annual energy:

- `total_energy_wh` is the energy integrated over the actual executed period;
- `annual_energy_wh` is populated only for a complete 8760-hour or 8784-hour
  execution and is otherwise null;
- period start/end and duration are explicit;
- monthly energy;
- specific yield;
- performance ratio;
- capacity factor over the executed period, explicitly based on installed DC
  nameplate power;
- peak DC;
- peak AC;
- clipping energy;
- shading energy loss for this explicitly unshaded scope;
- ordered loss summary with reference energy and loss fraction;
- data-quality summary.

Every electrical loss item retains the upstream reference energy used to
calculate its fraction.

### 14. SimulationRun

`SimulationRun v0.1` records:

- immutable run identity;
- ProjectRevision and SimulationConfiguration identity;
- engine version;
- timestamps;
- canonical high-level status;
- component revision manifest;
- weather/geometry/electrical revision IDs;
- model manifest;
- combined input hash;
- result reference;
- SummaryResult;
- ValidationFinding list;
- assumption ledger;
- model-resolution object;
- reproducibility manifest;
- detailed job-stage history;
- warning/error summary.

Canonical high-level status remains:

```text
queued
running
completed
completed_with_warnings
failed
cancelled
```

Detailed worker stages remain separately recorded:

```text
queued
validating
preprocessing
simulating
aggregating
reconciling
completed
```

This reconciles the Canonical Data Model status vocabulary with the Simulation
Engine job lifecycle instead of inventing two competing SimulationRun enums.

### 15. Reproducibility manifest

Every completed run records:

```text
project revision
scene revision
electrical revision
weather revision
component revisions
engine version
model manifest
simulation timestep
timezone
native weather resolution
working weather resolution
source timestamp convention
representative-time policy
solar evaluation offset
actual weather transformation chain
loss models
shading configuration
resolved numerical options
output configuration
input hashes
result logical hash
result file hash
```

Resolved numerical options are recorded, not merely the sparse user input.
This makes numerical defaults visible in the run report without mutating the
original SimulationConfiguration object.

### 16. Deterministic hashing

Phase 3.8E records stable SHA-256 identities for:

- engine version identity;
- ProjectRevision;
- SimulationConfiguration;
- Scene revision;
- ElectricalDesignRevision;
- WeatherDataset metadata;
- logical weather time series;
- module revision;
- inverter revision;
- component manifest;
- combined execution input.

The persisted result records both:

- physical Parquet-file SHA-256;
- logical time-series SHA-256.

Two runs with different run IDs but identical pinned engineering inputs and the
same engine version should therefore share the same combined input hash and
logical result hash. Changing only the engine-version identity changes the
combined execution-input hash even when the current numerical result happens to
be unchanged.

### 17. Run-package immutability

A run ID that already has persisted artifacts cannot be executed again into
the same output directory.

The adapter raises rather than overwriting:

```text
simulation-run.json
timeseries.parquet
summary-result.json
reproducibility-manifest.json
validation-findings.json
model-resolution.json
```

This is the filesystem-level V1 enforcement of the immutable SimulationRun
concept.

Database/object-store enforcement may later use stronger transactional
mechanisms.

### 18. Failed runs are persisted

Validation/model-resolution failures produce a persisted
`SimulationRun(status=failed)`.

The failed run retains:

- available input identity;
- input hash where available;
- ValidationFindings;
- assumptions;
- model-resolution object where available;
- job stage history.

It does not fabricate a result dataset or SummaryResult.

## New canonical schemas

Phase 3.8E adds:

```text
project-revision.schema.json
result-dataset-reference.schema.json
summary-result.schema.json
reproducibility-manifest.schema.json
simulation-run.schema.json
```

## Consequences

Positive:

- the product execution boundary now matches the architecture specification;
- revision identity reaches numerical execution;
- the current unshaded kernel can no longer be mistaken for a general canonical
  design runtime;
- validation/model limitations remain auditable;
- standard results have a durable columnar storage contract;
- result and input hashes support deterministic comparison and caching;
- completed run packages are immutable at the V1 filesystem boundary;
- Phase 3.9 comparisons can cite one immutable run manifest rather than
  reconstructing configuration from test code.

Limitations:

- the canonical adapter currently executes only the named homogeneous unshaded
  single-inverter scope;
- current fallback module/inverter model contracts are not yet numerically
  implemented in this kernel;
- near-shading scene execution belongs to later integration of the shading
  engine;
- synchronous filesystem persistence is a V1 implementation, not the final
  distributed worker/object-store architecture;
- standard result Parquet uses pyarrow in the current implementation.

## Regression requirements

Phase 3.8E is accepted only when tests prove:

1. a revision-pinned ProjectRevision + SimulationConfiguration executes
   end-to-end;
2. Scene/Electrical revisions resolve topology without caller-supplied runtime
   component dictionaries;
3. SimulationRun validates against its JSON Schema;
4. SummaryResult validates against its JSON Schema;
5. standard Parquet can be read back without semantic loss;
6. the run package persists all required metadata artifacts;
7. identical pinned inputs produce identical input hashes;
8. identical pinned inputs produce identical logical result hashes;
9. a repeated run ID cannot overwrite an existing run package;
10. missing required revisions return a failed run before physics;
11. solar-aware weather errors create a canonical blocking gate;
12. weather QC does not mutate source weather;
13. unsupported shading blocks rather than being flattened;
14. unsupported output configuration blocks explicitly;
15. ProjectRevision and SimulationConfiguration weather identities must match;
16. full repository CI passes.
