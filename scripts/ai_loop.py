from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import secrets
import signal
import stat
import subprocess
import sys
import tomllib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / ".ai"
REPORTS = AI / "reports"

MAX_ROUNDS = 3
MAIN_BRANCHES = {"main", "master"}

# Files the coding agent should never modify as part of a normal RawiBumi task.
PROTECTED_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    ".gitignore",
    "scripts/ai_loop.py",
}

# The reserved fence is deliberately distinct from ordinary JSON examples.
CONTRACT_FENCE = "ai-loop-contract"
VERIFICATION_CLASSES = {"TARGETED_VERIFICATION", "FULL_REGRESSION"}
COLLECTION_OPTIONS = {
    "addopts", "testpaths", "python_files", "python_classes", "python_functions",
    "norecursedirs", "collect_ignore", "collect_ignore_glob", "required_plugins",
    "pythonpath", "collect_imported_tests", "consider_namespace_packages", "usefixtures",
}
# Existing runtime/dependency stores are outside source-change accounting.
# Ignored files elsewhere are still monitored, without reading evidence payloads.
RUNTIME_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}


@dataclass(frozen=True)
class ExecutionContract:
    expected_branch: str
    expected_head: str
    allowed_changed_paths: tuple[str, ...]
    preexisting_untracked: dict[str, str]
    immutable_source_guards: dict[str, str]
    verification_argv: tuple[str, ...]
    verification_classification: str


def contract_path(value: object) -> str:
    if (
        not isinstance(value, str) or not value or "\\" in value
        or any(ord(c) < 32 for c in value)
        or any(p in {"", ".", ".."} for p in value.split("/"))
        or value.split("/")[0] in {".git", ".ai"}
        or set(value.split("/")) & RUNTIME_DIRS
    ):
        fail(f"Invalid exact repository path in execution contract: {value!r}")
    return value


def parse_execution_contract(task_text: str) -> ExecutionContract | None:
    # Any occurrence of the reserved name opts in. Broken/duplicate fences,
    # malformed JSON, unknown versions and duplicate keys never select legacy.
    if CONTRACT_FENCE not in task_text.lower():
        if re.search(r'"contract_version"\s*:', task_text):
            fail("Execution contract JSON requires the reserved fence; legacy fallback forbidden.")
        return None
    task_text = task_text.replace("\r\n", "\n")
    blocks = re.findall(
        r"^```ai-loop-contract\n(.*?)\n```[ \t]*$", task_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if len(blocks) != 1 or task_text.count(CONTRACT_FENCE) != 1:
        fail("Malformed or duplicate ai-loop-contract fence; legacy fallback forbidden.")

    def unique_keys(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate key: {key}")
            result[key] = value
        return result

    try:
        data = json.loads(blocks[0], object_pairs_hook=unique_keys)
    except (ValueError, TypeError) as exc:
        fail(f"Invalid execution contract JSON: {exc}; legacy fallback forbidden.")

    required = {
        "contract_version", "expected_branch", "expected_head", "allowed_changed_paths",
        "preexisting_untracked", "immutable_source_guards", "verification",
    }
    if not isinstance(data, dict) or set(data) != required:
        fail("Execution contract has missing or unknown fields.")
    if data["contract_version"] != "1.1":
        fail("Unsupported execution contract version; expected string '1.1'.")
    branch, head = data["expected_branch"], data["expected_head"]
    if not isinstance(branch, str) or not branch.strip() or branch in MAIN_BRANCHES:
        fail("Execution contract requires an explicit non-main expected branch.")
    if not isinstance(head, str) or not re.fullmatch(r"[0-9a-f]{40}", head):
        fail("Execution contract requires a full lowercase Git HEAD SHA-1.")
    allowed = data["allowed_changed_paths"]
    if not isinstance(allowed, list) or not allowed:
        fail("allowed_changed_paths must be a nonempty list of exact file paths.")
    allowed = tuple(contract_path(p) for p in allowed)
    if len(allowed) != len(set(allowed)):
        fail("Duplicate allowed_changed_paths entries.")
    if set(allowed) & PROTECTED_FILES:
        fail("Execution contracts cannot waive protected-file invariants.")

    def hashes(name: str) -> dict[str, str]:
        entries = data[name]
        if not isinstance(entries, dict):
            fail(f"{name} must map exact repository paths to SHA-256 hashes.")
        for path, digest in entries.items():
            contract_path(path)
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                fail(f"Invalid SHA-256 for {name}: {path}")
        return entries

    historical = hashes("preexisting_untracked")
    guards = hashes("immutable_source_guards")
    if any(historical[p] != guards[p] for p in historical.keys() & guards.keys()):
        fail("Conflicting historical and immutable guard hashes.")
    if set(allowed) & (historical.keys() | guards.keys()):
        fail("Mutable paths overlap historical files or immutable source guards.")
    verification = data["verification"]
    if not isinstance(verification, dict) or set(verification) != {"argv", "classification"}:
        fail("verification must contain exactly argv and classification.")
    argv = verification["argv"]
    if (
        not isinstance(argv, list) or not argv
        or any(not isinstance(a, str) or not a or "\0" in a for a in argv)
    ):
        fail("verification.argv must be a nonempty list of nonempty argv strings.")
    classification = verification["classification"]
    if not isinstance(classification, str) or classification not in VERIFICATION_CLASSES:
        fail("Invalid verification classification.")
    contract = ExecutionContract(branch, head, allowed, historical, guards, tuple(argv), classification)
    check_verification_classification(contract)
    return contract


def check_verification_classification(contract: ExecutionContract, *, check_files: bool = False) -> None:
    if contract.verification_classification == "FULL_REGRESSION":
        return
    if contract.verification_classification != "TARGETED_VERIFICATION":
        fail("Invalid verification classification.", 7)
    argv = contract.verification_argv
    # Only these entry points have collection semantics we can validate. In
    # particular, wrappers and Python -c/-m alternatives cannot claim targeted
    # coverage merely because 'pytest' occurs somewhere in their arguments.
    executable = Path(argv[0]).name if argv else ""
    if executable in {"pytest", "py.test"}:
        arguments = argv[1:]
    elif re.fullmatch(r"python(?:3(?:\.\d+)?)?", executable) and argv[1:3] == ("-m", "pytest"):
        arguments = argv[3:]
    else:
        fail("TARGETED_VERIFICATION requires an explicit pytest entry point.", 7)

    # An allowlist avoids pytest's option abbreviations and plugins introducing
    # uninspected collection controls. Never edit the owner's requested argv.
    flags = {"-x", "-s", "--exitfirst", "--quiet", "--verbose", "--disable-warnings",
             "--strict-config", "--strict-markers", "--showlocals", "-l"}
    values = {
        "-k": None, "-m": None,
        "--maxfail": r"[1-9]\d*", "--durations": r"\d+",
        "--tb": r"auto|long|short|line|native|no",
        "--capture": r"fd|sys|no|tee-sys", "--color": r"yes|no|auto",
    }
    targets = []
    seen_values = set()
    index = 0
    positional_only = False
    while index < len(arguments):
        arg = arguments[index]
        index += 1
        if not positional_only and arg == "--":
            positional_only = True
            continue
        if not positional_only and arg.startswith("-"):
            if arg in flags or re.fullmatch(r"-(?:q+|v+)", arg):
                continue
            option, separator, value = arg.partition("=")
            if option not in values:
                fail(f"Unsupported targeted pytest option: {arg}", 7)
            if option in seen_values:
                fail(f"Repeated targeted pytest option: {option}", 7)
            seen_values.add(option)
            if not separator:
                if index == len(arguments):
                    fail(f"Missing targeted pytest option value: {arg}", 7)
                value = arguments[index]
                index += 1
            pattern = values[option]
            if not value.strip() or value.startswith(("-", "@")) or any(ord(c) < 32 for c in value) or (
                pattern is not None and re.fullmatch(pattern, value) is None
            ):
                fail(f"Invalid targeted pytest option value: {arg}", 7)
            continue
        path, *nodes = arg.split("::")
        contract_path(path)
        if (
            path.startswith(("@", "-")) or not path.endswith(".py") or any(c in path for c in "*?[]{}")
            or any(not node or any(ord(c) < 32 for c in node) for node in nodes)
        ):
            fail(f"Targeted pytest selection must name an exact test file: {arg}", 7)
        targets.append(path)
    if not targets:
        fail("TARGETED_VERIFICATION requires explicit pytest test file paths.", 7)
    if check_files:
        for name in targets:
            path = ROOT / name
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != ROOT):
                fail(f"Targeted pytest file must not use symlinks: {name}", 7)
            if not path.is_file():
                fail(f"Targeted pytest file does not exist or is not a regular file: {name}", 7)


def file_fingerprint(name: str) -> tuple[int, str] | None:
    path = ROOT / name
    # Never follow a symlinked parent out of the worktree (or into .git).
    for parent in path.relative_to(ROOT).parents:
        if (ROOT / parent).is_symlink():
            fail(f"Symlinked parent in monitored repository path: {name}", 7)
    try:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            payload = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(mode):
            payload = path.read_bytes()
        else:
            fail(f"Expected a regular repository file: {name}", 7)
    except FileNotFoundError:
        return None
    return stat.S_IFMT(mode) | stat.S_IMODE(mode), hashlib.sha256(payload).hexdigest()


def git_paths(*args: str) -> set[str]:
    return set(filter(None, git(*args, "-z").split("\0")))


def untracked_files() -> set[str]:
    return git_paths("ls-files", "--others", "--exclude-standard")


def repository_snapshot() -> dict[str, tuple[int, str] | None]:
    visible = git_paths("ls-files", "--cached") | untracked_files()
    snapshot = {name: file_fingerprint(name) for name in sorted(visible)}

    def walk_error(exc: OSError) -> None:
        fail(f"Cannot inventory repository files: {exc}", 7)

    for directory, dirs, files in os.walk(ROOT, followlinks=False, onerror=walk_error):
        parent = Path(directory).relative_to(ROOT)
        symlinks = [name for name in dirs if (Path(directory) / name).is_symlink()]
        dirs[:] = [name for name in dirs if name not in RUNTIME_DIRS
                   and name not in symlinks and (parent / name).as_posix() != ".ai/reports"]
        for name in [*files, *symlinks]:
            relative = (parent / name).as_posix()
            if relative in visible or relative in {".git", ".ai/FINAL_REPORT.md"}:
                continue
            if name.endswith((".pyc", ".pyo")):
                continue
            # Metadata only for ignored files: no journal/evidence content scan.
            # ctime also detects replacement or same-size rewrites with restored mtime.
            info = (ROOT / relative).lstat()
            snapshot[relative] = (info.st_mode, repr((info.st_dev, info.st_ino,
                info.st_size, info.st_mtime_ns, info.st_ctime_ns)))
    return snapshot


def check_verification_overrides(argv: tuple[str, ...]) -> None:
    # Reject rather than silently sanitize the operator's environment. The
    # explicit argv stays byte-for-byte authorized; no extra pytest flags.
    blocked = sorted(
        key for key, value in os.environ.items() if value and (
            (key.startswith("PYTEST_") and key not in {"PYTEST_CURRENT_TEST", "PYTEST_VERSION"})
            or key in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"}
        )
    )
    if blocked:
        fail("Verification environment overrides are forbidden: " + ", ".join(blocked), 7)
    directories = set(ROOT.parents) | {ROOT}
    # Pytest can discover configuration next to a selected test, even when
    # ROOT has no config. Include target ancestors and ambient parent configs.
    for arg in argv[1:]:
        target = ROOT / arg.split("::", 1)[0]
        if target.is_file() or target.is_dir():
            directories.update(target.parents)
            if target.is_dir():
                directories.add(target)
        elif not arg.startswith("-") and ("/" in arg or target.suffix == ".py"):
            directories.update(target.parents)
    for directory in sorted(directories):
        for filename in ("pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"):
            path = directory / filename
            if not path.is_file():
                continue
            try:
                if filename.endswith(".toml"):
                    config = tomllib.loads(path.read_text(encoding="utf-8"))
                    if filename == "pyproject.toml":
                        options = dict(config.get("tool", {}).get("pytest", {}))
                        ini_options = options.pop("ini_options", {})
                        if not isinstance(ini_options, dict) or (options and ini_options):
                            fail(f"Invalid or mixed pytest TOML configuration: {path}", 7)
                        options.update(ini_options)
                    else:
                        options = config.get("pytest", {})
                else:
                    config = configparser.ConfigParser(interpolation=None)
                    config.read_string(path.read_text(encoding="utf-8"))
                    section = "tool:pytest" if filename == "setup.cfg" else "pytest"
                    options = dict(config[section]) if config.has_section(section) else {}
                conflicts = COLLECTION_OPTIONS & options.keys()
                if conflicts:
                    fail(f"Test-collection overrides in {path}: {', '.join(sorted(conflicts))}", 7)
            except (ValueError, OSError, configparser.Error, AttributeError, TypeError) as exc:
                fail(f"Cannot inspect verification configuration {path}: {exc}", 7)


@dataclass
class RunGuards:
    contract: ExecutionContract | None
    task_digest: str
    branch: str
    head: str
    index: str
    baseline: dict[str, tuple[int, str] | None]

    @classmethod
    def start(cls) -> RunGuards:
        task = AI / "TASK.md"
        if not task.is_file() or task.is_symlink():
            fail(".ai/TASK.md must be a regular file.")
        raw = task.read_bytes()
        contract = parse_execution_contract(raw.decode("utf-8"))
        branch, head = check_setup(contract)
        index = git("ls-files", "--stage", "-v", "-z")
        if contract is not None and any(not entry.startswith("H ") for entry in index.split("\0") if entry):
            fail("Nonstandard Git index flags are forbidden at V1.1 startup.", 7)
        state = cls(contract, hashlib.sha256(raw).hexdigest(), branch, head,
                    index, repository_snapshot() if contract is not None else {})
        state.check()
        if contract is not None:
            check_verification_overrides(contract.verification_argv)
        return state

    def check(self) -> None:
        task = AI / "TASK.md"
        if task.is_symlink() or not task.is_file() or hashlib.sha256(task.read_bytes()).hexdigest() != self.task_digest:
            fail("Authoritative .ai/TASK.md changed during the run.", 7)
        check_git_invariants(self.branch, self.head)
        if git("ls-files", "--stage", "-v", "-z") != self.index:
            fail("Git index entries or flags changed during the run.", 7)
        check_protected_files()
        if self.contract is None:
            return
        contract = self.contract
        current = repository_snapshot()
        changed = {p for p in self.baseline.keys() | current.keys()
                   if self.baseline.get(p) != current.get(p)}
        git_changes = set(changed_files()) - contract.preexisting_untracked.keys()
        forbidden = (changed | git_changes) - set(contract.allowed_changed_paths)
        if forbidden:
            fail("Changes outside execution contract: " + ", ".join(sorted(forbidden)), 7)
        for name, digest in {**contract.preexisting_untracked, **contract.immutable_source_guards}.items():
            fingerprint = file_fingerprint(name)
            if fingerprint is None or not stat.S_ISREG(fingerprint[0]) or fingerprint[1] != digest:
                fail(f"Historical file or source guard hash mismatch: {name}", 7)
            if name in contract.preexisting_untracked and fingerprint != self.baseline.get(name):
                fail(f"Historical file metadata changed: {name}", 7)
        for name in contract.allowed_changed_paths:
            fingerprint = file_fingerprint(name)
            if fingerprint is not None and not stat.S_ISREG(fingerprint[0]):
                fail(f"Authorized change path must be a regular file: {name}", 7)

    def assert_read_only(self, before: dict) -> None:
        self.check()
        if self.contract is not None and repository_snapshot() != before:
            fail("Read-only agent or verifier modified repository files.", 7)

    def changed_files(self) -> list[str]:
        historical = set(self.contract.preexisting_untracked) if self.contract else set()
        files = set(changed_files())
        if self.contract is not None:
            current = repository_snapshot()
            files.update(p for p in current.keys() | self.baseline.keys()
                         if current.get(p) != self.baseline.get(p))
        return sorted(files - historical)


def validate_review(review: dict) -> None:
    fields = {"BLOCKER": "blockers", "MAJOR": "majors", "MINOR": "minors", "OPTIONAL": "optional"}
    if review.get("status") not in {"pass", "blocked", "changes_required"}:
        fail("Invalid review status.", 7)
    findings = review.get("findings")
    if not isinstance(findings, list) or any(
        not isinstance(f, dict) or f.get("severity") not in fields for f in findings
    ):
        fail("Invalid review findings.", 7)
    for severity, field in fields.items():
        count = review.get(field)
        if type(count) is not int or count < 0 or count != sum(f["severity"] == severity for f in findings):
            fail("Inconsistent review finding counts.", 7)
    if review["status"] == "pass" and (review["blockers"] or review["majors"]):
        fail("Review claims PASS with unresolved BLOCKER/MAJOR findings.", 7)


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["ready", "blocked"],
        },
        "summary": {"type": "string"},
        "affected_areas": {
            "type": "array",
            "items": {"type": "string"},
        },
        "risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "tests_expected": {
            "type": "array",
            "items": {"type": "string"},
        },
        "questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "summary",
        "affected_areas",
        "risks",
        "tests_expected",
        "questions",
    ],
    "additionalProperties": False,
}


BUILDER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": ["implemented", "blocked"],
        },
        "summary": {"type": "string"},
        "files_changed": {
            "type": "array",
            "items": {"type": "string"},
        },
        "unresolved_issues": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "status",
        "summary",
        "files_changed",
        "unresolved_issues",
    ],
    "additionalProperties": False,
}


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "pass",
                "changes_required",
                "blocked",
            ],
        },
        "blockers": {"type": "integer", "minimum": 0},
        "majors": {"type": "integer", "minimum": 0},
        "minors": {"type": "integer", "minimum": 0},
        "optional": {"type": "integer", "minimum": 0},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": [
                            "BLOCKER",
                            "MAJOR",
                            "MINOR",
                            "OPTIONAL",
                        ],
                    },
                    "summary": {"type": "string"},
                    "evidence": {"type": "string"},
                    "required_action": {"type": "string"},
                },
                "required": [
                    "id",
                    "severity",
                    "summary",
                    "evidence",
                    "required_action",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "status",
        "blockers",
        "majors",
        "minors",
        "optional",
        "summary",
        "findings",
    ],
    "additionalProperties": False,
}


@dataclass
class TerminationState:
    defer_exit: bool = False
    received: int | None = None


@contextmanager
def termination_signals():
    """Turn terminal shutdown into unwinding, restoring caller handlers later."""
    state = TerminationState()

    def terminate(signum, frame):
        state.received = signum
        # Further terminal signals must not interrupt child/report cleanup.
        for number in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(number, signal.SIG_IGN)
        # Finish short critical sections (acquiring a Popen handle, final
        # group cleanup or report invalidation) before unwinding.
        if not state.defer_exit:
            raise SystemExit(128 + signum)

    # Register each restoration before installing its handler. ExitStack also
    # attempts the other restoration if one of the signal operations fails.
    with ExitStack() as restore:
        for number in (signal.SIGTERM, signal.SIGHUP):
            previous = signal.getsignal(number)
            # nohup's inherited SIGHUP ignore must survive both main() and
            # nested command scopes. SIGTERM still always triggers cleanup.
            if number == signal.SIGHUP and previous == signal.SIG_IGN:
                continue
            restore.callback(signal.signal, number, previous)
            signal.signal(number, terminate)
        yield state


def kill_process_group(process: subprocess.Popen[str]) -> None:
    # The group ID equals the child's PID because it started a new session.
    # Signal the group even if the leader has exited: descendants can keep
    # both the group and captured pipes alive. Do not query a vanished PID.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # The entire group has already exited.


def stop_process_group(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        kill_process_group(process)
        return process.communicate(timeout=5)
    except BaseException as exc:
        # A process that deliberately left the group may retain a pipe.
        # Bound pipe draining and reap even when draining/closing a pipe fails.
        try:
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    stream.close()
        finally:
            process.wait(timeout=5)
        if not isinstance(exc, subprocess.TimeoutExpired):
            raise
        stdout, stderr = exc.output or "", exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode(errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        return stdout, stderr


def run(
    cmd: list[str],
    *,
    prompt: str | None = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    if os.name != "posix":
        fail("Process-group cleanup requires a POSIX host.")
    with termination_signals() as termination:
        process = None
        communicated = False
        timed_out = False
        try:
            termination.defer_exit = True
            process = subprocess.Popen(
                cmd,
                cwd=ROOT,
                stdin=subprocess.PIPE if prompt is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                start_new_session=True,
            )
            termination.defer_exit = False
            if termination.received is not None:
                raise SystemExit(128 + termination.received)
            stdout, stderr = process.communicate(input=prompt, timeout=timeout)
            communicated = True
        except subprocess.TimeoutExpired:
            if process is None:
                raise
            timed_out = True
        finally:
            # Cover the boundary after communicate() as well as errors during
            # launch/communication. Normal completion already reaped the leader;
            # abnormal completion also needs bounded draining and reaping.
            termination.defer_exit = True
            try:
                if process is not None:
                    if communicated:
                        kill_process_group(process)
                    else:
                        stdout, stderr = stop_process_group(process)
            finally:
                # Keep shutdown responsive while constructing/returning the
                # result too: a deferred signal must never become success.
                termination.defer_exit = False
                if termination.received is not None:
                    raise SystemExit(128 + termination.received)
        if timed_out:
            fail(f"Command timed out after {timeout} seconds:\n{' '.join(cmd)}"
                 f"\n\nSTDOUT\n{stdout}\n\nSTDERR\n{stderr}")
        return subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)


def git(*args: str) -> str:
    result = run(["git", *args], timeout=120)

    if result.returncode != 0:
        fail(
            "Git command failed:\n"
            f"git {' '.join(args)}\n\n"
            f"{result.stderr}"
        )

    return result.stdout.rstrip("\n")


def fail(message: str, code: int = 1) -> None:
    print(f"\nERROR: {message}")
    raise SystemExit(code)


@contextmanager
def report_directory(directory: Path):
    """Anchor report operations to real directories, never agent symlinks."""
    if AI != ROOT / ".ai" or REPORTS != AI / "reports" or directory not in {AI, REPORTS}:
        raise ValueError("Report directories must be .ai and .ai/reports inside ROOT.")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as cleanup:
        root_fd = os.open(ROOT, directory_flags)
        cleanup.callback(os.close, root_fd)
        chain = [(None, ROOT, root_fd)]
        directory_fd = root_fd
        for name in ([AI.name] if directory == AI else [AI.name, REPORTS.name]):
            parent_fd = directory_fd
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            directory_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            cleanup.callback(os.close, directory_fd)
            chain.append((parent_fd, name, directory_fd))

        def check_directory() -> None:
            for parent_fd, name, descriptor in chain:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                if not os.path.samestat(current, os.fstat(descriptor)):
                    raise OSError("Report directory changed during publication.")

        check_directory()
        yield directory_fd, check_directory
        check_directory()


def publish_report(path: Path, content: str) -> None:
    """Replace a report entry atomically without ever opening its old inode."""
    if path != AI / "FINAL_REPORT.md" and path.parent != REPORTS:
        raise ValueError(f"Not an orchestrator report path: {path}")
    with report_directory(path.parent) as (directory_fd, check_directory):
        # Exclusive creation refuses an existing file or symlink. All later
        # operations stay anchored to the opened directory, even if renamed.
        temporary = f".{path.stem}.{secrets.token_hex(16)}.tmp"
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600, dir_fd=directory_fd,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as stream:
                stream.write(content)
            check_directory()
            opened = os.fstat(descriptor)
            current = os.stat(temporary, dir_fd=directory_fd, follow_symlinks=False)
            if opened.st_nlink != 1 or not os.path.samestat(opened, current):
                raise OSError("Report temporary file changed during publication.")
            os.replace(temporary, path.name,
                       src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
            check_directory()
        finally:
            try:
                os.close(descriptor)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory_fd)
                except FileNotFoundError:
                    pass


def publish_final_report(content: str) -> None:
    publish_report(AI / "FINAL_REPORT.md", content)


def save_text(path: Path, content: str) -> None:
    if path == AI / "FINAL_REPORT.md":
        publish_final_report(content)
        return
    publish_report(path, content)


def save_json(path: Path, data: dict) -> None:
    save_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


@contextmanager
def codex_output():
    """Give the unsandboxed CLI an anonymous inode, never a worktree pathname.

    Use the orchestrator PID: /proc/self/fd and pass_fds would depend on every
    CLI launcher preserving an extra descriptor through its own child launch.
    No named temporary or report file is exposed to Codex's path-based writer.
    """
    if not hasattr(os, "memfd_create"):
        fail("Safe Codex output requires Linux memfd and procfs; no path fallback.", 7)
    with ExitStack() as cleanup:
        descriptor = os.memfd_create("ai-loop-codex-output", flags=os.MFD_CLOEXEC)
        cleanup.callback(os.close, descriptor)
        os.fchmod(descriptor, 0o600)
        path = Path(f"/proc/{os.getpid()}/fd/{descriptor}")
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 0 or not os.path.samestat(info, path.stat()):
            fail("Safe anonymous Codex output is unavailable; no path fallback.", 7)
        yield path, descriptor


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"Could not parse JSON from {path}: {exc}")


def check_setup(contract: ExecutionContract | None = None) -> tuple[str, str]:
    task = AI / "TASK.md"

    if not task.exists():
        fail(".ai/TASK.md does not exist.")

    task_text = task.read_text(encoding="utf-8").strip()

    if not task_text:
        fail(".ai/TASK.md is empty.")

    if "# No Active Task" in task_text:
        fail(
            ".ai/TASK.md still says 'No Active Task'. "
            "Create a real task first."
        )

    branch = git("branch", "--show-current")

    if not branch:
        fail("Detached HEAD is not allowed for the AI loop.")

    if branch in MAIN_BRANCHES:
        fail(
            f"Refusing to run directly on '{branch}'. "
            "Create a task branch first."
        )

    status = git("status", "--porcelain", "--untracked-files=all")

    if contract is None and status:
        fail(
            "Working tree is not clean before task execution.\n\n"
            f"{status}\n\n"
            "Commit or stash existing source changes first. "
            "Ignored .ai files do not count."
        )

    head = git("rev-parse", "HEAD")

    if contract is not None:
        if (branch, head) != (contract.expected_branch, contract.expected_head):
            fail("Branch or HEAD does not match the execution contract.", 7)
        check_git_invariants(branch, head)
        if git_paths("diff", "--name-only", "--no-ext-diff", "--no-textconv"):
            fail("Tracked changes exist before task execution.", 7)
        actual = untracked_files()
        if actual != set(contract.preexisting_untracked):
            fail(
                "Startup untracked files do not match the historical allowlist. "
                f"Undeclared: {sorted(actual - contract.preexisting_untracked.keys())}; "
                f"missing: {sorted(contract.preexisting_untracked.keys() - actual)}", 7,
            )

    return branch, head


def check_git_invariants(start_branch: str, start_head: str) -> None:
    branch = git("branch", "--show-current")
    head = git("rev-parse", "HEAD")

    if branch != start_branch:
        fail(
            "AI changed the current Git branch.\n"
            f"Expected: {start_branch}\n"
            f"Actual:   {branch}",
            7,
        )

    if head != start_head:
        fail(
            "Git HEAD changed during automation. "
            "An agent may have created a commit or changed history.",
            7,
        )

    staged = run(["git", "diff", "--cached", "--quiet"])

    if staged.returncode == 1:
        fail(
            "The Git index contains staged changes. "
            "Agents must not stage files during the automated loop.",
            7,
        )

    if staged.returncode not in (0, 1):
        fail("Could not inspect the Git index.", 7)


def check_protected_files() -> None:
    changed = git_paths("diff", "--name-only", "--no-ext-diff", "--no-textconv") | untracked_files()

    protected = changed & PROTECTED_FILES

    if protected:
        fail(
            "Agent modified protected orchestration files:\n"
            + "\n".join(sorted(protected))
            + "\n\nStopping for human review.",
            7,
        )


def claude_structured(
    prompt: str,
    schema: dict,
    raw_path: Path,
) -> dict:
    command = [
        "claude",
        "-p",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema, separators=(",", ":")),
        "--permission-mode",
        "plan",
        "--permission-prompts",
        "none",
        "--no-session-persistence",
        "--allowedTools",
        "Read",
        "Grep",
        "Glob",
    ]

    result = run(
        command,
        prompt=prompt,
        timeout=3600,
    )

    save_text(
        raw_path.with_suffix(".stderr.txt"),
        result.stderr,
    )

    if result.returncode != 0:
        save_text(raw_path, result.stdout)
        fail(
            "Claude command failed.\n"
            f"See {raw_path} and "
            f"{raw_path.with_suffix('.stderr.txt')}"
        )

    save_text(raw_path, result.stdout)

    try:
        envelope = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(
            "Claude returned invalid JSON envelope: "
            f"{exc}\nSee {raw_path}"
        )

    structured = envelope.get("structured_output")

    if not isinstance(structured, dict):
        fail(
            "Claude output did not contain a valid "
            "'structured_output' object.\n"
            f"See {raw_path}"
        )

    return structured


def claude_plan() -> dict:
    print("\n[Claude] Planning and specification challenge...")

    prompt = """
You are the independent planner/reviewer for RawiBumi.

Read:
- AGENTS.md
- CLAUDE.md
- .ai/TASK.md

Inspect only the repository files relevant to the task.

Do NOT modify, create, delete, rename, or format any file.

Your job is to determine whether the task is sufficiently defined
for Codex to implement safely.

Evaluate:
- intended behavior;
- likely affected modules;
- engineering/scientific assumptions;
- architecture constraints;
- edge cases;
- expected tests;
- possible contradictions with existing canonical behavior.

Return status "blocked" if a material engineering, scientific,
architectural, schema, unit, topology, provenance, compatibility,
or requirement ambiguity must be resolved before implementation.

Otherwise return status "ready".
"""

    raw = REPORTS / "claude_plan_raw.json"

    plan = claude_structured(
        prompt,
        PLAN_SCHEMA,
        raw,
    )

    save_json(
        REPORTS / "claude_plan.json",
        plan,
    )

    print(f"  Status: {plan['status']}")

    if plan["summary"]:
        print(f"  {plan['summary']}")

    return plan


def codex_build(
    round_number: int,
    previous_review: Path | None,
    previous_full_test: Path | None,
) -> dict:
    print(f"\n[Codex] Implementation round {round_number}...")

    schema_path = REPORTS / "builder_schema.json"
    output_path = REPORTS / f"codex_round_{round_number}.json"

    # Invalidate stale evidence by replacing entries, never by opening their
    # old inodes or unlinking through a potentially redirected parent path.
    for stale in (
        output_path,
        REPORTS / f"codex_round_{round_number}_stdout.txt",
        REPORTS / f"codex_round_{round_number}_stderr.txt",
    ):
        save_text(stale, "")

    save_json(schema_path, BUILDER_SCHEMA)

    additional = []

    if previous_review is not None:
        additional.append(
            f"- {previous_review.relative_to(ROOT)}"
        )

    if previous_full_test is not None:
        additional.append(
            f"- {previous_full_test.relative_to(ROOT)}"
        )

    extra_context = ""

    if additional:
        extra_context = (
            "\nAlso read the following feedback from "
            "the previous round:\n"
            + "\n".join(additional)
            + "\n"
        )

    prompt = f"""
Read:
- AGENTS.md
- .ai/TASK.md
- .ai/reports/claude_plan.json
{extra_context}

You are the IMPLEMENTER for RawiBumi.

Implement the active task.

You are the only AI writer in this workflow.

Rules:
- modify only files necessary for the active task;
- preserve unrelated behavior;
- do not modify AGENTS.md, CLAUDE.md, .gitignore,
  or scripts/ai_loop.py;
- do not commit;
- do not push;
- do not stage files;
- do not switch branches;
- do not rewrite Git history;
- do not weaken tests simply to obtain a pass;
- add legitimate regression tests where appropriate;
- do NOT run pytest, npm tests, builds, benchmarks, or the full test suite;
- the orchestrator is responsible for executing verification commands after implementation.

If the task requires a material decision that AGENTS.md or TASK.md
requires escalation for, do NOT guess. Return status "blocked".

If Claude produced valid BLOCKER or MAJOR findings in a previous
round, address them.

If you believe a reviewer finding is incorrect, explain the
repository evidence in unresolved_issues rather than silently
ignoring it.
"""

    command = [
        "codex",
        "exec",
        "-s",
        "workspace-write",
        "-C",
        str(ROOT),
        "--output-schema",
        str(schema_path),
        "-o",
        "",  # Filled with a private descriptor path below, never output_path.
        "-",
    ]

    with codex_output() as (private_output, descriptor):
        command[command.index("-o") + 1] = str(private_output)
        result = run(command, prompt=prompt, timeout=7200)
        # run() has reaped the leader and cleaned its process group. Read only
        # the held inode, then publish using the orchestrator's safe writer.
        if os.fstat(descriptor).st_nlink != 0:
            fail("Anonymous Codex output unexpectedly acquired a filesystem link.", 7)
        with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as stream:
            stream.seek(0)
            output = stream.read()

    save_text(output_path, output)

    save_text(
        REPORTS / f"codex_round_{round_number}_stdout.txt",
        result.stdout,
    )

    save_text(
        REPORTS / f"codex_round_{round_number}_stderr.txt",
        result.stderr,
    )

    if result.returncode != 0:
        fail(
            f"Codex failed in round {round_number}. "
            f"See .ai/reports/codex_round_{round_number}_stderr.txt"
        )

    if not output:
        fail(
            "Codex did not produce its structured output file: "
            f"{output_path}"
        )

    try:
        data = json.loads(output)
    except (ValueError, TypeError) as exc:
        fail(f"Could not parse Codex JSON from private output: {exc}")

    print(f"  Status: {data['status']}")

    if data["summary"]:
        print(f"  {data['summary']}")

    return data


def snapshot_git(round_number: int, guards: RunGuards | None = None) -> tuple[Path, Path]:
    status_path = REPORTS / f"git_status_round_{round_number}.txt"
    diff_path = REPORTS / f"git_diff_round_{round_number}.patch"

    status = git("status", "--short")
    diff = git("diff", "--no-ext-diff", "--no-textconv", "--")

    if guards is not None and guards.contract is not None:
        files = guards.changed_files()
        manifest = {name: file_fingerprint(name) for name in files}
        status += "\n\nTask file inventory (mode, SHA-256; null = deleted):\n" + json.dumps(manifest, indent=2)
        # Ordinary git diff omits newly generated files. Capture their actual
        # contents for independent review, without staging anything.
        for name in sorted(set(files) - git_paths("ls-files", "--cached")):
            if not (ROOT / name).exists():
                continue
            result = run(["git", "diff", "--no-index", "--no-ext-diff", "--no-textconv", "--", "/dev/null", name])
            if result.returncode not in (0, 1):
                fail(f"Could not capture generated file for review: {name}", 7)
            diff += "\n" + result.stdout

    save_text(status_path, status + "\n")
    save_text(diff_path, diff)

    return status_path, diff_path


def claude_review(
    round_number: int,
    codex_report: Path,
    status_path: Path,
    diff_path: Path,
) -> dict:
    print(f"\n[Claude] Reviewing round {round_number}...")

    prompt = f"""
You are the independent RawiBumi code reviewer.

Read:
- AGENTS.md
- CLAUDE.md
- .ai/TASK.md
- .ai/reports/claude_plan.json
- {codex_report.relative_to(ROOT)}
- {status_path.relative_to(ROOT)}
- {diff_path.relative_to(ROOT)}

Inspect relevant changed source files and tests directly.
Inspect every newly generated file in the task inventory, including files
that ordinary git diff omits. Verification runs only after this review passes.

Do NOT modify, create, delete, rename, or format any file.

Review the ACTUAL implementation, not merely Codex's summary.

Evaluate:

1. Task compliance.
2. Engineering/scientific correctness.
3. Architectural consistency.
4. Backward compatibility.
5. Public contract/schema/unit/provenance stability.
6. Regression risk.
7. Test adequacy.
8. Scope discipline.
9. Whether tests could pass despite an incorrect implementation.

Severity:
- BLOCKER: task cannot safely be accepted.
- MAJOR: material correctness/completeness/reliability issue.
- MINOR: non-blocking issue worth recording.
- OPTIONAL: suggestion only.

Return "blocked" if a material ambiguity requires user/ChatGPT
arbitration.

Return "changes_required" if any BLOCKER or MAJOR remains.

Return "pass" only when:
- blockers = 0;
- majors = 0;
- the task is satisfied;
- no material ambiguity remains.
"""

    raw = REPORTS / f"claude_review_{round_number}_raw.json"

    review = claude_structured(
        prompt,
        REVIEW_SCHEMA,
        raw,
    )

    path = REPORTS / f"claude_review_{round_number}.json"
    save_json(path, review)

    print(
        "  Status: "
        f"{review['status']} | "
        f"B={review['blockers']} "
        f"M={review['majors']} "
        f"m={review['minors']} "
        f"O={review['optional']}"
    )

    if review["summary"]:
        print(f"  {review['summary']}")

    return review


def run_full_tests(round_number: int) -> tuple[bool, Path]:
    files = changed_files()

    docs_only = bool(files) and all(
        name.startswith("docs/") or name.endswith(".md")
        for name in files
    )

    if docs_only:
        print("\n[Tests] Documentation-only change — full regression skipped.")

        path = REPORTS / f"full_tests_round_{round_number}.txt"

        save_text(
            path,
            "SKIPPED: documentation-only change; no executable code changed.\n",
        )

        return True, path

    print("\n[Tests] Running full Python regression suite...")

    # Intentionally simple for Version 1.
    # If RawiBumi later needs a different canonical full-test command,
    # change this one location.
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
    ]

    result = run(
        command,
        timeout=7200,
    )

    path = REPORTS / f"full_tests_round_{round_number}.txt"

    content = (
        f"COMMAND: {' '.join(command)}\n"
        f"EXIT_CODE: {result.returncode}\n\n"
        "STDOUT\n"
        "================================================================\n"
        f"{result.stdout}\n\n"
        "STDERR\n"
        "================================================================\n"
        f"{result.stderr}\n"
    )

    save_text(path, content)

    passed = result.returncode == 0

    print(f"  {'PASS' if passed else 'FAIL'}")

    return passed, path


def targeted_pass_count(stdout: str) -> int | None:
    """Read pytest's terminal aggregate, failing closed on absent/unknown evidence.

    Do not search arbitrary output for 'passed': test prints, collection counts
    and expected/unexpected passes are not a positive pytest pass aggregate.
    The reviewed pytest environment remains trusted, as with exit status itself.
    """
    plain = re.sub(r"\x1b\[[0-9;]*m", "", stdout)
    lines = [line.strip() for line in plain.splitlines() if line.strip()]
    if not lines:
        return None
    summary = lines[-1].strip("= ")
    match = re.fullmatch(r"(.+) in [0-9]+(?:\.[0-9]+)?s(?: \([^\n()]+\))?", summary)
    if match is None:
        return None
    counts = {}
    for part in match[1].split(", "):
        item = re.fullmatch(
            r"([0-9]+) (passed|failed|errors?|skipped|deselected|xfailed|xpassed|warnings?|"
            r"reruns?|subtests passed|subtests failed|subtests skipped)", part,
        )
        if item is None or item[2] in counts:
            return None
        counts[item[2]] = int(item[1])
    if any(counts.get(key, 0) for key in ("failed", "error", "errors", "subtests failed")):
        return None  # Inconsistent with a successful exit.
    return counts.get("passed", 0)


def run_verification(round_number: int, contract: ExecutionContract | None) -> tuple[bool, Path]:
    if contract is None:
        return run_full_tests(round_number)
    check_verification_classification(contract, check_files=True)
    check_verification_overrides(contract.verification_argv)
    classification = contract.verification_classification
    print(f"\n[Tests] {classification}: {json.dumps(contract.verification_argv)}")
    result = run(list(contract.verification_argv), timeout=7200)
    passed = result.returncode == 0
    execution_evidence = ""
    if classification == "TARGETED_VERIFICATION":
        count = targeted_pass_count(result.stdout)
        passed = passed and count is not None and count > 0
        execution_evidence = (
            f"PYTEST_PASSED: {count if count is not None else 'UNKNOWN'}\n"
            f"EXECUTION_EVIDENCE: {'POSITIVE_PASS_COUNT' if count is not None and count > 0 else 'EMPTY_OR_UNPROVEN'}\n"
        )
    path = REPORTS / f"verification_round_{round_number}.txt"
    save_text(path, (
        f"CLASSIFICATION: {classification}\n"
        f"ARGV_JSON: {json.dumps(contract.verification_argv)}\n"
        f"EXIT_CODE: {result.returncode}\n"
        f"{execution_evidence}RESULT: {'PASS' if passed else 'FAIL'}\n\n"
        f"STDOUT\n{result.stdout}\n\nSTDERR\n{result.stderr}\n"
    ))
    print(f"  {classification}: {'PASS' if passed else 'FAIL'}")
    return passed, path


def changed_files() -> list[str]:
    # git diff does not include untracked files, so collect both
    # tracked modifications and new untracked files.
    return sorted(git_paths("diff", "--name-only", "--no-ext-diff", "--no-textconv") | untracked_files())


def generate_final_report(
    *,
    status: str,
    branch: str,
    base_head: str,
    rounds: int,
    reason: str,
    final_review: dict | None = None,
    full_test_path: Path | None = None,
    guards: RunGuards | None = None,
) -> str:
    files = guards.changed_files() if guards is not None else changed_files()
    diff_stat = git("diff", "--stat")

    lines = [
        "# RawiBumi Automated Task Final Report",
        "",
        f"## Status",
        "",
        status,
        "",
        "## Branch",
        "",
        branch,
        "",
        "## Base Commit",
        "",
        base_head,
        "",
        "## Rounds Used",
        "",
        str(rounds),
        "",
        "## Outcome",
        "",
        reason,
        "",
        "## Files Changed",
        "",
    ]

    if files:
        lines.extend(f"- `{name}`" for name in files)
    else:
        lines.append("- None")

    lines.extend(
        [
            "",
            "## Diff Stat",
            "",
            "```text",
            diff_stat or "(no diff)",
            "```",
            "",
        ]
    )

    if final_review is not None:
        lines.extend(
            [
                "## Claude Final Review",
                "",
                f"- Status: `{final_review['status']}`",
                f"- Blockers: {final_review['blockers']}",
                f"- Majors: {final_review['majors']}",
                f"- Minors: {final_review['minors']}",
                f"- Optional: {final_review['optional']}",
                "",
                final_review["summary"],
                "",
            ]
        )

        if final_review["findings"]:
            lines.extend(
                [
                    "### Findings",
                    "",
                ]
            )

            for finding in final_review["findings"]:
                lines.extend(
                    [
                        f"#### {finding['id']} — {finding['severity']}",
                        "",
                        finding["summary"],
                        "",
                        f"Evidence: {finding['evidence']}",
                        "",
                        f"Required action: {finding['required_action']}",
                        "",
                    ]
                )

    if guards is not None and guards.contract is not None:
        contract = guards.contract
        lines.extend([
            "## Execution Contract", "", "- Version: `1.1`",
            f"- Pinned TASK SHA-256: `{guards.task_digest}`",
            f"- Verification classification: `{contract.verification_classification}`",
            f"- Exact verification argv: `{json.dumps(contract.verification_argv)}`", "",
            "## Historical Untracked Files (unchanged; not task deliverables)", "",
            *[f"- `{name}` SHA-256 `{digest}`" for name, digest in sorted(contract.preexisting_untracked.items())],
            "",
        ])

    if full_test_path is not None:
        heading = (guards.contract.verification_classification
                   if guards is not None and guards.contract is not None else "Full Regression")
        lines.extend(
            [
                f"## {heading}",
                "",
                f"See `{full_test_path.relative_to(ROOT)}`.",
                "",
            ]
        )

    lines.extend(
        [
            "## Git Safety",
            "",
            "- Automatic commit: no",
            "- Automatic push: no",
            f"- HEAD expected to remain: `{base_head}`",
            "",
            "## Human Next Step",
            "",
        ]
    )

    if status == "PASS":
        lines.append(
            "Inspect `git diff` and this report. "
            "Commit manually only if satisfied."
        )
    else:
        lines.append(
            "Do not commit yet. Resolve the escalation with "
            "the user/ChatGPT first."
        )

    content = "\n".join(lines) + "\n"
    save_text(AI / "FINAL_REPORT.md", content)
    return content


INCOMPLETE_REPORT = (
    "# RawiBumi Automated Task Final Report\n\n"
    "INCOMPLETE: startup/verification gates have not passed or the run exited "
    "abnormally. See console output and .ai/reports for diagnostics.\n"
)


@dataclass
class FinalReportState:
    status: str = "INCOMPLETE"
    content: str = INCOMPLETE_REPORT


def main() -> None:
    # Only reports generated by this invocation are trusted. Agents can write
    # FINAL_REPORT.md, which is deliberately outside source-change accounting.
    final = FinalReportState()
    completed = False
    try:
        with termination_signals() as termination:
            try:
                save_text(AI / "FINAL_REPORT.md", INCOMPLETE_REPORT)
                _main(final)
                completed = True
            finally:
                termination.defer_exit = True
                content = final.content
                if final.status == "PASS" and not completed:
                    content = INCOMPLETE_REPORT
                # Preserve trusted escalation details and all .ai/reports evidence;
                # never trust a report read back from an agent-writable path.
                save_text(AI / "FINAL_REPORT.md", content)
                if termination.received is not None:
                    if final.status == "PASS":
                        save_text(AI / "FINAL_REPORT.md", INCOMPLETE_REPORT)
                    raise SystemExit(128 + termination.received)
    except BaseException:
        # Handler installation/restoration and the final write are also part
        # of the lifecycle. A failure there must invalidate a generated PASS.
        content = final.content if final.status != "PASS" else INCOMPLETE_REPORT
        save_text(AI / "FINAL_REPORT.md", content)
        raise


def _main(final: FinalReportState) -> None:
    with report_directory(REPORTS):
        pass

    print("=" * 64)
    print("RawiBumi AI Development Loop")
    print("=" * 64)

    guards = RunGuards.start()
    branch, start_head = guards.branch, guards.head
    classification = (guards.contract.verification_classification
                      if guards.contract is not None else "Full regression")

    def report(**kwargs: object) -> None:
        guards.check()
        content = generate_final_report(**kwargs, guards=guards)
        final.status = kwargs["status"]
        final.content = content

    print(f"Branch: {branch}")
    print(f"Base:   {start_head[:12]}")
    print("Writer: Codex")
    print("Reviewer: Claude")
    print(f"Maximum rounds: {MAX_ROUNDS}")

    guards.check()
    before = repository_snapshot() if guards.contract is not None else {}
    plan = claude_plan()
    guards.assert_read_only(before)
    if plan.get("status") not in {"ready", "blocked"}:
        fail("Invalid planner status.", 7)

    if plan["status"] == "blocked":
        report(
            status="ESCALATION_REQUIRED",
            branch=branch,
            base_head=start_head,
            rounds=0,
            reason=(
                "Claude planning found a material ambiguity "
                "that should be resolved before implementation."
            ),
        )
        fail(
            "Task blocked during planning. "
            "See .ai/reports/claude_plan.json and "
            ".ai/FINAL_REPORT.md.",
            3,
        )

    previous_review: Path | None = None
    previous_full_test: Path | None = None
    final_review: dict | None = None
    failed_verification_snapshot: dict | None = None

    for round_number in range(1, MAX_ROUNDS + 1):
        print("\n" + "=" * 64)
        print(f"ROUND {round_number}/{MAX_ROUNDS}")
        print("=" * 64)

        guards.check()
        build = codex_build(
            round_number,
            previous_review,
            previous_full_test,
        )

        guards.check()
        if build.get("status") not in {"implemented", "blocked"}:
            fail("Invalid builder status.", 7)

        if build["status"] == "blocked":
            report(
                status="ESCALATION_REQUIRED",
                branch=branch,
                base_head=start_head,
                rounds=round_number,
                reason=(
                    "Codex encountered a material decision "
                    "requiring escalation."
                ),
            )
            fail(
                "Codex blocked the task. "
                f"See .ai/reports/codex_round_{round_number}.json",
                4,
            )

        status_path, diff_path = snapshot_git(round_number, guards)

        codex_report = REPORTS / f"codex_round_{round_number}.json"

        guards.check()
        before = repository_snapshot() if guards.contract is not None else {}
        review = claude_review(
            round_number,
            codex_report,
            status_path,
            diff_path,
        )

        final_review = review

        guards.assert_read_only(before)
        if guards.contract is not None:
            validate_review(review)

        review_path = REPORTS / f"claude_review_{round_number}.json"

        if review["status"] == "blocked":
            report(
                status="ESCALATION_REQUIRED",
                branch=branch,
                base_head=start_head,
                rounds=round_number,
                reason=(
                    "Claude found a material issue requiring "
                    "user/ChatGPT arbitration."
                ),
                final_review=review,
            )
            fail(
                "Review requires arbitration. "
                f"See {review_path.relative_to(ROOT)}",
                4,
            )

        if review["status"] == "changes_required":
            print("\nReview requires another repair round.")
            previous_review = review_path
            previous_full_test = None
            continue

        # Claude has approved the implementation.
        guards.check()
        before = repository_snapshot() if guards.contract is not None else {}
        if guards.contract is not None and before == failed_verification_snapshot:
            fail("Verification cannot be retried without an implementation repair.", 7)
        full_pass, full_path = run_verification(round_number, guards.contract)

        guards.assert_read_only(before)

        if full_pass:
            report(
                status="PASS",
                branch=branch,
                base_head=start_head,
                rounds=round_number,
                reason=(
                    f"Claude review passed and {classification} passed."
                ),
                final_review=review,
                full_test_path=full_path,
            )

            print("\n" + "=" * 64)
            print("TASK COMPLETE")
            print("=" * 64)
            print("Claude review: PASS")
            print(f"{classification}: PASS")
            print("Automatic commit: NO")
            print("Automatic push: NO")
            print("")
            print("Review:")
            print("  git diff")
            print("  cat .ai/FINAL_REPORT.md")
            return

        print(
            f"\n{classification} failed. "
            "The failure will be returned to Codex "
            "for another repair round."
        )

        previous_review = review_path
        previous_full_test = full_path
        failed_verification_snapshot = before

    report(
        status="ESCALATION_REQUIRED",
        branch=branch,
        base_head=start_head,
        rounds=MAX_ROUNDS,
        reason=(
            "Maximum automated repair rounds reached "
            "without satisfying all gates."
        ),
        final_review=final_review,
        full_test_path=previous_full_test,
    )

    fail(
        "Maximum automated rounds reached. "
        "See .ai/FINAL_REPORT.md and return to user/ChatGPT.",
        2,
    )


if __name__ == "__main__":
    main()
