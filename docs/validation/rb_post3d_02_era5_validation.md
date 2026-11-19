# RB-POST3D-02 ERA5 validation runner

The runner is ready for explicitly launched validation; implementation and offline
regression coverage do not establish that genuine ERA5 execution has passed.
Engineering-design validation is **not exercised**. The Phase 6.10 B2 numerical
fixture is not an engineering-approved PV project, and its coordinates are fixture
coordinates, not a verified installation.

From the repository root, using the project's Python environment:

```sh
python tools/rb_post3d_02_era5_validation.py --help
python tools/rb_post3d_02_era5_validation.py --preflight
```

Preflight loads the existing B2 fixture and inspects request parameters offline.
It acquires no weather, runs no QC or simulation, and writes no artifacts. No mode
is selected implicitly. Only the user should launch live execution:

```sh
python tools/rb_post3d_02_era5_validation.py --execute
# Optional external artifact root:
python tools/rb_post3d_02_era5_validation.py --execute --output /external/validation
```

Each execution creates a unique job directory under the ignored
`.ai/validation/rb_post3d_02/` default root. Existing weather revisions and packages
are never deleted. Raw content-addressed snapshots, the acquisition manifest,
full canonical revision, QC findings, package, process logs, resource measurements
and report are retained there. An interrupted or failed package is diagnostic
evidence only. Exit status 0 for execute requires independent verification success.

The provider is the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api),
explicit model `era5`, using the existing adapter and its land selection.
Attribution is to Open-Meteo and Copernicus/ECMWF ERA5; retain the adapter manifest's
attribution and [CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/)
reference with exported evidence. The runner uses no API credentials and offers
no alternate endpoint or source fallback.

Request dates are inclusive GMT 2024-12-31 through 2025-12-31 at latitude
-6.425, longitude 106.831, fixed timezone UTC+07:00. No elevation override is sent.
The adapter assigns preceding-hour radiation means to interval starts by shifting
labels back one hour. State observations at the upstream label are assigned to
that preceding interval without interpolation. The runner never shifts these
canonical timestamps again. `direct_normal_irradiance` is DNI;
`direct_radiation` is not substituted for it.

The preserved source has 8784 native hourly starts from 2024-12-31 06:00+07:00
through 2026-01-01 05:00+07:00, ending exclusively at 06:00+07:00. Local 2025 is
inspected in memory: 8760 starts from 2025-01-01 00:00+07:00 through
2025-12-31 23:00+07:00. Its exclusive boundaries in UTC are
2024-12-31 17:00Z and 2025-12-31 17:00Z. No trimmed revision is persisted.
Both canonical QC and solar-aware QC inspect all 8784 rows before simulation.
Errors stop execution; warnings remain in evidence, without tolerance changes.
After both QC passes are recorded, negative required irradiance or wind values
also stop execution. Missing data is not interpolated. Native hourly units and adapter time-reference
metadata remain intact.

Returned grid latitude/longitude must be finite and within 40 km by a WGS-84
Vincenty inverse calculation. Nonconvergence fails closed. This test-specific
screen is not a meteorological accuracy guarantee. The canonical weather location
retains requested coordinates and elevation `None`; returned grid elevation is
recorded separately with its signed difference from the fixture's 93 m. The
existing solar model uses 0 m when canonical elevation is absent, and uses complete
ERA5 surface pressure when available, otherwise standard atmosphere at 0 m.
The fixture is never relocated or changed to an IANA timezone.

The direct `run_canonical_simulation` route re-pins only the project/configuration
weather identity, the store weather mapping, fixed period, and runtime workers
1/1. Scene, electrical topology, components, frozen selection, thermal and MPPT
semantics, module-quality override and diagnostics=False are preserved. A hash
of unaffected scientific inputs and output settings is compared before and after.
The existing project_revision_id serves as the weather-store namespace; no
project_id is added to the B2 fixture. No design gate or
synthetic design-validation evidence is used.

Only 2025-06-30 00:00+07:00 inclusive through 2025-07-02 00:00+07:00 exclusive
may execute: exactly 48 native hourly intervals, crossing the month boundary.
The runner rejects every other period, including annual execution. Full-source
hashing remains separate from selected-period execution. Midpoints, upstream
labels, solar evaluation times/offset metadata, local/UTC coverage and weather
fingerprints/bindings are reported. Detailed fidelity must remain
`level_2_bypass_substring`, without fallback, with `pcc_complete`. Mixed dark/active
MPPT failures remain fail-closed and appear in package findings/report/logs.

Execution (including acquisition/QC/persistence) has a two-hour wall limit;
a separate fresh Python verifier process has a one-hour limit. Process groups are
killed on timeout, monitor failure, resource breach, or exit, including surviving
descendants. One per-user lock covers all output roots. At least 20 GiB free disk
is required before simulation and at every monitor sample. Linux `/proc` descendant
PSS is sampled every 0.25 seconds and execution stops above 8 GiB. Sampling cannot
guarantee a peak bound or capture a short-lived allocation; no strict kernel
memory cap is claimed. If PSS cannot be measured, execution is refused or stopped.
Measurements cover disk free space and sampled PSS, with retained stage resources.

Canonical persistence performs its existing checks. The independent public
`verify_run_package()` returns the completion manifest on success and raises on
failure; the fresh worker records success only after this call returns. The final
report says PASS only after that worker succeeds. Existing energy and attribution
reconciliation are exercised by the public verifier; summaries, input hashes,
configuration and package verification evidence are retained. Package integrity
and numerical reconciliation do not prove physical yield accuracy or browser
engineering-design readiness.

Offline tests are in `tests/unit/test_rb_post3d_02_era5_validation.py`. They use
mocked provider JSON and mocked execution/supervision boundaries. The orchestrator
owns test execution. No live acquisition, simulation, benchmark, build, or package
verification was run during implementation.
