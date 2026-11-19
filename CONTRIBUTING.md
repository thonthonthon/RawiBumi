# Contributing to RawiBumi


RawiBumi is in beta: it works end to end, and its interface is still being reworked (see "Known work in progress" in the README). Contributions are welcome, but changes that affect engineering meaning must be treated differently from ordinary UI or refactoring work.


## Before contributing


1. Check the current architecture and subsystem specifications in `docs/`.
2. Keep external formats behind adapters. PAN, OND, weather formats, and imported geometry must not leak source-specific semantics into the simulation core.
3. Preserve units, provenance, revision identity, and missing/unknown states.
4. Do not introduce hidden engineering assumptions.
5. Do not silently change user-selected engineering state.
6. Prefer deterministic behavior unless a stochastic method is explicitly required and reproducibly seeded.


## Engineering changes


A change to a physical or empirical model should identify:


- requirement and physical meaning;
- input and output contract;
- units and conventions;
- algorithm/model and version;
- assumptions and applicability;
- edge cases;
- warning/error behavior;
- validation reference;
- numerical tolerance where relevant;
- regression-test impact.


If a change alters accepted simulation outputs beyond defined tolerances, the change should explain why and update the model/version metadata where appropriate.


## Testing


Contributions should add the narrowest useful tests:


- unit tests for mathematical and schema behavior;
- integration tests across subsystem boundaries;
- reference-project tests for complete engineering chains;
- regression tests for previously accepted numerical behavior.


Agreement with another simulator is evidence, not proof. Differences should be decomposed into model, convention, input, and assumption differences instead of tuned away blindly.


## Pull requests


Keep pull requests focused. Describe:


- what changed;
- why it changed;
- whether engineering semantics changed;
- affected schemas/models;
- tests added or updated;
- known limitations.


For major architecture or model changes, open an issue or design discussion before implementation.


## Data and licensing


Do not commit proprietary component databases, commercial weather data, private project files, credentials, or user uploads.


Public component data must have a redistribution-compatible source and retain provenance. User-supplied PAN/OND or other proprietary files belong only in private/local scopes unless redistribution rights are clear.


## License


RawiBumi is licensed under the GNU Affero General Public License v3.0. Contributions need the
[Contributor License Agreement](CLA.md): you keep the copyright in your contribution and give the project a licence
to use it, including under other licence terms (for example in a hosted service or a paid edition). Accept it by
adding this line to your pull request description:

> I have read the RawiBumi Contributor License Agreement (CLA.md, version 1.0) and I agree to it.

Pull requests without it cannot be merged.