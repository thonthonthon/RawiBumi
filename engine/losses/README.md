# Versioned project losses (S18a)

A present `numerical_options.loss_settings` selects the new stages. The object uses
`LossSettings` v0.1, versioned defaults and deliberate user `overrides`.
New projects select `recommended_defaults.v2`; stored v1 projects retain their exact
LID-zero resolution and metadata shape for byte compatibility.
An absent block retains the complete historical path described below, including
its global-resistance semantics and byte-identical outputs. Null/empty/unknown
blocks are invalid; the raw engine never silently supplies project defaults.

The order is post-IAM monthly soiling, unchanged thermal/module solve, LID,
pinned module quality, module dispersion, string dispersion, midpoint degradation,
independent DC circuit wiring, existing inverter stages, AC wiring per inverter,
plant transformer, then unavailability. Monthly schedules use local interval starts.
Every fraction is dimensionless; the browser displays percent. Ageing uses
`annual_rate * (operating_year - 0.5)`, not weather year or compound decay.

New projects use recommended_defaults.v2: an explicit LID override applies to every circuit; otherwise each circuit uses its module file's finite LID fraction in [0, 1). Missing or invalid values fall back to generic starting values: 0.5 % for TOPCon, HJT, heterojunction or IBC technology; 1.5 % for other crystalline silicon and unknown technology; 0 % for thin film. These are starting values, not measurements: check the datasheet. Clear the input to restore automatic LID. Each run records the per-circuit value and source. Earlier v1 projects retain LID 0 % unless overridden; “Use the current defaults” switches to v2 in one undoable save, preserving overrides. Saved results stay unchanged.

DC circuit j uses its own unmodified nominal STC reference:
`R_j = f_DC * V_STC,j / I_STC,j`, with runtime loss `I_j² R_j` and drop `I_j R_j`.
New-block circuits are always independent; identical banks never delegate to a
pooled global resistance. Unsupported reference inputs or a drop reaching operating
voltage refuse the run. Automatic manufacturing dispersion follows the recorded
series-count/technology and parallel-string rules; unknown technology requires an
override. Dispersion is separate from detailed irradiance-driven IV mismatch.

AC wiring uses `f_AC * P_i² / C_i` at each inverter's nominal AC rating, including
signed imports. An enabled transformer is energized at every interval: iron loss
is `a*C`, copper loss is `c*P²/C` on the signed inverter subtotal. Copper input is
required on enable. Its automatic reference is the sum of enabled inverter nominal
AC ratings. Iron loss at night appears as grid import. Unavailability removes
`u*max(P_after_transformer,0)`, preserving modeled imports. It is an export-energy
expectation, not a simulation of physical OFF periods or random outage days.

The waterfall has an explicit optical STC-reference bridge: post-IAM irradiance
and soiling attenuation times installed module STC capacity / 1000, followed by a
signed module-operating-effects bridge to actual raw MPP. Soiling is never applied
a second time to electrical power. The electrical chain conserves actual raw MPP
to PCC. Per-inverter outputs stop after their own AC wiring; their subtotal minus
plant transformer and unavailability losses equals PCC. Plant adjustments are not
prorated into inverter rows. Optics/thermal equations remain unchanged in S18a.

Detailed mode applies `IAM*(1-soiling)` to regional inputs before the existing
thermal solve, with retained pre-soiling diagnostics and scientific hash identity.
Resolved manufacturing dispersion follows selected detailed MPPT power, before
wiring (`detailed_iv_plus_dispersion_scalar`). Calibration-bound module quality
protections remain. Mixed detailed circuits derive their STC reference once using
the pinned IV kernels. The shared readiness/execution resolver refuses only when
automatic module-dispersion fractions disagree on one MPPT, naming the inverter,
MPPT and fractions; an explicit common override (including zero) resolves it. No solver, sampling, IAM or thermal equation changes.

## Historical absent-block chain

# Explicit electrical losses and result aggregation


Phase 3.7 turns the previously separate electrical-stage outputs into one ordered,
auditable energy chain.


The implemented boundary is:


```text
raw detailed array MPP
    ↓
module quality
    ↓
module mismatch
    ↓
string mismatch
    ↓
DC wiring I²R
    ↓
array virtual MPP
    ↓
MPPT voltage threshold
    ↓
inverter minimum-power threshold
    ↓
inverter conversion
    ↓
AC clipping
    ↓
inverter self-consumption
    ↓
PCC identity boundary
```


The PCC identity boundary currently equals net inverter AC output. Phase 3.7 does not
silently insert AC wiring, transformer, availability, curtailment, or plant auxiliary
losses.


## Array loss model


Model ID:


```text
array_losses.explicit_mpp_i2r.v0.1
```


### Module quality


The source convention is retained:


```text
positive fraction = loss
negative fraction = gain
```


For example:


```text
module_quality_loss_fraction = -0.0075
```


means a 0.75% MPP gain.


### Module and string mismatch


The current Phase-3 reference supplies explicit MPP power fractions. They are applied
sequentially and once.


These are simplified aggregate mismatch models. They are not substitutes for future
module/string IV mismatch physics.


### DC wiring


The Phase-3 reference uses the PVsyst global equivalent array resistance.


Runtime loss is:


```text
P_loss = I_array² × R_array
ΔV     = I_array × R_array
```


For the current identical-orientation benchmark, all active MPPTs share the same MPP
voltage, allowing one global voltage drop to be applied consistently.


If active tracker voltages differ materially, the global equivalent resistance model stops.
Per-circuit resistance data are required instead of fabricating one shared voltage drop.


The PVsyst 1.50% wiring-loss entry is treated as an STC reference/check on the equivalent
resistance. It is **not** also applied as a runtime percentage multiplier.


## Loss ledger


Model ID:


```text
loss_ledger.electrical_chain.v0.1
```


Each ledger channel has:


- an upstream power state;
- one signed loss/gain channel;
- a downstream power state;
- an interval reconciliation residual;
- annual integrated energy.


The sign convention is:


```text
positive = loss
negative = gain
```


Every stage must satisfy:


```text
downstream = upstream - signed_loss
```


within numerical tolerance.


The annual ledger must independently reconcile:


```text
PCC energy
=
raw array MPP energy
- sum(all signed loss energies)
```


A failed reconciliation is an error, not a warning.


## Energy integration


Interval-average power and irradiance are integrated using explicit canonical duration:


```text
E = P × Δt
H = G × Δt
```


The engine does not infer the last interval duration from timestamp spacing. The caller must
provide the canonical working interval duration or one duration per interval.


This is required so hourly, 15-minute, 10-minute, and one-minute simulations use the same
energy semantics.


Monthly grouping uses the local canonical interval-start timestamp.


## KPIs


Phase 3.7 implements:


```text
specific yield
    Yf = E_grid / P_STC


reference yield
    Yr = H_POA,incident / G_ref


performance ratio
    PR = Yf / Yr
```


with:


```text
G_ref = 1 kW/m²
```


unless explicitly overridden.


The Phase-3 PVsyst PR comparison therefore uses incident global POA, not effective
post-IAM irradiance.


## PVsyst EArray boundary


PVsyst's reported `EArray` is not equated to RawiBumi's `array_virtual_mpp`.


When inverter limiting binds, PVsyst can shift the actual DC operating point away from the
virtual MPP. Phase 3.6 currently models clipping as an explicit AC limiting channel and does
not reconstruct a new DC operating point from AC clipping.


Therefore Phase 3.7 keeps these quantities separate and marks direct PVsyst `EArray`
mapping as deferred. Phase 3.9 must compare/attribute this boundary rather than inventing a
back-calculated DC value.
## Circuit overrides and two AC boundaries (S18c)

`LossSettings` 0.1 accepts optional `overrides.circuit_overrides` and
`overrides.plant_ac_wiring`; absent extensions retain the previous serialization
and arithmetic. Circuit overrides bind canonical inverter/MPPT IDs to their source
electrical revision and a server-derived semantic-topology digest. Snapshot IDs and
names do not change that digest. Topology changes make the binding stale until an
explicit rebind or reset; unknown or shadowed targets are never discarded.

DC precedence is MPPT, inverter, project, Recommended default. Each circuit keeps
its own fixed nominal R = f·V_STC/I_STC and existing I²R kernel. Signed quality uses
MPPT, inverter, existing explicit engine override, pinned module, generic zero.
Negative quality is a gain. Detailed quality remains evidence-bound: separate
calibration applies once, embedded calibration is not applied twice, and unknown
nonzero or unequal effective factors within one MPPT refuse. Different MPPTs may
carry different supported scalars; no averaging or IV solver change is made.

An inverter-to-combiner segment inherits the old `ac_wiring_nominal_fraction` or
uses its explicit cable/percentage. The plant combiner-to-PCC segment applies once
to their combined post-segment power, before the existing plant transformer and
unavailability. Plant loss is never allocated back to inverter results.

Cable mode declares one-way metres, mm² **per phase**, line-to-line RMS volts,
material and conductor temperature (0–100 °C). It assumes balanced three-phase,
unity power factor with three identical phase conductors. R_phase=ρ(T)L/A,
I=P/(√3 V_LL), loss=3I²R_phase. No neutral, PE, return-length factor, reactance,
skin/proximity, ampacity, temperature solver or voltage-flow model is included.
The fixed material policy `conductor_properties.v1` uses annealed Cu (ρ20=0.017241
Ω·mm²/m, α20=0.00393/°C) and electrical EC-H19 Al (61% conductivity; ρ20=0.028264,
α20=0.00403). ρ(T)=ρ20[1+α20(T−20)]. The editable form suggestion is explicitly
labelled as an assumed 50 °C conductor temperature, never ambient temperature.
Property sources and the independent cable-convention comparison are recorded in
the S18c design evidence. The cable model is not a sizing or compliance tool.

Percentage mode names either `rated_ac` (own inverter nominal AC, or the sum of
participating physical inverter ratings for plant) or `custom` with an explicit
positive reference power in W. Loss=f·P²/P_ref. The product has no ambiguous STC
reference. Signed imports still dissipate nonnegative heat; zero power gives zero
wiring loss. New segments refuse a nonfinite/unrepresentable coefficient or a
modeled voltage drop/dissipation reaching its operating power; no clipping hides it.

Requested input/binding/origin evidence is immutable `circuit_loss_resolution` in
the selected run. Numerically redundant extensions use exact equality, preserving
the old effective summary, standard Parquet, loss summary and loss frame bytes;
requested provenance stays in the run audit. A one-ULP difference is active. Old
runs and library pins are never rewritten.

Material references: [NBS Handbook 100, §1.2](https://nvlpubs.nist.gov/nistpubs/Legacy/hb/nbshandbook100.pdf)
and [NBS Handbook 109, Table 1](https://nvlpubs.nist.gov/nistpubs/Legacy/hb/nbshandbook109.pdf).
The three-phase line-voltage convention is corroborated by the
[Electrical Installation Guide](https://www.electrical-installation.org/enwiki/Calculation_of_voltage_drop_in_steady_load_conditions).
