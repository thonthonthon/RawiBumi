# Phase 6.1 Corrective Hardening — Adversarial Test Matrix

**Status:** VALIDATED — Drive working baseline / GitHub CI synchronization pending  
**PR:** #74  
**Scope:** corrective trust-boundary hardening only

This matrix maps each pre-merge corrective requirement to a concrete fail-closed
test. It is a traceability aid, not a substitute for executable CI.

| Boundary | Adversarial input | Required result | Primary test |
|---|---|---|---|
| Parameterization authority | legacy `region_parameterization_available=True` | old boolean API rejected; cannot unlock Level 2 | `test_phase61_trusted_topology_needs_revision_bound_parameterization_evidence` |
| Parameterization module binding | evidence references another ModuleDefinition revision | Level 2 blocked | `test_phase61_parameterization_evidence_fails_closed_when_stale_or_unvalidated` |
| Parameterization topology binding | evidence references another topology revision | Level 2 blocked | `test_phase61_parameterization_scope_and_topology_revision_binding_fail_closed` |
| Parameterization validation | `validation_status != passed` | Level 2 blocked | `test_phase61_parameterization_evidence_fails_closed_when_stale_or_unvalidated` |
| Parameterization provenance | source-less evidence | evidence rejected | `test_phase61_parameterization_evidence_fails_closed_when_stale_or_unvalidated` |
| Parameterization scope | region/sub-string evidence reused as cell evidence | Level 3 blocked; Level 2 may remain available | `test_phase61_parameterization_scope_and_topology_revision_binding_fail_closed` |
| Bypass authority | model object present but unverified | Level 2 blocked | `test_phase61_bypass_model_presence_alone_does_not_unlock_level2` |
| Bypass provenance | component model has no source IDs | Level 2 blocked | `test_phase61_bypass_component_model_without_sources_is_not_execution_ready` |
| Bypass classification | model has no `model_authority` | contract rejected | `test_phase61_bypass_model_authority_semantics_fail_closed` |
| Explicit bypass assumption | explicit assumption with correct identity/rationale | executable but surfaced as assumption, not component truth | `test_phase61_explicit_bypass_assumption_is_executable_but_not_component_truth` |
| Geometry readiness | asymmetric self-intersecting polygon | topology remains structurally intelligible; Level 2 blocked | `test_phase61_self_intersecting_region_is_structural_but_not_execution_ready` |
| Geometry readiness | positive-area region overlap | topology remains structurally intelligible; Level 2 blocked | `test_phase61_positive_area_region_overlap_blocks_execution_but_not_structure` |
| Geometry readiness positive control | adjacent regions share edge/point only | execution readiness remains true | `test_phase61_region_geometry_readiness_separates_structure_from_execution` |
| SDM authority | raw `ModuleDefinition.capability_flags.detailed_sdm_ready=True` | Level 1+ blocked without trusted resolution artifact | `test_phase61_raw_module_capability_flag_cannot_unlock_detailed_sdm_fidelity` |
| SDM model identity | hand-crafted snapshot bool true but selected model is lower fidelity | Level 1+ blocked | `test_phase61_resolved_module_capability_evidence_fails_closed_when_stale_or_fabricated` |
| SDM validation | selected detailed model has failed validation | Level 1+ blocked | `test_phase61_resolved_module_capability_evidence_fails_closed_when_stale_or_fabricated` |
| SDM revision binding | resolved model references another module revision | Level 1+ blocked | `test_phase61_resolved_module_capability_evidence_fails_closed_when_stale_or_fabricated` |
| Resolver purity | raw validated inputs mutated after snapshot/result creation | pure resolver output unchanged | `test_phase61_capability_resolver_is_pure_derivation_over_validated_snapshots` |
| Resolver identity binding | otherwise-valid snapshots from different revisions mixed | Level 2 blocked | `test_phase61_pure_resolver_rejects_cross_revision_snapshot_mixing` |
| Topology inference prohibition | richer cell/bypass/layout counts without explicit topology | no Level-2 unlock | `test_phase61_counts_alone_never_unlock_detailed_topology_fidelity` |
| Topology trust | inferred/auto-validated/wrong-module topology | no Level-2 unlock | `test_phase61_inferred_auto_validated_or_wrong_revision_topology_does_not_unlock_level2` |
| IV point consistency | stored sample has wrong P vs V×I | curve rejected | `test_phase61_derived_artifact_examples_validate` |
| IV global-MPP consistency | declared global MPP is below represented sampled maximum | curve rejected | `test_phase61_derived_artifact_examples_validate` |
| IV local-MPP consistency | declared local candidate is not a represented sampled local extremum | curve rejected | `test_phase61_derived_artifact_examples_validate` |
| IV continuous-curve claim | solver guarantee asserted without basis | curve rejected | `test_phase61_derived_artifact_examples_validate` |
| IV continuous-curve positive control | explicit solver guarantee plus non-empty basis | contract accepts claim as solver declaration; no independent continuous proof is inferred | `test_phase61_derived_artifact_examples_validate` |
| Phase-5 compatibility | Phase-6 electrical configuration sent to Phase-5 geometry worker | fail closed | `test_phase61_phase5_worker_stays_fail_closed_on_phase6_configuration` |
| Fidelity fallback | unsupported fidelity requested under default policy | fail closed; downgrade only via explicit policy | `test_phase61_fidelity_fallback_is_never_silent` |

## Closure validation evidence

The corrective matrix is validated for the Drive working baseline on 25 September
2026. The following checks were executed from source materialized directly from the
Drive repository:

```text
Phase-6.1 focused contract suite       23 passed
Phase-5 shading-boundary compatibility  6 passed
Python compileall                       PASS
Draft 2020-12 closure-critical schemas  9 PASS
```

Before closure-only documentation edits, all 22 files changed by PR #74 matched
GitHub head `b8d17de8e5973cf93fc892d6865edd4065b525d9` exactly at content/byte level.

## Closure rule

For the **Drive working repository**, this matrix is considered **implemented and
validated** because the listed Phase-6.1 adversarial suite and the changed Phase-5
boundary compatibility suite execute successfully against the synchronized source.

For the **GitHub transport**, validation is still pending. PR #74 remains
draft/open/unmerged, and the hosted `validation` and
`phase511-closure-validation` jobs must later execute real repository steps and pass
on the exact synchronized head before the PR is marked ready or merged.

A GitHub workflow that terminates before repository steps execute is not a
validation pass and is not treated as a test failure caused by the code under test.
