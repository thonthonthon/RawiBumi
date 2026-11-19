# OpenSIMPV — Phase 4.9C Canonical Reference Project Roundtrip

**Status:** Phase-4 closure hardening tranche  
**Date:** 2026-09-24  
**Parent:** Phase 4.9 Reference Projects and UX Hardening

## 1. Objective

Phase 4.9C tests whether the existing Phase-4 engineering design environment survives persistence and re-entry without changing engineering intent.

The governing regression is:

```text
create / reconstruct design
        ↓
validate
        ↓
save canonical design state
        ↓
reload
        ↓
revalidate
        ↓
rerun where current numerical scope supports the design
```

The critical rule remains:

```text
save → reload
must not change:
- geometry
- module coordinates
- component revision bindings
- electrical topology
- validation findings
- canonical object hashes
```

Phase 4.9C does not add shading physics or broaden the current numerical execution kernel merely to make the reference matrix pass.

## 2. Canonical Design-State Package

Phase 4.9C adds a deterministic design persistence surface:

```text
opensimpv.design_state_package.v0.1
```

Persisted canonical objects:

```text
Scene
ElectricalDesignRevision
ProjectRevision
SimulationConfiguration
DesignValidationReport
```

Weather and component payloads remain independent immutable revisions. The package pins their revision identities through the canonical project/design objects rather than embedding mutable copies.

The package deliberately excludes:

```text
DesignWorkspaceState
selection state
undo/redo history
camera state
other UI-only state
```

Each saved canonical object receives a canonical SHA-256. The manifest also records a package SHA-256 derived from the object-hash set.

Reload fails closed when:

- an object hash changes;
- the package hash changes;
- ProjectRevision no longer pins the saved Scene/Electrical revisions;
- SimulationConfiguration no longer pins the saved ProjectRevision;
- DesignValidationReport no longer matches the saved project/scene/electrical revisions;
- persisted canonical project/configuration/validation objects fail schema validation.

This creates a product-level save/reopen contract without making filesystem serialization itself part of numerical physics.

## 3. Reference Project Matrix

### R1 — Simple flat rooftop

```text
1 flat roof
1 PV field
18 modules
1 string
1 inverter
tilt 0°
azimuth 0°
```

Current runtime: supported.

### R2 — Multi-roof commercial rooftop

```text
2 flat roofs
2 PV fields
36 modules
2 strings
1 inverter
common tilt/azimuth
```

Current runtime: supported.

The two-roof scene proves that multiple physical support surfaces do not alter the canonical electrical execution when their connected module orientation remains homogeneous.

### R3 — Rectangular ground-mounted site

```text
1 ground surface
1 PV field
18 modules
1 string
1 inverter
tilt 20°
azimuth 0°
```

Current runtime: supported.

This exercises ground-support semantics separately from the rooftop path.

### R4 — Obstacle-rich shaded reference scene

R4 reconstructs the frozen Phase-4.9B VC5 SHD geometry rather than inventing a new obstacle fixture.

PV table origins:

```text
X = 0, 23 m
Y = 8, 11, 14, 17, 20, 23 m
```

Each source table footprint:

```text
20.752 × 2.278 m
```

Obstacles:

```text
(-8.256538, -5.000000, 0)   40 × 10 × 5 m
(-8.242630, 24.358715, 0)   40 × 10 × 5 m
```

Canonical reconstruction:

```text
12 support surfaces
12 PV fields
216 modules
12 strings
1 inverter
2 shading obstacles
tilt 20°
azimuth 0°
```

Current runtime behavior is deliberately **not** changed:

```text
SIMULATION_SCOPE_UNSHADED_ONLY
```

R4 must survive save/reload/revalidation exactly while continuing to expose that scope boundary. Passing the reference test by ignoring the obstacles would be a failure.

### R5 — Multiple orientations with one inverter

```text
2 support surfaces
2 PV fields
36 modules
2 strings
1 inverter

orientation 1:
tilt 20°
azimuth 0°

orientation 2:
tilt 20°
azimuth 90°
```

The canonical design and topology remain valid engineering state.

The current homogeneous numerical runtime remains explicit:

```text
SIMULATION_SCOPE_REQUIRES_ONE_ORIENTATION
```

OpenSIMPV does not flatten these orientations into one artificial equivalent orientation during save/reload or simulation launch.

## 4. Roundtrip Results

For R1–R5:

```text
saved Scene == reopened Scene
saved ElectricalDesignRevision == reopened ElectricalDesignRevision
saved ProjectRevision == reopened ProjectRevision
saved SimulationConfiguration == reopened SimulationConfiguration
saved DesignValidationReport == reopened DesignValidationReport
```

Canonical hashes are unchanged.

Deterministic engineering revalidation produces the same report and report hash after reopening.

## 5. Numerical Rerun Results

R1–R3 are inside the existing runtime scope.

For each:

```text
before-save input_hash
=
after-reload input_hash

before-save result logical SHA-256
=
after-reload result logical SHA-256

before-save standard timeseries
=
after-reload standard timeseries
```

Engineering summary content is identical.

`simulation_run_id` is intentionally allowed to differ because it identifies an execution instance, not engineering state.

## 6. Unsupported-Scope Stability

R4 and R5 prove another required behavior:

```text
unsupported physics
≠
permission to reinterpret the design
```

Before and after reopening:

- R4 remains blocked by the unshaded-only numerical kernel;
- R5 remains blocked by the homogeneous-orientation numerical kernel;
- neither design is silently mutated;
- the same scope finding is reproduced.

This converts unsupported numerical scope into explicit reproducible behavior rather than hidden fallback.

## 7. Reference Component Boundary

The R1–R5 closure fixtures use:

- the manufacturer-supplied Jinko JKM550M-72HL4-V PAN fixture for module identity/model data;
- the manufacturer-supplied Huawei SUN2000-100KTL-M1 OND fixture for inverter identity and executable efficiency data.

The existing OND fixture does not contain enough verified current/frequency information to satisfy every Phase-4 engineering design check.

Therefore the Phase-4.9C regression fixture applies an explicit **synthetic test-only design overlay** for missing current/frequency limits.

That overlay:

- is visible in fixture metadata;
- is not represented as manufacturer evidence;
- is not represented as recovered PVsyst topology;
- exists only to exercise the already-implemented design-validation and persistence workflow.

## 8. Phase-4 Closure Assessment

The developmental Phase-4 exit gate is satisfied for the current scope.

OpenSIMPV can now maintain one canonical engineering design through:

```text
site / map context
→ exact scene geometry
→ PV field/module placement
→ component revision binding
→ strings
→ MPPT assignment
→ engineering validation
→ simulation configuration
→ supported simulation
→ save
→ reopen
→ revalidate
→ rerun
```

without changing engineering intent.

The R1–R5 reference matrix also demonstrates that designs outside the current numerical kernel remain reproducible and explicitly unsupported rather than silently simplified.

Therefore after Phase 4.9C:

```text
──────── PHASE 4 ENGINEERING DESIGN ENVIRONMENT
         CLOSED FOR CURRENT SCOPE ────────
```

This is a **design-environment maturity boundary**, not a claim that all PV physics is complete.

Specifically, closure does not claim:

- annual near-shading computation;
- diffuse/ground obstruction calculation;
- multi-orientation numerical execution in the current unshaded worker;
- electrical shading mismatch;
- bifacial behavior;
- tracker behavior.

The next developmental state is Phase 5 — Geometry-Aware PV Simulation.
