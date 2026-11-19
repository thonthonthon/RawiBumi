# Contributing

## Tests
```sh
.venv/bin/python -m pytest -q -n 8 tests/unit
cd apps/web && npm run verify        # generated types, boundaries, typecheck, unit tests, build, design gate
cd apps/web && npx playwright test   # browser tests against the in-browser demo
```
Some tests need the development history or private evidence and skip with a stated reason in a public checkout.

## Rules
- Keep engineering decisions with the user: suggestions and checks, never silent changes.
- Never tune the engine toward PVsyst; a difference with a sound reason is acceptable.
- Do not commit weather or component data you are not licensed to redistribute.
- A change that alters results must explain why, with a test that shows it.

## Proposing a change
Open an issue describing the problem, the evidence (a project file or steps to reproduce) and the expected result.
