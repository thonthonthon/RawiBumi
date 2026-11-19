# ADR 0032 — Phase 3.9H VC6 hourly stress and loading-ladder closure

Status: accepted as acceptance candidate; exact canonical execution pending external-oracle runtime
Date: 2026-09-23

## Context

VC6 is the strongest available hourly PVsyst loading case: 324 modules, 18 strings x 18 modules, 178.2 kWp, DC/AC about 1.78, 46 mΩ array resistance, and 0.05% string mismatch.

Detailed PVsyst 8.1.6 source: Sampel for OpenSimPV_Project_VC6_HourlyRes_0.CSV
SHA-256: 53377a31e66193cd6ad2b656f2e294612aa5c2727e61467ae1b31abb451bba3e

It completes the controlled hourly loading ladder VC0 → VC2 → VC4 → VC6, corresponding to DC/AC ratios of about 1.19, 1.39, 1.58, and 1.78.

## Decision

### 1. VC6 passes every frozen Phase-3.9H gate

Current residuals are:

- GlobInc: -0.01464%
- GlobEff: -0.12510%
- array nominal: -0.85332%
- irradiance effect: +0.32744 percentage point
- temperature effect: +0.24731 percentage point
- total mismatch: +0.00100 percentage point
- DC wiring: +0.01712 percentage point
- EArrMPP: -0.23875%
- inverter conversion: -0.07770 percentage point
- ordinary clipping: +0.39940 percentage point
- E_Grid: +1.59796%
- specific yield: +1.59796%
- PR: +0.01317 absolute
- monthly grid sensitivity RMS: 1.62552%
- monthly grid sensitivity maximum: 2.04849%

The ordinary clipping stage is the closest case to its frozen ±0.50 percentage-point gate. Its remaining margin is 0.10060 percentage point.

Therefore first_nonpassing_stage remains null.

### 2. ILPmxSH remains the largest individual grid-side missing model

PVsyst VC6 reports IL_Pmax = 13261.5364 kWh and inferred ILPmxSH = 3824.6276 kWh.

The candidate final-grid residual is +4087.4527 kWh (+1.59796%). It decomposes into:

- EArrMPP contribution: -659.9106 kWh
- conversion-loss contribution: -205.8684 kWh
- ordinary-clipping contribution: +1128.5234 kWh
- missing PVsyst ILPmxSH: +3824.6276 kWh
- other-loss contribution: +0.0807 kWh

ILPmxSH accounts for about 65.7% of gross absolute stage contributions.

### 3. Source-ILPmxSH subtraction remains only an attribution aid

Candidate E_Grid is 259878.9653 kWh. Subtracting source ILPmxSH gives 256054.3377 kWh versus PVsyst E_Grid of 255791.5126 kWh, a residual of +262.8251 kWh or +0.10275%.

Monthly sensitivity after the same aid is 0.17174% RMS and 0.34494% maximum absolute relative error.

This is not called an exact counterfactual because sub-hourly clipping can change conversion efficiency and the DC operating point.

### 4. EArrMPP-to-EArray identity is even stronger

PVsyst EArrMPP - EArray = 17086.2240 kWh.
PVsyst IL_Pmax + ILPmxSH = 17086.1640 kWh.
Difference = +0.0600 kWh.

Across VC4 and VC6 this independently confirms that high-loading EArray displacement is essentially the two clipping channels represented at the array operating-point boundary.

### 5. Upstream DC chain remains stable

Using the already validated common source optical/thermal family and scaling the PAN-derived electrical chain to 324 modules gives OpenSIMPV electrical-isolation EArrMPP = 276139.8482 kWh versus PVsyst EArrMPP = 276396.8013 kWh, a difference of -0.09297%.

No new material module/DC-model defect appears at the highest hourly loading.

### 6. Inverter-only isolation remains secondary to clipping semantics

Using PVsyst EArrMPP directly as inverter input gives OpenSIMPV conversion loss = 3724.9147 kWh versus PVsyst IL_Oper = 3510.2920 kWh, a +6.1141% difference in the conversion-loss channel.

OpenSIMPV AC clipping is 12376.3828 kWh versus PVsyst IL_Pmax of 13261.5364 kWh.

After source ILPmxSH is applied only as an attribution aid, the grid residual is +670.6116 kWh or +0.26217%. The conversion-loss channel is visibly less exact than at lower loading but remains secondary in annual system-energy impact to the clipping-resolution and EArray/DC-feedback boundaries.

### 7. Hourly loading ladder is closed as an acceptance-candidate campaign

All controlled hourly cases pass the frozen gates:

- VC0, DC/AC about 1.19: PASS
- VC2, DC/AC about 1.39: PASS
- VC4, DC/AC about 1.58: PASS
- VC6, DC/AC about 1.78: PASS

No case produces a first nonpassing stage.

As loading rises, residual attribution moves predictably from small IAM/thermal/SDM signatures toward ILPmxSH and EArray/DC operating-point feedback. This behavior is more informative than an annual-output-only parity score.

### 8. Exact canonical qualifier remains

The current evidence envelope is not relabelled as an unqualified exact canonical NREL-SPA execution. Promotion requires running the external CSVs through the repository's exact external-oracle path without changing the already frozen thresholds.

## Consequences

Phase 3.9H now has a complete controlled hourly stress ladder from DC/AC about 1.19 through 1.78.

The evidence supports: no material new upstream irradiance/thermal/module-model failure across load; clipping-resolution and EArray/DC-feedback semantics becoming dominant as DC/AC rises; ILPmxSH being first-order at high loading; final annual E_Grid never being sufficient on its own; and retaining the current no-fabricated-EArray architecture.

Minute validation remains separately blocked by the verified PVsyst 8.1 production sub-hourly Perez coefficient table.

## Governing rule

No hidden physics. No hidden resolution. No hidden loss. No silent assumption. No benchmark-revision mixing. No annual-output tuning. No ILPmxSH hidden inside ordinary clipping. No EArray fabricated from AC clipping. No sensitivity envelope relabelled as canonical execution.
