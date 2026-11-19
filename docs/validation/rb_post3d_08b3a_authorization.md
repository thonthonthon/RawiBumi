# RB-POST3D-08B3A authorization configuration and scope

`scientific_options.allow_synthetic_regions` accepts only literal Python/JSON
booleans. Absence means false without inserting a default into persisted inputs.
Invalid types are integrity errors, including for legacy selections and Level 0;
they cannot trigger explicit lower-fidelity fallback. Execution options grant no
scientific authority.

The existing `scientific_configuration` projection retains explicit scientific
options and removes execution options. Thus explicit false and true bind to the
existing configuration and combined scientific hashes. No schema, five-key
module-input payload, snapshot field, or legacy JSON serialization changes.

Frozen replay checks numerical candidates only when a region or cell evidence
reference occurs in a persisted selection. This includes persisted selections
for modules outside the active scene. An unreferenced valid v0.2 record does not
block legacy Level 0. Existing selection/source and registry quality checks remain.
Legacy v0.1 arbitrary metadata retains its original interpretation.

Selected evidence with version 0.2 or a top-level evidence_class must have the
exact pair `(0.2, NUMERICAL_ASSUMPTION)` and pass the full B1 structural validator.
Selected module and topology revisions and the parameterization ID plus exact
revision are resolved from pinned assets; no ID-only lookup authorizes execution.
All such paths then raise `NumericalAssumptionInputError` with the established
DENIED/B3 diagnostic, before fallback-eligible quality or availability handling.
Malformed quality, source identity, provenance or unsupported fallback cannot
produce geometry-only execution. `explicit_lower_fidelity` is not reinterpreted
as `fail_closed`; both policies still deny numerical assumptions in this stage.

True expresses intent only. B2 physics, provenance evaluation, policy constants,
trusted topology sets, readiness and Level-3 availability are unchanged. There
is no witness, solver permission, worker permission or numerical-assumption
execution. Future B3B/B3C/B3D must complete authenticated acceptance, witnesses,
solver/worker propagation, limitations and independent package verification
before enabling execution.

The new targeted regression file covers strict values, default absence,
configuration identity, legacy module bytes/metadata, selected classification
and corruption denial with both fallback policies, and unselected v0.2 Level 0.
Existing B1/B2 suites remain the coverage for physical policy and capability
non-readiness. No tests, builds or benchmarks were executed by the implementer;
verification is delegated to the orchestrator. No pass result is claimed.
