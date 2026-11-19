# Phase 6.9B increment 2: attribution energy and reporting contracts

The validated Phase 6.9B increment 1 tree (`ba17c9b`) is the authoritative power
input. This increment reads `detailed-dc-attribution.json`; it never evaluates
module, string or MPPT counterfactual physics. The physical and attribution
kernels, legacy shading-result schema, actual loss chain and PCC calculations
remain unchanged. No commit, browser UI, PCC counterfactual propagation or annual
acceleration is included.

## Immutable summary contract

`DetailedDCAttributionEnergySummary`, schema/model version 0.1, persists as
`detailed-dc-attribution-energy-summary.json`. Canonical JSON bytes and SHA-256
freeze the result. Its model ID is `rawibumi.phase69b.dc_attribution_energy.v0.1`.

Fields include:

- DC accounting basis, explanatory-only application and signed convention.
- Authoritative compact attribution SHA-256 and its scientific input, physical
  numerical-result, electrical-design and pinned module-input hashes.
- Attribution model/version, numerical policy, region solvers and sample count.
- MPPT, module and string scope IDs, plus tracker identity.
- Aggregation policy and observed simulation start/end/duration.
- Interval audit: canonical interval/evaluation identity, explicit seconds,
  validated U/N/B/S/C/T ledger, channel availability/reasons, power telescope,
  and unrounded signed channel Wh.
- Run-total, daily and monthly periods, with source interval indices, observed
  start/end/duration, coverage for every basis/channel and energy telescope.

Period energy covers the validated aggregate interval ledger across applicable
MPPT scopes. This contract does not add per-MPPT energy drilldowns. Scope IDs and
source hash retain the link to the authoritative scoped power result.

The detailed execution context references the summary by artifact name, model ID
and summary hash. The completion manifest covers the file. Historical detailed
packages without this reference remain valid. Legacy runs produce no new summary,
and existing SimulationRun, SummaryResult and actual energy ledger fields retain
all values and meanings.

## Integration, coverage and signed values

Available interval energy is exactly the existing floating-point integration
order: `power_w * duration_seconds / 3600`. Duration comes only from canonical
explicit seconds. Timestamp spacing is not used to infer it. `math.fsum` sums the
signed interval contributions without rounding, significance suppression,
extrapolation or coverage scaling.

Positive energy means reduction; negative energy means recovery. Raw signed net
energy is stored. Separate reduction/recovery magnitudes are deliberately not
provided; those optional presentation fields could obscure small net values
under cancellation. Small scientific terms remain in the interval audit and
period energy regardless of their apparent reporting significance.

Each basis/channel reports applicable, available, unavailable and not-applicable
interval counts and durations. Availability fraction is available duration divided
by applicable duration, or null when no applicable duration exists. Dark
not-applicable intervals never count as unavailable attribution coverage.

Completeness means:

- `complete`: all applicable observed intervals are available.
- `partial`: some applicable intervals are available and some are unavailable.
- `unavailable`: applicable intervals exist, with none available.
- `not_applicable`: no applicable intervals exist.

Availability remains `available` when an observed subtotal exists, including a
partial subtotal; `completeness` explicitly qualifies that subtotal. Otherwise it
is `unavailable` or `not_applicable`. `observed_signed_energy_wh` is the attributable
signed sum over available intervals, including exact zero after cancellation. It
is null if no intervals are available. `complete_signed_energy_wh` is populated
only for complete attribution coverage. Unavailable reason codes are sorted and
unique, with per-reason interval count and duration. Multiple reasons for an
interval do not duplicate that interval in unavailable coverage.

Completeness applies to **observed simulated intervals**, never coverage of a full
calendar month/year. Partial observed energy is never labelled total calendar
loss. There are no annual periods, annual extrapolation or full-year assertions.

## Power and energy telescopes

The authoritative input validator reconciles interval power channels. The summary
also checks the audit ledger arithmetic and each complete interval's power residual
against the existing source tolerance. For a complete aggregate telescope, all six
bases and all required channels must be complete on the same applicable interval
set. Otherwise the telescope is partial (or unavailable/not applicable), reports
blocking bases/channels and has a null whole-period energy residual.

A separately identified common available subset reports interval indices,
count/duration and its energy residual. This is not substituted for a complete
period telescope. Each complete period verifies:

`regional + bypass + series + parallel + tracker = total detailed DC attribution`

Energy absolute tolerance is the source 1e-7 W tolerance multiplied by common
available seconds / 3600; relative tolerance remains 1e-9. The recorded allowed
residual is the larger of absolute tolerance and relative tolerance times the
energy scale. Power tolerance remains 1e-7 W absolute, 1e-9 relative. No Phase
6.6–6.9B increment 1 tolerance is changed. C-T is integrated from the stored channel;
it is not hard-coded to zero. Controlled non-ideal tracker scalar fixtures prove
that a nonzero stored channel remains nonzero in energy; no tracker is implemented.

## Controlled examples

For U/N/B/S/C/T = 100/90/95/85/80/80 W and two available intervals of 900 and
1800 seconds, regional energy is 7.5 Wh, bypass energy -3.75 Wh, series energy
7.5 Wh, parallel energy 3.75 Wh, tracker energy 0 Wh and total DC attribution
15 Wh. Both power and integrated energy telescope residuals are zero.

When N becomes unavailable in the second interval, the regional/bypass channel
coverage is partial: applicable duration 2700 seconds, available 900 seconds,
unavailable 1800 seconds, fraction 1/3. Observed regional energy is 2.5 Wh and
complete energy is null; it is never scaled to 7.5 Wh. Series/parallel/tracker and
U-T remain complete. N blocks the aggregate telescope. Its common 900-second
subset reconciles separately. An additional dark 900-second interval does not
change applicable coverage or turn dark time into missing attribution.

An entirely dark 1800-second period has zero applicable and unavailable counts,
null availability fraction, null signed attribution energy and a not-applicable
telescope. Actual DC/night PCC consumption remains outside this report.

A 600-second interval starting `2026-01-31T23:55:00+07:00` belongs wholly to January,
even though it ends in February. Subsequent 1800- and 900-second February intervals
belong to February. At 10 W regional mismatch, January reports 1.6666666666666667 Wh
and February 7.5 Wh. Daily grouping uses the same local interval-start rule. No
boundary proration, missing-month filling, arbitrary-window splitting or full-year
claim is made. This matches existing canonical monthly energy semantics.

Signed cancellation retains the small residual contribution rather than zeroing
it. The controlled approximately 0.000331 W series channel remains positive after
1800-second integration, approximately 0.000165743 Wh, with its full scientific
floating-point value stored.

## Verification, runtime and limitations

Verification checks canonical summary hashing, closed schema, policy, interval
energy, deterministic reason aggregation, period coverage/energy and telescope
semantics. Package verification recomputes the summary from the bound compact
source, rejecting both internally inconsistent changes and internally consistent
summary/source substitutions. Full counterfactual IV curves are neither consumed
nor persisted by aggregation. Hash verification establishes consistency, not
external authentication or an independent physics recalculation.

The included compact test fixture was captured from the validated one-interval
canonical reference. Synthetic variations are explicitly scalar/temporal contract
fixtures and do not claim newly calculated electrical physics. Focused tests
monkeypatch counterfactual execution entry points to reject any physics call.
Relevant existing tests cover real persistence, module-quality independence,
actual-ledger isolation and historical/legacy compatibility.

Final focused suite: **10 passed in 1.80 seconds**. Relevant Phase 6.9A/6.9B,
energy and inverter regressions: **125 passed, 1 existing dependency warning in
2035.45 seconds (33:55)**. An earlier regression run was stopped after a schema
revision; it is excluded from these results. Complete suite: **825 passed,
1 existing Starlette dependency warning in 2232.92 seconds (37:12)**, with no
failures or skips. Logs: `/tmp/rawibumi-phase69b-inc2-focused.log`,
`/tmp/rawibumi-phase69b-inc2-relevant.log`, and
`/tmp/rawibumi-phase69b-inc2-full.log`.
Initial observation: warm-process one-interval compact aggregation and summary
validation took approximately 0.018 seconds; source file 14,811 bytes and canonical
summary 25,220 bytes. Times are local observations, not performance guarantees.
Expanded period coverage/audit metadata intentionally makes this summary larger
than a minimal power record. No annual-scale runtime or artifact-size claim is made.
The verified three-interval canonical package has a 29,065-byte canonical summary,
43,805-byte persisted summary and 502,414 total package bytes. Its run energy
telescope residual is 0 Wh. This adds 44,287 bytes to the prior 458,127-byte package
(the summary plus its context reference); actual result fields are unchanged.

Remaining limits: the validated input's physical domain and sampled-MPP precision;
observed-interval coverage rather than calendar completeness; aggregate ledger
reporting rather than per-MPPT energy drilldowns; floating-point numerical policy;
no arbitrary-period boundary splitting, significance UI, counterfactual thermal
feedback, PCC propagation, browser presentation or annual optimization.

## Changed files

- `engine/simulation/attribution_energy.py`: compact-only energy aggregation and immutable contract.
- `schemas/detailed-dc-attribution-energy-summary.schema.json`: new closed versioned schema.
- `engine/simulation/artifacts.py`: summary persistence, reference and verification.
- `tests/unit/test_phase69b_attribution_energy.py`: controlled compact-fixture coverage.
- `tests/integration/test_phase69b_dc_attribution.py`: summary integration and ledger/quality isolation checks.
- `tests/fixtures/phase69b/compact-attribution-reference.json`: validated compact golden input.
- `tests/fixtures/phase69b/README.md`: fixture provenance and test limits.
- `docs/phase69b-attribution-energy.md`: checkpoint contract and observations.
