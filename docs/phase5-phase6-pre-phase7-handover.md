# RawiBumi — Phase 5 & Phase 6 Stabilization and Pre-Phase-7 Handover

**Date:** 30 September 2026  
**Status:** Active stabilization / pre-Phase-7 plan  
**Authoritative working repository:** Google Drive `RawiBumi`  
**Execution / validation runner:** Google Colab  
**GitHub:** not required for the current development workflow; branching/version-control workflow may be introduced later when the software baseline is substantially complete or parallel development requires it.

---

## 1. Purpose

This handover defines the work required before RawiBumi enters Development Phase 7.

The objective is not to add new scope to Phase 5 or to rewrite the Phase-6 engineering roadmap. The objective is to:

1. restore a clean Phase-5 regression baseline after the OpenSIMPV → RawiBumi migration;
2. reconcile and close the implemented Phase-6.1–6.4 work on the authoritative Google Drive baseline;
3. integrate the new UI-A browser workspace without moving physics authority into the UI;
4. continue the already-defined Phase-6.5–6.12 electrical-shading / high-fidelity DC sequence;
5. freeze a reproducible Drive snapshot before Phase 7 begins.

The governing maturity boundary remains:

```text
Phase 6
= validated PV physics + testable browser vertical slice

Phase 7
= coherent grid-connected V1 product
```

Phase 7 remains responsible for broader product completeness and coherence: complete workflow refinement, onboarding, report generation, comprehensive result exploration, long-running job UX, error UX, and removal of normal-grid-connected product gaps.

---

## 2. Current baseline

### 2.1 Phase 5

The Phase-5 geometry-aware shading architecture remains valid and shall not be redesigned.

The full current Drive baseline was executed in Google Colab:

```text
655 tests collected
626 passed
29 failed
```

The 29 failures have been reduced to a small number of migration-related root causes.

The primary cascade is caused by accidental renaming of frozen canonical weather-provenance values:

```text
rawibumi_derived
rawibumi_transformation
```

where the frozen v0.1 canonical contract requires:

```text
opensimpv_derived
opensimpv_transformation
```

That schema mismatch causes the canonical SimulationRun to fail before numerical execution and explains the downstream Phase-5.5–5.9 failures.

Other failures are stale migration expectations, including:

- Phase-3.8D test expecting `OpenSIMPV_warning_only_gross_exceedance` while the active product-facing QC identifier is RawiBumi-branded;
- Phase-6.0C test expecting API phase `6.0D` while the current API reports `6.4`;
- Phase-6.2 tests still using old synthetic IDs such as `mod-opensimpv-*`, `topology-opensimpv-*`, and `assumption-opensimpv-*`;
- weather tests expecting renamed canonical provenance rather than the frozen v0.1 provenance token.

No evidence currently indicates a Phase-5 beam, sky, ground, annual-shading, or electrical-chain physics defect.

### 2.2 Phase 6

Current engineering progression:

```text
6.0A  Product-readiness contract                  CLOSED
6.0B  Weather acquisition foundation              CLOSED
6.0C  Browser site/scene shell                    CLOSED
6.0D  Browser UAT vertical slice / Gate A         CLOSED
6.1   Electrical-shading canonical contract       CLOSED on Drive baseline
6.2   Module topology / capability integration    IMPLEMENTED
6.3   Electrical regions / local irradiance       IMPLEMENTED
6.4   Level-1 module electrical shading           IMPLEMENTED
6.5+  Detailed mismatch/bypass chain              not yet authoritative
```

A previous focused validation exercise for Phase 6.2–6.4 passed 109 tests plus schema, compile, and TypeScript checks. However, the later full-suite run exposed migration regressions elsewhere in the current tree. Therefore Phase 6.2–6.4 shall be revalidated on the cleaned authoritative Drive baseline before being treated as closed.

### 2.3 UI-A staging

Staging location:

```text
apps/web/ui-a/
```

The staging package is:

```text
@rawibumi/web
version 0.2.0-ui-a
```

It adds:

```text
@fontsource/barlow
@fontsource/barlow-semi-condensed
dev:demo
build:demo
```

The staged UI is already visibly RawiBumi-branded in the audited product-facing surfaces:

```text
HTML title       = RawiBumi
start screen H1  = RawiBumi
workspace brand  = RawiBumi
package name     = @rawibumi/web
```

No `OpenSIMPV` / `opensimpv` hit was found among the staged UI-A source-file IDs during the current audit.

Therefore UI-A does **not** presently appear to require a visual product rename. A complete active-source branding audit shall still be included in the integration gate.

UI-A intentionally omits:

```text
apps/web/src/types.ts
apps/web/src/api.ts
apps/web/tsconfig.json
apps/web/vite.config.ts
```

The existing versions remain authoritative.

---

# 3. Working repository and validation model

## 3.1 Authoritative source

Until a later version-control workflow is introduced:

```text
Google Drive / RawiBumi
= authoritative working source tree
```

Google Colab is the execution environment, not the source authority.

Recommended validation pattern:

```text
Google Drive source
    ↓ copy
/content/RawiBumi
    ↓
dependency install
    ↓
pytest / benchmark / TypeScript / Vite
    ↓
validation evidence
    ↓
immutable validation snapshot / report in Google Drive
```

Running from a local `/content/RawiBumi` copy is preferred because it avoids Drive I/O overhead and prevents test-generated artifacts from dirtying the authoritative source tree.

## 3.2 Closure identity without Git commits

Because Git commits are not currently the working identity mechanism, every closure checkpoint shall record a reproducibility manifest containing at minimum:

```text
snapshot name
timestamp
Python version
Node version
npm version
requirements files
installed critical package versions
full source-file SHA-256 manifest
pytest command and result
benchmark / validation commands and results
TypeScript result
Vite build result
demo build result
known compatibility identifiers
known intentionally preserved historical identifiers
```

A Drive snapshot plus complete source-file SHA-256 manifest becomes the exact validated identity.

Historical Git/PR/SHA references remain historical provenance and shall not be rewritten.

---

# 4. Phase 5 — Stabilization and final closure

## Phase 5-R0 — Freeze the repair baseline

Before modifying migration defects:

1. create a named Drive snapshot or archive of the current tree;
2. record the current `626 passed / 29 failed` result;
3. preserve the diagnostic output proving the Phase-5 cascade is caused by canonical weather-schema rejection;
4. do not change shading equations or numerical models.

**Exit:** exact pre-repair state recoverable.

---

## Phase 5-R1 — Restore frozen canonical provenance vocabulary

Repair only the canonical provenance regression.

Required canonical tokens:

```text
series_origin:
    opensimpv_derived

upstream_generation.evidence:
    opensimpv_transformation
```

These identifiers are frozen serialized-contract values, not product branding.

Required work:

- restore weather resampling writer to `opensimpv_derived`;
- restore transformation evidence to `opensimpv_transformation`;
- remove `rawibumi_derived` from active canonical writer behavior;
- ensure `weather.core` and JSON Schema agree;
- update tests to validate the frozen contract;
- do not broaden the schema merely to accept both names unless a separately justified compatibility requirement exists.

**Exit:** the Phase-5.5 diagnostic SimulationRun no longer fails with `CANONICAL_SCHEMA_INVALID`.

---

## Phase 5-R2 — Correct stale rebrand expectations

Repair migration-test drift without changing physics.

Known corrections include:

```text
Phase-3.8D QC screen identifier
    OpenSIMPV_warning_only_gross_exceedance
    → RawiBumi_warning_only_gross_exceedance

Phase-6.0C API health expectation
    6.0D
    → current active phase value

current synthetic Phase-6 UAT IDs
    mod-opensimpv-*
    topology-opensimpv-*
    src-opensimpv-*
    assumption-opensimpv-*
    → corresponding rawibumi-* IDs
```

Apply these only where the identifiers represent current product-owned synthetic assets.

Do **not** globally replace `opensimpv`.

---

## Phase 5-R3 — Frozen-name classification gate

Before full regression, classify every remaining active `OpenSIMPV` / `opensimpv` occurrence into one of two buckets.

### Rename to RawiBumi

Rename when the identifier is current product identity, active UI copy, current synthetic UAT identity, current package identity, active API metadata, or active current-document title.

### Preserve

Preserve when the identifier is a frozen or historical compatibility surface, including examples such as:

```text
opensimpv_derived
opensimpv_transformation
opensimpv.dataframe.logical.v0.1
opensimpv.design_state_package.v0.1        legacy reader
OPENSIMPV_PROJECT_STORE                    legacy environment alias
opensimpv.beam_shadow.*                    frozen solver/model identity
opensimpv.sky_visibility.*
opensimpv.ground_visibility.*
historical ADR / Phase-5 documents
historical Git / PR / SHA references
external PVsyst filenames
.pvproj
```

**Exit:** remaining old-name occurrences are explainable by an allowlist, not accidental migration residue.

---

## Phase 5-R4 — Targeted regression

Run the smallest suite covering all known migration failures first:

```text
Phase 3.8D solar/weather QC
weather foundation
temporal execution
Phase 5.5
Phase 5.6
Phase 5.7
Phase 5.8
Phase 5.8H
Phase 5.9
Phase 5.11 closure
Phase 6.0C shell
Phase 6.2 catalog / topology / project shading state
```

Required result:

```text
0 failures in the previously failing clusters
```

Do not proceed to a full run while a known targeted failure remains.

---

## Phase 5-R5 — Full regression gate

Run:

```bash
python -m pytest -q
```

Required result:

```text
all collected tests pass
0 failures
```

Record:

- exact test count;
- runtime;
- Python version;
- relevant package versions;
- source-tree manifest identity.

---

## Phase 5-R6 — Phase-5 benchmark and validation gate

Execute the repository's existing Phase-5 closure evidence, including the existing:

- Phase-5.8 benchmark;
- Phase-5.8H benchmark/hardening evidence;
- Phase-5.9 annual benchmark;
- Phase-5.10 analytical/external validation;
- Phase-5.11 closure benchmark/regression.

Do not invent new acceptance tolerances.

Required result:

```text
reference vs accelerated parity remains inside frozen tolerances
no numerical regression caused by rebranding
```

---

## Phase 5-R7 — Close Phase 5 on the Drive baseline

Create:

```text
rawibumi-phase5-validated
```

or an equivalent immutable snapshot.

Record:

```text
full suite green
Phase-5 benchmark/validation green
canonical object/hash invariants preserved where branding is non-canonical
legacy package read compatibility preserved
new package write namespace = rawibumi.design_state_package.v0.1
frozen solver/provenance identifiers explicitly allowlisted
```

**Phase-5 exit:**

```text
Geometry-aware simulation baseline is clean,
reproducible, migration-safe, and ready to be consumed by Phase 6.
```

---

# 5. Phase 6 — Reconciliation before new detailed physics

## Phase 6-R0 — Replace the obsolete GitHub-dependent closure assumption

Historical Phase-6 validation documents that required GitHub Actions remain historical evidence.

For current work, use:

```text
VALIDATED
= tests/build/validation green on one exact Drive source manifest

INTEGRATED
= that exact validated source is the authoritative Drive working tree

CLOSED
= milestone exit criteria are met and closure evidence points to the exact Drive manifest
```

Do not rewrite old historical CI reports merely to remove GitHub language.

Create new current closure evidence that supersedes GitHub availability as a requirement.

---

## Phase 6-R1 — Revalidate Phase 6.1–6.4 on the repaired Phase-5 baseline

Run the existing focused suites for:

```text
Phase 6.1 contract/adversarial boundary
Phase 6.2 topology/capability integration
Phase 6.3 electrical regions/local irradiance
Phase 6.4 Level-1 module electrical shading
module electrical engine
string/MPPT
Phase-5 beam/sky/ground upstream regression
```

Also run:

```text
JSON Schema Draft 2020-12 validation
Python compile/import validation
web TypeScript typecheck
normal Vite build
```

Required result:

```text
Phase 6.1–6.4 green on the same exact source manifest
```

Then update the current Phase-6 status anchor so 6.2–6.4 are no longer left in a historical "CI pending" state.

---

# 6. Phase 6.UI-A — Browser workspace integration checkpoint

This checkpoint sits **between Phase 6.4 and Phase 6.5**.

It adds no PV physics and does not renumber the engineering physics tranches.

## 6.UI-A.1 Merge staging into the active browser

Merge:

```text
apps/web/ui-a/src/*
→ apps/web/src/
```

Preserve the existing:

```text
apps/web/src/types.ts
apps/web/src/api.ts
apps/web/tsconfig.json
apps/web/vite.config.ts
```

Replace:

```text
apps/web/package.json
```

with the UI-A package definition.

Add:

```text
apps/web/.env.demo
```

Run:

```bash
npm install
```

and commit the resulting `package-lock.json` equivalent into the authoritative Drive tree.

The lockfile must not remain stale after changing package dependencies.

---

## 6.UI-A.2 Branding and namespace audit

Verify all active product-facing UI source uses:

```text
RawiBumi
@rawibumi/web
VITE_RAWIBUMI_DEMO
```

Do not rename frozen backend compatibility IDs merely because they contain `opensimpv`.

Current preliminary audit indicates UI-A itself is already RawiBumi-branded.

---

## 6.UI-A.3 Compile and build gates

Required:

```bash
npm run typecheck
npm run build
npm run build:demo
```

Both normal API mode and demo mode must build.

---

## 6.UI-A.4 Authority / safety gate

UI-A must preserve the existing architecture:

```text
browser gesture
→ API command
→ canonical Python/domain authority
→ revisioned state
```

The UI must not independently calculate authoritative:

- PV packing;
- electrical topology;
- weather projection;
- solar position;
- POA;
- shading physics;
- module IV;
- inverter conversion;
- loss accounting.

Controls marked `Not wired` may maintain local visual/draft state but shall not silently enter canonical simulation inputs.

This boundary is mandatory.

---

## 6.UI-A.5 Browser UAT

Validate the existing Gate-A workflow through the new UI:

```text
create/open project
→ site coordinate
→ map or blank plane
→ support surface
→ obstacle
→ PV field
→ component selection
→ inverter
→ strings
→ MPPT assignment
→ weather acquisition
→ readiness
→ simulate
→ monthly energy / loss ledger / assumptions
→ save
→ reopen
```

Also validate demo mode separately; demo values remain explicitly synthetic.

---

## 6.UI-A.6 Cleanup

Only after successful build/UAT:

- delete obsolete `LocalPlan.tsx` if it remains unreferenced;
- remove staging-only duplication when the integrated source has been independently verified;
- keep `apps/web/ui-a/` temporarily if needed as rollback evidence, otherwise archive it rather than silently deleting the only known-good staging copy.

---

## 6.UI-A.7 Full regression after UI merge

Run the complete Python suite again plus the web build gates.

The UI merge must not change scientific results.

**Exit:**

```text
new UI-A is the active RawiBumi browser shell
without changing engineering/physics authority
```

---

# 7. Continue the existing Phase-6 physics roadmap

The existing engineering-guide sequence remains valid.

## Phase 6.5 — Substring / Bypass Reference Kernel

Implement a slow, transparent reference solver first.

Required focus:

- explicit substring/branch topology;
- local irradiance input;
- bypass diode transition behavior;
- analytical transition fixtures;
- no premature annual optimization.

**Exit:** reference substring/bypass behavior is explainable and testable.

---

## Phase 6.6 — Nonuniform Module IV Assembly

Assemble protected substrings / branches into full module IV and PV curves.

Required:

- exact topology order;
- explicit bypass state;
- nonuniform regional irradiance;
- deterministic curve/state identity;
- comparison against analytical/reference cases.

**Exit:** detailed module IV is physically coherent before string integration.

---

## Phase 6.7 — General Series String IV

Support non-identical module curves in series while preserving canonical module order.

Required:

- shaded + unshaded module mixtures;
- multiple bypass states;
- no assumption that all modules share one operating point curve;
- deterministic series assembly.

**Exit:** general mismatched series strings supported.

---

## Phase 6.8 — Parallel Strings & MPPT Operating Point

Combine string curves at common voltage.

Keep separate:

```text
physical combined P-V curve
!=
tracker/control assumption
```

The first tracker may use ideal global MPP only when explicitly identified.

**Exit:** multiple mismatched strings can feed one MPPT under an explicit operating-point model.

---

## Phase 6.9 — Detailed SimulationRun Integration & Loss Ledger

Integrate:

```text
regional irradiance
→ detailed module DC
→ string IV
→ parallel strings
→ MPPT
→ inverter
→ PCC
```

Keep distinct counterfactual attribution for:

```text
geometric irradiance reduction
electrical mismatch / bypass interaction
MPPT interaction
```

No double counting.

### Gate B — detailed-physics browser test

UI-A becomes the browser host for Gate B.

Add only the minimum product wiring required to:

- choose/request the supported electrical-shading fidelity;
- display resolved fidelity;
- display fallback/blocking reason;
- display detailed-shading limitations;
- expose relevant electrical-loss attribution;
- rerun the same canonical project without changing its geometry.

This does **not** require completing every item in UI-A `pending.ts`.

---

## Phase 6.10 — Annual Acceleration & Bounded Persistence

Only after the detailed reference chain is correct:

- affected-region filtering;
- curve/state caching;
- bounded result artifacts;
- deterministic equivalence checks;
- performance telemetry;
- cold/warm parity;
- no scientific identity dependence on volatile cache telemetry.

**Exit:** detailed annual execution becomes practical without changing reference physics.

---

## Phase 6.11 — Analytical / Independent / Cross-Software Validation

Preserve the validation hierarchy:

```text
analytical truth
→ controlled RawiBumi synthetic cases
→ independent open implementation
→ cross-software comparison
→ annual end-to-end attribution
```

Use independent tools only where genuinely independent.

PVsyst remains cross-software evidence, not the definition of RawiBumi correctness.

**Exit:** detailed electrical-shading behavior is supported by decomposed evidence, not final-energy fitting.

---

## Phase 6.12 — Closure Hardening & User Acceptance

Freeze at minimum:

- no-mismatch regression;
- module mismatch family;
- bypass family;
- string mismatch family;
- parallel/MPPT mismatch family;
- save/reload/reproducibility;
- provider-weather snapshot reproducibility;
- map vs blank-workspace equivalence;
- UI-A browser end-to-end reference project;
- Gate-B detailed-physics browser flow;
- annual deterministic identity;
- performance evidence;
- active-name / compatibility-name classification;
- full Python regression;
- web typecheck/build/demo-build.

Required closure statement:

```text
────── PV PHYSICS WORKFLOW STABLE ──────
```

Only after this statement is supported by executable evidence does Phase 7 begin.

---

# 8. UI scope boundary before Phase 7

## Integrate before Phase 7

Required now:

```text
UI-A shell
9-step workflow
2D plan/editor surface
current API-backed operations
explicit Not-wired controls
demo mode
Gate-A workflow
minimum Gate-B fidelity/result controls
```

## Do not let UI expansion delay Phase-6 physics

Generally defer to Phase 7 unless directly required by Gate B:

```text
full UI-B endpoint completion
complete import workflows
all scene editing commands
full imagery configuration
complete load / zero-export productization
full time-series explorer
report generation
complete export bundle UX
long-running job UX
broad error/onboarding UX
```

## UI-C / 3D

The staged UI describes UI-C as the 3D workspace.

Unless a narrow read-only 3D diagnostic is explicitly required for a Phase-6 validation case, full UI-C belongs after the Phase-6 physics closure, under Phase-7 product completeness.

---

# 9. Final pre-Phase-7 acceptance matrix

Phase 7 shall not start until all applicable gates below are green on one authoritative Drive snapshot.

| Gate | Required result |
|---|---|
| Phase-5 targeted regression | PASS |
| Full pytest | 0 failures |
| Phase-5 benchmark/validation | PASS within frozen tolerances |
| Phase-6.1 focused/adversarial | PASS |
| Phase-6.2 focused | PASS |
| Phase-6.3 focused | PASS |
| Phase-6.4 focused | PASS |
| Phase-6.5–6.9 reference/detailed physics | PASS |
| Phase-6.10 exact accelerated parity | PASS |
| Phase-6.11 validation matrix | PASS |
| JSON Schema validation | PASS |
| Python compile/import | PASS |
| TypeScript typecheck | PASS |
| normal Vite build | PASS |
| demo Vite build | PASS |
| UI-A Gate-A browser UAT | PASS |
| Phase-6 Gate-B detailed browser UAT | PASS |
| save/reopen deterministic identity | PASS |
| active product-name audit | RawiBumi clean |
| frozen/historical old-name allowlist | documented |
| source SHA-256 manifest | recorded |
| validation environment manifest | recorded |
| immutable Drive closure snapshot | created |

---

# 10. Recommended execution order

```text
A. Phase 5 repair
   R0 freeze
   R1 canonical weather tokens
   R2 stale rename tests/IDs
   R3 identifier allowlist
   R4 targeted regression
   R5 full pytest
   R6 Phase-5 benchmarks/validation
   R7 validated snapshot

B. Phase 6 existing-work reconciliation
   R0 Drive/Colab closure protocol
   R1 revalidate and close 6.1–6.4

C. UI-A integration
   merge staging
   dependency/lock update
   branding audit
   typecheck/build/demo-build
   Gate-A browser UAT
   full regression
   integrated snapshot

D. Phase 6 detailed electrical physics
   6.5 substring/bypass
   6.6 nonuniform module IV
   6.7 series string IV
   6.8 parallel strings/MPPT
   6.9 SimulationRun + loss ledger + Gate B
   6.10 annual acceleration
   6.11 validation
   6.12 closure

E. Pre-Phase-7 freeze
   full regression
   web builds
   browser UAT
   benchmark/validation
   source manifest
   immutable Drive snapshot
   Phase-7 handover
```

---

# 11. Immediate next actions

The next actions from the current state are:

1. apply the Phase-5 migration repair;
2. run the targeted previously failing tests;
3. run full pytest;
4. run Phase-5 closure benchmark/validation evidence;
5. freeze the clean Phase-5 Drive snapshot;
6. revalidate Phase 6.1–6.4 on that exact baseline;
7. integrate UI-A;
8. validate UI-A in API and demo modes;
9. freeze a post-UI-A Phase-6.4 integration snapshot;
10. begin Phase 6.5 only after all preceding gates are green.

---

## 12. Handover rule

When development resumes in another session, start from this order:

```text
Do not begin Phase 6.5 merely because 6.4 code exists.

First prove:
Phase 5 clean
→ Phase 6.1–6.4 clean
→ UI-A integrated and non-authoritative
→ full baseline reproducible

Then continue:
6.5 → 6.12

Then begin:
Phase 7
```

No new physics or broad product feature should be introduced while an earlier closure gate remains red unless it is required specifically to diagnose that gate.
