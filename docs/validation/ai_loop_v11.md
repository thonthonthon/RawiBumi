# AI orchestration V1.1

This is one-time, owner-authorized infrastructure maintenance of
`scripts/ai_loop.py`. The implementation preserves Claude planning, Codex as
the sole implementation writer, Claude independent review, deterministic
verification, and `MAX_ROUNDS = 3`. No staging, commits, pushes, history edits,
or branch changes are performed. No production dependency is added. The loop
uses the standard library, including `tomllib` (Python 3.11 or later; the
repository operator interpreter is Python 3.12). Command execution requires a
POSIX host for process-group cleanup; other hosts fail before launching a
command. Safe Codex structured output additionally requires Linux `memfd_create`
and accessible `/proc/<orchestrator-pid>/fd`; unavailable facilities fail closed
before Codex launches, with no ordinary-path fallback.

The scientific R2E task remains paused. Neither the active TASK nor its archive
is changed by this maintenance. This document supplies the embedding format;
it does not activate a task or authorize a workload.

## Contract format and selection

An operator embeds exactly one fenced JSON object in the single authoritative
`.ai/TASK.md`. Its fence language is `ai-loop-contract`. The reserved name must
occur only in that fence's opening line. The parser accepts LF or CRLF task
files and pins the SHA-256 of the original bytes, including whitespace.

Absence of the reserved name selects the existing legacy workflow: clean-tree
startup, the original full-test command, and the original documentation-only
skip. Presence opts in irrevocably for that run. Broken or duplicate fences,
duplicate JSON keys, missing/unknown fields, wrong types, unknown versions,
invalid hashes, conflicting path roles, or invalid classifications stop before
agents execute. They never select generic pytest as a fallback. Uppercase
spellings of the reserved name are treated as malformed opt-in.
Bare contract JSON containing a `contract_version` key without the reserved
fence also fails closed.

The following is an R2E embedding example using the observed pre-maintenance
baseline. It must be independently checked against the owner's eventual Git
checkpoint and restored TASK before use. In particular, `expected_head` must
match the checkpoint actually selected by the owner. Do not run the loop with
the current maintenance TASK: it has no execution contract and tests are
operator-owned for this maintenance.

````markdown
```ai-loop-contract
{
  "contract_version": "1.1",
  "expected_branch": "ai/rb-post3d-08p2-e2-r2a-memo-observe",
  "expected_head": "8ad1cfcd6165d8cdbb3104fc236c76f694dee955",
  "allowed_changed_paths": [
    "scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py",
    "tests/unit/test_rb_post3d_08p2e2_r2e_memory.py",
    "docs/validation/rb_post3d_08p2e2_r2e_memory.md"
  ],
  "preexisting_untracked": {
    "docs/validation/rb_post3d_08p2e2_memo_opportunity.md": "7cd5a8c8b3383811d91faa33fa204105f92e569bd7e14f5e9ab1500dbbf0d44f",
    "scripts/benchmarks/rb_post3d_08p2e2_memo_opportunity.py": "bc05765543d0ff75f6d99ec45b5ae5363dba8b7bb282adcf454d0a5ea1c798b3",
    "tests/unit/test_rb_post3d_08p2e2_memo_opportunity.py": "e4c88ea3a1880320ddf9ef79e016f4d6e86823e4837c2db7f4f348668ca098a6"
  },
  "immutable_source_guards": {
    "shading/electrical/substring_reference.py": "45157f6a93c9e066b54ddffe70875cf06bed4a17816ca8a0cd797d4120b1a3ba"
  },
  "verification": {
    "argv": [
      ".venv/bin/python", "-m", "pytest", "-q",
      "tests/unit/test_rb_post3d_08p2e2_r2e_memory.py"
    ],
    "classification": "TARGETED_VERIFICATION"
  }
}
```
````

All seven top-level fields are required. The version is the string `"1.1"`;
HEAD is a full lowercase 40-character Git SHA-1. Hash maps contain lowercase
64-character SHA-256 values; empty maps are permitted for tasks with no such
files. The change list is a nonempty list of exact repository-relative file
paths, with no duplicates, traversal, absolute paths, or backslashes. Entries
are compared literally, with no glob expansion. `.git`, `.ai`, runtime stores,
and protected orchestration files cannot be mutable entries. The contract is
an execution constraint, not a mechanism for granting another protected-file
exception. This maintenance's owner authorization applies to the direct
implementation session.

Historical files and source guards cannot overlap mutable paths. Historical
and guard entries may coincide only with identical hashes. Historical files
must be the exact set of Git-visible untracked files at startup, and must be
regular files with matching bytes. The loop does not accept preexisting
tracked edits, even within the allowed change list. A resumed dirty
implementation requires operator disposition; it is not silently adopted.

The verification object contains exactly `argv` and `classification`.
Classification is either `TARGETED_VERIFICATION` or `FULL_REGRESSION` and is
explicit owner input, subject to the targeted selection checks below. The loop
does not infer scientific qualification or broader coverage from command
success. Argv is a nonempty array of nonempty strings without NUL bytes. The
task author is responsible for the command's meaning and consistency with the
written task. Contract presence always bypasses the legacy documentation-only
skip and generic test command.

## Integrity gates and review evidence

Startup checks TASK availability, branch, expected HEAD, staged state, the
historical file inventory and hashes, immutable guard hashes, protected files,
and verification overrides. Detached HEAD and main/master remain forbidden.
Nonstandard index flags such as assume-unchanged and skip-worktree are refused
in V1.1. The logical index (object IDs, modes, stages and flags) is pinned;
Git's normal stat-cache refreshes do not cause false alarms.

Checks run before and after planning, implementation, review and verification,
and before generating a final result. TASK bytes, branch, HEAD and index must
remain fixed. All tracked files and Git-visible untracked files are inventoried
using NUL-delimited Git output and fingerprinted by type, permissions and
SHA-256. At boundaries, additions, deletions and modifications outside the
exact change list stop the loop. Historical bytes and metadata remain fixed.
Source guards are rehashed at every gate. Symlinked parents and nonregular
mutable/historical/guard files are refused.

Ignored files outside runtime stores are also inventoried using inode, size,
mode, mtime and ctime, detecting newly generated ignored files and changes to
ignored TASK archives/evidence without scanning journal payloads. The runtime
exceptions are `.git`, dependency directories `.venv`, `venv`, `node_modules`,
Python `__pycache__`/ignored bytecode, `.pytest_cache`, `.ai/reports`, and
`.ai/FINAL_REPORT.md`. Tracked files remain fingerprinted even when their
names match an ignored/runtime convention. Existing ignored files form an
immutable startup baseline; declared historical untracked evidence uses the
stronger SHA-256 check. This is a boundary integrity check, not an OS sandbox:
changes made and restored entirely inside an agent invocation cannot be
observed, nor does it enforce network/process policy inside agents. Existing
agent permissions and instructions continue to apply.

Planning and review remain read-only: even an allowed source edit during those
phases fails. Verification also must not edit repository sources. Runtime
report/cache writes remain permitted. An unreadable inventory or failed Git
command stops the run.

Before review, `git_status_round_N.txt` includes the task file inventory and
hashes. `git_diff_round_N.patch` includes ordinary tracked diffs plus no-index
patches of generated files, including new ignored files, without staging.
Claude is instructed to inspect every generated file directly. A review PASS
with nonzero BLOCKER/MAJOR findings, inconsistent severity totals or an unknown
status is rejected. Deterministic verification starts only after review passes
and the integrity gates succeed again.

## Exact verification and repair rounds

V1.1 invokes `verification.argv` unchanged, as an argv list, with `cwd=ROOT`
and explicit `shell=False`. It does not substitute the running Python
interpreter, append pytest flags, or use a shell command string. The R2E
example therefore invokes exactly:

```text
[".venv/bin/python","-m","pytest","-q","tests/unit/test_rb_post3d_08p2e2_r2e_memory.py"]
```

`TARGETED_VERIFICATION` fails closed unless the command has a recognized
pytest entry point: `pytest`/`py.test` (optionally with an executable path), or
`python`, `python3`, or `python3.N` followed immediately by `-m pytest`.
Wrappers, arbitrary scripts, alternate modules and interpreter flags are not
accepted for this classification. Each collection argument must explicitly
name an exact repository-relative `.py` file, optionally followed by nonempty
`::` node selectors. At least one file is required. The literal file paths in
the task's argv authorize verification selection; they need not be mutable
entries in `allowed_changed_paths`. That list governs edits, including any
new test file the builder must create. No separate contract field is added.

Bare pytest, option-only selections, directories, package collection, glob
paths, response files, absolute/traversing paths and mixed file/directory
selections are refused. Before command execution, every selected file must
exist as a regular file without symlink components. Files may be absent at
startup so the builder can create authorized tests. Syntax is validated while
parsing the contract, before agents execute, and rechecked with file existence
immediately before verification.

Targeted pytest uses a conservative option allowlist. Accepted flags are
`-q`/`-qq` (and further repetitions), `-v`/`-vv` (and further repetitions),
`--quiet`, `--verbose`, `-x`/`--exitfirst`, `-s`, `--disable-warnings`,
`--strict-config`, `--strict-markers`, and `-l`/`--showlocals`.
Accepted value options are `-k`, `-m`, `--maxfail` (positive integer),
`--durations` (nonnegative integer), `--tb` (`auto`, `long`, `short`, `line`,
`native`, `no`), `--capture` (`fd`, `sys`, `no`, `tee-sys`), and `--color`
(`yes`, `no`, `auto`). Values must be separate argv elements or use `=`;
empty values, values beginning with `-` or `@`, control characters and repeated
value options are refused. `--` can delimit file selections. Unknown options
and abbreviations fail closed, including options that replace configuration,
load plugins, change collection, rerun cached failures, only collect, or exit
without running tests (`-c`, `-o`/`--override-ini`, `--rootdir`, `--pyargs`,
`-p`, `--ignore`, `--deselect`, `--lf`, `--ff`, `--collect-only`, `--help`,
and `--version`, among others). The loop never repairs rejected argv or falls
back to a full suite. An intentionally unrestricted pytest command must carry
the owner's explicit `FULL_REGRESSION` classification and authorization;
this repair does not authorize executing one.

Nonempty `PYTEST_*` environment overrides are refused, except the harmless
`PYTEST_CURRENT_TEST` and `PYTEST_VERSION` markers. This includes `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`,
plugin-autoload controls and xdist overrides. Nonempty `PYTHONPATH`,
`PYTHONHOME`, `PYTHONSTARTUP` and `PYTHONUSERBASE` are refused as import-path
overrides. Values are not logged. The loop rejects rather than silently
sanitizes the environment.

Before agents and again immediately before verification, the loop inspects
`pytest.toml`, `.pytest.toml`, `pytest.ini`, `.pytest.ini`, `tox.ini`, `setup.cfg`
and `pyproject.toml` at the repository root, its ancestors, and argv target
ancestors. Both native TOML and `ini_options` tables are inspected, matching the
locally installed pytest 9.1.1 configuration formats (inspected without running
pytest). Collection overrides (`addopts`, `testpaths`, `python_files`,
`python_classes`, `python_functions`, `norecursedirs`, `collect_ignore`,
`collect_ignore_glob`, `required_plugins`, `pythonpath`, `collect_imported_tests`,
`consider_namespace_packages`, `usefixtures`) are rejected, including empty
declarations. Malformed configuration fails closed. Existing test code,
conftest hooks and installed plugins still belong to the reviewed execution
environment; this check cannot prove arbitrary Python code has no side effects.

Each command starts in a new POSIX session with captured text stdout/stderr
and `shell=False`. After normal completion, the loop sends `SIGKILL` to the
command's process group to remove surviving descendants, including when the
leader exited successfully. The captured stdout/stderr and leader's original
exit status are preserved. A group that already disappeared is harmless;
other group-cleanup errors propagate as failures. On timeout or interruption,
the same group kill precedes bounded pipe draining and direct-child reaping.
`communicate()` drains both pipes and waits for the direct child; terminated
descendants are reaped by their parent or the OS.
Pipe draining after the kill has a five-second bound. If pipes remain open,
the loop closes them, waits up to five seconds for the direct child, and
reports the partial captured output. This contains ordinary descendants that
inherit the group; it is not a sandbox for processes deliberately detaching
into another session/group. A timeout remains a fatal error with exit status
1 and captured diagnostics in the console, never a successful structured
response or verification result. Completed commands retain their original
return code, separate text stdout/stderr, prompt input and structured-output
parsing behavior. Interruption or communication errors also trigger group
cleanup before the error propagates; a pipe-draining failure still waits for
the direct child. A group-kill error on an abnormal exit also closes pipes and
attempts the bounded direct-child wait before propagating the failure. Group
cleanup runs in a `finally` covering launch and communication, including the
boundary immediately after communication returns.

The main loop and command scopes install temporary `SIGTERM`/`SIGHUP` handlers
on the main Python thread. An inherited `SIGHUP = SIG_IGN`, as set by `nohup`,
is left ignored throughout both outer and nested scopes: no temporary SIGHUP
handler is installed or restored for that scope. Default and custom SIGHUP
handlers retain the existing temporary shutdown behavior and restoration.
SIGTERM still triggers cleanup even when SIGHUP is ignored.
Shutdown exits with `128 + signal_number` through
the cleanup paths. A signal received during `Popen` is deferred until the
process handle is available, then its group is killed and the direct child
reaped. Subsequent terminal shutdown signals are ignored while that scope
unwinds. Shutdown during final normal group cleanup is deferred until the
group kill completes. Prior handlers are restored on every scope exit. These
restorations are all attempted even if one handler operation fails. Shutdown
remains active while constructing and returning the completed command result,
so a signal after group cleanup cannot silently become command success. These
controls cannot handle `SIGKILL`, power loss, or processes deliberately leaving
the command's session/group; operator supervision is still necessary.

A nonzero verification exit, including pytest's no-tests-collected exit,
cannot produce PASS. Failure evidence goes back to Codex for an implementation
repair, followed by another independent review. A failed verification cannot
run again against the identical repository snapshot. Three is the maximum
number of implementation rounds, including the first; they are not measurement
retries. This maintenance does not authorize R2E, M0/M1, electrical simulations,
measurements, benchmarks, or full regression execution.

For `TARGETED_VERIFICATION`, exit zero is necessary and insufficient: the final
nonempty stdout line must be a recognized pytest aggregate with at least one
ordinary `passed` test and no failed/error counts. Standard colored, quiet and
verbose aggregates are recognized; counts of skipped, deselected, expected or
unexpected passes, subtests alone, and collection alone do not satisfy this
gate. Entirely skipped/deselected/unexecuted runs fail, even if pytest exits
zero. Missing, malformed or inconsistent evidence also fails. The parser uses
the final aggregate, rather than an arbitrary earlier occurrence of `passed`
in test output. As with exit status, the reviewed pytest code/plugins and
terminal reporter remain trusted; this is not authentication of arbitrary
Python output against a deliberately dishonest reporter.

Argv remains exact. No plugin, environment override, report option or pytest
flag is injected. In particular, an authorized `-qq` invocation that suppresses
the aggregate fails as unproven; the orchestrator does not silently reduce its
quiet level or infer passes from progress dots. An owner must explicitly
authorize summary-producing argv for qualification. Unsupported R2E platforms
must still produce **failing tests rather than skipped tests**; `skip`,
`skipif` and `importorskip` must not mask a missing required platform facility.
Legacy task verification and `FULL_REGRESSION` retain their existing behavior.

V1.1 writes `verification_round_N.txt` with classification, JSON argv, exit
code, the gate's `RESULT`, and stdout/stderr. Targeted reports additionally
record `PYTEST_PASSED` (an integer or `UNKNOWN`) and `EXECUTION_EVIDENCE`
(`POSITIVE_PASS_COUNT` or `EMPTY_OR_UNPROVEN`). A zero exit with empty/unproven
execution follows the same bounded repair/review path as other verification
failures and cannot publish final PASS. Console output and `.ai/FINAL_REPORT.md` use
`TARGETED_VERIFICATION` for targeted contracts and never call that result full
regression. The final report separates historical files from task deliverables
and records the pinned TASK digest. Before startup, the loop invalidates any
previous final PASS with an `INCOMPLETE` report. A lifecycle `finally` rewrites
the final report using only this invocation's trusted report text held in
memory, never an agent-written report read back from disk. Refused/interrupted
runs cannot inherit an earlier or forged success. Normal blocked/exhausted
outcomes retain their complete trusted `ESCALATION_REQUIRED` report; hard
integrity failures and exceptions produce `INCOMPLETE`. Even a failure after
generating a PASS invalidates that PASS. Final report writing defers terminal
shutdown until report invalidation finishes. The outer failure boundary also
invalidates PASS if handler installation/restoration or final report writing
raises. It retries the trusted non-PASS write once. Diagnostic files in
`.ai/reports` remain intact. This assumes the report directory remains writable;
persistent filesystem errors can prevent report repair and require operator
intervention. Operator inspection remains required.

All orchestrator report writes use one atomic publisher: `save_text`,
`save_json`, Claude raw/structured responses and stderr, Codex schema and
captured stdout/stderr, Git snapshots, verification logs, legacy test logs,
and every final-report write. It accepts only direct `.ai/reports` children
and `.ai/FINAL_REPORT.md`. It opens ROOT, `.ai`, and (when needed) `reports`
using `O_DIRECTORY | O_NOFOLLOW`. Newly created directories use mode 0700;
existing directory permissions are preserved. Directory identity is checked
before publication, immediately before replacement and after replacement.
Symlinked or substituted directories fail closed. Creation, replacement and
cleanup are relative to the held directory descriptors.

Each write exclusively creates a random mode-0600 temporary file in the
destination directory with `O_CREAT | O_EXCL | O_NOFOLLOW`. It writes UTF-8
through the held descriptor, checks the temporary inode's identity and single
link count, then replaces the destination entry with `os.replace`. Existing
absolute, relative or dangling symlinks are replaced without opening their
targets. Existing hardlinks are replaced without rewriting the linked bytes;
removal necessarily changes the old inode's link count/ctime. Temporary-name
collisions fail without opening or deleting the colliding entry. Temporary
files and held descriptors are cleaned on success and failure. Codex stale
output invalidation uses atomic empty replacements, never pathname-based
unlinking through an agent-controlled parent directory.

The Codex CLI itself opens `-o`; securing `save_text` cannot secure that separate
writer. The orchestrator creates a mode-0600 anonymous `memfd`, keeps its
descriptor open, and supplies `/proc/<orchestrator-pid>/fd/<fd>` as `-o`.
There is no temporary pathname that an agent can replace or hardlink. The
orchestrator PID is essential: the installed Node Codex launcher spawns the
native CLI, and extra inherited descriptors need not survive that launch.
`/proc/self/fd` plus `pass_fds` would not provide that guarantee. Procfs binds
the output to the orchestrator's held inode, independent of any worktree
symlink. This is the CLI's output handling, outside the implementation
agent's workspace sandbox; agent sandbox settings remain `workspace-write`.

After `run()` completes its normal process-group cleanup, the orchestrator
reads only the held anonymous inode, verifies that it has no filesystem links,
closes it, and atomically publishes the canonical round JSON in `.ai/reports`.
It parses the in-memory result without reopening the agent-writable report
path. CLI failure, empty/invalid JSON, interruption and missing host facilities
cannot select stale structured output. Anonymous descriptors are closed on
every exit. No change to `run()`'s argv, signal or process-group handling is
needed for this handoff. Missing `memfd`/procfs or a CLI unable to write the
descriptor path stops the run; there is no weaker named-output fallback.

The publisher does not repair unsafe directories or touch symlink targets.
Persistent filesystem errors can prevent safe report repair and require
operator intervention. Trusted PASS/INCOMPLETE and escalation rules remain
unchanged, including invalidation after failed final publication. Atomic
replacement gives complete-report visibility, without a power-loss durability
guarantee. These controls prevent linked-path redirection of orchestrator/CLI
report sinks; they do not add an OS sandbox against arbitrary same-user
process-memory access or processes deliberately escaping the command group.

## Operator qualification (not executed by the builder)

Inspect the three authorized files before running this bounded synthetic suite:

```bash
.venv/bin/python -m pytest -q tests/unit/test_ai_loop_v11.py
```

The tests mock every process and agent call and use tiny temporary worktrees.
They exercise contract parsing, malformed opt-in/no fallback, exact argv,
historical files, startup refusal, boundary tampering, source/hash/index
checks, environment/config overrides, explicit `shell=False`, generated-file
review, read-only phases, severity consistency, targeted reporting, bounded
repairs, unchanged-failure refusal and legacy command selection. Regression
cases also cover unrestricted/mixed/conflicting targeted argv, response-file
and wrapper rejection, file checks at verification, generated tests, distinct
full-regression reporting, group cleanup after leader exit or group disappearance,
bounded pipe draining, captured streams/return codes, and structured-output
success/refusal, plus cleanup on interruption or pipe errors. All subprocess
creation, handler installation and group signals in these tests are mocked;
no real processes are spawned or killed. Additional lifecycle cases cover
forged/stale PASS reports, retained escalation diagnostics, late exceptions,
SIGTERM/SIGHUP in every agent/verification phase and during child launch,
normal-exit descendant cleanup, shutdown during result construction, failed
handler restoration/final writes, and shutdown through nested `main()` and
command scopes with mocked process-group cleanup. End-to-end legacy `main()`
cases cover the original regression argv, documentation-only skip and failed
verification across all three repair rounds with feedback. They do not
import the R2E harness or run any scientific workload.

The preceding security/lifecycle correction added adversarial cases for absolute, relative and
dangling report symlinks, hardlinks, redirected report/root directories,
directory substitution during replacement, temporary-name collisions, atomic
replacement failures before/after publication, and symlink substitution in
each agent/verification phase and at the atomic replacement boundary. These
cases assert symlink targets' bytes/metadata stay intact, hardlinked evidence
bytes remain intact, and trusted PASS, INCOMPLETE or escalation content is
published as appropriate. Mocked signal cases cover inherited SIGHUP ignores in
nested scopes, normal completion, timeouts, SIGTERM during launch/communication/group
cleanup, and combined main/command lifecycles in each phase. Existing tests
for nonignored SIGHUP and SIGTERM cleanup/restoration are retained.
The owner reports that independent review of that baseline found zero BLOCKER
or MAJOR findings and 272 passing tests. That result predates this final
hardening; it is not a qualification result for the current changes.

This final hardening adds bounded cases for external-path report symlinks and
hardlinks across text/JSON publishers and captured process output, redirected
ROOT/`.ai`/`reports` directories, directory swaps at open/replace, exclusive-name
collisions, and temporary/descriptor cleanup on publication failure. Mocked
Codex cases distinguish the CLI's anonymous `-o` writer from later canonical
JSON/stdout/stderr publication, replant links during the implementation call,
redirect the report directory, and cover nonzero exit, missing/invalid output,
exceptions, shutdown and unavailable memfd/procfs with no fallback. Targeted
cases cover positive/mixed aggregates, ANSI color, skipped/deselected/xfail-only
results, zero passes, missing/suppressed/conflicting evidence, unchanged argv,
nonzero exits despite positive counts, and three-round escalation with no final
PASS for empty execution. All agent and verification process launches remain
mocked. Temporary filesystem and anonymous-descriptor operations are real and
bounded. No tests, benchmarks, simulations, M0 or M1 were executed for this
hardening. The added cases and retained baseline await operator qualification.

Optional read-only whitespace/scope inspection:

```bash
git diff --check
git diff -- scripts/ai_loop.py
git status --short
```

Tests were deliberately not executed during implementation. Qualification and
independent inspection are outstanding. After qualification and the owner's
Git checkpoint decision, the operator may restore the archived R2E task and
embed a reviewed contract with the correct baseline. That is a later task;
neither restoration nor R2E verification is part of this change.
