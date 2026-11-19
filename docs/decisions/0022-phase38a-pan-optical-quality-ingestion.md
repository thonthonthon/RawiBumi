# ADR 0022 — Phase 3.8A PAN optical and module-quality ingestion

Status: accepted for Phase 3.8A  
Date: 2026-09-23

## Context

The Phase-3 numerical runner previously required the caller to repeat three
module-specific values that can already exist in a user-supplied PAN file:

- module absorptance used by the PVsyst thermal balance;
- module incidence-angle modifier (IAM) profile;
- module nominal-power tolerance used to initialize PVsyst module quality.

That breaks the canonical architecture boundary. A PAN import may preserve the
raw fields, but a real simulation should consume canonical module behavior rather
than depend on benchmark-specific duplication of PAN values.

The Jinko JKM550M-72HL4-V manufacturer fixture contains:

- `Absorb=0.90`;
- `PNomTolLow=0.00`;
- `PNomTolUp=3.00`;
- a nine-point `PVObject_IAM` `UserProfile` stored as
  `TCubicProfile`.

## Decision

### 1. PAN remains an interchange format

PAN source paths are interpreted only by the PAN adapter. The simulation engine
does not read PAN field names.

The mapping flow is:

```text
PAN raw document
  -> versioned scalar field mapping
  -> PAN-specific structured semantic assembly
  -> canonical ModuleDefinition
  -> runtime resolution
  -> numerical models
```

Unknown or unsupported PAN fields remain preserved in the ImportRecord/raw map.

### 2. Canonical absorptance

`Absorb` maps to:

```text
optical.absorptance_fraction
```

This value is a module property. Mounting heat-transfer coefficients remain
array/project configuration.

At runtime, absorptance precedence is:

```text
explicit simulation override
  -> ModuleDefinition optical.absorptance_fraction
  -> documented generic fallback 0.90
```

The selected source is recorded in simulation metadata.

### 3. Canonical IAM

For verified `IAMMode=UserProfile` and `IAMProfile=TCubicProfile`, the PAN
adapter assembles the effective points into:

```text
optical.iam
  model_type: tabulated
  execution_model_id: iam.tabulated.pvlib_interp.v0.1
  interpolation_method: cubic
  points: [{angle_deg, modifier}, ...]
```

The source mode, source profile type, source interpolation mode code, and
source IDs are retained.

OpenSIMPV does **not** claim that pvlib cubic interpolation is numerically
identical to PVsyst's internal `TCubicProfile` implementation. The source
profile identity and the OpenSIMPV execution model are deliberately separate so
Phase 3.9 can attribute any remaining difference.

If a canonical IAM model is present but unsupported by the current Phase-3
runtime, execution fails explicitly instead of silently discarding it.

### 4. Nominal-power tolerance and module quality

`PNomTolLow` and `PNomTolUp` map to signed fractional bounds:

```text
quality.nameplate_power_tolerance.lower_fraction
quality.nameplate_power_tolerance.upper_fraction
```

For bounds (L,U), the documented PVsyst default module-quality performance
offset is represented as:

```text
performance_offset = L + 0.25 * (U - L)
OpenSIMPV module_quality_loss_fraction = -performance_offset
```

The sign inversion is intentional because OpenSIMPV uses positive values for
loss and negative values for gain.

Examples:

```text
0% .. +3%  -> -0.75% loss fraction = 0.75% gain
-3% .. +3% -> +1.50% loss fraction
```

The derived value stores its method ID and source provenance.

At runtime, module-quality precedence is:

```text
explicit simulation override
  -> ModuleDefinition quality.default_module_quality_loss_fraction
  -> 0.0
```

### 5. Explicit overrides remain authoritative

A simulation configuration may intentionally override component-derived IAM,
absorptance, or module quality. Overrides are never silently overwritten by the
component defaults.

An IAM profile supplied as a runtime override without an explicit IAM model ID
is rejected as ambiguous.

## Consequences

Positive:

- the imported component now carries its simulation-relevant optical/quality
  behavior into the engine;
- benchmark configuration no longer needs to be the authoritative source for
  PAN-derived values;
- provenance and override precedence are inspectable;
- Phase 3.9 can isolate PVsyst interpolation/model differences instead of mixing
  them with missing ingestion.

Limitations:

- exact PVsyst `TCubicProfile` interpolation remains an external-compatibility
  question;
- the current mapping ledger covers the verified IAM point paths used by the
  representative fixture; unrecognized additional fields remain raw rather
  than being guessed;
- this decision does not address PVsyst 8.1 transient thermal behavior or
  sub-hourly Perez coefficients.

## Regression requirements

The Phase 3.8A gate requires tests proving:

1. Jinko PAN `Absorb`, tolerance bounds, IAM mode/profile, effective point
   count, and IAM points map canonically.
2. The original source fields are removed from the unmapped set only when their
   semantics are explicitly handled.
3. The canonical module validates and retains source provenance.
4. The Jinko 0..+3% tolerance derives `-0.0075`.
5. A symmetric -3..+3% tolerance derives `+0.015`.
6. Runtime resolution consumes canonical IAM, absorptance, and module-quality
   defaults.
7. Explicit simulation overrides take precedence.
8. Generic fallbacks are disclosed in metadata.
9. The end-to-end unshaded runner consumes resolved canonical module defaults.
