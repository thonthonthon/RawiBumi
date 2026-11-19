# RB-POST3D-08B1 numerical assumption evidence foundation

## Scope and accepted references

This stage implements only versioned evidence structure and deterministic stored-value integrity. Binding references are `.ai/TASK.md`, the RB-POST3D-08A region provenance audit, the approved RB-POST3D-08B implementation traceability audit, and SD1–SD4 in `.ai/TASK.RB08B_IMPLEMENTATION_FROZEN.md`. The active B1 task restricts implementation to four paths. Later-stage execution requirements remain mandatory deferred work.

## Legacy v0.1 compatibility

The original schema property definitions, required fields, enums and optional metadata are retained in `$defs/v0_1`. Explicit version dispatch selects that definition. The existing production evidence validator, provenance sets, capability logic and canonical serializer are unchanged. Arbitrary legacy metadata, including `metadata.numerical_assumption`, remains accepted and grants no additional authority. No persisted records are migrated or rewritten.

## v0.2 evidence envelope

The strict v0.2 definition inherits common binding, model, payload, source, quality, notes and metadata properties. It adds exactly `evidence_class`, `parameterization_revision_id`, `assumption_declaration` and `consistency_record`. It requires schema version `0.2`, contract version `0.1`, class `NUMERICAL_ASSUMPTION`, provenance `simulation_assumption`, both status fields `not_applicable`, and a null validation record. It cannot impersonate manufacturer validation. The schema ID remains unchanged.

## Typed assumption declaration

The declaration includes identity/revision, accountable source ID, author, rationale, evidence class, module source (including distinct original and retained PAN digests), topology identity/revision/digest, parameterization identity/revision/digest, integer region count 3, limitations and its digest. All listed fields are required; every typed object rejects extra fields. Authorship is supplied evidence, not manufactured by validation or treated as a signature.

All eight canonical disclosures from traceability section 8 must form the exact ordered prefix, including punctuation. Additional unique meaningful disclosures may follow in Unicode lexical order. No category is inferred from prose.

## Typed consistency record

Policy is `rawibumi.level2.uniform_iv_equal_series`, version `1.0.0`, model family `pvsyst_sdm`, absolute tolerance `0.0001 V`. Cases must be exactly `(1000,25)`, `(800,45)`, `(400,15)` in order, with exactly five ascending nonnegative current samples each. Required sample fields retain voltage units and signed residual semantics.

B1 checks exact recorded arithmetic: residual equals assembled voltage minus module voltage, and aggregate maximum equals the maximum of all fifteen absolute residuals. A recorded true result requires maximum at or below tolerance. False is permitted even with small residuals because the full policy includes physical and source gates not evaluated here. This necessary-condition interpretation follows the planning recommendation; a recorded flag is never independent physical PASS evidence.

The required current fractions are 0.10, 0.30, 0.50, 0.70, 0.90 of computed whole-module Isc. B1 validates count and ascending order only. Computing Isc and checking actual fractions require the B2 kernels. JSON numeric types reject booleans; semantic checks reject nonfinite values and negative zero. Region count must be a Python integer, so 3.0 is rejected at this boundary.

## Deterministic digests

`numerical_assumption_object_sha256` applies the existing `_canonical_sha256` procedure to a copy excluding only the object's own `digest_sha256`. Every other supplied field remains bound. Serialization uses sorted keys, compact separators, `ensure_ascii=False`, `allow_nan=False` and UTF-8, followed by lowercase SHA-256 hex. Numbers are serialized as supplied; 1 and 1.0 retain their different canonical bytes. No defaults are inserted and caller data is not mutated.

## Cross-field validation

`assert_numerical_assumption_evidence_structure` performs strict schema and semantic validation separately from readiness. Envelope class, parameterization ID/revision/payload digest, module revision and topology revision must match declaration values. The consistency record must reference the recomputed declaration digest. Both object digests are recomputed. PAN/topology/parameterization digests require lowercase 64-hex format. Format and intra-record equality do not establish asset fingerprint authenticity.

## Tests and compatibility evidence

The new unit module covers legacy acceptance and nonmutation, metadata-neutral readiness, schema structure, valid v0.2, missing and extra properties, forged statuses, digest formats, each bound leaf mutation, cross-field bindings, limitations, case/sample ordering, numeric failures, signed residuals, maximum and forged PASS. Capability regressions use both trusted and untrusted topology and both region and cell evidence. They check that production validators deny execution and no Level-2 or Level-3 readiness is gained.

Tests were **not executed by the implementer**, per the active task. Orchestrator verification should run the new module plus existing Phase-6.1 contract and schema-registry regressions. No test success is claimed here.

## Deferred provenance and physics

Selected asset fingerprints, SourceRecord resolution and revision binding, authenticated scientific opt-in, whole-module and regional numerical reevaluation, exact Isc fractions, secondary conservation/bypass/thermal gates, worker permission transport, persistence and verifier integration remain deferred. No solver, scientific model, manufacturer data, source registry or runtime fallback behavior is changed.

## Explicit nonexecution boundary

The production `assert_electrical_parameterization_evidence` remains v0.1-only. Structurally valid v0.2 therefore raises `ElectricalShadingContractError`, produces parameterization readiness false, and fails executable binding with a ValueError rather than a fallback-eligible DetailedInputError. Schema acceptance through consumers referencing the schema ID grants no execution permission. Trusted topology cannot overcome denied parameterization readiness; assumed topology remains untrusted. No full Level-2 READY or assumption-backed Level-3 capability is granted.

## Reproducibility and acceptance verdict

Fixtures are deterministic synthetic contract data, without module-array simulation, weather acquisition or benchmarks. Digest tests use the approved byte algorithm and Unicode content. The changes add no dependency and leave branch/HEAD untouched.

Implementation is submitted for orchestrator verification and read-only review. Final acceptance remains pending targeted tests, existing regressions, and zero blocker/major review findings. This is not full RB-POST3D-08B completion, numerical execution authorization, manufacturer topology confirmation, or physical-yield validation.
