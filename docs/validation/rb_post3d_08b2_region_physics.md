# RB-POST3D-08B2 region physics and provenance acceptance

B2 provides scientific-input acceptance for the B1 v0.2 numerical-assumption
branch. An accepted result grants no execution permission, manufacturer
validation, region calibration or physical-yield accuracy. B3 authorization and
independent package enforcement remain required. The B1 evidence schema,
canonical digest algorithm, required disclosures and legacy v0.1 validators are
unchanged. No manufacturer data or trusted provenance sets are modified.

## Evidence and source identities

`evaluate_numerical_assumption_acceptance(module, topology, definition, evidence,
sources)` takes the actual selected assets and the caller's authenticated source
registry. It does not authenticate a person or obtain assets from a catalogue.
B3 must supply its authenticated selection; self-consistent SHA-256 values alone
are not authentication of authorship or manufacturer origin.

`assert_numerical_assumption_source_bindings` validates the unchanged SourceRecord
schema, registry keys, referenced IDs and three distinct bindings. The original
and retained PAN roles are resolved through their respective declared file hashes;
equal anchors still require two distinct records. The assumption record must
match the declared source ID, be user_input/manual_entry, have meaningful title
and source_notes, explicitly null manufacturer and file_hash equal to the
recomputed declaration digest. Imported-by need not equal author. Declaration
author/rationale remain hash-bound provenance claims.

Available bytes can be supplied by exact source ID through `source_bytes`.
The resolver checks caller-supplied raw bytes without BOM/newline normalization.
SourceRecord.filename is descriptive and never authorizes filesystem access; the
resolver has no dependency on tests/fixtures. B3 must resolve accessible retained
bytes within its authenticated, approved evidence store and supply them here. Current Jinko retained digest
must also occur in the selected module's source IDs; that hash-as-ID convention
is not imposed universally. Original-byte authenticity is reported separately:
without supplied original bytes it is source-record-backed integrity only.
Reconstructing original bytes from the retained copy is never claimed.

## Asset linkage

Both selected assets require exactly three keys in metadata.numerical_assumption:
assumption_id, assumption_revision_id, evidence_class=NUMERICAL_ASSUMPTION.
They must exactly match the declaration. Module identity/revision, topology
identity/revision/full canonical hash, parameterization identity/revision/payload
hash and model identity/version are checked against the actual selected payloads.
Same-ID replacement revisions fail. Assumed topology remains inferred/unverified.
Geometry must be simple, nonoverlapping and cover one normalized module; complete
known active-area fractions must sum to one. The policy accepts exactly three
series protected substrings with one equivalent branch/region each. It does not
infer connectivity or double current from PAN NCelP or bypass-diode count.

## Real-kernel evaluator

The evaluator uses the canonical validated whole-module parameter extractor,
PVsyst calcparams mapping and pvlib singlediode/v_from_i. Private shared state
construction and series-adapter helpers retain the existing regional kernel and
production common-current module assembly. The public region builder still
requires legacy executable evidence; private numerical helpers confer no permit.
The evaluator returns accepted/rejected, exact failure diagnostics, a recomputed
consistency_record and derived gate diagnostics. The raising validator uses
NumericalAssumptionInputError, which is not a DetailedInputError.

Under the approved PVsyst representation, Ns, Rs, Rsh_ref and Rsh_0 divide by
three. Iph, I0, gamma, mu_gamma, alpha_sc, bandgap and reference G/T remain unchanged.
R_sh_exp remains the same dimensionless irradiance exponent. Parameter meanings
come from the existing canonical calcparams mapping. The evaluator checks finite
source parameters, integer divisible series count, explicit regional parameter
semantics and the actual numerical equivalence; it never repairs selected inputs.
Reverse resistance/domain and diode models remain independent declared assumptions.

## Uniform fixed-current methodology

For exactly (1000 W/m²,25 °C), (800,45), (400,15), evaluate 0.10,0.30,0.50,0.70,0.90
of the actual whole-module Isc. Compare whole-module V(I) to the real assembled
regional V(I), using signed residual assembled minus whole in volts. Maximum
absolute residual must be <=1e-4 V; no relative or power-only substitute applies.
The submitted entire B1 consistency record, including current values, voltages,
residuals, maximum, passed and digest, must equal deterministic recomputation.
Both forged PASS and supplied false on a passing candidate are rejected.
Exact numeric record equality requires the same pinned solver, pvlib version and
engine implementation identity used to author the record. Changing these may
reject an otherwise equivalent model. B3 must pin these identities for independent
verification; introducing a recomputation tolerance requires authorization and
cannot silently change the B1 record contract.
A failed primary gate returns the computed failing record for diagnostics.

## Conservation and signed power

Independent branch/substrings evaluations are reconciled against the shared
production adapter at all 15 uniform points and every bypass bracket point.
Regional I(V) independently checks series current. PV branch currents plus bypass
current must equal delivered current within 1e-6 A. Region voltages must sum to
branch voltage; protected substring voltages must sum to adapter terminal voltage
within 1e-6 V. Signed region powers minus nonnegative diode dissipation must equal
terminal I*V within 1e-5 W. Negative regional/module voltages are retained. The
conservation checks explicitly reject nonfinite electrical quantities.

## Bypass and reverse bias

Uniform generating samples must have inactive bypass. Shade each selected
substring in stable series order using fractions 0.5,0.1,0.01 at 1000 W/m²/25 °C.
The existing protected-substring solver derives transition current at its actual
model clamp. Probe below/at/above that current, with delta starting at
max(2e-8 A,1e-6 times transition current), at most 20 bounded enlargements.
All probes must stay in the explicit supported current domain. States must be
inactive/inactive/active, with equality inactive under existing solver conventions.
Active voltage equals the actual clamp within 1e-10 V, equality within 1e-6 V.
Continuity is checked against the actual unbypassed bracket voltage change plus
1e-6 V, not a universal physical clamp threshold. An unresolvable transition
rejects the candidate. Real linear reverse-region evaluation must retain negative
voltage. No bypass or reverse solver is replaced.

## Temperature response and precision

At fixed 1000 W/m² and 24/25/26 °C, compare whole-module and assembled-region
central finite differences for Isc,Voc,Imp,Vmp,Pmp and fixed-current voltage.
The common reference current is 0.5 of the 25 °C whole-module Isc and must remain
within all three generating domains. Each response error must be at most
max(0.005 times absolute source response,1e-5 in the quantity's units per °C).
Source response directions are preserved without asserting universal coefficient
signs. Secondary characteristic agreement also uses the approved 0.5%/1e-5 floor.

Continuous golden-section MPP is an acceptance diagnostic; production sampled
MPPT remains unchanged. Isc comes from the existing module root solver with
1e-10 A/V tolerances and 200 iterations. Each optimizer requires an interior
maximum, inactive generating bypass, finite output, bracket width
<=1e-10*max(1,Isc) A and at most 256 V(I) evaluations. A tenfold-tighter rerun must
agree in Imp/Vmp/Pmp within 1e-8 A/V/W. Failures include measured diagnostics;
no tolerance is relaxed. The tighter deterministic rerun checks bracket
convergence, not independent accuracy against the true optimum. Whole-module
characteristic and temperature comparisons provide separate numerical checks.
Real-kernel feasibility is pending orchestrator tests.

## Domain restrictions

Acceptance evaluates the stated finite policy grid, dark-region endpoints and
explicit current/reverse-voltage domains. Nonfinite/prohibited source parameters,
invalid topology, incomplete regions, incompatible model definitions, unsupported
solver, below-absolute-zero temperature, negative irradiance, unsupported currents
or reverse voltages, and convergence failure reject. No normalization, clipping,
solver substitution or undocumented extrapolation makes a candidate pass.
A finite policy grid is not blanket support for arbitrary runtime conditions.
Existing runtime condition checks continue unchanged; B3 must retain them.

## Fail-closed dispatch

Until B3, every recognizable v0.2 evidence record is denied by a non-fallback
scientific authorization error before detailed payload schema/quality validation.
Frozen quality validation also denies v0.2 anywhere in the pinned registry,
including unselected assets. Consequently pinning any v0.2 evidence blocks store
construction/replay and even Level-0 dispatch until B3 scopes authorization to
selected evidence or explicitly retains this registry-wide restriction. Dispatch inspects frozen selected
region/cell evidence before runtime availability checks and the Level-0 shortcut.
Malformed quality, missing/duplicate definitions and unsupported envelopes cannot
turn numerical evidence into a geometry-only fallback. Legacy v0.1 fallback,
quality handling, five-key payload serialization and execution hashes are unchanged.

## Cost and cache

Acceptance is reusable per immutable candidate, not called per module timestep
or snapshot replay. A bounded LRU holds 64 canonical input byte strings, each at
most 64 KiB; larger inputs are evaluated uncached. The key contains actual complete
module/topology/definition/evidence/source contents, solver, pvlib version, module
solver ID/version, acceptance implementation identity and all policy/precision
constants. Digests and provenance are checked before lookup. Available source
bytes are rechecked before reuse, so modified retained files cannot reuse physics
success. SourceRecord filenames are not opened; callers supply fresh bytes. Results are stored as immutable serialized bytes and returned as fresh
objects. A source/title/notes/payload/revision change misses. No permission boolean
is cached. `use_cache=False` gives independent evaluation for B3 verification.
No runtime, RSS or full-array benchmark is claimed.

## Regression and observed evidence

The new test module covers three-source resolution, required source fields,
PAN/declaration hash relationships, available bytes and authenticity strength,
Jinko source identity, asset metadata/revisions/digests, ID-only substitutions,
real equivalent and incorrect resistance/thermal transforms, forged consistency
records, conservation/power, bypass/reverse behavior, MPP precision, domain and
convergence failure, cache mutation safety, production dispatch non-fallback
rejection, legacy pin/fallback behavior and continued execution denial.
The review reported 66 passing and two failing targeted tests in the previous
round, plus 363 passing related tests. The two failing rejection expectations
have been corrected: G2 now corrupts PV branch current, and the restricted reverse
domain asserts the actual branch-voltage reachability failure. The dispatch
quality case now uses schema-valid non-subset source IDs, and an isolated G8
negative test perturbs the regional thermal response. These revisions have not
been executed by the implementer.
Positive physical tests use real numerical kernels. Deliberate corruption of
kernel results tests rejection arithmetic; it is not evidence of equivalence.
No test was executed by the implementer. Only static AST parsing and Git diff
whitespace inspection were performed. The orchestrator must run this new module,
B1 evidence regressions and relevant existing electrical/pinning/dispatch suites.
Implementation success and numerical precision remain pending that verification.

## B3 obligations

B3 must call and enforce this evaluator using authenticated scientific selection,
strict scientific opt-in, immutable snapshot witnesses and supported Level-2
fail-closed configuration. It must transport permission through serial/process
execution and attribution, bind complete assumption disclosures into execution
provenance, and independently reconstruct/enforce all source and physics gates
from package inputs with fresh evaluation. B2 adds no configuration option,
witness, package schema or execution authorization. Level-3 restrictions remain.
No Huawei pilot, 190-module run or weather acquisition was performed.
