# ADR 0032 — Electrical topology editing uses canonical draft entities

**Status:** Accepted  
**Date:** 2026-09-24

## Context

The simulation engine already consumes canonical StringCircuit, MPPTInstance and InverterInstance objects, but the design environment had no editor for producing that topology.

The required interaction creates strings before MPPT assignment, while the historical schema required every StringCircuit to have a non-null target.

Automation must remain optional and must not become a hidden electrical-design authority.

## Decision

1. Phase 4.6 edits ElectricalDesignRevision directly; no parallel UI topology model is authoritative.
2. Canonical draft strings may have `target_mppt_instance_id=null` only while disabled/unassigned.
3. Manual string creation preserves the engineer-supplied series order.
4. A module may belong to only one StringCircuit.
5. Manual MPPT assignment updates StringCircuit and MPPTInstance reciprocally in one atomic command.
6. Verified physical inverter input count is enforced as a structural connector constraint.
7. Adding an inverter derives MPPT instances from the exact pinned inverter revision.
8. Suggest String Length is STC/reference-condition advisory only; temperature/current validation remains Phase 4.7.
9. Create Strings, Assign Strings and Balance MPPT are explicit commands and never run reactively.
10. Existing Phase-3 balanced-assignment helpers are reused rather than duplicated.
11. Assign Strings cannot silently redistribute unselected existing strings; Balance MPPT is the explicit redistribution command.
12. Structural topology consistency is separated from electrical engineering validity.
13. Electrical edits use atomic undo/redo and explicit revision commit.
14. The acceptance suite verifies editor-generated topology directly with the existing simulation topology resolver.

## Consequences

The design environment can author the same canonical topology used by runtime simulation, while incomplete drafts remain representable.

Phase 4.7 can focus on electrical engineering rules rather than fixing topology-authoring semantics.

The editor may intentionally hold disabled unassigned draft strings, but an enabled unassigned string remains a structural error.
