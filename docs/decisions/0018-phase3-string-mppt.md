# Decision 0018 — Phase 3.5 keeps string/MPPT topology explicit and restricts analytical aggregation to common MPP state

**Status:** Accepted for Phase 3.5  
**Date:** 2026-09-23

## Context

Phase 3.4 provides per-module:

```text
Isc
Voc
Imp
Vmp
Pmp
```

The system architecture requires explicit:

```text
Module
→ String
→ MPPT
→ Inverter
```

and manual MPPT assignment must remain possible.

The Phase-3 PVsyst reports expose:

- 18 modules in series;
- total string counts of 12, 14, 16, and 18;
- one Huawei SUN2000-100KTL-M1 inverter;
- operating voltage 200..1000 V.

The Huawei OND separately establishes:

```text
NbMPPT = 10
NbInputs = 20
```

but the current evidence does not establish individual PVsyst string-to-MPPT assignment,
physical per-MPPT input count, or a verified per-MPPT operating-current limit.

## Decision

### Series strings

The Phase-3 analytical model is:

```text
string.identical_series_mpp.v0.1
```

For identical module states:

```text
V_string = N × V_module
I_string = I_module
P_string = N × P_module
```

This is exact for the current unshaded/electrically identical benchmark.

The model refuses to claim general mismatch capability. Future shaded or non-identical
series circuits require full IV-curve aggregation.

### MPPT assignment

String-to-MPPT assignment is explicit simulation input derived from the electrical design.

The runtime never invokes automatic assignment implicitly.

A deterministic balanced helper is available for suggestions and benchmark fixture
construction. It preserves string order while assigning contiguous groups, with lower MPPT
indices receiving the extra strings.

For the current 10-MPPT reference this gives:

```text
12 strings → [2,2,1,1,1,1,1,1,1,1]
14 strings → [2,2,2,2,1,1,1,1,1,1]
16 strings → [2,2,2,2,2,2,1,1,1,1]
18 strings → [2,2,2,2,2,2,2,2,1,1]
```

These distributions are explicitly labeled:

```text
source_claim = not_pvsyst_reported
```

They are OpenSIMPV analytical benchmark topology, not reconstructed PVsyst wiring.

### Input-count semantics

The OND fields:

```text
NbInputs = 20
NbMPPT   = 10
```

are preserved as total-input and MPPT counts.

OpenSIMPV does not infer a physical per-MPPT input limit by dividing the two values. Such a
limit is enforced only when an independently verified `input_count_per_mppt` exists.

The global total-input count may still reject a design with more assigned strings than
verified total DC inputs.

### Parallel MPPT aggregation

The Phase-3 model is:

```text
mppt.identical_parallel_mpp.v0.1
```

Analytical aggregation requires all assigned strings to have:

- identical active/inactive state;
- common Vmp within tolerance;
- common Voc within tolerance.

Then:

```text
Vmp_MPPT = common Vmp
Imp_MPPT = sum string Imp
Pmp_MPPT = sum string Pmp
```

and `Pmp = Vmp × Imp` is reconciled.

If string voltages differ materially, the engine fails and requires future full IV
aggregation. It does not sum individual MPP powers and call that the true common operating
point.

### Constraint handling

Phase 3.5 evaluates:

```text
Vmp < MPPT minimum
Vmp > MPPT maximum
Imp > verified MPPT operating-current limit
```

but does not alter the electrical state.

Voltage/current limiting and inverter clipping are Phase 3.6 responsibilities.

Unknown current limit is represented as unknown, not unlimited.

### Independent trackers

Independent MPPT powers can be summed for total available DC power.

Their voltages are not averaged into one synthetic inverter DC voltage. Phase 3.6 must
consume the tracker states explicitly or use a common voltage only when the trackers are
actually equal.

## Validation

Phase 3.5 regressions cover:

- exact series voltage/current/power scaling;
- duplicate string-ID rejection;
- explicit assignment completeness and uniqueness;
- total-input and independently verified per-MPPT input-limit handling;
- the four Phase-3 balanced benchmark distributions;
- exact parallel current/power aggregation;
- night-state constraint behavior;
- voltage and current constraint flags without clipping;
- rejection of mismatched string MPP voltage;
- total available power across independent trackers;
- benchmark provenance marking OpenSIMPV assignment as not PVsyst-reported.

## Consequences

- the numerical engine now reaches explicit MPPT DC state;
- electrical topology remains user-authoritative rather than hidden automation;
- missing Huawei current-limit evidence is not fabricated;
- the current unshaded benchmark can be aggregated efficiently without claiming general
  mismatch capability;
- Phase 3.6 can add inverter efficiency, thresholds, limiting, and clipping on a stable MPPT
  input contract.
