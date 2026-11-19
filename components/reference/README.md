# RawiBumi synthetic reference components


These JSON definitions are deliberately synthetic, redistributable reference
components used by the browser/API product shell and deterministic tests.


They are **not** vendor products and must not be presented as manufacturer data.


Their purpose is to make a clean self-hosted RawiBumi checkout immediately
testable before a user imports PAN/OND/CSV data or connects a larger open
component catalog.


## Phase 6.2 electrical-shading reference assets


- `module-topology-uat-550.json` is an explicit RawiBumi-owned synthetic
  `ModuleTopologyDefinition` bound to `mod-rawibumi-uat-550-r1`.
- `source-topology-uat-550.json` is the canonical `SourceRecord` for that topology.
- The topology is maintainer-authored reference data. It is **not** inferred from
  `module-uat-550.pan` cell count, parallel count, bypass count, or layout tokens.
- Its 0.55 V bypass model is an explicit simulation assumption carried by the
  topology contract; it is not manufacturer bypass-diode truth.
- The reference catalog intentionally contains no production region/cell
  parameterization evidence at this tranche.


These assets exist to exercise revision binding, provenance, fail-closed capability
resolution, and product integration before detailed mismatch physics is implemented.