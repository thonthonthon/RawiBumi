# Reference benchmark tooling

VAL1a prepares P2 and P3 for a later benchmark. It always reports **blocked** and produces no energy verdict. It never calls simulation. P1 is deferred.

Run from the repository root with an external, empty disposable directory:

```sh
.venv/bin/python -m validation.pvsyst_benchmark.cli \
  --manifest .ai/validation/VAL1/INPUTS.json \
  --scratch "$VAL1_DISPOSABLE_ROOT" \
  --output .ai/validation/VAL1/final
```

The private manifest contains exactly P2 and P3. Each entry supplies `csv`, `vc`, `prj`, `shd`, a `modules` list, `inverter`, and a `completion` specification. The latter contains `model_token`, exact `identity_checks`, missing `fields`, and a citation `source` with document, page/section and URL. Source paths and values belong in ignored evidence only. Inputs are read in place; raw component retention is confined to the external disposable library. No source file is rewritten.

The command uses the real HTTP application through TestClient for component import, cited completion and project creation. Weather attaches through the approved canonical weather-store/service bootstrap. It creates no scene approximation or electrical topology. The later headline policy is standard geometry-aware execution with an effective thermal basis.

The reader accepts only the registered version, column/unit pairs, complete hourly interval-start labels and finite values. It supports Latin-1 exports and discovers comma or semicolon headers. Solar evaluation is at the interval midpoint; the design evidence checks this against the reference solar columns and records the separate sunrise/sunset timing limitation. The basis register separates orientation-2 components from proved plant channels. Unproved or absent quantities are unavailable, never zero.

Weather recovers DNI from `BeamHor / sin(HSol)`, without clipping or a low-sun floor. Positive beam with a nonpositive source sine is refused. Execution retains its independent solar geometry. P3 omits the entire wind column under the approved zero-Uv policy; values are never clamped. Both basic and solar-aware QC are recorded.

The source extractor retains unmapped keys in an unsupported register. Scene checks reconcile counts and orientations, compare saved/embedded world geometry, refuse non-linear shading modes, and test nine discrete table-anchor hypotheses against independent support faces. An anchor is accepted only if uniquely consistent. Missing transforms are unavailable. Mesh topology classes distinguish proven vertical prisms from general or damaged meshes; there is no footprint/maximum-height substitution. The fixed millimetre serialization checks are not optimized against energy or used to tune placement.

Private JSON contains source hashes, extraction ledgers, QC, component completion receipts and reconstruction evidence. Public summaries use an explicit allowlist: P-label, blocked status and reason codes only. Comparison functions are available for aligned, basis-qualified series and synthetic metric tests; this preparation command does not publish a yield comparison. MESH1, per-circuit settings, unresolved component readiness and user AC/transformer inputs remain explicit prerequisites.

Run the synthetic tests with `pytest tests/unit/test_val1_*.py`. They include a no-simulation guard, the actual cited-completion route against fictional data, malformed-reader refusals, reconstruction gates and a privacy scan. All fixtures are invented, not excerpts of reference files. No production files, dependencies or public contracts are changed.

## Complete-project readiness (VAL1b)

`headline_assembly.assemble_case` implements the approved DEC-160/A1 assembly through the real HTTP routes, with the unchanged VAL1a weather bootstrap. Supply a client whose project store and component library are both outside the repository, a private input manifest, the approved plant-loss fraction, and a private receipt dictionary. The function never dispatches simulation and refuses a simulation URL in its HTTP wrapper. The VAL1a preparation CLI above retains its original blocked/no-verdict behavior.

`headline_scene` maps the approved front-view anchors and applies the proved identity rotation plus the source translation. Only the identity-specific A1 source-face exception may be omitted, after its line-offset, area, horizontal-plane and invalid-polygon guards pass. Every retained face is validated unchanged. The receipt records the exception, original face index, preserved vertices, geometry statistics, signed-area shadow estimate and conservative convex-hull envelope at a labelled elevation threshold. This is not an all-angle annual energy bound. No general mesh repair or degenerate-face filter exists. P2 retains declared table rectangles; P3 uses physical module occupancy, with the declared-versus-occupied deviations retained as evidence. Exact known typed-list terminators require matching declaration types and counts; other unknown scene semantics are refused.

`headline_electrical` orders tables spatially, then modules by row and column, creates consecutive source-length strings, and uses the approved balanced integer division across inverters and their MPPTs. The source-derived custom AC reference uses PAN nameplate power and the existing unclipped OND conversion at STC voltage. It does not use reference energy, replace the engine interpolation, or include clipping. Per-inverter DC/AC ratios are retained for the later clipping attribution.

Assembly checks HTTP readback for the loss, circuit, optics, thermal and shading settings; verifies module IAM and absorption through the existing configuration resolver; and requires complete readiness with every placed module represented exactly once in the execution plan. A readiness receipt is permission to request annual-run approval, not a benchmark verdict. Hourly inverter overshoot and clipping attribution remain required after separately authorized runs. The synthetic VAL1b tests are `pytest tests/unit/test_val1b_*.py`; they include an end-to-end annual-weather assembly with simulation prohibited.

For headline comparisons, pass an independently proved case-specific register to
`Reference.basis(..., proven_bases=...)`; absent entries are unavailable. The
historical default classifications are not a proof for a new case. `AngInc` uses
orientation 1; raw `FIAMAlb` is unavailable as a factor. The headline comparison
helpers require unique evidence, retain the superseded diffuse diagnostic, and
export only P-labels, relative deviations and runtime in public summaries.
