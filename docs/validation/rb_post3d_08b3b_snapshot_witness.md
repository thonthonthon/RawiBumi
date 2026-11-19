# RB-POST3D-08B3B snapshot witnesses

B3B adds verifiable content transport and corrects the two B3A regressions.
It does not enable numerical-assumption execution. Selected v0.2 inputs remain
invalid for execution with `NUMERICAL_ASSUMPTION_EXECUTION_DENIED`, including
when scientific opt-in is true or explicit lower-fidelity fallback is requested.

## Structure and binding origins

`SnapshotWitnessContext` holds immutable canonical scientific-configuration
bytes, their SHA-256 identity, and the actual immutable
`FrozenDetailedSelectionSnapshot`. `AssumptionSnapshotWitness` holds a reference
to that shared context and separate module membership fields:

| Binding | Repository authority and validation |
| --- | --- |
| Scientific configuration | Existing `detailed_dispatch.scientific_configuration` projection, `semantic_scientific_payload`, and canonical JSON SHA-256, identical to the context `simulation_configuration` fingerprint algorithm |
| Frozen selection | Actual canonical payload, `payload_sha256`, and `scientific_input_sha256`, independently recomputed by structural frozen replay |
| Module membership | Validated `electrical_shading_selections` entry, registry key, actual ModuleDefinition identity and revision |
| Topology membership | Selection's topology revision, pinned topology registry entry, actual topology identity/revision and declaration's canonical topology digest |
| Parameterization membership | Evidence's `parameterization_revision_id` resolves the registry entry; definition revision, ID, module/topology/model bindings and payload digest must agree |
| Evidence | Exact selected evidence ID, full canonical evidence SHA-256, B1 structural and cross-field checks |
| Assumption and consistency | Recomputed B1 declaration and consistency digests and their cross-link, retained explicitly in the membership record |
| Source registry | Exact registry in the five-key payload and frozen bytes; existing source-record validator checks the distinct original/retained PAN records and assumption record/digest |
| Effective opt-in | Strict `validate_synthetic_region_option` on the canonical scientific configuration; missing means false, only literal booleans are accepted |
| Exact payload | Five-key module-input SHA-256 and byte equality with the assets resolved from the selected registries, including sources |

Module, topology and parameterization identifiers are also retained in their
complete canonical selected records. Revision binding is never an ID-only lookup.
Source metadata does not grant permission. PAN fingerprints are recorded-content
integrity assertions; the witness builder does not open source filenames or
claim verification of unavailable original PAN bytes or externally certified
human authorship.

## Construction and trust boundaries

`build_snapshot_witness_context(configuration, frozen_selection)` validates the
scientific electrical configuration schema and strict option, applies the
existing scientific projection, and verifies the frozen bytes and persisted
selection identity. `build_detailed_snapshot_witness(context, module_revision_id)`
revalidates that context, resolves the exact selected assets, validates their
schemas and recorded bindings, and derives membership and effective opt-in.
Neither function takes an authorization boolean. Both false and true effective
values can be transported; neither yields execution permission.

The input provider must independently establish that the supplied configuration
and frozen selection belong to the intended run. These functions validate
content, not external origin. The internal `_replay_structure` path permits
inspection of v0.2 selections to construct witnesses without calling the public
execution-denying replay path. It grants no readiness or execution permit and
does not perform B2 physical acceptance. Public freeze, pin, frozen replay and
module replay continue to deny selected numerical evidence.

Zero-argument `DetailedModuleInputSnapshot.replay()` validates an attached
witness before its ordinary payload validation. It rederives all membership
fields, verifies canonical configuration and frozen hashes, enforces literal
boolean type and exact payload membership, and rejects invalid types, substituted
revisions, digests, foreign module membership and contradictory effective opt-in.
`SnapshotWitnessError` is a ValueError subclass, deliberately distinct from
fallback-eligible `DetailedInputError`.

`compare_snapshot_witness_context(witness, configuration, frozen_selection)`
compares the witness against separately supplied expected scientific inputs.
It rejects foreign configuration or selection even when the witness is internally
self-consistent. It rederives module membership as well. The caller must obtain
these expected inputs independently of the witness; passing the witness's own
contents proves only consistency. The comparator produces no execution permit.

An external caller can reconstruct a fully self-consistent witness and hashes.
Replay cannot independently prove where such content originated. It still ends
in unconditional numerical execution denial. Content hashes are not a
cryptographic signature, account authentication, manufacturer signature or
externally authenticated producer identity. Production execution must eventually
compare membership against independently trusted execution context and enforce
all deferred B3 gates.

## Compatibility and immutable sharing

The optional third module snapshot field `witness` defaults to None and is
excluded from repr. Historical two-argument construction and zero-argument
replay remain valid. Default snapshots retain their historical equality/hash
behavior; attached witnesses are immutable, hashable dataclasses whose content
participates in equality. There is no new serialized payload field.

The five-key canonical module payload, legacy byte algorithm,
`scientific_input_sha256` and attribution source-module-input hashes are
unchanged. No witness is inserted into existing persisted source-module-input
records. A numerical witness attached to a legacy payload fails exact membership
comparison. No changes are made to detailed_downstream.py.

Create one context per actual configuration/frozen-selection pair and reuse it
when constructing module witnesses. Module snapshots then share the same
configuration bytes and frozen payload bytes by object identity; only membership
records differ. There is no global interning or memoization cache, mutable
permission state, secret token or signature. Frozen dataclasses and bytes can be
shared safely between threads; serialization within one object graph can preserve
sharing across process transport. Independently serialized messages need not
preserve object identity. Worker integration and reauthentication remain deferred.
Replay currently revalidates content rather than caching successful checks;
B3B makes no replay-cost or pilot-budget claim.

## B3A corrections and denial ordering

Frozen replay first checks hashes, canonical structure and the existing persisted
selection validator. It then applies selection-scoped numerical denial, before
quality validation and parameterization registry validation. String selections,
list evidence IDs and missing identity fields therefore preserve meaningful
selection diagnostics and raise controlled ValueError-compatible failures.
Additional identifier checks guard mapping-key access after structural validation.
The denial helper also validates structure when called directly.

The previous denial path called the executable v0.1 evidence-binding validator,
which inherently rejects even valid v0.2 evidence. The new recorded-binding
helper compares exact definition revision, parameterization ID, module/topology
bindings, model/version and payload digest without changing executable readiness.
A schema-valid selected v0.2 record now reaches the final explicit diagnostic
that authenticated execution is not enabled. Malformed quality still receives
numerical denial before fallback-eligible quality validation.

Dispatch relies on frozen `record()` validation and classifies these errors as
invalid inputs. The redundant denial after successful `record()` is removed.
Neither fallback policy can downgrade selected numerical evidence to geometry.
Unselected v0.2 evidence continues to allow unrelated legacy Level-0 operation;
ordinary v0.1 runtime availability and fallback semantics remain unchanged.

## Test design and verification status

The new targeted test module covers legacy constructor/replay/payload/hash
compatibility, each witness identity, revision and digest, strict and absent
opt-in, invalid witness types/structures, foreign self-consistent contexts,
rehashed configuration contradictions, two-module shared byte-object identity,
foreign module membership, public malformed-selection replay/freeze/dispatch,
schema-valid v0.2 dispatch denial under both policies, malformed quality ordering,
legacy fallback, unselected v0.2 Level-0 and unchanged detailed readiness.

Fixtures are small deterministic B1 records with actual selected module,
topology and parameterization revisions and resealed declaration/consistency
bindings. Schema acceptance is asserted before dispatch mutations. These stored
sample records are contract fixtures, not evidence of B2 physical acceptance or
real yield. No execution authorization is mocked into a PASS.

No tests, builds, benchmarks or verification commands were executed by the
implementer, as required by the active task. Results and acceptance remain
pending orchestrator verification and Claude independent review. No 190-module
pilot, weather acquisition, Git staging, commit, push or branch change occurred.

## Deferred obligations and nonexecution boundary

B3C must integrate permission propagation through production series-module
adapters, regional execution and detailed backend boundaries, serial attribution,
process-worker attribution, and worker fail-closed classification. Production
parameterization resolution and witness attachment are not changed by B3B.

B3D must independently verify persisted packages, freshly recompute all B2
physics/provenance gates with no producer PASS authority, validate execution
limitations, and establish final trusted-boundary authorization before conditional
Level-2 activation. Retained source bytes must be checked where available.
The approved SD1 decision uses the verifier's installed implementation identity
and fresh scientific recomputation; it does not establish the exact historical
producer solver build or historical bitwise reproducibility.

Trusted topology classifications, validated-source classes, B2 physical policies,
electrical solvers, package verification and attribution workers remain unchanged.
There is no new Level-3 readiness and no numerical-assumption Level-2 activation.
B3B acceptance alone cannot constitute full B3 authorization or independent
verification acceptance.
