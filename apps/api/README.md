# RawiBumi browser API — Phase 6.0C


This service exposes the first runnable product shell over the existing
RawiBumi engineering kernels.


## Run


From the repository root:


```bash
python -m pip install -r requirements-validation.txt
python -m pip install -r apps/api/requirements.txt
uvicorn apps.api.server:app --reload --host 127.0.0.1 --port 8000
```


Project bundles are stored under `var/projects` by default. Override with:


```bash
RAWIBUMI_PROJECT_STORE=/path/to/projects
```

Legacy deployments may continue to use `OPENSIMPV_PROJECT_STORE`; the API reads it only as a fallback when `RAWIBUMI_PROJECT_STORE` is unset.

## Boundary


The API does not implement a second geometry/electrical model.


It orchestrates:


- `LocalCoordinateSystem`;
- `SceneEditorSession`;
- `PVFieldPackingSession`;
- `ElectricalTopologyEditorSession`.


The persisted `ProjectWorkspaceBundle` is an envelope around canonical
Project/Scene/ElectricalDesignRevision objects plus pinned component revisions
and explicitly non-simulation workspace state.


## Production note


Phase 6.0C is a first self-hostable engineering shell, not a hardened
multi-tenant internet service. Authentication, authorization, database-backed
concurrency, job queues and deployment hardening remain later product work.


## Phase 6.2 electrical-shading capability surface


The API now exposes the frozen Phase-6.1 capability boundary without adding a
mismatch solver:


```text
GET  /api/projects/{project_id}/electrical-shading/capability
POST /api/projects/{project_id}/electrical-shading/selection
```


The capability endpoint is read-only derivation. The selection endpoint persists:


- exact `ModuleTopologyDefinition` revision;
- exact region/cell parameterization evidence IDs when supplied;
- exact referenced `SourceRecord` objects;
- requested and resolved fidelity;
- explicit fallback policy and fallback result.


These assets live under `pinned_electrical_shading_assets`, separately from
`pinned_components`. Electrical-shading selection state does not mutate Scene or
ElectricalDesignRevision authority. Unsupported fidelity remains fail-closed
unless the caller explicitly selects `explicit_lower_fidelity`.

## S1 geometry integrity

PV-field creation rejects positive-area module overlaps across all fields with
HTTP 422. The response names the existing fields to update. Rejected drafts do
not save a bundle or increment a revision. Module edges may touch: intersection
area must exceed 1e-6 m² to constitute an overlap.

`POST /api/projects/{id}/obstacles/box` and obstacle moves through
`POST /api/projects/{id}/scene/move` accept:

```json
{
  "on_module_conflict": "reject",
  "discard_dependent_strings": false,
  "dry_run": false
}
```

`reject` is the default. An obstacle that overlaps modules returns HTTP 422 with
`detail: {"message": "...", "conflicts": [...], "options": {...}}`. Each conflict
identifies its module, PV field, obstacle or other module, and other PV field
when applicable. Other API errors retain their existing string `detail`.

`dry_run: true`, with any option, returns HTTP 200 without saving:

```json
{
  "dry_run": true,
  "conflicts": [],
  "options": {
    "remove_modules": {
      "module_instance_ids": [],
      "module_count": 0,
      "stc_power_w": 0.0,
      "string_ids": [],
      "requires_discard_dependent_strings": false
    },
    "refill_field": {
      "available": true, "fields": [], "string_ids": [],
      "requires_discard_dependent_strings": false,
      "requires_discard_manual_layout": false
    }
  }
}
```

`stc_power_w` sums each affected module's pinned revision `stc.pmp_w`.
`remove_modules` removes overlapping modules and setback violations against this
obstacle in each field with an overlap. Surviving modules retain their ids and
placements. If any module in this removal set belongs to a string, the operation
requires `discard_dependent_strings: true`. Affected strings are deleted whole;
they are never shortened. Scene and electrical revisions are saved together in
one atomic bundle save, with one project revision increment. An emptied field
is retained. Without overlap, setback violations are warnings and do not trigger
automatic removal.

`refill_field` re-packs affected fields around the obstacle (see S4 below).

Obstacle overlaps and setbacks require overlapping vertical ranges. The stored
`transform.position_z_m` is the module **centre**, as defined by
`geometry.scene.surface_plane.module_center_z` and used by the 3D generator.
Its vertical range is centre ± (up-slope dimension / 2) × sin(tilt), using
definition height for portrait and width for landscape. The obstacle occupies
`[base_elevation_m, base_elevation_m + height_m]`; a zero-height obstacle conflicts
only at a base inside the module's closed vertical range. Modules above an
obstacle are unaffected. Disabled modules are ignored.

S1 geometry rules govern conflict detection, readiness and removal. The existing
packer remains plan-only and counts touching as an obstacle conflict. Therefore
a later re-fill may remove additional modules that `remove_modules` kept. S4
keeps that existing packing behavior (DEC-9); height-aware packing is a separate
future decision. Packing obstacle findings
are not used as execution gates.

Readiness still loads old bundles. It reports blocking `SCENE_MODULE_OVERLAP`
and `SCENE_MODULE_OBSTACLE_OVERLAP`, warning `SCENE_MODULE_OBSTACLE_SETBACK`,
and warning `PV_FIELD_EMPTY`. Pair findings show the first 50 per rule and then
summarize additional pairs. The simulation preflight refuses geometry blockers
with HTTP 422. Detailed readiness appends the same findings after existing
findings; geometry blockers force `blocked_detailed_inputs` even when explicit
lower-fidelity fallback is requested. Warnings do not change readiness.

Unresolvable modules or malformed obstacles in stored bundles are skipped by
the geometry calculation and reported as blocking `SCENE_LAYOUT_UNRESOLVED`
findings, one per entity (first 50, then a summary). Remaining resolvable geometry
is still checked. Missing PV fields, unpinned or unusable module definitions,
and invalid entity geometry therefore produce readiness reports rather than
geometry lookup exceptions. Simulation remains blocked by the normal preflight.

## S10 site-local weather windows

Weather `start_date` and `end_date` are inclusive calendar dates in the site's
timezone. Open-Meteo is requested in UTC with one extra day on either side;
the padded end is capped at today's UTC date. After the existing preceding-hour
label conversion and timezone conversion, only interval starts inside
`[first real instant of start, first real instant of end + 1 day)` are retained.
Ordinarily each bound is local midnight. If midnight repeats, its earlier
occurrence starts the date (Havana 2023-11-05 has 25 rows). If midnight is skipped,
the first valid time starts it (São Paulo 2018-11-04 starts at 01:00, with 23 rows).
Consecutive local days tile without overlaps or gaps. A wholly skipped local
window, such as Pacific/Apia 2011-12-30, returns HTTP 422 before any provider call.
Only the bounds are resolved this way; no source timestamps are changed or
deduplicated. The site's actual timezone rules apply, including daylight saving.
A complete Jakarta calendar year therefore contains 8,760 hours (8,784 in a
leap year) and produces twelve monthly bins.

The dataset period records those requested local bounds with their UTC offsets.
The original padded response is stored byte-for-byte as the snapshot and retains
its SHA-256 provenance anchor. A distinct `timezone_normalization` transformation
with algorithm `local_window_trim` records the original requested local dates,
resolved local bounds, padded UTC dates,
input/retained row counts and rows dropped at each end. The existing interval
convention, state alignment, units and source semantics are unchanged.

Missing response hours remain missing. For S10-trimmed datasets, QC also reports
missing leading/trailing intervals as `WX_TIME_GAPS` errors with counts and
examples, including an entirely empty retained window. Internal gaps keep their
existing checks. No rows are fabricated, filled, shifted or interpolated. Other
weather importers retain their existing period and QC behavior. These changes
apply to new acquisitions; previously pinned weather is not rewritten.

## S2 readiness and module coverage

Standard `GET /api/projects/{id}/execution-readiness` now runs the same engineering
design validator used for simulation, with the pinned component revisions and
browser preflight electrical snapshot. Weather is not required for validation:
before acquisition, weather-required and electrical-design findings appear
together. Validator `blocking_error`, `error` and `warning` findings retain their
rule ids, messages, entity ids and severities under `category: "design_validation"`.
Their context contains `validation_category`, `classification`, `measured_value`,
`limit_value`, `unit` and the original finding's `context`. Informational findings
and per-call finding ids/timestamps are omitted. Only `blocking_error` prevents
readiness. Snapshot or validation failures become a blocking
`DESIGN_VALIDATION_UNAVAILABLE` finding with the exception message; the readiness
endpoint still returns HTTP 200.

`MODULES_NOT_SIMULATED` warns about enabled placed modules outside the execution
plan groups, for example `5 placed modules (2.75 kWp STC) will not be simulated`.
The context contains `module_count`, `stc_power_w`, `stc_power_incomplete`,
`by_reason`, sorted `module_instance_ids` (first 200), and `omitted_module_count`.
Power sums each module's pinned `stc.pmp_w`; missing power is flagged as incomplete.
Disabled placements are not counted. S1-unresolved placements remain included:
topology can classify them, with the execution-plan fallback covering other cases.

For modules belonging to multiple strings, strings are considered by id. The
first matching reason is `unstrung`, `string_unassigned`, `string_disabled`,
`mppt_missing_or_disabled`, `inverter_missing_or_disabled`, or
`execution_plan_excluded`. An unassigned string is classified as unassigned even
when it is also disabled. The fallback includes sorted `plan_finding_codes` for
related plan errors, or all plan error codes if none can be related.

The coverage warning is always last and never blocks readiness. Detailed mode
retains its existing validation findings and decisions; only this warning is
appended after those findings and S1 geometry findings. Standard-mode mapped
validation findings do not leak into detailed responses.

**Simulate behavior changes:** a standard-mode design blocked by engineering
validation now receives HTTP 422, `simulation execution preflight failed: …`,
before execution, with no run record persisted. Previously the same request
returned HTTP 200 and persisted a `failed` run. Designs that pass preflight keep
the existing run behavior.

## S4 PV-field update, delete and obstacle re-fill

`PATCH /api/projects/{id}/pv-fields/{field_id}` accepts optional `name`,
`orientation`, `azimuth_deg`, `tilt_deg`, `mounting_height_m`, `module_gap_x_m`,
`module_gap_y_m`, `row_pitch_m`, `perimeter_setback_m`, and `obstacle_setback_m`.
Unknown properties and empty changes return 422. Unknown projects return 404;
unknown fields return 422. Numeric constraints match field creation, including
the existing azimuth normalization modulo 360.

A name-only update preserves every module and requires no discard flag.
Other changes re-pack the same field id. `discard_manual_layout: true` is required
when its `layout_status` is `manual`. If the impact report identifies affected
strings, `discard_dependent_strings: true` is also required. Only affected
strings are deleted, whole; unaffected strings keep their membership. Tilt and
mounting-height changes replace identities according to the accepted identity
rules. Unchanged physical placements retain ids for setback/pitch changes.

`dry_run: true` computes a preview without requiring either discard flag or
saving. It includes `pv_field_id`, `module_count_before/after`,
`retained_module_count`, `added_module_count`, `removed_module_count`,
`stc_power_w_before/after`, `string_ids`, `requires_discard_dependent_strings`,
`requires_discard_manual_layout`, `conflicts`, and the full `layout_impact`.
Counts/power cover the field's stored module instances; added/removed counts
are actual id-set differences, including identity replacements that the impact
report pairs as moved modules. Power uses each module's pinned `stc.pmp_w`.
An empty PATCH packing result is refused with the existing zero-modules error.
Cross-field module overlaps and obstacle overlaps also prevent committing a
re-pack; dry-run reports those conflicts. A name-only update is unaffected.

`DELETE /api/projects/{id}/pv-fields/{field_id}` removes that field and all its
module instances. Query parameters are `dry_run` and `discard_dependent_strings`
(both default false). The preview contains `pv_field_id`, `module_count`,
`stc_power_w`, `string_ids`, and `requires_discard_dependent_strings`. Every
string referencing any removed module requires the discard flag, including
mixed-field strings in older bundles. Pinned component revisions stay pinned.
CORS permits DELETE.

Obstacle create/move now supports `on_module_conflict: "refill_field"` and
`discard_manual_layout` in addition to the existing options. With overlap,
affected fields are rebuilt against the draft obstacle, using their existing
exclusion rules. The refill preview contains `available`, per-field before/after
counts and STC power, the union of affected `string_ids`, and both required-flag
booleans. With no overlap, every option commits normally without re-packing.

If exclusion rules leave an obstacle overlap after rebuilding, the refill option
reports `available: false`, `reason: "field_exclusion_rules_ignore_obstacle"`,
`remaining_conflicts`, and its calculated per-field counts. The whole refill
commit returns structured 422; rules are preserved and `remove_modules` remains
available. Cross-field conflicts likewise prevent a refill commit. Manual and
string discard flags do not override geometry conflicts.

The existing packer remains plan-only and touch-inclusive (DEC-9), so re-fill
can remove modules above a low obstacle that S1's height-aware removal would
keep. Preview shows that actual result. All scene and whole-string changes
are saved atomically once, with one project revision increment. A refused edit,
preview, or failed save leaves the stored bundle unchanged. Existing readiness
reports newly unstrung modules after edits without additional readiness rules.

## S3 scene commands and polygon obstacles

`POST /api/projects/{id}/scene/commands` wraps the existing canonical
`SceneEditorCommand` without changing its schema:

```json
{
  "command": {
    "schema_name": "SceneEditorCommand",
    "schema_version": "0.1",
    "command_id": "rotate-roof-1",
    "command_type": "rotate",
    "target_entity_ids": ["surface-id"],
    "parameters": {"angle_deg": 30, "origin": [0, 0]}
  },
  "on_module_conflict": "reject",
  "discard_dependent_strings": false,
  "discard_manual_layout": false,
  "dry_run": false
}
```

Supported commands are `rotate`, `move`, `move_vertex`, `edit_exact_dimension`,
`edit_exact_angle`, `edit_elevation`, `draw_polygon`, `delete` and `copy`. The other 17
canonical enum values return 422 explaining that they are not supported yet.

`copy` (UX2 Duplicate) takes one roof, keep-out or obstacle and `{dx_m, dy_m}`
(finite, no other keys, within the scene bounds). It adds one clone named
"‹name› copy" with server-generated surface or obstacle and scene-object IDs, as one
scene revision and one undo entry labelled "Duplicate ‹name›.". PV fields, modules,
tables and strings are never copied; a roof that hosts fields is copied as an empty
roof, and the source and its fields are unchanged. The clone's `parent_surface_id` and
`group_id` are cleared (`COPY_CLEARED_KEYS`), so it joins neither the source's parent
nor its group; every other key is the clone's own value, and a test fails on any
unreviewed key. An obstacle or keep-out copy that lands on modules takes the same
`on_module_conflict` choices as a move. `imported_mesh` obstacles are refused (422,
read-only).

**`with_pv: true` (UX3 paste, roofs only)** also copies every PV field on that roof onto the clone, in the same
command: one scene revision, one undo step, labelled "Paste ‹name› with PV."
- A **generated** field is re-created with the source's packing parameters (module, orientation, azimuth, tilt, gaps,
  row pitch, mounting height, setbacks, table configuration, exclusion rules, row alignment, requested counts) and
  filled on the clone. The copy is a fresh fill: obstacles at the new place apply, and manual module edits aren't
  carried over.
- An **explicit** field's tables on that roof are rebuilt with new field, table and module IDs, anchors moved by
  `(dx_m, dy_m)`, and `provenance.copied_from_pv_field_id` recorded. Tables on other roofs stay where they are.

Strings and inverters are never copied, so pasted modules arrive unstrung and the electrical design is untouched.
Fields with edge-specific setbacks are refused (422) because they can't be reproduced yet. Any overlap of the pasted
modules with existing modules, obstacles or keep-outs is a 422 with its `conflicts`, and nothing is written.
Selection is session state. The `undo`/`redo` command types stay unsupported here;
HTTP undo/redo is the project-level route under "Session-only undo and redo". The envelope is checked once against the committed schema with format
validation. Separate parameter models reject unknown/missing keys and non-finite
numbers. Polygon vertices are limited to 3–1,000 finite XY pairs. Polygon validity,
preserve/source values, snap kinds and editability remain engine checks.

Geometry edits target exactly one entity; `delete` accepts one or more targets;
`draw_polygon` accepts none and generates surface/object ids. Parameters follow
the existing engine method names: rotation angle and optional origin; move XY
deltas; vertex index and target XY with optional snapping; edge index and exact
length or azimuth with optional preserve/source; or base elevation. Polygon
surfaces accept type, vertices, base elevation, slope, azimuth and PV usability.
Holes, obstacle-height edits and resizing are not exposed.

Targets resolve by either entity id or `scene_object_id`, with the engine's
surfaces → obstacles → reference-lines order and first-match semantics. The
existing `/scene/move` now applies the same canonical guards, closing its alias
bypasses. A support surface carrying PV fields cannot be reshaped, moved or
deleted; the refusal names its fields. Delete the fields first through S4.
Multi-target delete is atomic, including unknown or locked targets.

Support-surface elevation changes are allowed (DEC-11). The engine updates module
Z while preserving ids, XY, membership and strings. A new module–obstacle overlap
pair returns structured 422 with no obstacle options; pre-existing pairs alone
do not block the edit. Its dry-run reports only the new pairs. Every obstacle
geometry edit goes through the existing reject/remove/refill policy and flags.

Successful edits save one scene and project revision; the electrical revision
changes only for authorized whole-string deletion. Refusals never save. Dry-runs
never write: ordinary commands return `{"dry_run": true, "conflicts": []}`;
obstacles retain their conflict/options previews. Support/validation guards still
refuse during dry-run. Out-of-range engine indexes return 422 locally on this
route; other route error contracts are unchanged.

`POST /api/projects/{id}/obstacles/extrusion` accepts `name`, `vertices`,
`base_elevation_m`, required non-negative `height_m`, and the same conflict flags
and dry-run option as box obstacles. It stores an `extruded_polygon` with
server-generated ids and applies exactly the same conflict policies.

Deleting obstacles or creating/editing/deleting walkways and exclusion areas
does not re-fill fields (DEC-12). For a field with a stored packing hash, changed
packing inputs produce the non-blocking `SCENE_PV_FIELD_LAYOUT_STALE` warning.
This also applies to a new obstacle that clears modules but changes resolved
packing inputs. Explicitly re-fill through S4 to regenerate the layout and clear
the warning. Manual/unpacked fields have no current hash and do not get this
warning. Uncomputable hashes on damaged fields are skipped. Detailed readiness
preserves the warning without changing readiness or execution class.

Frontend wiring and its existing “Not wired” badges remain S7 work.

## S5 electrical command batches

`POST /api/projects/{id}/electrical/commands` accepts an ordered batch of 1–200
canonical `ElectricalTopologyCommand` envelopes. The wrapper and per-command
parameters reject extra or missing fields; ids must be non-empty strings and
integer parameters must be integers, rather than numeric strings or floats.
Non-finite JSON numbers return 422. S14a added its five string edits, and S14b its
five design commands, to the command schema's `command_type` enum (additive
changes).

For example, after creating seven strings, assign six to chosen MPPTs and remove
the seventh in one request:

```json
{
  "commands": [
    {
      "schema_name": "ElectricalTopologyCommand",
      "schema_version": "0.1",
      "command_id": "assign-first-three",
      "command_type": "assign_strings_to_mppt",
      "parameters": {"string_ids": ["S001", "S002", "S003"], "mppt_instance_id": "your-mppt-1-id"}
    },
    {
      "schema_name": "ElectricalTopologyCommand",
      "schema_version": "0.1",
      "command_id": "assign-next-three",
      "command_type": "assign_strings_to_mppt",
      "parameters": {"string_ids": ["S004", "S005", "S006"], "mppt_instance_id": "your-mppt-2-id"}
    },
    {
      "schema_name": "ElectricalTopologyCommand",
      "schema_version": "0.1",
      "command_id": "delete-remainder",
      "command_type": "delete_string",
      "parameters": {"string_id": "S007"}
    }
  ],
  "dry_run": false
}
```

Supported edits are `create_string`, `assign_strings_to_mppt`, `unassign_strings`,
`delete_string`, `create_strings`, `assign_strings`, `balance_mppt`, the S14a
string edits `split_string`, `join_strings`, `reverse_string`, `move_module` and
`swap_modules`, and the S14b commands `set_orientation_tolerance`,
`set_orientation_override`, `set_inverter_pairing`, `apply_mppt_layout` and
`replicate_pattern` (below).
`create_string.module_instance_ids` preserves the exact wiring order (1–2,000
modules). Supply a `string_id` to reference it later in the batch; when omitted,
the server chooses the lowest free `S###`, skipping all electrical entity ids,
including earlier commands. Optional name, polarity and notes go to the engine.
New strings start disabled and unassigned. Assignment supports `enable` (default
true); unassignment clears reciprocal MPPT links and disables the strings.

`create_strings` accepts 1–20,000 module ids, a positive integer `string_length`,
`ordering` (`row_major` by default, `selection`, or `serpentine`), `remainder_policy`
(`error` by default, or `allow_shorter`) and `id_prefix` (`S` by default).
Serpentine (S14a) is row-major per field with every other row of that field
reversed, so a string turns at a row end instead of returning to the row's start;
each field starts with its first row forward. `assign_strings` selects
an inverter, while `assign_strings_to_mppt` selects an exact MPPT. Existing input
capacity and module-availability checks remain authoritative in the engine.

S14a string edits, each one engine command:

- `split_string {string_id, after_module_instance_id, new_string_id?}`: the modules
  after that module become a new string (the lowest free `S###` when the id is
  omitted). It keeps the original's MPPT, `enabled` state, polarity and notes.
  Splitting after the last module, or onto an MPPT without a free verified DC
  input, is refused.
- `join_strings {first_string_id, second_string_id}`: the second string is appended
  to the end of the first and removed, with its MPPT link.
- `reverse_string {string_id}`: reverses the wiring order, so the two ends swap.
- `move_module {module_instance_id, to_string_id?, index?}`: takes a strung module
  out of its string, into `to_string_id` at `index` (appended when null), or into
  no string when `to_string_id` is null. A string left empty is deleted.
- `swap_modules {first_module_instance_id, second_module_instance_id}`: exchanges
  two strung modules' places, in one string or across two.

S14b design commands, each one engine command and one undo step:

- `set_orientation_tolerance {tolerance_deg}` (0–1°) and
  `set_orientation_override {mppt_instance_id, reason}` (a reason of 1–500
  characters, or null to clear) edit `electrical_design.orientation_policy`.
- `set_inverter_pairing {inverter_instance_id, pv_field_ids}` saves the PV fields
  an inverter is paired with as `paired_pv_field_ids`; an empty list clears it.
  The pairing is advisory: it is the pool of notation Apply, and strings from
  other fields get a `pairing` live-check warning.
- `apply_mppt_layout {inverter_instance_id, layout, pv_field_ids?}`, where `layout`
  has one list of string lengths per MPPT (0 = empty input). Strings already
  matching by MPPT and length stay; the inverter's other strings are unassigned,
  not deleted. Missing ones come first from unassigned pool strings of that
  length, then from unstrung pool modules in row-major order. The pool is the
  given fields, else the pairing, else every field. A wrong MPPT count, more
  strings than verified inputs, or too few modules refuses the whole command.
- `replicate_pattern {source_pv_field_id, source_table_id, targets?}` works on
  explicit tables; generated fields have none until the table model. The strings
  lying wholly inside the source table are copied slot by slot, unassigned, to
  each identical table (same size, orientation, module revision and module slots)
  whose modules are all unstrung. By default that's every identical table; with
  `targets`, only those. Partly wired tables are skipped and listed.

**Orientation policy (S14b).** Strings on one MPPT whose module normals agree
within the tolerance (1° unless the design sets less) are one orientation group,
both for the checks and for the simulation. The execution plan runs them at the
module-weighted mean normal and records `orientation_merge` on the group. A
design with identical orientations keeps its exact plan. Beyond the tolerance,
`MPPT_ORIENTATION_MISMATCH` warns. An override with a reason silences that warning,
but `SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT` still blocks the run and names the
override, because the engine can't yet model mixed orientations on one MPPT. The
engine library compares exactly when a design carries no policy; the app applies
its 1° default. Pairing and override reasons aren't part of the design
fingerprint; a tolerance other than 1° is.

Commands run in order in one editing session. A failure returns string `detail`
with the zero-based index, command id, type and error, and saves nothing. Successful
changed batches save once, increment electrical and project revisions once, and
leave the scene unchanged. Success returns the project view plus `command_results`
(`command_id`, `command_type`, `result`). Assignment/balance maps become sorted
lists of `{mppt_index, string_ids}`; create-string returns the created string,
automatic creation returns new ids, unassignment returns sorted ids, and deletion
returns null. A batch whose canonical design is unchanged returns 200 without
writing or advancing revisions.

With `dry_run: true`, the response contains `dry_run`, `command_results`,
`topology_view` and the full `topology_consistency` for the draft. It never writes.
A single `suggest_string_length` or `inspect_inverter` command is read-only and
returns just `{command_id, command_type, result}`, including when `dry_run` is
true. Read-only commands cannot be mixed into a multi-command batch. Suggestions
use reference conditions and do not replace engineering validation.

**Live string checks (S14a).** Every project view, including the response to a
batch, has `topology_checks: {basis, strings}`. Each string has `vmp_v` (its Vmp
at STC), `window_v` (its MPPT's operating window, or null when unassigned) and
the checks `voltage_window`, `max_voltage`, `current`, `unequal_lengths`,
`orientation`, `inputs` and `pairing`, each `pass`, `warn`, `fail` or `unavailable`
with a message. The checks come from the engine's design validation at the
readiness configuration's design cell temperatures (−10 °C and 70 °C) and the
design's normal-angle orientation tolerance, regrouped per string. An overridden
orientation mismatch is `pass`, with its reason. An unassigned string's checks are unavailable,
except a Voc limit it already exceeds. If validation can't run, every check is
unavailable with the reason. The checks are shown, never enforced.

Topology editing does not run electrical design validation as a gate (DEC-14). A consistent
21-module string can be saved as a draft; S2 readiness reports its electrical
violations and blocks simulation. Structural consistency is required to commit
(A1): any remaining error returns 422 with repair guidance and each finding's
code, entity id, message and origin (`pre-existing` or `introduced`). A batch can
repair old errors and commit. Old errors remain visible in dry-run reports and
do not force a commit for read-only or no-op requests. The engine commit guard
is unchanged.

This repair refusal has structured `detail: {"message": "...before committing (N errors).",
"findings": [...]}` (DEC-29). The message contains no Python-formatted finding list;
each finding retains its code, entity id, message and origin. Other electrical-command
refusals keep their string detail and `command <i> (<id>, <type>):` label.

Some hand-edited or imported structural errors cannot be repaired with supported
commands, such as `mppt_unknown_inverter`: there is no inverter or MPPT removal.
Those bundles cannot commit through this route until repaired elsewhere; existing
routes have the same limitation. S8 must validate imports.

`add_inverter` points to the existing `/inverters` route, which pins its component
revision. `commit_revision` is refused because the batch commits implicitly.
Existing strings, assignments and inverter routes keep their contracts. Inverter
removal, split/join/reverse/swap and moving a module between strings need engine
support. Frontend command mapping, including plural deletion, remains S7 work.

## S6 project/site edits, deletion and validation

`PATCH /api/projects/{id}` accepts `name` (trimmed, 1–160 characters) and/or
`description` (up to 2,000 characters; null clears it). Metadata edits update
`updated_at` without changing the project revision.

`PATCH /api/projects/{id}/site` accepts one or more of `name`, `latitude_deg`,
`longitude_deg`, `elevation_m` and `timezone`, plus optional
`clear_weather_selection` (default false). Coordinates and timezone follow project
creation rules, including an IANA timezone and an origin away from the poles.
Site elevation is limited to −500 through 9,000 m. Unknown fields and non-finite
values are rejected. A changed site advances the project revision once; identical
values return 200 without a write.

The site, its local-coordinate origin and the workspace site copy stay consistent.
Coordinate-system and site ids are preserved, with the existing zero rotation.
Scene geometry retains its local metres. Changing the origin moves its placement
on the map overlay. A change to latitude, longitude, elevation or timezone with
pinned weather requires `clear_weather_selection: true`, because the weather
request depends on those inputs (including elevation/downscaling). The refusal
names the pinned revision. With the flag, the selection and project revision's
weather id are cleared; weather files and historical runs remain unchanged.
A site-name change does not require clearing weather. Readiness requires a new
weather selection after clearing one.

`DELETE /api/projects/{id}?confirm={id}` permanently removes that project's run
directory, weather directory and finally its bundle. The exact confirmation token
is required. Every target is preflighted for containment and symlinks before any
removal; nested symlinks are removed without following their targets. Only the
exact project paths are removed; sibling paths with a matching prefix and shared
`weather-snapshots/` content remain. Bundle-last ordering leaves a partially
completed delete listed and retryable. A successful response names the deleted
project and reports whether its bundle, runs and weather paths were removed.
A second delete returns 404. Encoded slash-containing ids reach id validation,
without taking precedence over the existing nested DELETE routes.

Simulation and weather acquisition use a per-project in-progress counter. While
either operation runs, project deletion and site editing return 409. Metadata,
scene/layout and electrical edits stay available. On completion, the operation
reloads the current project under the store lock and merges only its run record
or weather selection. It preserves edits made while computing, and a missing
project raises instead of being recreated. Run records retain the input scene,
electrical and weather revisions used for their computation.

The registry is process-local: run this self-hosted server with **one uvicorn
process/worker**, as documented. Every service save also checks the loaded
`updated_at` against storage under the store lock. A stale edit returns 409 with
`project changed concurrently; reload and retry`, preserving the newer edit or
merged result. Reload the project before retrying. If it was deleted, the save
returns 404 and cannot recreate it; only explicit project creation may create a
missing bundle. Sequential edits and repeated saves of the same updated bundle
continue normally.

Scene bounds apply at commit to new or geometrically changed surfaces/obstacles:
all vertices must lie within ±50,000 m in X/Y, either bounding-box side must be at
most 10,000 m, base elevation must be −1,000 through 10,000 m, and obstacle height
must be 0–1,000 m. Unchanged legacy outliers do not block unrelated edits.
Rectangle surface types use the scene-schema enum. PV-field azimuths on create
and PATCH, and polygon-surface azimuths, must be in [0, 360); the API refuses
out-of-range values instead of letting the engine wrap them. Polygon slopes must
be in [0, 90). Blank polygon and extrusion names become Surface and Obstacle.

Validation errors on established routes keep list `detail`; non-finite input
values are rendered recursively as the strings nan, inf and -inf. S3/S5 routes
and the new PATCH routes keep string `detail`. Weather acquisition refuses an
archive end date after today in UTC before transport. Provider HTTP 4xx errors
return 422 with the unavailable-period message; provider 5xx and network failures
remain 503. Providers, canonical schemas and engineering kernels are unchanged.


The browser Site panel sends only changed site keys. Before a weather-bound edit,
it names the pinned weather revision and requires confirmation to clear its
selection; stored runs and weather files are retained. The project list supports
rename and permanent deletion, with deletion enabled only after typing the exact
project name. The API confirmation remains the project id.

The browser distinguishes the two 409 cases: an in-progress simulation/weather
operation shows the engine message without a reload; a concurrent-save conflict
reloads the project and asks the user to repeat the edit. Neither case triggers
an automatic retry. Scene and electrical command ids use cryptographically random
RFC 4122 v4 ids even over plain HTTP, where `crypto.randomUUID` is unavailable.

`GET /api/simulation-defaults` is read-only and requires no project or weather.
Its timestep, albedo, thermal coefficients and loss options come from the same
option builder used by `_phase5_configuration` for real runs. Numerical values
are unchanged. The browser offers only the engine's 60-minute timestep.

Module quality is applied from the pinned module definition's
`quality.default_module_quality_loss_fraction`, falling back to zero when absent
(negative means gain). The defaults endpoint reports this source and fallback;
it does not classify module quality as unmodelled. Soiling, LID, AC ohmic,
availability and degradation are not modelled by this browser run path.

Support-surface edits can opt in to dependent-field handling with
`dependent_fields: "apply"` on `/scene/commands` or `/scene/move`. The default
`"reject"` keeps the previous support-field refusals and messages. Apply re-fills
each dependent field with its stored parameters, in field-id order, using the
existing packer and identity rules. `delete` instead removes the dependent fields
and their modules. Elevation edits retain their existing behavior: modules follow
in z without re-packing.

Use `dry_run: true` first. The response lists each dependent field's action,
module counts and STC watts before/after, affected whole strings, manual-layout
and string-discard requirements, and geometry conflicts. An empty re-filled field
or an S1 overlap blocks commit. Strings are deleted whole only with
`discard_dependent_strings: true`; discarding a manual layout separately requires
`discard_manual_layout: true`. The scene and electrical changes save once. A
failed rebuild, missing flag, invalid target or geometry conflict saves nothing;
the existing optimistic 409 protection still applies. The browser previews this
impact and sends only the required flags after explicit confirmation.

The scene command schema now supports `scale`: exactly one HTTP target, a finite
`factor` in `(0, 100]` and an optional `[x, y]` origin in local metres. It scales XY
uniformly, including holes, about that origin or the targets' bounding-box centre;
it does not change base elevation or obstacle height. Obstacles use the existing
conflict choices, and the existing geometry bounds still apply. The engine undo
step remains local to its editing session; the browser's deletion confirmation
states that the committed deletion cannot be undone.

## S11a keep-outs and scene geometry edits

`POST /api/projects/{id}/scene/commands` also supports these single-target
commands, with strict parameter objects (unknown keys are refused):

| Command | Parameters |
| --- | --- |
| `insert_vertex` | `edge_index`, `x_m`, `y_m`; inserts after the edge's start vertex |
| `delete_vertex` | `vertex_index`; leaves at least three polygon or two reference-line vertices |
| `move_edge` | `edge_index`, `dx_m`, `dy_m`; translates both endpoints by that local-metre vector |
| `edit_height` | `height_m`; obstacle only, from 0 through 1,000 m |

Indices follow the stored, unclosed ring. All commands check locks, finite inputs,
valid geometry and the existing scene bounds before saving. They refresh edge
provenance and invalidate changed obstacle parameterization. Vertex/edge edits
on roofs carrying fields use the dependent-field preview and confirmation flow
described above. Raising an obstacle uses the existing obstacle conflict options.

Creating or editing an `exclusion_area` or `walkway`, including through the
rectangle route, uses the same `reject`, `remove_modules` and `refill_field`
choices, `dry_run` preview and independent string/manual-layout discard flags.
The conflict set follows the unchanged packer: resolved exclusion surfaces in
plan, using `polygons_overlap_or_touch`. Contact and tiny overlaps count; height
and the field's obstacle setback do not apply. Explicit `surface_ids` take
precedence over the automatic selection flags and type filter. The keep-out
polygon itself defines the clearance zone.

Only selected keep-outs cause conflicts. An ignored keep-out commits normally
with every conflict option, including `refill_field`, without changing the
field. Its dry-run response may include informational
`ignored_by_fields: [{pv_field_id, reason: "field_exclusion_rules_ignore_keepout"}]`
for intersecting support footprints. This list never blocks a save. A selected
keep-out that still conflicts after rebuilding makes refill unavailable and
refuses that commit; removal remains available if rebuilding fails.

Readiness reports existing modules touching or overlapping selected keep-outs as
non-blocking `SCENE_MODULE_KEEPOUT_OVERLAP` warnings, bounded to 50 pairs plus a
summary. Existing obstacle and module-overlap blockers retain their rules.

The browser keep-out tool persists exclusion zones or walkways, offers the
keep-out conflict dialog, and maps saved exclusions to keep-out entities. Outer
vertex insertion/deletion, edge drag and Inspector obstacle height persist
through these commands. Edge drag sends the exact normal-offset vector used by
the UI preview. S11b below adds persisted holes and non-flat plane definitions;
legacy draft entities still require discarding their edits before engine commands.

## S11b roof planes and holes

`/scene/commands` adds three single-surface commands:

- `edit_plane`: `slope_deg` in [0,90), downhill `azimuth_deg` in [0,360),
  `base_elevation_m` in [−1000,10000], and `elevation_reference` (null,
  `{mode:"boundary_centroid"}`, or `{mode:"explicit_xy",x_m,y_m}`). XY references
  must be within ±50 km. Base elevation is the height at that reference point.
- `add_hole`: `vertices`, a valid polygon strictly inside the outer boundary,
  without touching or overlapping another hole.
- `remove_hole`: a zero-based `hole_index`.

Vertex move/insert/delete and edge move now accept `ring` (default 0 for the
outer ring, 1 for the first hole, etc.). The indices follow each stored, unclosed
ring. Hole edits keep all holes strictly inside and mutually disjoint. Unknown
parameters, non-finite values, invalid indices and out-of-bounds geometry are
refused without a save. These operations check locks, refresh provenance and
form one engine undo step. Obstacles cannot receive plane or hole commands.

A plane edit keeps module XY, IDs, strings and layout intact. The engine
recomputes module-centre Z from the support plane plus the field's vertical
mounting height. Newly introduced S1 module–obstacle overlaps refuse the edit
with structured conflicts and no destructive options; `dry_run` reports those
pairs without writing. The field becomes stale and offers re-fill; the plane
edit never re-packs it automatically.

Hole changes on roofs carrying fields use the S9 dependent-field preview,
re-fill and confirmation flags. Filling excludes modules touching or overlapping
holes and applies the field's perimeter setback to hole edges. `validate_field_layout`
reuses `module_outside_support_or_setback` for contact, overlap or a hole-edge setback
violation (with a hole-specific message), preserving the existing conflict-report schema.
The existing outer-boundary/obstacle rules and every hole-less packing result
remain unchanged. Readiness uses the specified physical-gap rule: plan overlap
area above 1e-6 m² reports blocking `SCENE_MODULE_OVER_HOLE`, bounded to 50 pairs
plus a summary. Its finding IDs identify the support and zero-based hole index.

The Inspector saves flat, reference-edge and datum planes. Reference-edge planes
use the edge midpoint as explicit XY reference. Under A1, a nonzero edge tilt
whose centroid cross product is exactly zero is refused locally with guidance to
choose another reference edge or datum mode; no request is sent. The existing
`planeZ` formula is unchanged. Saved planes and holes map back into the UI;
outer/hole vertex and edge edits persist. A selected roof's plan controls offer
removal of each hole, with the same dependent-field preview when needed.

Surface move and rotate carry all holes in the same mutation, as scale already
does. Plane, azimuth and reference behavior are unchanged. Engine mirror, copy
and array retain their pre-existing hole-transform limitation; these commands
are outside the HTTP slice and must not be used as hole-preserving transforms.

Standard module-receiver roofs with holes retain compiled module shading and
simulation support. Surfaces explicitly marked `shading_receiver: true` remain
subject to the existing aggregate-plane receiver contract: holes produce
`surface_receiver_compile_failed`. This slice never clears that flag or changes
shading code. Supporting holes on aggregate receivers requires a separate engine
and contract decision. The 3D height-model route/view remains S11c.

## S13b manual module delete and move

`POST /api/projects/{id}/pv-fields/modules/commands` accepts a command object:

```json
{
  "command": "move_modules",
  "module_instance_ids": ["module-id-1", "module-id-2"],
  "dx_m": 0.1,
  "dy_m": 0.0,
  "dry_run": false
}
```

Commands are `move_modules` or `delete_modules`. Supply 1–10,000 unique existing
module IDs; IDs can span fields. Unknown/duplicate IDs and extra keys are 422.
Moves require finite `dx_m` and `dy_m`, each within ±10,000 m; deletes forbid
both keys, including explicit null values. Flags `dry_run` and
`discard_dependent_strings` default to false.

A delete preview (`dry_run: true`) returns `fields`, with each field's ID/name,
`module_count_before/after`, `stc_power_w_before/after`, `string_ids`, and
`field_becomes_empty`; it also returns the union `string_ids`, `module_count`,
and `requires_discard_dependent_strings`. Previews never write. A commit removes
exactly those placements and deletes every string containing one of them whole.
Without `discard_dependent_strings: true`, a strung deletion is refused with a
structured 422 naming the affected strings. Empty fields remain and contribute
the existing non-blocking `PV_FIELD_EMPTY` warning. A project with no executable
modules retains its existing execution-plan blocker.

A move translates the group rigidly in one engine mutation, preserving module
IDs, field/support membership and strings. Z is re-derived from each module's
own support plane plus its field's vertical mounting height. The API checks the
union of `validate_field_layout` for affected fields and `validate_scene_layout`,
and refuses any finding involving a moved module on either side. This covers
support/setback boundaries, holes, selected exclusions, obstacles and overlaps.
Unrelated legacy conflicts do not prevent the edit. Under A1, module edge/corner
contact is allowed by the existing packer primitive; obstacle and hole contact
remain subject to their stricter checks. Exclusion selections and all existing
validator tolerances are unchanged. Modules cannot change to another support.
A move preview returns `moved_count` and `conflicts`. A refused commit returns
422 with `message` and conflicts containing `code`, `module_instance_id`,
`other_id` and `pv_field_id`, and saves nothing.

Either commit marks affected fields `manual`, retains generated row information
only as lineage, and clears the current `packing_input_hash`. Later S4 re-fills
and S9 roof edits require their existing `discard_manual_layout` confirmation.
Each command commits one scene revision, plus one electrical revision if whole
strings are removed, in a single optimistic save. The existing operation
registry protects site/deletion races; stale writes return the S6 409 without
overwriting newer edits. Readiness and simulation continue to accept valid
manual layouts.

On the 2D plan in Scene and PV layout, non-table modules support selection,
group drag (Shift snaps the delta to 0.10 m), and arrow nudges of 0.10 m or
1.00 m with Shift. Every deletion, including unstrung modules, previews and asks
for confirmation; Cancel sends no commit. Only required discard flags are sent
on confirmation. Movement refusals show engine conflict details in the toast.
Calls use the existing busy and 409 reload handling without automatic retry.
Active demo tables retain their prior gestures and table controls; their module
Inspector points to those controls. The remaining `moduleEdit` badge covers
adding or rotating individual modules, not these new live edits.

### Module drop-to-fill (S13c)

`POST /api/projects/{id}/pv-fields/modules/commands` accepts `on_conflict: "reject" | "fill"`
for `move_modules` (default `reject`). Valid rigid moves remain exact, including selections
from several fields. Arrow-key nudges use this exact path. Only a conflicting move with
`fill` runs the fallback, within one field on its original roof.

The fallback uses the field's unchanged packer settings, removing only the requested row
and per-row count caps. It excludes slots overlapping any unmoved module by more than
1e-6 m². The translated group's footprint bounds, expanded by half the larger module
plan dimension, define the drop region. Eligible slots nearest the translated group
centroid are chosen (ties: higher y, lower x). Original modules and chosen slots pair in
reading order: y descending, x ascending, quantized to 1 mm. Placed modules retain their
IDs and take the slot's full transform and row/column/grid/**table** indices. In a manual
field those indices describe lineage, not a table identity, and may repeat.

A `dry_run: true` fallback returns `mode: "fill"`, `placed_count`, `removed_count`,
`placed_ids`, `removed_ids`, `string_ids`, `requires_discard_dependent_strings`,
`stc_power_w_before`, `stc_power_w_after`, `reasons` and raw `conflicts`. STC powers
refer to the selected modules before and after fitting. A valid exact dry run retains
the existing `moved_count`/`conflicts` preview. Dry runs never save. A commit requires
`discard_dependent_strings: true` only when removed modules belong to strings; those
strings are deleted whole. Strings containing only retained modules are unchanged.
The scene and any necessary electrical revision are saved together once.

Every module-command 422 and preview carries `reasons`: objects with `code`, `count`
and readable English `message`, plus optional `name` and numeric `setback` (metres)
for translation. Counts deduplicate moved module IDs, including either side of a
module-overlap pair; names identify the obstacle, roof or keep-out. Unknown conflict
codes fall back to their code text. Raw conflicts remain available for diagnostics.
Invalid request bodies also return structured reasons with validation errors.

A fill with no available slot, a group centroid outside its own roof, or a conflicting
selection spanning fields is refused without saving. Both layout validators check the
placed modules before any commit; a post-check discrepancy refuses the entire edit
for engineering review. The dialog previews removed modules and whole strings before
confirmation; Cancel sends no commit. The demo explicitly reports that drop-to-fill
needs the engine.

### Re-fill target and module replacement (RF1)

The PV layout form follows a single selected engine roof, or the roof chosen in
Support surface. A roof with a field opens that field's stored settings; a roof
without one gets a new fill and a unique `<roof name> array` default name. On a
roof switch, an empty or untouched default follows the roof; a typed name stays.
Multiple
fields on a roof are listed, and selection targets the first by `pv_field_id`;
individual field cards remain available. Success or Cancel exits re-fill mode.
Changing the support selector switches targets; it does not move an existing field.

`PATCH /api/projects/{id}/pv-fields/{field_id}` also accepts an optional
`module_definition_revision_id`. A different revision re-packs with the new
footprint and power, retaining placement IDs according to the existing identity
rules. The preview's `string_ids` lists **every** string touching the field's
pre-edit modules, even when a same-size rebind retains every ID. This electrical
rebind list is separate from the unchanged physical `layout_impact` report.
Confirmation requires `discard_dependent_strings: true` when that list is nonempty;
these strings are deleted whole, including strings crossing fields. Other strings
remain unchanged. The new module is pinned only after all refusal checks on commit;
a preview or failed request never pins or saves. Unchanged/omitted module revisions
retain the previous behavior. Unknown revisions and a PATCH `support_surface_id`
remain 422 refusals. Readiness still checks the selected module's simulation support.

The dialog shows the old and new module names, counts, STC power and affected
strings before Confirm. The demo explicitly refuses module replacement with
`DemoUnavailableError("Changing the module needs the engine")`: its legacy filler
uses a fixed synthetic module, and RF1 leaves demo table code unchanged.

### Global component library (S12a)

`POST /api/component-library/imports?filename=module.pan&dry_run=true` accepts an
`application/octet-stream` raw body, up to 2 MiB. No multipart dependency is used.
PAN and OND extensions are case-insensitive. Preview reports canonical parameter
values, schema findings, shared project readiness findings and layout-only reasons.
A schema-incomplete file can be previewed but cannot be committed. Set `dry_run=false`
to persist it; the response is `{entry, created}`. Duplicate bytes of the same kind
return the existing revision without writes.

The library defaults to the project store's sibling `component-library` directory.
`create_app(library_root=...)` can override it for isolated tests. Each immutable
`modules/<revision>.json` or `inverters/<revision>.json` contains `definition` and
`library` metadata; original bytes are retained in `sources/sha256/<hash>.<ext>`.
Writes use temporary files and atomic replacement under a process lock. Preview
and listing a missing library create no directory. Imports never change a project
revision. Fields and inverters pin their chosen canonical definitions through the
existing routes, so hiding or losing the library never changes an already pinned
project. Re-importing changed bytes creates a new revision rather than replacing one.

`GET /api/component-library?include_hidden=true` includes hidden entries. POST to
`/api/component-library/<revision>/hide` or `/unhide` changes only visibility.
Hidden definitions remain internally resolvable. The global catalogue omits them;
a project's view additionally includes its own pinned library revisions, including
hidden revisions and pins whose library directory is missing. Those local entries
use the pinned definition and shared readiness rules. Other projects do not inherit
these pins. This keeps existing field power, re-fill inputs and inverter labels
intact without unhiding an item globally or changing any saved bundle.
Reference summaries gain only `source: "reference"`; visible library summaries
have `source: "library"` and `synthetic_reference: false`.

Text is decoded with UTF-8 (accepting a BOM), then cp1252 only when the first 4 KiB
contain the ASCII `PVObject_` header. The entry records `source_encoding`; provenance
hashes always describe the original bytes. Synthetic cp1252 degree-comment tests
cover this path. A `pvModule;` legacy header, or non-text bytes without `PVObject_`,
gets `legacy_binary_pan_unsupported` and instructions to export modern text from
PVsyst. Parsers and all engine interpretation rules remain unchanged.

Preview power/current/voltage units use canonical values. Absolute power temperature
coefficients are converted from W/°C to %/°C using canonical STC Pmp; explicit relative
coefficients are multiplied by 100, and unknown bases remain null. Voc coefficient
is `mu_voc_v_per_c` in V/°C. `efficiency_fraction` selects the stated European metric
first, otherwise stated maximum, and `efficiency_metric` identifies which; the UI
displays percent and the metric name. No sampled-curve maximum is substituted.
Physical cell count, physical DC-power limits and total DC-current limits remain null
when absent. PV-array sizing limits and electrical series/parallel counts do not
supply these missing values. Per-MPPT operating current is shown separately.

Library readiness calls the shared module rule, or shared inverter capability issues
plus the existing Phase-5 inverter helper. The raw Huawei OND fixture is schema-ready
but layout-only: design gates still block missing current/frequency data. No hidden
datasheet overlay is applied. Imported Jinko simulates on the default geometric
shading path with an executable reference inverter and no module topology; detailed
electrical shading still needs its own supported assets. ENG1, ENG2 and frequency-rule
changes are separate slices. Demo library operations refuse with an engine-required
message and create no fake entries.

### OND importer upgrades (ENG1)

Component-library entries now record `library.importer_version: 2`. Missing version
metadata means version 1. Duplicates are matched by kind, original-byte SHA256 and
importer version. An explicit re-import of bytes previously imported by an older
version creates a new revision of the same definition and records
`library.remapped_from`; previews also expose `remapped_from` and the Import window
shows the replaced revision. Preview never writes or hides anything. On commit the
older revision is hidden, remains available to its existing project pins, and can
still be unhidden. No background migration or project-pin change occurs. Repeating
the import with version 2 returns the version-2 revision without writes.

The five verified OND display modes now share the same guarded Pin/Pout assembly.
Zero European/maximum efficiency summaries mean not given, allowing preview to
fall back to a stated nonzero maximum. Missing nominal AC frequency is a candidate
warning about datasheet/grid compatibility, not an energy or design blocker; no
50 Hz value is inserted. Raw Huawei OND still requires the physical per-MPPT
operating current before design readiness. Supplying it is S12a2, rather than a
hidden OND overlay. Existing pinned revisions retain their stored capability flags
until the user explicitly adopts a new revision.

### Module Voc coefficient tolerance (ENG2)

Importer version **3** applies the narrow beta-Voc readiness exception. An imported
module whose only failed check is beta-Voc becomes simulation-ready and carries
`MODULE_SDM_VOC_TEMPCO_MISMATCH`; its raw off-STC evidence still records failure.
The outer validation aggregate means accepted under the readiness policy, with
an explicit `readiness_tolerances` model annotation. STC, point, trend, alpha and
gamma failures remain blocking for detailed readiness.

Engineering string-voltage checks use the conservative cold-Voc/hot-Vmp envelope
for these annotated modules; actual energy, current and power calculation stays
on the SDM. Ordinary and reference module design results do not change.
Re-importing a v2 PAN explicitly creates a v3 revision through the existing
versioned library mechanism, hides the old revision and keeps old project pins
intact. No background upgrade or pin replacement occurs.

### Cited datasheet completion (S12a2)

`POST /api/component-library/{revision_id}/complete` fills missing inverter data:

```json
{"fields":{"mppt_template.max_operating_current_a":26},"source":{"document":"Manufacturer datasheet","page_or_section":"Electrical characteristics","url":"https://example.com/datasheet"},"dry_run":true}
```

Numbers must be finite, without string coercion. Extra request/source fields are refused.
Allowed paths: `mppt_template.max_operating_current_a` (0–200 A, exclusive zero),
`mppt_template.max_short_circuit_current_a` (0–300 A, exclusive zero and at least the
operating current), `ac_limits.nominal_frequency_hz` (50 or 60), and
`dc_limits.max_dc_current_a` (0–5000 A, exclusive zero). Only absent/null values can
be supplied. Existing values, even identical ones, return `completion_conflicts_with_file`;
other paths return `completion_field_not_allowed`. Document (1–200 characters) and
page/section (1–100) are mandatory (`completion_source_required`); URL is optional HTTP(S).

A dry run writes nothing and returns a normal preview plus `completion_fields` (the
remaining absent allowed paths, units and bounds) and `completed_fields` (values and
citations). Save with `dry_run:false` returns `{entry,created}`. It creates the next
revision of the same component identity through the canonical source-overlay builder,
records field provenance and `library.completed_from` / `library.completion`, then hides
the base revision. Raw bytes and existing project pins are preserved. Base revision plus
canonical fields/source hash makes repeated completion idempotent; a different citation
creates a different revision. Reimporting raw bytes never silently adopts a user overlay.
Library list entries include `completion_preview` for opening the same completion form.

Importer version 4 also accepts single `ProfilPIO` curves as three identical voltage
curves with an explicit `INVERTER_SINGLE_EFFICIENCY_CURVE` warning; the runtime is
unchanged. An empty upload returns `component_file_empty`: “The file is empty. Copy it
again from its source.” Preview `reasons` are now `{code,message,...params}` objects:
English uses the service message; Indonesian uses recognized codes; unknown codes and
passthrough findings retain the service message. `basic_design_not_ready` carries
underlying `rule_ids`. Missing MPPT current remains a design blocker until completed.
The form requires importing an uncommitted file to the library before completion.

### Weather file import (S12b)

`POST /api/projects/{project_id}/weather/import?filename=weather.epw&dry_run=true`
accepts a raw `application/octet-stream` body, up to **50 MiB**. Supported formats:
EPW, TMY3, OpenSIMPV CSV, Meteonorm DAT and documented PVsyst Standard CSV. There
is no multipart dependency. Detection, parsing, interval conventions and QC use
the existing weather subsystem unchanged. Imports do not use S10's provider window
trim and never shift, fill, repair or interpolate the parsed series.

Preview returns format, basename, SHA-256, file/site coordinates and distance,
source/canonical/site timezone information, period, cadence, row count, variables,
typical-year marker, twelve monthly GHI integrals and a period total in kWh/m²,
plus QC findings, coded warnings and `requires_accept_distant_location`.
`annual_ghi_kwh_m2` is the sum over the **supplied period**, never an extrapolated
annual yield for a partial file. Months without rows are zero; months containing
unknown GHI and their total are null. Calendar grouping follows the canonical file
timezone, shown in the preview. Typical-year months are labelled without an
observation year; coverage and row count remain explicit.

File location within 10 km is accepted. Above 10 km adds
`weather_location_distant`; above 50 km also requires the explicit commit query
flag `accept_distant_location=true`. Missing coordinates add
`weather_location_unknown`. Elevation differences above 500 m and declared source
UTC offsets differing from the site's standard offset add informational warnings.
The standard offset excludes DST, at the dataset's first canonical instant.
OpenSIMPV CSV may supply a source timezone without a numeric source offset; the
unknown numeric offset is shown as unavailable. No offset is invented or applied.

Commit uses `dry_run=false`, refuses failed/error/blocking QC as
`weather_quality_failed`, and returns `{selection,manifest,preview,duplicate}`.
The existing project busy registry blocks imports during another operation and
protects site edits/deletion during import. Saving reloads the current project
under the store lock and uses optimistic concurrency, preserving ordinary scene
and electrical edits. Selection and its project-revision weather reference change
together; earlier runs retain their immutable weather revision and artifacts.

Raw bytes are in the existing SHA-256 snapshot store with suffix `.weather`.
The weather revision store's generic `acquisition_manifest` slot contains a
`kind: "file_import"` record: format, filename, sha256, importer, importer_version,
size, imported_at, file location, original distance, warnings and explicit distant
acceptance. `importer_version` versions this file-import pipeline; canonical
transformation algorithms retain their existing independent versions. This record
is not a provider `WeatherSourceAcquisitionManifest` and asserts no provider
retrieval. No schema changed. Reimporting identical bytes within a project
reselects the same immutable weather revision, retaining its original import
manifest. Coherence is rechecked against the current site, including renewed
explicit distance acceptance when required.

Errors have `detail: {code,message,...}`: `weather_file_empty`,
`weather_file_too_large` (413), `weather_format_unsupported`,
`weather_parse_failed`, `weather_quality_failed` and `pvsyst_met_not_supported`.
The last explains how to export hourly weather from PVsyst as **PVsyst Standard
CSV**; internal text/binary `.MET` decoding remains deferred.

**Mixed-year EPW limitation (A1):** the EPW importer preserves its source years.
Files built from months of different years that fail existing timestamp QC are
refused, with `weather_quality_failed` and `reason_code:
weather_typical_year_mixed_years`, plus the plain instruction to use a single-year
file or export PVsyst Standard CSV. The preview carries the same coded warning.
Regular fixed-year EPW and continuous actual data crossing a year boundary remain
accepted. Non-continuous mixed-year PVsyst Standard timestamps are likewise
refused by unchanged QC. S12b1 will address EPW normalization; S12b never retimes
such data. TMY3's existing mixed-year anchor normalization remains supported and
can execute a full typical-year simulation.

### Standard multi-group and multi-inverter runs (S16)

`GET /execution-readiness` and `POST /simulate` support electrically separable groups:
each MPPT's strings have one module revision, orientation, albedo and modules-in-series.
Different MPPTs and enabled inverters may differ. The standard geometry-aware beam,
sky and ground path is retained; receivers use their own group's area-weighted factors
while all scene occluders remain physical inputs.

Manual mixed-MPPT assignments remain valid draft edits. Readiness blocks them with
`SIMULATION_SCOPE_MIXED_STRINGS_ON_ONE_MPPT`, a plain message naming the MPPT/inverter,
and group details. Automatic assignment and rebalance keep compatibility groups on
separate trackers and refuse atomically if capacity is insufficient. An empty enabled
inverter reports “assign strings to it or disable it”. New multi execution refuses
nonzero global DC-array resistance; a present loss-settings block supplies the supported per-circuit wiring law. Detailed
multi-inverter requests return `SIMULATION_SCOPE_DETAILED_SHADING_SINGLE_INVERTER`
before dispatch under either fallback policy; existing detailed eligibility is retained.

Legacy single-group/single-inverter result objects are unchanged. Newly supported runs
add optional `summary_result.execution_breakdown`: group DC/POA, per-inverter period
energy/specific yield/clipping/voltage and startup losses, recorded simulated DC nameplate,
and group/inverter time-series references. Those datasets are stored and hashed in the
immutable run package. Annual energy stays null for partial periods. Plant and inverter
PR use DC-nameplate-weighted equivalent unshaded POA, with actual per-group POA retained.
No single plant module temperature or voltage is fabricated.

The per-inverter conversion policy is
`power_weighted_voltage_efficiency_at_total_inverter_dc_power`, with one startup/AC
limit/clipping decision per inverter. It pools accepted MPPT power; it is not PVsyst's
default independent-input allocation. PVsyst comparisons must account for power sharing;
this route makes no general claim of PVsyst multi-MPPT numerical parity. Net inverter
AC sums at the PCC without a new downstream AC loss model.


## Loss settings

`PATCH /api/projects/{id}/losses` accepts `{"overrides": {...}}` or
`{"reset_to_recommended_defaults": true}` alone. Values are dimensionless fractions,
reference power W; null leaves remove an override and inherit the versioned rule.
Arrays replace atomically. Soiling accepts 12 monthly fractions or an annual
shortcut, never both. Unknown inputs, nonfinite numbers, invalid ranges, exhausted
ageing and enabling a transformer without copper input return plain 422 messages
before saving. PATCH bumps the project revision once; scene/electrical revisions
stay unchanged. A no-op creates no revision. Existing optimistic 404/409 protection
applies, with no automatic client retry.

`GET /api/simulation-defaults` includes `loss_settings` with Recommended defaults
and sources. New projects store the minimal versioned override object. Old projects
inherit it on their next browser run without a GET writing their bundle. Existing
runs remain immutable. Browser runs always pass this block; raw engine runs without
it retain their historical behavior. Results displays the selected run's immutable
resolved values, sources, settings hash and circuit references. Old runs show legacy
settings and never substitute today's project inputs.

Loss inputs include monthly soiling, first-exposure LID, automatic or explicit
manufacturing dispersion, per-MPPT STC wiring, per-inverter nominal-power AC wiring,
midpoint linear annual degradation and operating year, optional continuously
energized transformer, and deterministic positive-export unavailability. AC wiring
and unavailability at zero mean **not set**. Module quality stays pinned/read-only;
optics and thermal settings remain read-only pending the next slice. The waterfall
separates optical reference energy from actual raw MPP, and the inverter subtotal
minus plant adjustments equals PCC. Detailed mode retains its IV mismatch and also
applies the independent manufacturing-dispersion scalars downstream. See the loss
engine README for equations and boundaries. Demo results stay explicitly synthetic.

For a detailed MPPT, automatic manufacturing module-dispersion fractions must
agree across its strings/modules. If they differ, readiness and execution refuse
with the inverter name, MPPT name and fractions before dispatch. Set an explicit
module-mismatch override (0 is allowed); no maximum or weighted allocation is
assumed. Agreeing automatic fractions need no override. String dispersion still
uses the total parallel string count on that MPPT.

### Optics and thermal settings

`PATCH /api/projects/{id}/optics-thermal` saves a separate versioned settings object. Send
`{"overrides": {...}}` for a partial change, or `{"reset_to_recommended_defaults": true}` to reset only this form.
A null override leaf removes that override. Unknown fields, nonfinite values and conflicting annual/monthly albedo
are refused. A no-op on an inherited legacy project writes nothing and creates no revision. Real changes use the
same optimistic concurrency guard as other edits.

Recommended defaults select hourly Perez, the pinned module's IAM table with a normal-glass Fresnel fallback when
absent, semi-integrated mounting (air duct below) with Uc 20 / Uv 0, effective irradiance **after soiling** for heat
balance, and albedo 0.20 in each local month. The fallback assumes no anti-reflective coating; it is not a measured
module profile. Malformed declared tables are refused, rather than silently replaced. The absorption coefficient
continues to come from the pinned module, with the existing 0.9 fallback.

For a legacy-reference comparison, the incident heat-balance basis remains selectable, including through the API:

```json
{"overrides":{"thermal":{"irradiance_basis":"incident_pre_iam"}}}
```

Other transposition choices are `isotropic`, `hay_davies`, `perez_1990` and `perez_driesse`. IAM choices are
`module_auto`, `module_table`, `physical_glass` and `none`. Thermal presets are `semi_integrated`, `open_rack`,
`insulated_back`, `dome` and `custom`. Custom Uc must be positive and Uv nonnegative; nonzero Uv requires wind data.
The efficiency denominator follows the selected heat-balance irradiance basis.

`albedo.monthly_values` contains exactly twelve fractions in [0,1]; `albedo.annual_value` is the shortcut. Resolve
months from local interval starts, as for soiling. Present settings override the support surface's scalar albedo.
Only all-zero completed GHI/DNI/DHI intervals use the exact zero-input transposition limit. Nonzero-input NaNs are
not filled or interpolated. Detailed runs retain separate isotropic/circumsolar/horizon visibility and their
requested fidelity. A physically inadmissible negative combined irradiance is refused.

The defaults endpoint includes `optics_thermal_settings`; project views include `resolved_optics_thermal_settings`.
Each new run stores its immutable resolved snapshot and per-module IAM source. Results uses the selected run's
snapshot; older runs never borrow current project choices. Resetting optics/thermal does not reset losses.

### Circuit loss settings and two AC segments (S18c)

PATCH `/api/projects/{id}/losses` retains its existing `overrides`/reset contract.
Optional `circuit_overrides` contains `binding.electrical_revision_id`, plus
`inverters` and `mppts` maps keyed by canonical instance IDs. Rows accept
`dc_wiring_stc_fraction` and signed `module_quality_fraction`; inverter rows also
accept `ac_wiring`. The server derives `binding.topology_sha256`; a caller-supplied
wrong digest or stale submitted revision is refused. To explicitly rebind after a
topology change, submit the current electrical revision and PATCH the old digest
to null; the server recomputes it. Readiness reports `LOSS_SETTINGS_INVALID` on
stale/missing targets under both fidelity policies. `loss_binding_findings` in the
project view explains stale settings immediately. Reset works while stale.

`plant_ac_wiring` is independent of inverter segments and applies once before
transformer/unavailability. Both it and an inverter `ac_wiring` accept:

- `{mode:"percent", loss_fraction:f, reference:"rated_ac"}`; or `reference:"custom"`
  with `reference_power_w` explicitly supplied;
- `{mode:"cable", length_one_way_m:L, cross_section_per_phase_mm2:A,
  material:"copper"|"aluminium", line_voltage_v:V, conductor_temperature_c:T,
  phase_system:"balanced_three_phase", power_factor:1}`.

Fractions use dimensionless units; wiring is [0,1), quality (-1,1). Cable temperature
is explicit and editable; voltages must match the pinned three-phase combiner bus.
The model assumes fixed-temperature equal conductors at unity power factor. See
`engine/losses/README.md` for the resistance law and property convention. There is
no cable-sizing or undefined STC-reference feature. Null removes an override.
No-op settings save creates no revision. An enabled empty inverter still needs
strings or disabling under the existing readiness rule.

New runs record `circuit_loss_resolution`: actual circuit references, resolved
fractions/quality/origins, AC modes and physical constants, and the inverter/plant
energy reconciliation. Results uses the selected run's immutable record. Old run
artifacts and numerical outputs with absent/redundant new settings stay unchanged.
Poly-Si `mtSiPoly` PANs now map explicitly and use the existing documented
crystalline-silicon bandgap completion. Re-import under importer version 5 creates
a new immutable revision; it never automatically changes a project's module pin.

### Exact mesh obstacles and explicit PV tables

`POST /api/projects/{id}/scene/geometry` accepts ordered `operations`, optional
`dry_run` and `discard_dependent_strings` booleans. Each operation supplies a unique
`operation_id` and `operation_type`: `create_mesh`, `replace_mesh`, `delete_mesh`,
`create_explicit_field`, or `delete_explicit_field`. Mesh operations identify
`obstacle_id`; creation also supplies `scene_object_id`, `name`, `mesh` and
`provenance`. A mesh has metre-valued `vertices_m` and ordered indexed `faces`,
with an optional proper rigid transform. The opaque faces are two-sided, including
open/nonmanifold sets; closed meshes do not imply solid interiors. Nothing is
welded, repaired or extruded. Face deviation above 1e-9 m through 1 mm is accepted
with `nonplanar_within_tolerance` evidence and original-vertex triangulation;
above 1 mm is refused.

Explicit creation supplies `pv_field_id`, `name`, `tables` and `provenance`.
Each table supplies `table_id`, `anchor_xyz_m`, `anchor_convention`, `tilt_deg`,
`azimuth_deg`, `module_definition_revision_id`, `modules_across`, `modules_up`,
`module_orientation`, `module_gap_across_m` and `module_gap_up_m`. Optional
`rectangle` gives `width_m`/`height_m`; optional `support_surface_id` declares a
support without changing the anchor height. Anchors are `center`, `lower_left`,
`lower_center`, `lower_right`, `left_center`, `right_center`, `upper_left`,
`upper_center`, `upper_right`. Left/right are seen facing the table front (right
is east for a south-facing table). Module IDs are deterministic. No packer is
invoked; no field-wide module, tilt or azimuth is inferred from the first table.

Limits per request: 16 MiB streamed JSON, 2,048 operations, 2,000 tables,
512 meshes, 50,000 vertices, 50,000 faces, 500,000 index references,
512 indices per face and 50,000 generated modules. Byte excess returns 413;
validation errors return 422 with `code`, `message`, operation position/identity,
object identity and `findings`. A preview writes nothing. A failed operation,
physical conflict, unconfirmed dependent string deletion or optimistic-save
conflict leaves storage unchanged. Commit saves one scene/project revision and
one electrical revision when deleting dependent whole strings; an identical
no-op saves nothing. Explicit layouts and meshes are read-only through ordinary
geometry tools; replace/delete them using the bulk API. Delete explicit fields
before editing their declared supports. Existing field deletion also previews
and deletes explicit fields with the same string confirmation policy.

`GET /api/projects/{id}/scene/geometry-3d` returns exact derived world vertices,
triangles, original face boundaries and module corners with source revision/hash.
The 3D view uses these only for the new objects; load errors never substitute an
extrusion or guessed module height. Degenerate module plan projections use a
line/point readback, not a fabricated polygon. Bulk editor transactions are
one undo step each through the project-level undo/redo routes (session-only; see
"Session-only undo and redo"). Browser studies always enable whole-scene module self-shading, generated
fields included (RB-4D, 2026-11-08; see "Row-to-row shading" below). Standard and
detailed execution keep their existing electrical topology/evidence requirements.


## Project shading accuracy

`PATCH /api/projects/{project_id}/shading-accuracy` saves a versioned project choice:

```json
{"overrides":{"level":"high"}}
```

Only `standard` and `high` are accepted. Reset with
`{"reset_to_recommended_defaults":true}` or remove an explicit level with
`{"overrides":{"level":null}}`. Repeating identical stored settings creates no
revision. An explicit Standard override changes provenance from inherited defaults;
resetting it restores the default source. Settings edits use the existing optimistic
concurrency guard and bump the project revision, without changing geometry or wiring.

Standard (recommended) uses sky 48×12, horizon 48×1 at 10°, and ground 48×12.
High (slower, finest sampling) uses sky 72×18, horizon 72×1 at 10°, and ground 72×18.
These are denser samples of the existing models, not a different sky or ground model.
High is not guaranteed to reduce every quadrature error monotonically.

`GET /api/simulation-defaults` exposes `shading_accuracy`; project views expose
`resolved_shading_accuracy`. Missing settings on an existing project resolve to Standard
on its next run; reads do not rewrite the bundle. Each browser run records the actual
choice, source and numeric resolutions in its immutable run/model/reproducibility
snapshot. Results use the selected run's evidence; unavailable legacy evidence is
labelled as not recorded. Current project settings never replace an old run's inputs.

High takes longer, especially with detailed electrical shading. The standard path
caches static sky/ground snapshots; the detailed path currently recomputes region
visibility each interval and can take hours for long studies. Fidelity is never
silently reduced. Explicit engine configurations retain their own grids and are
unchanged when the new browser settings block is absent.

### Session-only undo and redo

Every changed design save records one in-process history entry; previews, no-ops,
workspace changes, reads, exports and simulation results do not. Weather acquisition
and import, electrical-shading asset import, and project create/delete are barriers.
Global library changes do not alter existing project pins. Hard-delete is permanent.

`POST /api/projects/{id}/undo` and `/redo` take
`{expected_project_revision_id, expected_entry_id}`. Both the entry at the requested
end of the ring and the exact current design projection must match. Success creates
fresh scene, electrical and project revisions, preserving entity IDs, pins and saved
runs. Structural/pin/weather validation failure returns 422 without advancing history;
no extra geometry-readiness gate is applied. Unavailable history returns 409 with
`detail.reason: history_unavailable` or `revision_mismatch`, clearing the ring. This
is distinct from the unchanged `updated_at` edit conflict and busy-operation 409.
The old `/scene/commands` undo/redo commands remain unsupported (422).

Each entry's label is the operation's change summary. A save that does not create a
new project revision (`PATCH /api/projects/{id}`) is labelled from that operation:
"Rename project" or "Edit project details", never the earlier revision's summary.

`POST /api/projects/{id}/electrical-shading/selection` records an undoable entry but
returns the selection result, not a `ProjectView`, so a browser cannot observe that
entry's ID (GETs never add browser steps). No browser control calls this route yet.
Before one does, the route must return the `ProjectView`; otherwise the browser's next
undo is refused with 409 `revision_mismatch`.

`ProjectView.history` is transient (never part of the bundle): `limit`, retained
ordered `past`/`future` entry IDs and labels, and `reason`. GETs never create steps.
The browser owns the combined local/engine stack. Reload/project switch clears that
stack; old server entries become unreachable and expire. Local branching clears
client redo; unreachable server redo is released at the next edit, expiry or eviction.

Operator settings are read at startup. Values must be ASCII decimal digits only
(`^[0-9]+$`, so no sign, whitespace or `_`); anything else is refused:

| Environment variable | Default | Bounds / meaning |
|---|---|---|
| `RAWIBUMI_UNDO_HISTORY_STEPS` | 10; exactly `RAWIBUMI_DEPLOYMENT_EDITION=commercial` gives 100 | 1–100; either edition may override |
| `RAWIBUMI_UNDO_PROJECT_BYTES_MAX` | 268435456 | Positive; retained serialized snapshot bytes per project |
| `RAWIBUMI_UNDO_TOTAL_BYTES_MAX` | 1073741824 | Positive; process-wide snapshot bytes |
| `RAWIBUMI_UNDO_IDLE_SECONDS` | 1800 | Positive; monotonic seconds since last edit/traversal |

Restore validates the whole bundle schema while holding the project store lock. On a
2.2 MB bundle carrying the P3 reference design (2,592 modules) that validation took
0.23–0.26 s and the projection 0.013 s (2026-11-08, one workstation).

Adjacent immutable snapshots share storage. Per-project limits drop the oldest
steps; the global cap evicts least-recently-edited projects. An oversized state is a
history barrier rather than a refusal to save a valid design. Byte caps bound payload,
not the interpreter's total RSS or JSON serialization scratch memory. History has no
accounts or telemetry; Phase 8 will need authenticated ownership and shared storage
before a multi-process/multi-user deployment. The existing native-PDF edition gate
is independent and unchanged.

Undo preserves all saved runs. Project-list rename is unchanged and has no new
list-level undo control.

### Project files, backups and schema versions (DATA1)

**Export and import.** `GET /api/projects/{id}/export?include_results=true|false` returns one `.rawibumi` file, a ZIP
holding:
- `manifest.json`: format `rawibumi-project` v1, export time, engine version, project ID, schema version,
  `include_results`, and every member's size and sha256;
- `project.json`;
- the project's weather revisions and the raw weather snapshots their manifests reference;
- its overlay images;
- optionally, its saved run packages.

Without results, each run record keeps its summary and carries `package_omitted: true`. CSV, report, PDF and run
result routes refuse such a run with "This run's result package wasn't included in the imported file."

`POST /api/projects/import?filename=&replace=false` takes the file as a streamed body (at most 2 GB). It checks, in
order:
1. archive safety: relative paths only, no `..`, no links, at most 5,000 entries, 2 GB uncompressed, and a 200×
   expansion guard;
2. the manifest and every checksum;
3. the project file (corruption check, schema upgrade, bundle schema);
4. that every entry sits in its expected place for that project;
5. weather snapshot and overlay image hashes.

Nothing is written before all of this passes. Writes are staged, and on any failure the original trees are moved back,
so an import either completes or leaves things as they were. The project keeps its ID. If it already exists, the
answer is 409 `{code: "project_exists"}` unless `replace=true`; a replace takes a protected backup first. An import is
an undo-history barrier. Importing as a new copy with fresh IDs isn't offered yet.

**Backups.** Every save also writes that version to `<store>/.backups/<id>/<UTC stamp>-r<revision>.json`; the newest 20
are kept, and the newest is the current save. A protected copy (`…-protected-<reason>.json`, at most 10) is taken before
an import-replace, a backup restore or a schema upgrade. `GET /api/projects/{id}/backups` lists them, newest first.
`POST /api/projects/{id}/backups/{backup_id}/restore` checks the backup, takes a protected copy of the current file and
restores it; it is an undo-history barrier and waits for no running simulation. Backups are removed with the project.

**Damaged files and versions.** A project file that isn't UTF-8 JSON, isn't a `ProjectWorkspaceBundle`, misses
required parts or names another project is reported, not hidden:
- the project list shows it as `status: "unreadable"` with a `reason`;
- opening it returns 409 `{code: "project_unreadable"}`;
- it can be restored from its backups.

`apps/api/migrations.py` holds the ordered schema upgraders (version → next version). A file on an older schema is
upgraded once on load, after a protected `schema-upgrade` backup. A file from a newer app is refused unchanged with
409 `{code: "project_too_new"}` ("saved by a newer RawiBumi"). The current schema is `0.1`, and no upgrader exists yet.

### Row-to-row shading (RB-4D)

Every browser study runs with `shading_configuration.self_shading_enabled = true`, so modules shade one another: beam
row-to-row shading, and front rows masking the sky and ground views. Until 2026-11-08 this was on only for scenes with
explicit tables, and generated multi-row fields were optimistic: on clear-sky years, by 0.2% at tilt 10° and pitch
3.2 m, and by 1.6% (Jakarta) to 5.3% (Sydney) at tilt 20° and pitch 2.6 m, enough to reverse a tilt or pitch choice
(`.ai/validation/4D/REPORT.md`). A single row is unchanged. The standard path applies area-fraction (linear) beam
shading without partial-shading electrical mismatch, so its shading loss is a lower bound; the detailed electrical
path adds mismatch. Multi-row annual runs take about 8× longer than before.

Each new run record stores `module_self_shading: true`. Saved runs are never rewritten; runs without the field
predate the change, and the browser notes that their multi-row results may be optimistic.

### Imagery (UX1)

Imagery is context only (`map_measurement_role: context_only`): it never sets an
engineering dimension. A project keeps it in its own optional bundle section
`imagery`, a `MapLayerConfiguration`. It is not part of the scene, so it never changes
the scene revision or scene hash, and it is not part of the RES1 design fingerprint,
so it never marks a run as from an earlier design. It is an S17 undo key. A restore
that changes only imagery or project labels keeps the scene and electrical revisions;
only the project revision advances.

- `POST /api/projects/{id}/imagery/assets?filename=` takes the raw image bytes:
  PNG, JPEG or WebP only, at most 10 MB (413 above) and 8,192 px per side. Images are
  checked by signature and header dimensions; pixels are never decoded. The asset ID
  is content-addressed (`img-` plus 24 hex characters). Images are kept per project
  until the project is deleted, so an undo can always bring an earlier overlay back,
  and `DELETE /api/projects/{id}` removes them (`removed.imagery`).
- `GET /api/projects/{id}/imagery/assets/{asset_id}` returns the bytes with the stored
  type and `nosniff`.
- `PUT /api/projects/{id}/imagery` takes a `MapLayerConfiguration`, or `null` to
  clear it, and returns the project view. It is one undo step, labelled "Edit
  imagery". Rules: the JSON schema and the configuration validator; at most one
  `xyz_raster` provider and one `uploaded_asset`; only `aerial_imagery` and
  `orthophoto` layers; a template must be `https://` with `{z}`, `{x}` and `{y}` and
  must use `{key}` rather than a literal key query value; `credential_reference`
  must be `browser-key:<name>`; an orthophoto's image must be uploaded to this
  project, with the same pixel size; control points must be finite. Layers may
  carry `opacity` (0.1–1) and `locked`.

No imagery key is shipped, stored or sent to the engine. The browser keeps the
bring-your-own-key provider and its key in its own storage, and fills in `{key}` when
it requests tiles. A project stores only the template, the attribution and the
`credential_reference`.

### Design basis of saved runs (RES1)

Each new run record stores `design_fingerprint` (`sha256:` plus 64 hex), taken from
the bundle `run_study` reads at launch, so edits made while the run is in progress
never relabel it. `ProjectView.design_fingerprint` is the current design's value; it
is transient and never written to the bundle. Both hash the canonical JSON of the
undo projection above without `project.name`, `project.description` and the
context-only `imagery` section, so a
project rename doesn't mark runs as outdated. Every other design change does,
including entity names and `site.name`. An undo back to the exact design matches
again.

Runs saved before RES1 have no fingerprint and are not backfilled; the browser
treats them as design-unknown.

### Annual P50–P95 (UNC1)

`GET /api/projects/{id}/runs/{run_id}/annual-pxx` returns an `AnnualPxxView`: the annual energy exceedance P50,
P75, P90 and P95 of a completed annual run's PCC energy, under the project's uncertainty-assumption ledger. It uses
the analytical Gaussian method of the standalone Uncertainty Engine's U1 v1.0, implemented natively in
`engine/uncertainty/annual_pxx.py`; U1's reference fixtures reproduce bit for bit.

- **Mean:** the run's annual energy is treated as the annual mean in this version. `basis.annual_mean_basis` is
  `typical_year_as_mean` or `historical_year_as_mean`, from the weather dataset's calendar type.
- **No numerical defaults:** every term has its σ (kWh or a fraction of the mean), source, justification, scope,
  provenance and a unique double-count group. Correlation is `independent_explicit` with a basis statement, or a
  `matrix_explicit` that is symmetric, positive semidefinite and has a basis statement.
- **P99** is always `unavailable` (`P99_NOT_QUALIFIED`).
- **Refusals:** a negative Gaussian quantile is refused (`NEGATIVE_GAUSSIAN_TAIL`), never clipped. `Pr(Y≤0)`, the
  covariance and the signed per-term allocations (not physical losses) are disclosed.
- **Unavailable states** are data with reason codes (`RUN_NOT_ANNUAL`, `RUN_NOT_COMPLETED`, `NO_ASSUMPTIONS`, or a
  U1 code), never zeros.
- **Label:** always `model_based_estimate` / `assumption_based`.

`PUT /api/projects/{id}/uncertainty-assumptions` with `{"ledger": {...} | null}` saves or clears the ledger. The
ledger is the optional bundle section `uncertainty_assumptions`. A save is an undo step, bumps no design revision and
is outside the design fingerprint, because it never changes a simulation. An invalid ledger returns 422 with the
U1 code and its JSON path. With a ledger present, the export deliverable adds `annual-pxx.json` (the same view)
and `annual_pxx_status` in its manifest.

### Launch readiness warnings, run series and D14 (S15)

New run records also store `readiness_warnings`: the readiness findings of severity
`warning` at launch (`rule_id`, `severity`, `entity_id`, `message`, `category`), for
example modules left out of the run. Older runs don't have the field.

`GET /api/projects/{id}/runs/{run_id}/timeseries` returns the run's stored hourly
series as site-local day × 24-hour matrices (AC power in kW, POA, GHI, and cell and
ambient temperature). A missing hour is null; a repeated daylight-saving hour is
averaged and counted in `quality`. The response also has the monthly table: energy,
unshaded POA, GHI, specific yield, PR = energy ÷ (kWp × unshaded POA) as for the
engine's annual PR, and the staged-ledger losses per channel. It reconciles with the
run summary and refuses on a mismatch. It reads only the verified package
(completed, registered, hourly, not `package_omitted`). `POST .../exports` adds
Parquet and the full deliverable; see `reporting/exports/README.md`.

**One DC nameplate (D14).** A module's DC nameplate is its datasheet nominal power
(`stc.nominal_power_w`), else its STC `pmp_w`, as the engine's installed capacity
already was. The validator's DC/AC ratio and string power, the layout and fill
previews, the readiness exclusion warning, and the new catalogue summary field
`nominal_power_w` use it. Catalogue `pmp_w` stays as the STC specification value.
Engine results are unchanged. The run package, `input_hash`, the server report and
the exports are unchanged. The browser shows only figures saved with an earlier or
unknown run, and its HTML report refuses such a run.
