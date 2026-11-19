# ADR 0058 — Phase-6.3 Derived Region Geometry & Irradiance Boundary

**Status:** Accepted  
**Date:** 27 September 2026

## Context

Phase 6.2 makes exact module-topology revisions explicit, project-pinnable and
capability-gated. Detailed electrical shading still needs a deterministic bridge from
the placed module receiver to the physical regions declared by that topology, followed
by local irradiance inputs. This bridge must not become another editable geometry or
electrical-design authority.

## Decision

1. `ElectricalRegionMap` is derived physics data only. It never mutates or replaces
   `SceneRevision`, `CompiledShadingGeometry`, `ModuleTopologyDefinition`, or
   `ElectricalDesignRevision`.
2. Region derivation consumes one exact module-plane receiver and one exact selected,
   project-pinned `ModuleTopologyDefinition` revision bound to that module definition.
3. Intrinsic module topology coordinates remain `module_front_uv_normalized_width_height`.
4. Portrait placement leaves intrinsic UV unrotated. Landscape placement is frozen as
   a 90° clockwise rotation when viewed from the module front because the current Scene
   contract has no separate landscape handedness field.
5. The placement transform convention, source compiled-geometry hash, selected topology
   revision and mapped region geometry participate in the derived map hash.
6. Region-level visibility reuses the established Phase-5 beam, sky and ground kernels.
   The regional query geometry is ephemeral and is not persisted as Scene geometry.
7. Regional geometric output remains a `ShadingResult` with
   `receiver_granularity = electrical_region` and
   `electrical_shading_scope = not_modeled`.
8. Beam, sky-diffuse and ground-reflected channels remain separate through local
   irradiance derivation.
9. Local irradiance ordering is `unshaded POA × geometric visibility × explicit optical
   modifier`. Optical correction is never inferred from a geometry factor.
10. Default optical modifiers are unity; non-unity modifiers must be explicit caller
    inputs. This contract does not silently reapply IAM or another optical model.
11. Local irradiance uses the Phase-6.1 `single_module_temperature` thermal scope.
12. Map/result identity mismatches, stale revision binding, missing region receivers,
    and invalid numeric ranges fail closed.
13. Phase 6.3 introduces no region electrical parameter derivation, bypass solver,
    module/string IV solver, or MPPT solver.

## Consequences

- topology and geometry remain independent authorities connected by a reproducible
  derived artifact;
- landscape topology mapping is no longer ambiguous for v0.1 projects;
- Phase-5 visibility kernels can be reused at region resolution without redefining
  their scientific semantics;
- later mismatch physics receives explicit per-region irradiance rather than an
  unexplained module shaded-area percentage;
- future changes to orientation mapping require an explicit contract/version change
  rather than silently changing existing results.
