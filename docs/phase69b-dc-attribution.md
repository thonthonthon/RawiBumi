# Phase 6.9B increment 1: explanatory detailed DC attribution

This checkpoint adds interval-level and short controlled multi-interval attribution.
The immutable physical baseline is `phase-6.9a-validated` (tree at
`2acde3bfe2ef3a5107a6540657234271dd74dea5`). Actual selected-MPPT DC,
residual treatment, wiring, inverter, and PCC remain authoritative. Attribution
executes after physical execution and supplies no inputs to that loss chain.
Nothing is committed by this increment.

## Power states and signed accounting

All powers use the actual interval/evaluation identity, actual module temperature,
pinned parameterization and evidence, existing region solver, and actual string
sample count. A global MPP means the maximum of represented IV samples under the
existing solver policy; it does not claim an exact continuous optimum.

| State | Definition |
| --- | --- |
| U | Each module's actual area-weighted effective irradiance is applied uniformly to its regions; each module is independently optimized with its existing protected topology. Effective irradiance already includes geometry and optics. Temperature is retained. |
| N | Actual nonuniform regional effective irradiance, bypass disabled, each module independently optimized within supported unprotected region/branch domains. |
| B | Actual nonuniform regional effective irradiance and enabled bypass, each module independently optimized using the validated protected-module adapter. |
| S | Sum of the global MPP powers of the actual physical series-string curves. Those curves are consumed from the actual execution diagnostics. |
| C | Global MPP power of each actual shared-MPPT combined parallel curve, consumed from actual diagnostics. |
| T | Actual selected tracker power, consumed from actual execution. |

Independent module and string powers are summed within their physical MPPT scope,
then across MPPTs for the interval ledger. Module and string scope IDs are retained.
The signed convention is **reference minus evaluated**: positive is a reduction,
negative is recovery. The channels are U-N, N-B, B-S, S-C, and C-T respectively;
the endpoint total is U-T. The telescope residual is the accurately summed five
channels minus U-T. C-T is calculated from the two actual powers, never set to
zero by assumption. The current ideal-global-MPP tracker is also checked against
the existing power tolerance. The contract can represent future non-ideal tracker
differences without changing channel meanings.

No geometric shading energy is booked again. DC attribution Wh remains separate
from PCC shading-loss Wh and from the existing `ElectricalShadingResult` schema.
The downstream module-quality scalar is not applied to any state or channel;
frozen parameterization coefficients remain authoritative, including embedded
calibration. The Phase 6.9A declaration continues to govern downstream treatment.
Zero quality proceeds, separate
application of Jinko -0.0075 multiplies downstream DC by 1.0075, embedded quality
does not apply that scalar, and unknown nonzero quality remains fail-closed at
downstream continuation. Its valid selected-MPPT DC can still be explained.

## Bypass-off domains and availability

The bypass-off adapter uses the existing region electrical states and unprotected
parallel-branch solver. Each substring's supported common-voltage lower endpoint
is the maximum of its branches' supported endpoint voltages. Supported branch
currents at that common voltage are summed; the module current ceiling is the
minimum across substrings. The adapter disables the diode and sums the bounded
substring voltages at the requested series current.

N is only optimized if that supported domain reaches module V=0. Otherwise the
adapter cannot claim coverage of the whole positive-generation domain and returns
`bypass_off_positive_power_domain_not_covered`. Other bounded solver rejections
return `bypass_off_domain_unsupported`. No supported reverse voltage/current domain
is extended, and no partial-domain maximum is called a global MPP. This is a
conservative sufficiency rule: it can decline an otherwise estimable optimum
rather than assert unsupported physics.

Every basis and channel is `available`, `unavailable`, or `not_applicable`.
Unavailable and not-applicable values are null with reason codes. An unavailable
N makes U-N and N-B unavailable while B-S, S-C, C-T, and possibly U-T remain
available. A telescope is then `partial` with null residual, even when its
endpoint total is known. Unavailable attribution never invalidates already
completed physical execution or becomes a zero loss.

For `inactive_dark`, actual DC is exactly zero but attribution power bases and
operating points are not invented. The bases/channels/telescope are explicitly
not applicable. Dark independent scopes have no MPP; they do not contribute to a
sum over generating scopes. Inverter night consumption stays in actual PCC.

Energy uses explicit interval duration, P * seconds / 3600. Missing applicable
intervals produce null complete-channel energy plus an explicitly named available
subtotal and coverage durations. Dark not-applicable durations remain separately
identified. They never masquerade as evaluated zero electrical mismatch.

## Immutable compact contract and verification

`DetailedDCAttributionResult` schema/model version 0.1 is separate from frozen
legacy shading-result channels. Canonical JSON bytes and a result SHA-256 freeze
intervals, evaluation times, durations, module/string/MPPT scopes, all power bases,
channels, status/reasons, telescope residuals, policy, and duration-based energy.
It binds the physical scientific input hash, actual numerical-result hash,
electrical design hash, pinned module input hashes (including parameterization
evidence and quality declaration), local-state hashes, region solvers, sample
count, and attribution model identity.

Production persists `detailed-dc-attribution.json`, referenced separately by the
existing detailed context and covered by the completion manifest. Actual physical
scientific identity and run input hash are unchanged. Verification recomputes the
hash, enforces the closed schema and policy, reconciles scope sums/channels/energy,
and binds frozen inputs and compact physical selected-MPPT states. When full
physical diagnostics are present, string, combined-curve and local-state bindings
are additionally checked. This proves artifact consistency, not an independent
recalculation of counterfactual physics from compact outputs alone.

Full counterfactual curves are transient solver diagnostics. They persist only
when `output_configuration.detailed_diagnostics` is explicitly true, in a separate
`detailed-dc-attribution-diagnostics.json` artifact bound to the compact result
and per-module curve hashes. Changing diagnostic retention does not change the
compact attribution hash. This increment adds no reporting presentation.

Tolerances: power/telescope and direct-reference parity use absolute 1e-7 W and
relative 1e-9; IV voltage/current use 1e-9 V/A and at most 200 iterations. Energy
absolute tolerance is 1e-7 * covered_seconds / 3600 Wh, relative 1e-9. Existing
Phase 6.6-6.9A tolerances are unchanged. Telescope residual comparison to zero uses
the absolute power tolerance; endpoint/direct parity uses both tolerances.

## Controlled numerical evidence

The Phase 6.8C four-module, two-string, one shared-MPPT reference at 1000 W/m²,
25°C, unity optics, with one occluded region and 101 string samples produces:

| Basis | W |
| --- | ---: |
| U | 2543.1186253936125 |
| N | 2424.1372911652925 |
| B | 2426.7174557099297 |
| S | 2426.7171242241366 |
| C | 2264.1653389107187 |
| T | 2264.1653389107187 |

| Channel | W |
| --- | ---: |
| Regional mismatch | 118.98133422832007 |
| Bypass interaction | -2.5801645446372277 |
| Series interaction | 0.00033148579314001836 |
| Parallel interaction | 162.5517853134179 |
| Tracker interaction | 0 |
| U-T | 278.9532864828939 |
| Telescope residual | 0 |

The very small series difference in this fixture is subject to represented-grid
sampling effects; a separate unequal-irradiance uniform-module series fixture
at 500 and 1000 W/m² gives B=988.9651445376421 W, S=702.1002467672956 W,
and B-S=286.8648977703465 W. Uniform single-module U=N=B is
664.1118472222423 W. A mild nonuniform case has U>N while bypass remains inactive;
N and B agree within tolerance. The severe case has multiple local maxima and
negative N-B recovery.

A supported reverse-domain narrowing to -0.7997 V for the occluded region
retains valid protected physical execution, U, and B, but rejects N. Regional
and bypass channels are null, unrelated channels remain available, and the
telescope is explicitly partial. No reference current domain is expanded.

## Validation and observations

Final focused attribution suite: **16 passed in 525.57 seconds**. Legacy
electrical-shading contract suite: **23 passed in 0.86 seconds**. Existing legacy
API smoke test: **1 passed**, with the existing dependency warning. A broader
sandbox regression run was stopped; its inherited API was
verified outside the sandbox and all regressions are included in the complete
suite. Complete suite: **814 passed, 1 existing dependency warning in 2235.46
seconds (37:15)**. No tests failed or were skipped. Logs:
`/tmp/rawibumi-phase69b-final-focused.log`,
`/tmp/rawibumi-phase69b-legacy-contract.log`,
`/tmp/rawibumi-phase69b-api-focused.log`, and
`/tmp/rawibumi-phase69b-full.log`. Tests cover
uniform/nonuniform inputs, signed bypass recovery, multiple maxima, series and
parallel mismatch, computed ideal tracker equality, complete/partial telescope,
bounded N rejection, dark semantics/night consumption, quality independence,
actual-ledger equality with attribution disabled, direct/orchestrated parity,
duration integration, deterministic replay, tamper checks, compact and optional
diagnostic persistence, and legacy execution.

Initial controlled observations (local machine, not performance guarantees):
four-module one-interval attribution took 31.85 seconds, with 9,336 canonical
compact bytes versus 132,913 optional counterfactual diagnostic bytes. The bounded
case took 30.36 seconds with 9,571 versus 121,592 bytes. A three-interval canonical
run including physical execution, attribution and persistence took 134.85 seconds;
its persisted attribution file was 36,012 bytes and complete package 458,127 bytes.
Times depend on solver inputs and machine load. No annual-scale performance claim
or acceleration is made.

Remaining scientific limits are the Phase 6.9A execution envelope, pinned region
parameterization/reverse domains, represented-sample MPP resolution, conservative
N availability, and interval/DC accounting. Non-ideal tracker models are
representable but not implemented. Counterfactual temperature feedback, new
physical shading/reverse models, downstream/PCC counterfactual propagation,
browser UI, annual acceleration and Phase 6.9B reporting presentation are outside
this checkpoint.

## Changed files

- `shading/electrical/dc_attribution.py`: bounded independent-module states.
- `engine/simulation/detailed_attribution.py`: immutable explanatory ledger and verification.
- `schemas/detailed-dc-attribution.schema.json`: new versioned closed schema.
- `engine/simulation/detailed_dispatch.py`: post-physical attribution orchestration.
- `engine/simulation/detailed_downstream.py`: result/persistence plumbing only.
- `engine/simulation/canonical.py`: optional attribution result field.
- `engine/simulation/artifacts.py`: separate artifact persistence and verification.
- `tests/integration/test_phase69b_dc_attribution.py`: controlled validation.
- `docs/phase69b-dc-attribution.md`: checkpoint scientific contract and evidence.

The detailed physical producer, electrical kernels, `_run_fixed_tilt()`, residual
loss/inverter kernels, quality declarations and legacy shading schemas are
unchanged from the validated tag.
