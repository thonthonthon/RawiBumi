# ADR 0039 — Canonical Design-State Package Is the Phase-4 Save/Reopen Boundary

**Status:** Accepted  
**Date:** 2026-09-24  
**Decision scope:** Phase 4.9C

## Context

Phase 4 already separates:

```text
canonical engineering state
≠
editor/UI workspace state
```

Phase 4.8 also established that simulation consumes revision-pinned canonical objects rather than DesignWorkspaceState.

Phase 4.9C requires a concrete save/reopen contract that can prove engineering-state identity across application sessions.

## Decision

OpenSIMPV uses a deterministic canonical design-state package as the Phase-4 persistence boundary.

The package contains:

```text
Scene
ElectricalDesignRevision
ProjectRevision
SimulationConfiguration
DesignValidationReport
```

It does not contain UI-only state.

Weather and component payloads are not duplicated into this package. Their immutable revision identities remain pinned by the canonical objects and are resolved through the revision store.

Each saved object is canonical-hashed. A second package hash protects the object-hash set.

Reload fails closed when hashes or revision relationships no longer reconcile.

## Consequences

### Positive

- save/reopen can be regression-tested independently from frontend implementation;
- UI changes cannot silently change simulation state;
- stale validation evidence is detectable;
- existing revision architecture remains authoritative;
- canonical state can be reproduced in self-hosted and future hosted deployments.

### Deliberate limitations

The package is not:

- a repository/database implementation;
- a backup format guarantee for every future version;
- a container for raw component/weather source files;
- a serialization of undo history or camera state;
- a substitute for schema/version migration.

Future storage implementations may use database rows, archives, object storage, or another transport, provided they preserve the same canonical objects, revision relationships and integrity behavior.
