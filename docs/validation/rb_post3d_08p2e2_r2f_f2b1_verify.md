# RB-POST3D-08P2E2-R2F-F2-B1 — independent fake-evidence verification

This is fake-only code, tests and documentation. M0/M1 execution and production
experiments remain on hold. No production observation, memory sampler, simulator,
policy C or environment installation is part of this change. F2-A is unchanged.

## Public interface and schemas

The import-safe, standard-library-only module is
`scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b1_verify`. It imports only the committed
pure F2-A observer; it has no execution entry point and performs no I/O.

* `verify_report(report)` returns a sealed verification summary with schema
  `rawibumi.passive-memory-verifier.f2b1.v1.verification`. Its outcome is
  `VERIFIED_FAKE_OBSERVATION` for one eligible reconstructed artificial report,
  otherwise `NOT_COMPARABLE`. Its metric delta is always null. Verifying one
  report does not establish a comparison or independence.
* `compare_verified_reports(baseline, candidate)` independently verifies both
  inputs and returns a sealed comparison with schema
  `rawibumi.passive-memory-verifier.f2b1.v1`. Only two eligible, compatible inputs
  can return `COMPARABLE_FAKE_OBSERVATIONS`. Every failure returns
  `NOT_COMPARABLE` and a null metric delta.

Inputs must have the pinned schema
`rawibumi.passive-memory-observer.f2a.v1`. No public F2-A schema or function is
modified, and F2-A's literal-identity `compare_reports` does not decide F2-B1
comparability.

Every public output, including errors, pins:

```text
production_memory_qualification = INCONCLUSIVE
production_chronological_peak = NOT_OBSERVED
input_kind = FAKE_INPUT_ONLY
```

There is no budget acceptance, 717-slot projection, measured runtime speedup,
numerical parity or live-memory claim.

## Independent deterministic reconstruction

Each input passes these checks in order:

1. Strict JSON-safe object copying, canonical serialization and source digest.
   Non-string keys, non-JSON types (including tuples and subclasses), nonfinite
   floats, cycles, excessive nesting, unencodable strings and unrepresentable
   integer serialization are refused without echoing the submitted payload.
   Every string value and object key must be strictly UTF-8 encodable; surrogate
   code points are rejected before the source digest, even in resealed reports.
2. F2-A integrity verification, pinned schema and required configuration/raw
   evidence object containers.
3. A fresh `F2-A.reconcile(configuration, raw_supplied_observations)` call.
   The **entire** reconstructed sealed report must match the submitted report
   by canonical JSON bytes, including every derived section, metadata, caveat,
   digest, reason and key. This also distinguishes `true` from `1` and integers
   from floats; Python object equality would not do so.
4. The fixed fake-only envelope, `OBSERVATION_COMPLETE`, zero reasons,
   `coverage_complete is True`, independently declared nonblank input/run/workload
   IDs, valid conditions/records containers, a non-null nonnegative integer
   `sampled_aggregate.max_rss_bytes`, and an unambiguous topology shape.

An intact INVALID or INCONCLUSIVE F2-A report can reconstruct successfully but
is ineligible for comparison. A self-resealed report with changed derived fields
fails reconstruction even if its integrity digest is correct. Missing or extra
derived keys fail too. Boundary exception handling converts malformed structures,
recursion and failed reconciliation into fixed reason codes and sealed errors;
exception messages and unsafe submitted data are not copied to outputs.

Reconstruction catches **falsified derived fields**, not malicious alteration of
raw evidence followed by complete regeneration of a consistent report. SHA-256
seals establish deterministic integrity, not authorship, authenticity or truth.
Unauthenticated reports are not admissible production measurements.

## Conditions and topology equivalence

Canonical byte equality is required for workload IDs, the full declared raw
conditions, and every configuration setting outside `topology`. Required phases
are compared as an ordered list, conservatively: reordering them does not bypass
configuration equality. Unknown extra settings are retained in the comparison.
Only `conditions`, `workload_id` and configuration define declared comparability
settings. Extra top-level raw evidence keys are run-specific evidence covered by
the source input digest; they are not additional declared conditions.

Within topology, only the concrete parent/worker `[pid, starttime_ticks]`
identities and workers' equivalent `parent` identity references are dropped.
The shape retains:

* all other topology settings, including `start_method` and
  `max_concurrent_workers`;
* parent count and total worker count;
* the multiset of parents, each represented by its worker count and sorted
  multiset of complete non-identity worker descriptors.

Parent declaration order and worker declaration order have no meaning in F2-A
and are ignored. For example, two parents with worker counts `[2, 0]` match
`[0, 2]`, but do not match `[1, 1]`. Descriptor grouping stays associated with
the relevant parent; descriptors are not pooled across parents. All extra worker
fields are retained, even if their values resemble identities. Only the defined
`identity` and `parent` fields are removed.

Missing rosters/settings, malformed identities, duplicates, unknown parent
references or unsupported spawn declarations fail closed with
`TOPOLOGY_NOT_NORMALIZABLE`. Different valid shapes yield `TOPOLOGY_MISMATCH`.
The input reports, configuration and raw evidence are never modified.

## Independence, provenance and metric semantics

Both artificial reports must independently declare `input_id` and
`independent_run_id`, and both declarations must differ across sides. Verified
source input digests must differ. Canonically identical raw `records` lists are
also rejected, even when the IDs and source input digests differ.

These checks are assertions about fake data, **not proof of real experimental
independence**. The identical-record check is literal canonical equality. Copies
that relabel PIDs or alter other raw values can evade it. F2-B1 does not infer
independence from real process lifetimes or authenticate any declaration.

The `baseline` and `candidate` summaries retain:

* SHA-256 of the entire canonical submitted sealed report when JSON-safe, even
  if subsequent integrity/reconstruction checks fail;
* the reconstructed source input digest and configuration digest;
* reconstructed input/run/workload IDs, outcome, full sorted structured F2-A
  reasons and sorted unique reason codes;
* reconstruction/eligibility flags, sorted verification reason codes and the
  reconstructed sampled maximum when it is a valid nonnegative integer.

Outcome/reason metadata and source input/configuration digests remain null until
full reconstruction matches. Consequently rejected forged outcomes are never
presented as verified provenance. The submitted-report digest is an identifier,
not an endorsement.

Comparison `reasons` are structured `{side, code}` objects sorted by side then
code. Sides are `baseline`, `candidate`, or `pair`. Verification failures include
`MALFORMED_REPORT`, `INTEGRITY_MISMATCH`, `SCHEMA_MISMATCH`,
`RECONSTRUCTION_MISMATCH`, `RECONSTRUCTION_FAILED`, `MISSING_INPUT_DECLARATION`,
`INVALID_ENVELOPE`, `INPUT_NOT_OBSERVATION_COMPLETE`,
`MISSING_OR_INVALID_SAMPLED_METRIC`, `MALFORMED_EVIDENCE` and
`TOPOLOGY_NOT_NORMALIZABLE`. Pair reasons include `WORKLOAD_MISMATCH`,
`CONDITIONS_MISMATCH`, `CONFIGURATION_MISMATCH`, `TOPOLOGY_MISMATCH`,
`INPUTS_NOT_INDEPENDENT` and a defensive `COMPARISON_FAILED`. Pair comparisons
are attempted only when both reconstructed inputs are eligible.
`INVALID_ENVELOPE` is a defense-in-depth check: the pinned F2-A reconciler already
supplies the envelope, and submitted envelope changes fail reconstruction first.

The sole metric delta is
`candidate_minus_baseline_sampled_max_rss_bytes`: candidate sampled maximum
minus baseline sampled maximum. It is an integer and preserves negative signs
and zero. It is null on every noncomparable result. This uses F2-A's sampled sum
of process VmRSS under declared bounded sequential reads; shared pages may be
counted repeatedly, and the sampled maximum is not a chronological system peak.
Independent per-process VmHWM values are never summed into a simultaneous peak.

## Regression coverage and execution status

The new unit tests use internally consistent artificial rosters, supplied proc
text, cgroup counter text, explicit holder coverage and complete final readings.
Positive controls establish COMPLETE inputs and a comparable unmodified pair
before negative mutations. Coverage includes different process identities,
parent/worker counts and per-parent distributions, maximum concurrency, extra
settings/descriptors, condition/workload/threshold/phase differences, truncation,
OOM/OOM-kill, status/smaps swap, absent workers and holder coverage, malformed
configuration/evidence, all derived-section forgeries, missing/extra keys, type
aliasing, reused declarations, identical records, negative/zero deltas,
determinism, no mutation, import safety and calls with live I/O disabled.
Unicode cases cover surrogate values and keys in both unsealed and resealed
reports, plus a positive comparison with valid UTF-8 Unicode keys and values.

There are no skips, expected failures, production imports or new dependencies.
The implementer has not executed pytest, builds, benchmarks or test functions.
The orchestrator owns the targeted verification command:

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_post3d_08p2e2_r2f_f2b1_verify.py
```

Acceptance remains pending that execution and the read-only review; no PASS
result is claimed here.

## Remaining limitations

D1 verified canonical/dispatch/producer/attribution/downstream/persistence/
verification call sites and two spawn-capable paths. It did not establish
complete live holder release observations. Actual phase coverage, actual holder
CREATE/RELEASE coverage and live sample timestamps remain unresolved, only for
future F2-B work. This task does not authorize their observation. There is no real
chronological memory peak or memory budget acceptance.
