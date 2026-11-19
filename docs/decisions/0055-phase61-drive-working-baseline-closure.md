# ADR 0055 — Phase-6.1 Drive Working-Baseline Closure and GitHub Synchronization Boundary

**Status:** Accepted  
**Date:** 25 September 2026

## Context

Phase 6.1 was developed on GitHub PR #74, but the hosted GitHub Actions jobs later
began terminating before repository steps executed during a quota/runner-availability
period. The repository source was copied to the project Google Drive folder so
engineering work could continue without weakening the Phase-6.1 validation boundary.

Before Drive closure work began, the Drive repository was compared against GitHub
PR #74 head:

```text
b8d17de8e5973cf93fc892d6865edd4065b525d9
```

All 22 files changed by PR #74 were present in Drive and matched that head exactly
at content/byte level.

The project therefore needs an explicit distinction between closure of the active
Drive working baseline and synchronization/merge of the GitHub transport copy.

## Decision

1. The Google Drive `OpenSIMPV` folder is the active working repository while the
   GitHub Actions execution constraint remains unresolved.
2. Phase 6.1 is **CLOSED for the Drive working baseline** after direct execution of
   the closure-critical checks against Drive-materialized source:

   ```text
   Phase-6.1 focused contract suite       23 passed
   Phase-5 shading-boundary compatibility  6 passed
   Python compileall                       PASS
   Draft 2020-12 closure-critical schemas  9 PASS
   ```

3. This Drive closure does **not** assert that GitHub PR #74 is merged, ready for
   merge, or currently green. The PR remains draft/open/unmerged until its exact
   synchronized head executes the required GitHub workflows successfully.
4. Phase 6.2 may proceed immediately in Drive against the frozen Phase-6.1
   contracts.
5. When GitHub Actions becomes available again, synchronization shall:
   - copy the Drive closure-only documentation changes to the Phase-6.1 branch;
   - run the normal `validation` workflow;
   - run the retained `phase511-closure-validation` workflow;
   - require both workflows to execute repository steps and pass on the exact head;
   - mark PR #74 ready and merge only that exact validated head.
6. GitHub synchronization must not introduce a second Phase-6.1 architecture pass.
   A Phase-6.1 implementation change is justified only by a concrete defect found
   during synchronization or validation.
7. Drive-only project-reference material and generated/runtime artifacts are not
   repository source. In particular, do not synchronize `__pycache__/`, runtime
   cache content under `var/`, or the project specification Google Docs into Git
   unless a later repository decision explicitly changes that rule.
8. During the Drive-primary period, source files shall not be independently edited
   in both Drive and GitHub. Drive is authoritative for new work until a deliberate
   synchronization point is declared.

## Consequences

- Phase 6.1 has a truthful closed state for the active development baseline.
- Phase 6.2 is unblocked in Drive.
- GitHub lifecycle state remains separately visible and cannot be mistaken for a
  completed merge.
- Later GitHub synchronization is a transport/validation operation, not a redesign
  of the electrical-shading boundary.
- If GitHub revalidation exposes a real defect, correct the source in Drive first,
  update the closure handover, and then synchronize the corrected state.

## Frozen architecture retained

This decision changes repository workflow only. It does not change ADR 0054 or any
Phase-6.1 engineering authority:

```text
Scene / ModuleInstance                  geometry authority
ElectricalDesignRevision                connectivity authority
Phase-5 ShadingResult                   geometric shading authority
ModuleTopologyDefinition                optional revision-bound internal topology
validated evidence objects              capability authority
pure capability resolver                derived fidelity only
```

No production mismatch solver is introduced by this closure decision.
