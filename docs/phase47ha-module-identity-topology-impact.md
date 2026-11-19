# OpenSIMPV — Phase 4.7H-A Module Identity and Topology Impact Hardening

**Status:** Implementation specification  
**Date:** 2026-09-24  
**Parent:** Phase 4 Engineering Design Environment

## 1. Problem

Phase 4.3 originally generated module IDs from occupied row/column order:

```text
<field-id>-r<occupied-row>-c<occupied-column>
```

That representation was deterministic, but it did not provide safe cross-revision object identity.

After an explicit rebuild, the same row/column address could refer to a physically different generated placement. Existing `StringCircuit.module_instance_ids` could therefore continue resolving while silently referring to different physical modules.

That violates the Phase-4 requirement that geometry and electrical engineering intent remain reproducible and explicit.

## 2. Frozen identity rule

For **generated field rebuilds**:

```text
same generated physical placement
→ existing ModuleInstance ID may survive

changed/new generated physical placement
→ new deterministic ModuleInstance ID
```

Fresh generated IDs use:

```text
<field-id>-m-<placement-hash-prefix>
```

The placement fingerprint currently includes:

- PV field ID;
- support surface ID;
- canonical XY position;
- generated azimuth;
- portrait/landscape orientation;
- field tilt;
- mounting height;
- identity algorithm version.

The fingerprint intentionally excludes:

- component revision ID;
- physical module dimensions;
- canonical Z.

A same-placement component revision change can therefore keep module identity while still requiring electrical/design revalidation. Canonical Z is excluded until Phase 4.7H-C resolves the remaining 2D/3D height semantics.

## 3. Backward compatibility

Existing Phase-4.3 row/column IDs are not discarded merely because the identity algorithm changed.

During an explicit rebuild:

```text
legacy module
+
new generated placement
+
identical placement fingerprint
        ↓
preserve legacy ModuleInstance ID
```

This prevents a no-op rebuild from invalidating existing string topology.

Once a placement changes, the old ID is not reassigned to the new location.

## 4. Packing lineage versus identity

Grid lineage remains useful for explaining a rebuild.

Generated modules retain:

```text
grid_row_index
grid_column_index
```

These form a deterministic packing-slot key used to pair old/new placements in the impact report.

They are **not** the canonical ModuleInstance identity.

This separation allows OpenSIMPV to say:

```text
same generated slot
moved from A to B
old ModuleInstance ID invalidated
new ModuleInstance ID created
```

without silently treating A and B as the same physical placement.

## 5. PVFieldLayoutImpactReport

Every explicit repack can now produce a deterministic read-only report containing:

```text
retained_module_ids
moved_modules
removed_module_ids
added_module_ids
invalidated_module_ids
affected_strings
topology_status
impact_hash
```

The report is available from normal packing commands and component-driven field rebuilds.

### Retained

The same ModuleInstance ID exists before and after and has the same placement fingerprint.

### Moved

A deterministic packing slot exists before and after, but its physical placement changed.

For generated rebuilds this normally means:

```text
old ID != new ID
```

### Removed / added

No deterministic slot pairing exists.

### Invalidated

Old module IDs that no longer resolve to the rebuilt Scene.

## 6. Electrical topology rule

The layout-impact analyzer may inspect an ElectricalDesignRevision, but it never mutates it.

If a string still references invalidated IDs:

```text
topology_status = review_required
membership_status = stale_reference
```

The report exposes:

- affected string ID;
- invalidated referenced module IDs;
- module IDs unresolved in the rebuilt Scene.

The engineer must explicitly repair or recreate string membership.

OpenSIMPV does **not** automatically:

- substitute new modules into strings;
- preserve a string by row/column coincidence;
- rebalance MPPTs;
- rewrite topology during geometry operations.

## 7. Component-driven rebuilds

`ComponentDesignSession.apply_module_revision_and_rebuild_field()` now emits both:

```text
component revision impact
+
layout/topology impact
```

This closes the previous gap where a component revision rebuild could alter module placement/count without a canonical description of which existing string memberships had become stale.

## 8. Manual movement boundary

Phase 4.7H-A governs **generated rebuild replacement** semantics.

It does not yet define the final identity rule for an engineer explicitly dragging a module.

That is Phase 4.7H-B.

The intended distinction is:

```text
generated rebuild
→ replacement semantics

explicit manual move
→ engineer-authored object edit
```

The latter may legitimately preserve object identity while changing geometry, provided the edit and resulting conflicts are explicit.

## 9. Determinism

For identical authoritative inputs and identity algorithm version:

- fresh generated module IDs are identical;
- layout impact classification is identical;
- affected string ordering is identical;
- impact hash is identical.

Impact analysis is read-only.

## 10. Regression gate

Automated tests cover:

- deterministic placement-derived IDs;
- uniqueness of generated IDs;
- stored placement fingerprints;
- unchanged rebuild preserving legacy row/column IDs;
- changed spacing invalidating only changed placements;
- deterministic old/new slot pairing;
- stale StringCircuit reference reporting;
- no automatic ElectricalDesignRevision mutation;
- layout-impact schema validity;
- deterministic layout-impact hash.

## 11. Exit criterion

Phase 4.7H-A is complete when an explicit generated field rebuild can no longer silently reuse a ModuleInstance identity for a different generated physical placement, and any resulting stale string membership is deterministically reported without automatic electrical redesign.

Next hardening phase:

```text
4.7H-B — Manual module and vertex editing semantics
```
