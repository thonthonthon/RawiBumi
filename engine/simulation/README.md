# Simulation orchestration


The simulation subsystem owns deterministic model selection, simulation configuration
resolution, time-step orchestration, and immutable run metadata.


Phase 1 implements **component model resolution** under `engine/simulation/models/`.


Current entry points:


```python
from engine.simulation.models import (
    resolve_module_model,
    resolve_inverter_model,
    resolve_simulation_models,
)
```


The resolver selects the highest justified registered component model and emits an explicit
assumption/limitation ledger.


Phase 3 numerical execution currently includes:


```text
engine/simulation/temporal.py
engine/simulation/unshaded.py


engine/timeline/
engine/solar/
engine/irradiance/
engine/optical/
engine/thermal/
engine/module/
engine/inverter/
engine/losses/


electrical/string/
electrical/mppt/
```


The timeline consumes canonical weather time semantics and produces strict interval
start/end/midpoint/evaluation timestamps. The solar layer evaluates the named NREL SPA model
at those representative times. Phase 3.2 adds interval-aware DNI/DHI completion and explicit
unshaded POA transposition with beam/sky/ground and anisotropic diffuse subcomponents kept
separate. Phase 3.3 applies component-aware IAM to produce effective irradiance and adds an
explicit PVsyst-style thermal heat-balance model. Phase 3.4 executes the validated
PVsyst-v6 single-diode model per module and closes the thermal/electrical efficiency loop
with an explicit fixed-point solver. Phase 3.5 aggregates identical module states into
explicit strings, validates manual string-to-MPPT assignment, and aggregates only
common-voltage identical strings at each independent MPPT. Phase 3.6 applies MPPT voltage
eligibility, startup threshold, voltage-dependent inverter conversion, AC power limiting,
clipping, and explicit night/standby self-consumption. Phase 3.7 inserts signed module
quality/mismatch and resistance-based DC wiring before the inverter, integrates interval
energy from explicit duration, calculates core PV KPIs, and reconciles a named electrical
loss ledger through a PCC identity boundary at net inverter AC output. Phase 3.8 adds an
explicit temporal-execution boundary that keeps native weather cadence, current input-series
cadence, and working simulation cadence separate; records interval-level lineage; and runs
the complete fixed-tilt unshaded chain through one common orchestration path at 60, 300, 900,
or 3600 seconds (and other exact integer-ratio cadences where supported). Phase 3.8A closes
the module-ingestion/runtime boundary for PAN-derived IAM, absorptance, and nameplate-quality
defaults. Runtime precedence is explicit simulation override -> canonical component value ->
documented generic fallback, and the chosen source is recorded in result metadata. Phase 3.8B
adds a selectable PVsyst 8.1 adapted-Prilliman transient thermal path. The runner derives module
unit mass from canonical mechanical mass and one-sided area, preserves the steady-state
temperature as an intermediate, feeds the transient interval-average temperature into the
single-diode model, and records the thermal-history assumptions required for later PVsyst
8.1.6 attribution. Phase 3.8C adds a distinct PVsyst-8.1 Perez transposition
contract, including the documented 2° low-sun beam/circumsolar cutoff and a
timestep-bound coefficient registry. Hourly compatibility executes on the
Perez-1990 reference set. Sub-hourly compatibility fails closed until the
timestep-specific PVsyst 8.1 production coefficient table is supplied with
provenance; ordinary pvlib Perez, Perez-Driesse, and the older published
one-minute proof-of-concept table are not silently relabeled as exact PVsyst
8.1 behavior. Phase 3.8D closes the earlier solar-aware weather-QC deferral
with a separate validation layer that consumes the same SolarPositionResult as
simulation, applies BSRN V2 physical/component checks, adds conservative
time-reference diagnostics, and never mutates source weather. Clear-sky
screening remains opt-in and requires an explicit reference series. General AC
wiring, transformer, availability, curtailment, plant auxiliary stages, and
the final PVsyst cross-software acceptance comparison remain later work.


See:


- `docs/simulation-model-resolution.md`
- `docs/decisions/0005-progressive-simulation-model-resolution.md`
- `docs/decisions/0014-phase3-timeline-solar.md`
- `docs/decisions/0021-phase3-temporal-execution.md`
- `docs/decisions/0022-phase38a-pan-optical-quality-ingestion.md`
- `docs/decisions/0023-phase38b-pvsyst81-transient-thermal.md`
- `docs/decisions/0024-phase38c-pvsyst81-perez-low-sun.md`
- `docs/decisions/0025-phase38d-solar-aware-weather-qc.md`
- `docs/decisions/0026-phase38e-canonical-simulation-run.md`
- `docs/decisions/0027-phase39-pvsyst-v816-attribution.md`


Later numerical execution must consume the existing resolved component contracts rather than
re-implement model-selection heuristics independently.




## Phase 3.8E canonical execution boundary


The product-level entry point is now:


```text
ProjectRevision
+ SimulationConfiguration
+ CanonicalRevisionStore
        ↓
run_canonical_simulation(...)
        ↓
SimulationRun
+ SummaryResult
+ ValidationFindings
+ ReproducibilityManifest
+ Parquet result reference
```


The current executable canonical scope is explicitly versioned as:


```text
fixed_tilt_unshaded_homogeneous_single_inverter.v0.1
```


The adapter resolves module/inverter revisions, string length, MPPT assignments,
field orientation, and support-surface albedo from the canonical Scene and
ElectricalDesignRevision. Unsupported canonical designs are blocked rather than
flattened into an approximate runtime configuration.


Weather passes through Phase-2 plus Phase-3.8D solar-aware QC before physics.
A failed weather QC report is promoted to a separate canonical
`SIMULATION_WEATHER_QC_FAILED` blocking finding while preserving the original
finding severities.


Completed standard time series are persisted as compressed Parquet and referenced
through a content-addressed ResultDatasetReference. The run package also stores
summary, model-resolution, validation, and reproducibility JSON artifacts. A
persisted run ID is immutable and cannot be overwritten.


SummaryResult separates executed-period `total_energy_wh` from
`annual_energy_wh`; the latter is populated only for a complete 8760/8784-hour
run. The reproducibility input identity includes the engine version as well as
the pinned project/configuration/revisioned engineering inputs.




See `docs/decisions/0026-phase38e-canonical-simulation-run.md`.




## Phase 3.9 PVsyst attribution boundary


Phase 3.9 adds a separate report-level attribution layer under
`validation/attribution`. It does not alter the simulation physics.


The comparison is ordered from weather through POA, IAM/effective irradiance,
module loss stages, EArrMPP, inverter conversion/clipping, E_Grid, and PR. The
earliest failed comparable stage controls where investigation begins; known model
differences are reported as candidates rather than automatically declared causal.


PVsyst `EArrMPP` is the current DC acceptance mapping for RawiBumi
`array_virtual_mpp`. PVsyst `EArray` is intentionally excluded because it
contains inverter operating-point displacement that the present RawiBumi
inverter chain does not back-propagate into DC.


The supplied PVsyst reports do not contain the exact Meteonorm 9 interval weather
series, so report-level comparisons are currently `not_admissible` as final
same-input acceptance evidence. Minute cases also remain blocked by the verified
PVsyst 8.1 production Perez coefficient dependency.


See:


- `tests/benchmarks/phase39_pvsyst_v816_attribution.yaml`
- `docs/phase39-pvsyst-attribution-status.md`
- `docs/decisions/0027-phase39-pvsyst-v816-attribution.md`




## Phase 4.8 design integration


Phase 4.8 adds the application-side bridge in `engine/simulation/design.py`.


The high-level Phase-4 path is:


~~~text
Scene revision
+ ElectricalDesignRevision
+ exact component revisions
+ WeatherDataset revision
+ DesignValidationReport
        ↓
ProjectRevision
+ SimulationConfiguration
        ↓
run_validated_design_simulation()
        ↓
run_canonical_simulation()
        ↓
SimulationRun
~~~


The DesignValidationReport must match the exact Project/Scene/Electrical revisions and the current engineering validation rule set. Blocking or stale validation evidence stops before physics.


The validation report is persisted and its ID/hash/rule set are recorded in the run, but it is not part of the numerical combined input hash because it is derived evidence rather than physics state.


DesignWorkspaceState is not accepted by this bridge.


## Phase 5.5 beam-only geometry-aware vertical slice


Phase 5.5 adds a supported geometry-aware fixed-tilt path for one homogeneous execution group.


Direct POA beam is modified by the area-weighted module receiver visibility after transposition and before IAM. Sky diffuse and ground-reflected POA remain unchanged. The full receiver factor vector is persisted separately, and electrical mismatch remains explicitly not modeled.


See docs/phase55-beam-only-vertical-simulation.md.


## Phase 5.6 component-aware diffuse sky vertical slice


Phase 5.6 extends the geometry-aware homogeneous fixed-tilt path without
changing Phase-5.5 direct-beam physics.


After POA transposition, isotropic diffuse is modified by the weighted global
sky visibility, circumsolar diffuse by current sun-direction visibility, and
the horizon term by a separately weighted low-elevation horizon visibility.
The component terms are then reconciled before IAM. Ground-reflected POA
remains unchanged.


Module receiver sky/circumsolar/horizon factors are retained in the existing
receiver-factor dataset while area-weighted group factors feed the current
homogeneous electrical worker.


See `docs/phase56-diffuse-sky-obstruction.md`.


## Phase 5.7 ground/albedo obstruction vertical slice


Phase 5.7 extends the geometry-aware homogeneous fixed-tilt path with a third
independent front-side geometry channel.


After the Phase-5.5 beam and Phase-5.6 sky stages, receiver-side weighted
lower-hemisphere ground visibility scales only the existing ground-reflected
POA term. Beam, isotropic sky, circumsolar, horizon, and total sky diffuse are
preserved.


The runtime records receiver-level ground factors and an explicit
receiver-area-weighted group approximation. Numerical albedo remains separate
from geometric ground visibility.


See `docs/phase57-ground-albedo-obstruction.md`.


## Phase 5.8 annual sampling and exact shading acceleration


Geometry-aware execution now records an explicit annual shading sampling policy:


    canonical_simulation_solar_evaluation_timestamps


A null `sun_position_resolution_seconds` means no extra temporal coarsening.
Non-null values fail closed until a sampling/interpolation model exists.


With `cache_policy.mode="exact"`, runtime reuses prepared exact receiver query
geometry across all annual beam states and can warm-hit static sky/ground
ShadingResult entries. `cache_policy.mode="none"` remains the reference oracle
path. Both modes use the same physical equations and are tested for numerical
identity on the R4 reference geometry.


See `docs/phase58-annual-cache-measured-acceleration.md`.


## Phase 5.8H pre-annual execution hardening


Before annual result semantics are frozen in Phase 5.9, Phase 5.8H separates
deterministic scientific provenance from volatile execution telemetry.


Large receiver-factor outputs no longer require one full in-memory DataFrame.
Canonical execution predicts working-interval × receiver row count and streams
datasets above 250,000 rows through deterministic bounded Parquet chunks while
preserving the same logical-content SHA-256 as the in-memory path.


Component model-resolution identity is content-derived rather than SimulationRun
ID-derived. Cold and warm exact-cache runs therefore retain identical deterministic
model provenance; only `SimulationRun.execution_telemetry` may differ.


See `docs/phase58h-pre-annual-hardening.md`.
## Separable groups and multiple inverters (S16)

The standard canonical path executes homogeneous string groups independently through
POA, geometry modifiers, IAM, thermal/SDM and the existing DC-loss stages. Solar and
weather preparation are shared. Each populated MPPT must contain one module revision,
orientation, albedo and series length. Several groups may use different MPPTs of one
inverter, or different enabled inverters. Automatic assignment/rebalance accepts group
keys supplied by the API; manual mixed assignments remain editable but block execution.

Each physical inverter converts its complete MPPT bank once. The unchanged policy is
`power_weighted_voltage_efficiency_at_total_inverter_dc_power`: for accepted total P,
conversion is the sum of (Pj/P) × F(P,Vj), with startup, AC limit and clipping once per
inverter. Net inverter AC, including its modeled self-consumption, sums at the PCC.
There is no added AC wiring, transformer, availability or curtailment model.

Do not claim general PVsyst multi-MPPT parity. PVsyst's default independent-input
nominal-power fractions differ from pooled conversion under uneven loading. Comparisons
must account for its power-sharing setting; a per-input allocation model would require
another scientific decision. See [PVsyst's model](https://www.pvsyst.com/help/physical-models-used/grid-inverter/inverter-model-multi-mppt.html)
and [power sharing](https://www.pvsyst.com/help/project-design/grid-connected-system-definition/multi-mppt-inverters/power-sharing.html).

New multi topologies require zero global DC-array resistance; the versioned per-circuit wiring
allocation is defined. An enabled inverter without simulated strings must receive
strings or be disabled. Detailed electrical shading retains its existing single-inverter
eligibility; multi-inverter requests are refused before dispatch under either fallback
policy. No detailed numerical runtime or low-level physical kernel changes in S16.

Legacy one-group/one-inverter summary, time-series and loss outputs keep their existing
bytes. Only new multi topologies emit `execution_breakdown`, with exact group POA/DC and
per-inverter energy, yield and losses. Group and inverter Parquet datasets belong to the
immutable verified run package. Plant/inverter POA for KPI normalization is the simulated
DC-nameplate-weighted equivalent **unshaded** POA. Actual group POA remains available;
no plant module temperature, DC voltage or IAM coefficient is invented. Shading keeps
full-scene occluders and the existing per-group receiver-area approximation. Annual
shading loss uses a whole-plant clear-visibility counterfactual, including each inverter's
nonlinear conversion and clipping.

## Opt-in optics and thermal settings

`numerical_options.optics_thermal_settings` is independently versioned from loss settings. An absent block keeps the
legacy model selection, scalar albedo and incident heat balance byte-identical. Browser adapters supply Recommended
defaults; the raw engine does not opt old configurations in implicitly. An explicit legacy numerical policy also
preserves its scalar group descriptor when the original albedo resolution agrees. The immutable run snapshot keeps
the new block's actual sources separately from that compatible descriptor.

The settings module resolves model choices, presets and local-month albedo. Hourly Perez uses the existing hourly
coefficient family and true-elevation low-sun cutoff. Module-auto IAM reads the pinned table, falling back only when
absent to the analytic normal-glass Fresnel cover with no assumed AR layer. Existing tabulated interpolation and
solid-angle diffuse integration remain unchanged. No spectral, bifacial or transient browser feature is implied.

A present effective-basis choice uses post-geometry, post-IAM, post-soiling irradiance in thermal coupling and the
already computed effective-basis module efficiency. The legacy basis continues using incident irradiance and
incident-basis efficiency. Output efficiency columns retain their declared meanings. No IV or thermal equation,
solver, tolerance or sampling change is made.

Exactly zero completed horizontal GHI, DNI and DHI imply zero transposed channels, only on the opt-in branch. The
policy and count are recorded; all other nonfinite sources fail closed. The soiling/STC bridge remains post-IAM and
pre-soiling, with the signed operating-effects bridge to actual raw MPP. New optics choices change those quantities,
not the meanings or order of the S18a electrical stages.

### Circuit and plant wiring settings (S18c)

Optional loss extensions resolve canonical inverter and MPPT overrides before the
existing per-circuit DC kernels. The scalar law and inverter conversion are unchanged.
Own inverter AC segments precede summation; a new plant AC segment follows that sum
and precedes the existing plant transformer/unavailability. See
`engine/losses/README.md` for explicit cable/percentage units, assumptions, references,
precedence, stale-binding rules and immutable selected-run evidence.

Absent extensions and exact redundant inputs retain the parent summary, standard
Parquet and loss-ledger bytes. Requested origins are recorded separately in the
run's `circuit_loss_resolution`. Detailed execution uses only evidence-bound
per-MPPT quality scalars and the existing clear-STC references; unsupported quality
relationships refuse instead of averaging or silently downgrading.


Exact digest and private spool handling
--------------------------------------

Logical result digests keep the existing canonical header, ordered rows/columns,
scalar tokens and UTF-8 byte stream. Scalar floating classification uses stdlib
predicates after the existing float conversion; `.17g` formatting, signed zero,
NaN/infinity tokens and timestamp fallback remain unchanged. Each digest stream
may reuse exact numeric tokens in a private cache bounded to 4,096 entries and
1 MiB of retained key/token bytes. Float keys retain binary64 bits. Unknown or
oversize values bypass the cache.

Multi-group receiver factors first pass through private temporary Parquet spools.
Those spools retain validation, stable sorting, Arrow schema, codec and bounded
chunks, but publish no canonical result reference and compute no unused content
digests. The final sorted merge still uses the canonical receiver-factor sink:
its Parquet bytes, logical/physical digests, package references and verification
remain authoritative. Temporary spools are removed with their owning run scope.


## Browser sampling presets (SKY1)

The browser resolves independently versioned `shading_accuracy` settings through
`engine/simulation/shading_accuracy.py`. Standard uses sky/ground 48×12 and 48 horizon
sectors; High uses sky/ground 72×18 and 72 horizon sectors. Horizon keeps one band at
10°. This changes integration resolution only; patch geometry and numerical kernels
are unchanged. Existing browser projects switch to Standard on their next run.

The browser adapter places the stored setting in `numerical_options.shading_accuracy`
and actual numeric grids in `shading_configuration`. Conditional run transport checks
that they agree and records `resolved_shading_accuracy`. Without this block, explicit
engine configurations and their artifacts preserve parent behavior and bytes. There
is no hidden legacy browser preset; old explicit engine grids remain valid.

Detailed electrical shading retains the requested per-region sampling and fidelity.
Its current per-interval diffuse integration is a known scaling limit; Standard and
High do not introduce a shortcut or lower-fidelity fallback. The browser run snapshot
also records ground sampling, rather than implying it follows a sky-only label.
