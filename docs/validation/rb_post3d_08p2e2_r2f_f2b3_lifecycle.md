# F2-B3 disabled-by-default holder lifecycle seam

Task: RB-POST3D-08P2E2-R2F-F2-B3. Predecessor:
`552292e6b1a27998c98a410f858b6f1df0186000`.

The qualification label for this slice is **F2-B3 CODE SEAM ACCEPTED / HOLDER
CONCURRENCY UNQUALIFIED**. This describes the limited code seam; final acceptance
still requires Claude review PASS and the orchestrator's focused verification.
The implementer has not executed pytest, simulations, benchmarks, builds, M0 or
M1. No passing test count or production result is asserted here.

## Scope and default behavior

Only `module_series_adapter.py` and `dc_attribution.py` are edited production
files. The new `branch_memo_lifecycle.py` imports only standard-library `json`
and `math`; its module body performs no I/O, clock sampling, environment access,
process discovery or mutable state initialization. The other two new files are
the focused unit suite and this document. No production dependencies are added.

Both model factories accept the optional keyword-only `lifecycle_sink=None`.
The normal public factory forwards an explicitly supplied sink to
`_build_series_model_from_checked_states`; that internal builder also accepts it
directly. All previous positional arguments and keywords remain valid. Default
calls never import or call the lifecycle module, compute hook metadata or slot
counts, or allocate a recorder. The model is assigned to a local before return
to allow a guarded hook after successful construction. The existing scientific
operations retain their order, including copies, state construction, hashing,
holder allocation and model construction. Instrumentation is absent from model
fields, scientific hashes, numerical identities and V(I) closure cells.

The two `_BranchEndpointHolder(...)` calls remain in their original factory
functions. Neither the holder class nor its `__slots__` changes. The branch
current memo limit remains **256**. No numerical solver, topology, units, cache
policy, execution dispatch, worker or persistence behavior is changed.

## Explicit synthetic use

```python
from shading.electrical.branch_memo_lifecycle import BranchMemoLifecycleSink

sink = BranchMemoLifecycleSink(
    identity_namespace="synthetic_case_1",
    max_events=8,
    identity_metadata={"declared_fake_identity": [17, "test-start"]},
)
# Supply this only to a direct synthetic unit-fixture factory call:
# model = build_phase66_series_module_operating_model(..., lifecycle_sink=sink)
# model = build_bypass_off_module_model(..., lifecycle_sink=sink)
report = sink.report()
```

There is no environment activation, global enable flag, transport, process
collector, finalizer or background work. Production dispatch, attribution-basis
evaluation and workers do not forward a sink. This is **not end-to-end
instrumentation or worker coverage**.

The exact `BranchMemoLifecycleSink` type is required; duck-typed sinks and
subclasses fail before scientific work. Each test owns its isolated deterministic
counter and required namespace. Successful CREATEs allocate
`namespace:holder:N` and `namespace:owner:N`, starting at 1. No `id(obj)`, PID,
process start time or real clock is consulted by the seam. The unchanged holder
internals retain their existing private use of Python object identity for branch
lookup; those values are never instrumentation IDs. Separate recorders must use
distinct test-declared namespaces if their evidence will be combined; this slice
does not merge reports or establish cross-recorder uniqueness.

For direct hook contract tests, `holder_created` also accepts an explicit pair
of string `holder_id` and `owner_id` values. A pair is mandatory when either ID
is supplied. Reused IDs, IDs shared between roles, mismatched owner confirmations
and duplicate confirmations fail. These hook declarations do not authenticate
an allocation or model: supported factory call sites establish placement, and
all supplied evidence remains **TEST_SUPPLIED_UNAUTHENTICATED**. Arbitrary
in-process mutation or monkeypatching of private recorder state is outside this
contract; there is no signed evidence or security boundary.

Events contain only contiguous sequence numbers, CREATE or OWNER_RETURN, string
holder/owner IDs, factory role, nonnegative integer slot count and an optional
declared clock tick. Factory roles are `normal` and `bypass_off`; they describe
the allocation path, not an execution phase or worker role. The normal path is
also used for attribution U/B bases and B2 acceptance, so `normal` does not prove
a producer invocation. An owner ID identifies the intended model owner before
that model exists; `owner_return_observed` separately records confirmation.

The recorder never accepts holder, model, V(I) function or regional-state objects
as evidence. It retains only bounded primitive evidence and an optional
test-supplied clock dependency. That dependency must not capture observed
objects. Factory closures capture no sink, tokens or hook metadata. Reports are
independent JSON copies, including nested identity metadata, event records and
holder declarations. Mutating inputs or returned reports cannot rewrite the log.

## Ordering, bounds and failures

CREATE occurs immediately after successful holder allocation. A constructor
exception emits nothing and consumes no successful identity. OWNER_RETURN occurs
only after successful model construction, immediately before return. It confirms
the return boundary; no consumer receipt or subsequent model ownership is
authenticated. A post-allocation solver/model-constructor exception leaves CREATE
without OWNER_RETURN. Neither path invents a disposal event, and no cleanup
handler closes the holder.

The recorder is single-caller, with no locks or concurrent/worker protocol. Event
sequence describes hook order within that recorder, not chronological concurrent
peak. Optional `clock` must be callable with a nonblank `clock_id`; without both,
configuration fails. Without a clock, ticks are null and clock provenance is
NOT_SUPPLIED. With one, ticks must be nonnegative nondecreasing exact integers
(at most 64 bits), and provenance is TEST_SUPPLIED_UNAUTHENTICATED. Equal ticks
are allowed. Clock units and authenticity are never inferred. There is **no
wall-clock sampling**.

The default event cap is 64; tests may explicitly select 1 through 4096. No
trimming or ring-buffer overwrite occurs. A cap failure can leave CREATE with
no confirmed return. Slot counts are exact integers, excluding booleans, from
0 through `2**64 - 1`. Identity tokens are nonblank UTF-8 strings of at most
128 characters; namespaces are limited to 64 characters. Optional identity
metadata must be an exact JSON object, limited to 4096 serialized UTF-8 bytes,
256 visited values/keys, depth 8, finite floats and 64-bit magnitude integers.
No custom serialization, coercion or copy hooks are called.

Invalid runtime contracts and clock failures raise `LifecycleContractError`,
which derives directly from Exception rather than ValueError, so numerical
availability handlers cannot silently absorb it. Failure latches the recorder
as FAILED, preserves prior evidence and prevents subsequent successful events.
Reentrant event recording from the injected clock also fails, even if the clock
catches that failure. An externally replaced raising hook propagates its error;
there is no successful owner-return event unless the hook finishes recording it.
Enabled instrumentation can prevent a factory return, including after allocation
or model construction. It is **not performance neutral or production qualified**.

## Unresolved disposal and qualification

No explicit logical-owner termination is established by these source snapshots.
Factory return, interval end, phase boundary, executor shutdown request, garbage
collection and Python finalization do not prove holder RELEASE. Object
finalization is not owner disposal. `holder_released` and `owner_terminated`
always reject; even an externally supplied termination witness is not accepted
without a separately validated owner protocol. These rejection methods store no
witness or observed-object reference and create no event.

Every report, including an empty or failed recorder, retains:

| Field | Value |
| --- | --- |
| coverage_status | UNRESOLVED |
| model_owner_provenance | INCOMPLETE |
| holder_release | NOT_OBSERVED |
| owner_termination | NOT_OBSERVED |
| production_memory_qualification | INCONCLUSIVE |
| production_chronological_peak | NOT_OBSERVED |

Every recorded holder remains UNRESOLVED. No HOLDER_RELEASE_OBSERVED,
OWNER_TERMINATION_OBSERVED, complete holder coverage, concurrent peak,
performance proof or allocator proof is produced. This report is not F2-A
observer evidence or an F2-B2 provider schema, and cannot establish F2-A/F2-B2
holder_coverage complete. Missing allocations outside these direct calls remain
unknown.

The accepted **F2-B2 diagnostic precedence MINOR** remains unchanged: an earlier
INCONCLUSIVE adapter diagnostic may precede a later non-identity INVALID defect.
F2-B2 still fails closed and retains raw input in that case. F2-B3 neither edits
that adapter nor claims to repair its diagnostic precedence.

Source edits and the new electrical module change the file set/hashes collected
by E1 `SOURCE_FILES`; existing E1 references cannot authorize future E2 replay
against this changed tree. Stage-specific historical dirty-tree guards may reject
these new paths. No evidence/reference is regenerated, no provenance check is
bypassed, and M0/M1 and production experiments remain on hold.

## Regression evidence and handoff

The new fake-only suite reuses the existing Phase-6.6 synthetic REGION fixtures.
It pins the planner's predecessor scientific-input hashes and canonical V(I)
digests, checks omitted/None/enabled parity, identity fields, signatures and the
legacy internal positional call. It also covers both allocation sites, all-dark
models, a one-dark-substring bypass-off rejection, constructor and later failures,
hook/clock failure, invalid configuration/events, duplicate identities, capacity,
clock reentrancy, mutation independence, no retained observed objects, closure
usability and unchanged reports following model collection. Isolated source
execution with I/O/process/clock functions blocked checks import safety. No
skip/xfail markers are added.

The V(I) golden digest is SHA-256 of compact, key-sorted JSON, `allow_nan=False`,
of the full three V(I) results at `0`, `ceiling/2`, `ceiling`. Both default-fixture
ceilings are 24 A and both holders have six slots. Golden values are tied to the
predecessor's pinned numerical environment; parity must be verified in the same
`.venv` by the orchestrator. No git subprocess or historical source execution is
used by these tests.

After Claude review PASS, the orchestrator alone runs:

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_post3d_08p2e2_r2f_f2b3_lifecycle.py
```

Acceptance requires a positive pass count and zero skips, unchanged immutable
source guards and pinned preexisting untracked files, and exactly the five
authorized paths. The implementer's static syntax, whitespace and scope/hash
checks do not substitute for this pending execution or reviewer acceptance.
