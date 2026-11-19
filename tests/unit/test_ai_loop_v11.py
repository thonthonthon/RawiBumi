"""Synthetic orchestration tests: all processes/agents are mocked; no workloads."""
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import ai_loop as loop


R2E_ARGV = [
    ".venv/bin/python", "-m", "pytest", "-q",
    "tests/unit/test_rb_post3d_08p2e2_r2e_memory.py",
]
HEAD = "8ad1cfcd6165d8cdbb3104fc236c76f694dee955"
BRANCH = "ai/synthetic"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def evidence_metadata(path: Path) -> tuple[int, ...]:
    info = path.stat()
    # Repository reads may change atime; writes/replacements must not change
    # identity, mode, link count, size, mtime or ctime of historical evidence.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def payload() -> dict:
    return {
        "contract_version": "1.1",
        "expected_branch": BRANCH,
        "expected_head": HEAD,
        "allowed_changed_paths": ["new.py", "docs/new.md"],
        "preexisting_untracked": {"history.py": digest(b"historical\n")},
        "immutable_source_guards": {"source.py": digest(b"frozen\n")},
        "verification": {"argv": R2E_ARGV, "classification": "TARGETED_VERIFICATION"},
    }


def task_text(data: dict | None = None) -> str:
    return "# Synthetic task\n\n```ai-loop-contract\n" + json.dumps(payload() if data is None else data) + "\n```\n"


def review(status: str = "pass") -> dict:
    return dict(status=status, blockers=0, majors=0, minors=0, optional=0,
                summary="synthetic independent review", findings=[])


@pytest.fixture(autouse=True)
def lifecycle_signals(monkeypatch):
    """Model handler installation without changing the test runner's signals."""
    handlers = {signal.SIGTERM: signal.SIG_DFL, signal.SIGHUP: signal.SIG_DFL}

    def install(number, handler):
        previous = handlers[number]
        handlers[number] = handler
        return previous

    monkeypatch.setattr(loop.signal, "getsignal", lambda number: handlers[number])
    monkeypatch.setattr(loop.signal, "signal", Mock(side_effect=install))
    return handlers


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Tiny worktree and logical Git model; no real Git or agent invocation."""
    monkeypatch.setattr(loop, "ROOT", tmp_path)
    monkeypatch.setattr(loop, "AI", tmp_path / ".ai")
    monkeypatch.setattr(loop, "REPORTS", tmp_path / ".ai/reports")
    for key in tuple(os.environ):
        if key.startswith("PYTEST_") or key in {"PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE"}:
            monkeypatch.delenv(key)
    (tmp_path / ".ai").mkdir()
    (tmp_path / ".ai/TASK.md").write_text(task_text())
    (tmp_path / "history.py").write_bytes(b"historical\n")
    (tmp_path / "source.py").write_bytes(b"frozen\n")
    target = tmp_path / R2E_ARGV[-1]
    target.parent.mkdir(parents=True)
    target.write_bytes(b"# synthetic existing test file\n")
    state = SimpleNamespace(branch=BRANCH, head=HEAD, staged=False,
                            index="H 100644 blob 0\tsource.py\0", verification_exit=0,
                            verification_stdout="1 passed in 0.01s\n")
    tracked = {"source.py": b"frozen\n", R2E_ARGV[-1]: target.read_bytes()}

    def untracked():
        return sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*")
                      if (p.is_file() or p.is_symlink())
                      and p.relative_to(tmp_path).parts[0] != ".ai"
                      and not p.name.endswith(".log")
                      and p.relative_to(tmp_path).as_posix() not in tracked)

    def changed():
        return sorted(p for p, raw in tracked.items()
                      if not (tmp_path / p).exists() or (tmp_path / p).read_bytes() != raw)

    def git(*args):
        if args == ("branch", "--show-current"):
            return state.branch
        if args == ("rev-parse", "HEAD"):
            return state.head
        if args == ("ls-files", "--stage", "-v", "-z"):
            return state.index
        if args == ("ls-files", "--cached", "-z"):
            return "\0".join(tracked) + "\0"
        if args == ("ls-files", "--others", "--exclude-standard", "-z"):
            return "\0".join(untracked()) + ("\0" if untracked() else "")
        if args[:2] == ("diff", "--name-only"):
            return "\0".join(changed()) + ("\0" if changed() else "")
        if args[:2] == ("diff", "--stat"):
            return "synthetic diff stat"
        if args[0] == "diff":
            return "synthetic tracked diff\n"
        if args[0] == "status":
            return "\n".join([*(" M " + p for p in changed()), *("?? " + p for p in untracked())])
        raise AssertionError(f"Unexpected synthetic git command: {args}")

    def run(cmd, **kwargs):
        if cmd == ["git", "diff", "--cached", "--quiet"]:
            return subprocess.CompletedProcess(cmd, int(state.staged), "", "")
        if cmd[:3] == ["git", "diff", "--no-index"]:
            return subprocess.CompletedProcess(cmd, 1, "+" + (tmp_path / cmd[-1]).read_text(), "")
        if cmd == R2E_ARGV:
            return subprocess.CompletedProcess(cmd, state.verification_exit, state.verification_stdout, "")
        raise AssertionError(f"Unexpected process invocation: {cmd}")

    process_runner = loop.run
    monkeypatch.setattr(loop, "git", Mock(side_effect=git))
    monkeypatch.setattr(loop, "run", Mock(side_effect=run))
    legacy_tests = loop.run_full_tests
    monkeypatch.setattr(loop, "run_full_tests", Mock(side_effect=AssertionError("legacy fallback")))
    return SimpleNamespace(root=tmp_path, state=state, tracked=tracked,
                           legacy_tests=legacy_tests, process_runner=process_runner)


def test_contract_selects_exact_targeted_argv():
    contract = loop.parse_execution_contract(task_text())
    assert list(contract.verification_argv) == R2E_ARGV
    assert contract.verification_classification == "TARGETED_VERIFICATION"
    assert loop.parse_execution_contract("# Ordinary legacy task\n") is None
    assert loop.parse_execution_contract(task_text().replace("\n", "\r\n")) == contract


@pytest.mark.parametrize("argv", [
    R2E_ARGV,
    ["pytest", "tests/unit/test_one.py"],
    [".venv/bin/py.test", "-vv", "tests/unit/test_one.py::TestCase::test_case"],
    ["python3.12", "-m", "pytest", "-k", "first or second", "-m", "unit",
     "--maxfail=1", "--tb", "short", "tests/unit/test_one.py", "tests/unit/test_two.py"],
    [".venv/bin/pytest", "-q", "--", "tests/unit/test_one.py"],
])
def test_targeted_selection_accepts_only_explicit_files_without_rewriting(argv):
    data = payload()
    data["verification"]["argv"] = argv
    contract = loop.parse_execution_contract(task_text(data))
    assert contract.verification_argv == tuple(argv)


@pytest.mark.parametrize("arguments", [
    [], ["-q"], ["-k", "one"], ["--"], ["."], ["tests"], ["tests/unit"],
    ["tests/**/*.py"], ["tests/test_[ab].py"], ["/tmp/test_other.py"],
    ["../test_other.py"], ["./tests/test_one.py"], ["tests/../test_one.py"],
    ["@tests.py"], ["tests/test_one.py::"],
    ["tests/test_one.py", "tests"],
    ["tests/test_one.py", "tests/test_two.py", "."],
    ["--pyargs", "some_package"], ["--pyargs", "tests/test_one.py"],
    ["tests/test_one.py", "--pyargs"],
    ["tests/test_one.py", "-c", "elsewhere.ini"],
    ["tests/test_one.py", "-celsewhere.ini"],
    ["tests/test_one.py", "--rootdir=elsewhere"],
    ["tests/test_one.py", "-o", "addopts=tests"],
    ["tests/test_one.py", "--override-ini=addopts=tests"],
    ["tests/test_one.py", "--override=addopts=tests"],
    ["tests/test_one.py", "--ignore=tests/test_one.py"],
    ["tests/test_one.py", "--ignore-glob=*"],
    ["tests/test_one.py", "--deselect=tests/test_one.py::test_one"],
    ["tests/test_one.py", "--lf"], ["tests/test_one.py", "--ff"],
    ["tests/test_one.py", "--stepwise"], ["tests/test_one.py", "--collect-only"],
    ["tests/test_one.py", "--help"], ["tests/test_one.py", "--version"],
    ["tests/test_one.py", "--doctest-modules"],
    ["tests/test_one.py", "-p", "custom_plugin"],
    ["tests/test_one.py", "--unrecognized-plugin-option"],
    ["tests/test_one.py", "-k"], ["tests/test_one.py", "-k", ""],
    ["tests/test_one.py", "-k", "--pyargs"],
    ["tests/test_one.py", "-k", "@options.txt"],
    ["tests/test_one.py", "-k", "one", "-k", "two"],
    ["tests/test_one.py", "--maxfail=invalid"],
    ["tests/test_one.py", "--capture=invalid"],
])
def test_targeted_collection_fails_closed_without_fallback(repo, arguments):
    data = payload()
    data["verification"]["argv"] = ["pytest", *arguments]
    with pytest.raises(SystemExit):
        loop.parse_execution_contract(task_text(data))
    loop.run.assert_not_called()
    loop.run_full_tests.assert_not_called()


@pytest.mark.parametrize("argv", [
    ["python", "-m", "pytest"],
    ["python", "-c", "import pytest; pytest.main()"],
    ["python", "-I", "-m", "pytest", "tests/test_one.py"],
    ["env", "pytest", "tests/test_one.py"],
    ["sh", "-c", "pytest tests/test_one.py"],
    ["custom-runner", "tests/test_one.py"],
])
def test_targeted_entry_points_cannot_hide_unrestricted_collection(argv):
    data = payload()
    data["verification"]["argv"] = argv
    with pytest.raises(SystemExit):
        loop.parse_execution_contract(task_text(data))


def test_unrestricted_pytest_is_accepted_only_as_full_regression():
    data = payload()
    data["verification"] = {"argv": ["python", "-m", "pytest", "-q"],
                            "classification": "FULL_REGRESSION"}
    contract = loop.parse_execution_contract(task_text(data))
    assert contract.verification_classification == "FULL_REGRESSION"
    assert contract.verification_argv == ("python", "-m", "pytest", "-q")


@pytest.mark.parametrize("text", [
    "```ai-loop-contract\n{broken}\n```",
    "```ai-loop-contract\n{}",
    "```AI-LOOP-CONTRACT\n{}\n```",
    '```json\n{"contract_version":"1.1"}\n```',
    task_text() + task_text(),
    '```ai-loop-contract\n{"contract_version":"1.1","contract_version":"1.1"}\n```',
])
def test_malformed_fences_and_duplicate_json_never_fall_back(text):
    with pytest.raises(SystemExit):
        loop.parse_execution_contract(text)


@pytest.mark.parametrize("field,value", [
    ("contract_version", "1.2"), ("contract_version", 1.1),
    ("expected_head", "short"), ("expected_branch", "main"),
    ("allowed_changed_paths", ["../escape.py"]),
    ("allowed_changed_paths", ["/absolute.py"]),
    ("allowed_changed_paths", [".ai/TASK.md"]),
    ("allowed_changed_paths", ["new.py", "new.py"]),
    ("allowed_changed_paths", ["scripts/ai_loop.py"]),
    ("allowed_changed_paths", ["history.py"]),
    ("preexisting_untracked", {"history.py": "bad"}),
    ("verification", {"argv": "pytest -q", "classification": "TARGETED_VERIFICATION"}),
    ("verification", {"argv": [], "classification": "TARGETED_VERIFICATION"}),
    ("verification", {"argv": ["pytest"], "classification": "SUCCESS"}),
])
def test_contract_rejects_invalid_fields(field, value):
    data = payload()
    data[field] = value
    with pytest.raises(SystemExit):
        loop.parse_execution_contract(task_text(data))


@pytest.mark.parametrize("change", ["missing", "unknown"])
def test_contract_field_set_is_strict(change):
    data = payload()
    if change == "missing":
        del data["verification"]
    else:
        data["fallback"] = True
    with pytest.raises(SystemExit):
        loop.parse_execution_contract(task_text(data))


def test_historical_untracked_files_are_accepted_but_not_deliverables(repo):
    guards = loop.RunGuards.start()
    assert guards.changed_files() == []
    (repo.root / "new.py").write_text("# generated\n")
    guards.check()
    assert guards.changed_files() == ["new.py"]


@pytest.mark.parametrize("mutation", ["undeclared", "missing_history", "bad_history", "dirty_tracked", "branch", "head", "staged"])
def test_startup_refuses_dirty_tree_and_wrong_baselines(repo, mutation):
    if mutation == "undeclared":
        (repo.root / "other.py").write_text("unauthorized")
    elif mutation == "missing_history":
        (repo.root / "history.py").unlink()
    elif mutation == "bad_history":
        (repo.root / "history.py").write_text("tampered")
    elif mutation == "dirty_tracked":
        (repo.root / "source.py").write_text("tampered")
    elif mutation == "branch":
        repo.state.branch = "other"
    elif mutation == "head":
        repo.state.head = "f" * 40
    else:
        repo.state.staged = True
    with pytest.raises(SystemExit):
        loop.RunGuards.start()


@pytest.mark.parametrize("mutation", ["task", "source", "history", "new", "branch", "head", "staged", "index", "symlink"])
def test_boundary_tampering_fails_closed(repo, mutation):
    guards = loop.RunGuards.start()
    if mutation in {"task", "source", "history", "new"}:
        name = {"task": ".ai/TASK.md", "source": "source.py", "history": "history.py", "new": "outside.py"}[mutation]
        (repo.root / name).write_text("tampered")
    elif mutation == "symlink":
        (repo.root / "new.py").symlink_to(repo.root / "source.py")
    elif mutation == "index":
        repo.state.index += "new index entry"
    elif mutation == "staged":
        repo.state.staged = True
    else:
        setattr(repo.state, mutation, "changed")
    with pytest.raises(SystemExit):
        guards.check()


def test_source_guard_mismatch_is_checked_without_a_git_diff(repo):
    data = payload()
    data["immutable_source_guards"]["source.py"] = "0" * 64
    (repo.root / ".ai/TASK.md").write_text(task_text(data))
    with pytest.raises(SystemExit):
        loop.RunGuards.start()


def test_ignored_new_files_and_archived_task_changes_are_not_scope_escape(repo):
    archived = repo.root / ".ai/TASK.saved.md"
    archived.write_text("immutable archive")
    guards = loop.RunGuards.start()
    archived.write_text("modified archive")
    with pytest.raises(SystemExit):
        guards.check()


def test_new_ignored_file_outside_allowlist_is_rejected(repo):
    guards = loop.RunGuards.start()
    (repo.root / "outside.log").write_text("ignored but unauthorized")
    with pytest.raises(SystemExit):
        guards.check()


def test_permitted_new_ignored_file_is_in_review_evidence(repo):
    data = payload()
    data["allowed_changed_paths"].append("new.log")
    (repo.root / ".ai/TASK.md").write_text(task_text(data))
    guards = loop.RunGuards.start()
    (repo.root / "new.log").write_text("generated ignored content")
    guards.check()
    status, diff = loop.snapshot_git(1, guards)
    assert "new.log" in status.read_text()
    assert "generated ignored content" in diff.read_text()


@pytest.mark.parametrize("index", ["h 100644 blob 0\tsource.py\0", "S 100644 blob 0\tsource.py\0"])
def test_nonstandard_index_flags_are_refused_at_startup(repo, index):
    repo.state.index = index
    with pytest.raises(SystemExit):
        loop.RunGuards.start()


def test_exact_command_no_docs_skip_no_fallback(repo):
    guards = loop.RunGuards.start()
    (repo.root / "docs").mkdir()
    (repo.root / "docs/new.md").write_text("docs only")
    passed, path = loop.run_verification(1, guards.contract)
    assert passed
    loop.run.assert_called_with(R2E_ARGV, timeout=7200)
    assert "ARGV_JSON: " + json.dumps(R2E_ARGV) in path.read_text()
    assert "TARGETED_VERIFICATION" in path.read_text()
    assert "FULL_REGRESSION" not in path.read_text()
    loop.run_full_tests.assert_not_called()


def test_verification_failure_never_selects_full_suite(repo):
    guards = loop.RunGuards.start()
    repo.state.verification_exit = 5  # pytest no collection is also failure
    passed, path = loop.run_verification(1, guards.contract)
    assert not passed
    assert "EXIT_CODE: 5" in path.read_text()
    loop.run_full_tests.assert_not_called()


@pytest.mark.parametrize("mutation", ["no_targets", "directory", "missing", "symlink", "symlink_parent"])
def test_selection_is_revalidated_immediately_before_verification(repo, mutation):
    contract = loop.parse_execution_contract(task_text())
    target = repo.root / R2E_ARGV[-1]
    if mutation == "no_targets":
        contract = replace(contract, verification_argv=tuple(R2E_ARGV[:-1]))
    elif mutation == "symlink_parent":
        real = target.parent.rename(target.parent.with_name("real_unit"))
        target.parent.symlink_to(real, target_is_directory=True)
    else:
        target.unlink()
        if mutation == "directory":
            target.mkdir()
        elif mutation == "symlink":
            target.symlink_to(repo.root / "source.py")
    with pytest.raises(SystemExit):
        loop.run_verification(1, contract)
    loop.run.assert_not_called()
    loop.run_full_tests.assert_not_called()


def test_generated_target_can_be_absent_at_startup_but_must_exist_for_verification(repo):
    data = payload()
    target_name = "tests/unit/test_new.py"
    data["allowed_changed_paths"].append(target_name)
    data["verification"]["argv"] = ["pytest", "-q", target_name]
    (repo.root / ".ai/TASK.md").write_text(task_text(data))
    guards = loop.RunGuards.start()
    (repo.root / target_name).write_text("# synthetic generated test\n")
    guards.check()
    loop.run.reset_mock()
    loop.run.return_value = subprocess.CompletedProcess(data["verification"]["argv"], 0, "1 passed in 0.01s\n", "")
    loop.run.side_effect = None
    passed, _ = loop.run_verification(1, guards.contract)
    assert passed
    loop.run.assert_called_once_with(data["verification"]["argv"], timeout=7200)


def test_full_regression_classification_and_outputs_remain_distinct(repo, capsys):
    data = payload()
    argv = ["python", "-m", "pytest", "-q"]
    data["verification"] = {"argv": argv, "classification": "FULL_REGRESSION"}
    (repo.root / ".ai/TASK.md").write_text(task_text(data))
    guards = loop.RunGuards.start()
    loop.run.side_effect = None
    loop.run.return_value = subprocess.CompletedProcess(argv, 0, "full stdout", "full stderr")
    passed, path = loop.run_verification(1, guards.contract)
    assert passed
    loop.run.assert_called_with(argv, timeout=7200)
    assert "CLASSIFICATION: FULL_REGRESSION" in path.read_text()
    assert "STDOUT\nfull stdout" in path.read_text()
    assert "STDERR\nfull stderr" in path.read_text()
    loop.generate_final_report(status="PASS", branch=BRANCH, base_head=HEAD, rounds=1,
                               reason="synthetic", full_test_path=path, guards=guards)
    assert "FULL_REGRESSION: PASS" in capsys.readouterr().out
    report = (repo.root / ".ai/FINAL_REPORT.md").read_text()
    assert "## FULL_REGRESSION" in report
    assert "TARGETED_VERIFICATION" not in report
    loop.run_full_tests.assert_not_called()


@pytest.mark.parametrize("key", ["PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTEST_XDIST_WORKER", "PYTHONPATH", "PYTHONHOME"])
def test_environment_overrides_are_rejected_before_command(repo, monkeypatch, key):
    contract = loop.parse_execution_contract(task_text())
    monkeypatch.setenv(key, "override")
    with pytest.raises(SystemExit):
        loop.run_verification(1, contract)
    loop.run.assert_not_called()


@pytest.mark.parametrize("filename,content", [
    ("pytest.ini", "[pytest]\naddopts = tests/other.py\n"),
    ("setup.cfg", "[tool:pytest]\npython_files = *.py\n"),
    ("tox.ini", "[pytest]\ntestpaths = other\n"),
    ("pyproject.toml", '[tool.pytest.ini_options]\naddopts = "--pyargs other"\n'),
    ("pyproject.toml", '[tool.pytest]\naddopts = ["--pyargs", "other"]\n'),
    ("pytest.toml", '[pytest]\naddopts = ["-k", "some_test"]\n'),
    (".pytest.toml", '[pytest]\npythonpath = ["other"]\n'),
    ("tests/unit/pytest.ini", "[pytest]\naddopts = --ignore=selected.py\n"),
])
def test_config_collection_overrides_are_rejected(repo, filename, content):
    path = repo.root / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if filename.startswith("tests/"):
        target = repo.root / R2E_ARGV[-1]
        target.write_text("# synthetic test target\n")
    with pytest.raises(SystemExit):
        loop.check_verification_overrides(tuple(R2E_ARGV))


def mock_process(monkeypatch, *, returncode=0, communicate=None):
    process = Mock(pid=12345, returncode=returncode)
    process.communicate.side_effect = communicate
    process.communicate.return_value = ("stdout\n", "stderr\n")
    popen = Mock(return_value=process)
    killpg = Mock()
    monkeypatch.setattr(loop.subprocess, "Popen", popen)
    monkeypatch.setattr(loop.os, "killpg", killpg)
    # A regression to subprocess.run must also never start a real command.
    monkeypatch.setattr(loop.subprocess, "run", Mock(side_effect=AssertionError("unexpected subprocess.run")))
    return process, popen, killpg


@pytest.mark.parametrize("returncode", [0, 7, -9])
@pytest.mark.parametrize("prompt", [None, "structured prompt\n"])
@pytest.mark.parametrize("group_gone", [False, True])
def test_subprocess_preserves_argv_prompt_returncode_and_streams(monkeypatch, returncode, prompt, group_gone):
    process, popen, killpg = mock_process(monkeypatch, returncode=returncode)
    if group_gone:
        killpg.side_effect = ProcessLookupError()
    result = loop.run(R2E_ARGV, prompt=prompt, timeout=17)
    popen.assert_called_once_with(
        R2E_ARGV, cwd=loop.ROOT, stdin=subprocess.PIPE if prompt is not None else None,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=False,
        start_new_session=True,
    )
    process.communicate.assert_called_once_with(input=prompt, timeout=17)
    assert result.args == R2E_ARGV
    assert (result.returncode, result.stdout, result.stderr) == (returncode, "stdout\n", "stderr\n")
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.wait.assert_not_called()  # communicate() already reaped the leader.


@pytest.mark.parametrize("leader_returncode", [None, 0])
@pytest.mark.parametrize("group_gone", [False, True])
def test_timeout_kills_entire_group_and_drains_and_reaps_child(monkeypatch, capsys, leader_returncode, group_gone):
    process, popen, killpg = mock_process(
        monkeypatch, returncode=leader_returncode,
        communicate=[subprocess.TimeoutExpired(R2E_ARGV, 17, output=b"partial"),
                     ("complete stdout\n", "complete stderr\n")],
    )
    events = []

    def kill(*args):
        events.append("kill group")
        if group_gone:
            raise ProcessLookupError()

    killpg.side_effect = kill
    original_communicate = process.communicate.side_effect

    def communicate(**kwargs):
        events.append("communicate")
        value = next(original_communicate)
        if isinstance(value, Exception):
            raise value
        return value

    process.communicate.side_effect = communicate
    with pytest.raises(SystemExit) as exc:
        loop.run(R2E_ARGV, prompt="input", timeout=17)
    assert exc.value.code == 1
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert events == ["communicate", "kill group", "communicate"]
    assert process.communicate.call_args_list[1].kwargs == {"timeout": 5}
    process.kill.assert_not_called()  # A leader-only kill would miss descendants.
    output = capsys.readouterr().out
    assert "timed out after 17 seconds" in output
    assert "complete stdout" in output and "complete stderr" in output
    assert output.count("complete stdout") == 1
    popen.assert_called_once()


def test_timeout_pipe_draining_is_bounded_and_partial_bytes_are_reported(monkeypatch, capsys):
    process, _, killpg = mock_process(monkeypatch, communicate=[
        subprocess.TimeoutExpired(R2E_ARGV, 17),
        subprocess.TimeoutExpired(R2E_ARGV, 5, output=b"partial stdout", stderr=b"partial stderr"),
    ])
    with pytest.raises(SystemExit):
        loop.run(R2E_ARGV, prompt="input", timeout=17)
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.wait.assert_called_once_with(timeout=5)
    process.stdin.close.assert_called_once()
    process.stdout.close.assert_called_once()
    process.stderr.close.assert_called_once()
    output = capsys.readouterr().out
    assert "partial stdout" in output and "partial stderr" in output


def test_subprocess_launch_failure_does_not_signal_a_group(monkeypatch):
    _, popen, killpg = mock_process(monkeypatch)
    popen.side_effect = FileNotFoundError("missing command")
    with pytest.raises(FileNotFoundError):
        loop.run(["missing"])
    killpg.assert_not_called()


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
@pytest.mark.parametrize("during_launch", [False, True])
def test_terminal_shutdown_cleans_group_and_restores_handlers(monkeypatch, lifecycle_signals, number, during_launch):
    previous = dict(lifecycle_signals)
    process, popen, killpg = mock_process(monkeypatch)

    def shutdown():
        lifecycle_signals[number](number, None)

    if during_launch:
        def launch(*args, **kwargs):
            shutdown()  # Deferred until Popen returns the cleanup handle.
            assert all(handler == signal.SIG_IGN for handler in lifecycle_signals.values())
            return process
        popen.side_effect = launch
    else:
        calls = 0

        def communicate(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                shutdown()
            assert all(handler == signal.SIG_IGN for handler in lifecycle_signals.values())
            return "partial stdout", "partial stderr"
        process.communicate.side_effect = communicate

    with pytest.raises(SystemExit) as exc:
        loop.run(["synthetic-agent"], timeout=17)
    assert exc.value.code == 128 + number
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert process.communicate.call_args.kwargs == {"timeout": 5}
    assert lifecycle_signals == previous


@pytest.mark.parametrize("error", [None, RuntimeError("synthetic scope failure")])
def test_nohup_ignore_survives_nested_signal_scopes(lifecycle_signals, error):
    lifecycle_signals[signal.SIGHUP] = signal.SIG_IGN
    previous = dict(lifecycle_signals)

    def nested():
        with loop.termination_signals():
            assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
            outer_term = lifecycle_signals[signal.SIGTERM]
            with loop.termination_signals():
                assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
                assert callable(lifecycle_signals[signal.SIGTERM])
                if error is not None:
                    raise error
            assert lifecycle_signals[signal.SIGTERM] is outer_term

    if error is None:
        nested()
    else:
        with pytest.raises(RuntimeError, match="scope failure"):
            nested()
    assert lifecycle_signals == previous
    assert all(call.args[0] != signal.SIGHUP for call in loop.signal.signal.call_args_list)


@pytest.mark.parametrize("outcome", ["normal", "timeout", "sigterm_launch", "sigterm_communicate", "sigterm_cleanup"])
def test_nohup_command_preserves_ignore_and_process_group_cleanup(monkeypatch, lifecycle_signals, outcome):
    lifecycle_signals[signal.SIGHUP] = signal.SIG_IGN
    previous = dict(lifecycle_signals)
    process, popen, killpg = mock_process(monkeypatch)

    def terminate():
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        lifecycle_signals[signal.SIGTERM](signal.SIGTERM, None)

    def launch(*args, **kwargs):
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        if outcome == "sigterm_launch":
            terminate()
        return process

    def communicate(**kwargs):
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        if "input" in kwargs:
            if outcome == "timeout":
                raise subprocess.TimeoutExpired(["synthetic-agent"], 17)
            if outcome == "sigterm_communicate":
                terminate()
        return "stdout", "stderr"

    def kill(*args):
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        if outcome == "sigterm_cleanup":
            terminate()

    popen.side_effect = launch
    process.communicate.side_effect = communicate
    killpg.side_effect = kill
    if outcome == "normal":
        result = loop.run(["synthetic-agent"], timeout=17)
        assert (result.returncode, result.stdout, result.stderr) == (0, "stdout", "stderr")
    else:
        with pytest.raises(SystemExit) as exc:
            loop.run(["synthetic-agent"], timeout=17)
        assert exc.value.code == (1 if outcome == "timeout" else 128 + signal.SIGTERM)
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    if outcome in {"timeout", "sigterm_launch", "sigterm_communicate"}:
        assert process.communicate.call_args.kwargs == {"timeout": 5}
    assert lifecycle_signals == previous
    assert all(call.args[1] == signal.SIG_IGN for call in loop.signal.signal.call_args_list
               if call.args[0] == signal.SIGHUP)


def test_normal_exit_group_cleanup_failure_propagates(monkeypatch):
    _, _, killpg = mock_process(monkeypatch)
    killpg.side_effect = PermissionError("group cleanup refused")
    with pytest.raises(PermissionError, match="group cleanup refused"):
        loop.run(["synthetic-agent"])


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_shutdown_during_normal_group_cleanup_finishes_kill(monkeypatch, lifecycle_signals, number):
    process, _, killpg = mock_process(monkeypatch)
    events = []

    def kill(*args):
        lifecycle_signals[number](number, None)
        events.append("group kill completed")

    killpg.side_effect = kill
    with pytest.raises(SystemExit) as exc:
        loop.run(["synthetic-agent"])
    assert exc.value.code == 128 + number
    assert events == ["group kill completed"]
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.communicate.assert_called_once()


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_shutdown_while_returning_completed_result_is_not_success(monkeypatch, lifecycle_signals, number):
    process, _, killpg = mock_process(monkeypatch)

    def complete(*args):
        # A terminal signal can arrive after the last group kill, while the
        # CompletedProcess is being constructed. It must still abort the call.
        lifecycle_signals[number](number, None)
        raise AssertionError("shutdown was silently deferred past return")

    monkeypatch.setattr(loop.subprocess, "CompletedProcess", Mock(side_effect=complete))
    with pytest.raises(SystemExit) as exc:
        loop.run(["synthetic-agent"])
    assert exc.value.code == 128 + number
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.communicate.assert_called_once()


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_shutdown_during_timeout_cleanup_finishes_draining(monkeypatch, lifecycle_signals, number):
    process, _, killpg = mock_process(monkeypatch, communicate=[
        subprocess.TimeoutExpired(["synthetic-agent"], 17),
        ("partial stdout", "partial stderr"),
    ])
    events = []

    def kill(*args):
        lifecycle_signals[number](number, None)
        events.append("group kill completed")

    killpg.side_effect = kill
    with pytest.raises(SystemExit) as exc:
        loop.run(["synthetic-agent"], timeout=17)
    assert exc.value.code == 128 + number
    assert events == ["group kill completed"]
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert process.communicate.call_args.kwargs == {"timeout": 5}
    assert process.communicate.call_count == 2


@pytest.mark.parametrize("error", [KeyboardInterrupt(), OSError("communication failed")])
def test_interrupted_communication_cleans_group_and_propagates_error(monkeypatch, error):
    process, _, killpg = mock_process(monkeypatch, communicate=[error, ("partial", "stderr")])
    with pytest.raises(type(error)):
        loop.run(R2E_ARGV)
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert process.communicate.call_args_list[1].kwargs == {"timeout": 5}


def test_timeout_cleanup_still_reaps_when_pipe_draining_fails(monkeypatch):
    process, _, killpg = mock_process(monkeypatch, communicate=[
        subprocess.TimeoutExpired(R2E_ARGV, 17), OSError("pipe read failed"),
    ])
    with pytest.raises(OSError, match="pipe read failed"):
        loop.run(R2E_ARGV, timeout=17)
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.wait.assert_called_once_with(timeout=5)


def test_timeout_group_kill_failure_still_closes_pipes_and_reaps(monkeypatch):
    process, _, killpg = mock_process(monkeypatch, communicate=[
        subprocess.TimeoutExpired(R2E_ARGV, 17),
    ])
    killpg.side_effect = PermissionError("group cleanup refused")
    with pytest.raises(PermissionError, match="group cleanup refused"):
        loop.run(R2E_ARGV, prompt="input", timeout=17)
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    process.communicate.assert_called_once_with(input="input", timeout=17)
    for stream in (process.stdin, process.stdout, process.stderr):
        stream.close.assert_called_once()
    process.wait.assert_called_once_with(timeout=5)


def test_structured_claude_output_and_stderr_are_preserved(repo, monkeypatch):
    monkeypatch.setattr(loop, "run", repo.process_runner)
    structured = {"status": "ready", "summary": "synthetic"}
    process, _, killpg = mock_process(monkeypatch)
    process.communicate.return_value = (json.dumps({"structured_output": structured}), "diagnostic stderr")
    raw = loop.REPORTS / "claude.json"
    assert loop.claude_structured("prompt", loop.PLAN_SCHEMA, raw) == structured
    assert json.loads(raw.read_text())["structured_output"] == structured
    assert raw.with_suffix(".stderr.txt").read_text() == "diagnostic stderr"
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "invalid_json"])
def test_failed_process_cannot_produce_structured_success(repo, monkeypatch, failure):
    monkeypatch.setattr(loop, "run", repo.process_runner)
    process, _, killpg = mock_process(monkeypatch, returncode=1 if failure == "nonzero" else 0)
    stdout = json.dumps({"structured_output": {"status": "ready"}})
    process.communicate.return_value = ("invalid" if failure == "invalid_json" else stdout, "stderr")
    if failure == "timeout":
        process.communicate.side_effect = [subprocess.TimeoutExpired(["claude"], 3600), (stdout, "stderr")]
    with pytest.raises(SystemExit):
        loop.claude_structured("prompt", loop.PLAN_SCHEMA, loop.REPORTS / "claude.json")
    assert killpg.call_count == 1


def test_generated_file_contents_are_in_review_snapshot(repo):
    guards = loop.RunGuards.start()
    (repo.root / "new.py").write_text("generated = 17\n")
    status, diff = loop.snapshot_git(1, guards)
    assert "generated = 17" in diff.read_text()
    assert digest(b"generated = 17\n") in status.read_text()
    assert "Task file inventory" in status.read_text()


def test_read_only_agents_cannot_modify_even_authorized_paths(repo):
    guards = loop.RunGuards.start()
    before = loop.repository_snapshot()
    (repo.root / "new.py").write_text("unauthorized reviewer write")
    with pytest.raises(SystemExit):
        guards.assert_read_only(before)


@pytest.mark.parametrize("bad", [
    dict(blockers=1), dict(majors=1), dict(majors=True),
    dict(findings=[dict(severity="MAJOR")]), dict(status="unknown"),
])
def test_inconsistent_review_evidence_cannot_pass(bad):
    with pytest.raises(SystemExit):
        loop.validate_review(review() | bad)


def install_agents(monkeypatch, repo, *, edit=True, reviewer=None):
    events = []
    planner = Mock(side_effect=lambda: events.append("plan") or dict(status="ready"))

    def build(*args):
        events.append("build")
        if edit:
            (repo.root / "new.py").write_text(f"# implementation round {args[0]}\n")
        return dict(status="implemented", summary="synthetic", files_changed=["new.py"], unresolved_issues=[])

    def inspect(*args):
        events.append("review")
        if edit:
            assert "new.py" in args[2].read_text()
        return reviewer() if reviewer else review()

    monkeypatch.setattr(loop, "claude_plan", planner)
    monkeypatch.setattr(loop, "codex_build", Mock(side_effect=build))
    monkeypatch.setattr(loop, "claude_review", Mock(side_effect=inspect))
    original = loop.run_verification

    def verify(*args):
        events.append("verify")
        return original(*args)

    monkeypatch.setattr(loop, "run_verification", Mock(side_effect=verify))
    return events


@pytest.mark.parametrize("link_kind", ["absolute", "relative", "dangling", "hardlink"])
@pytest.mark.parametrize("content", [loop.INCOMPLETE_REPORT, "## Status\n\nPASS\n"])
def test_atomic_report_replaces_link_without_writing_its_target(repo, monkeypatch, link_kind, content):
    final = loop.AI / "FINAL_REPORT.md"
    target = repo.root / ("missing.md" if link_kind == "dangling" else "history.py")
    if link_kind == "hardlink":
        os.link(target, final)
    else:
        final.symlink_to("../history.py" if link_kind == "relative" else target)
    # Hardlink creation changes ctime, so pin evidence after preparing the attack.
    before = target.stat() if target.exists() else None
    replace_report = loop.os.replace
    replacements = []

    def publish(source, destination, **kwargs):
        assert source.startswith(".FINAL_REPORT.") and source.endswith(".tmp")
        assert destination == "FINAL_REPORT.md"
        assert kwargs["src_dir_fd"] == kwargs["dst_dir_fd"]
        temporary = loop.AI / source
        assert temporary.is_file() and not temporary.is_symlink()
        assert temporary.read_text() == content
        assert temporary.stat().st_mode & 0o777 == 0o600
        if before is None:
            assert not target.exists()
        else:
            assert target.stat() == before
        replacements.append(source)
        return replace_report(source, destination, **kwargs)

    monkeypatch.setattr(loop.os, "replace", Mock(side_effect=publish))
    loop.save_text(final, content)
    assert len(replacements) == 1
    assert final.is_file() and not final.is_symlink()
    assert final.read_text() == content
    if before is None:
        assert not target.exists()
    else:
        assert target.read_bytes() == b"historical\n"
        # Reads may update atime, while replacement must leave evidence intact.
        after = target.stat()
        assert (after.st_ino, after.st_size, after.st_mtime_ns) == (
            before.st_ino, before.st_size, before.st_mtime_ns)
        if link_kind != "hardlink":
            assert after.st_ctime_ns == before.st_ctime_ns
    assert not list(loop.AI.glob(".FINAL_REPORT.*.tmp"))


def test_report_entry_swapped_at_atomic_replace_does_not_redirect_write(repo, monkeypatch):
    final = loop.AI / "FINAL_REPORT.md"
    final.write_text("STALE PASS\n")
    target = repo.root / "history.py"
    before = evidence_metadata(target)
    replace_report = loop.os.replace

    def redirect(source, destination, **kwargs):
        final.unlink()
        final.symlink_to(target)
        return replace_report(source, destination, **kwargs)

    monkeypatch.setattr(loop.os, "replace", Mock(side_effect=redirect))
    loop.save_text(final, loop.INCOMPLETE_REPORT)
    assert not final.is_symlink()
    assert final.read_text() == loop.INCOMPLETE_REPORT
    assert evidence_metadata(target) == before
    assert target.read_bytes() == b"historical\n"
    assert not list(loop.AI.glob(".FINAL_REPORT.*.tmp"))


def test_report_directory_symlink_is_refused_before_agents(repo, monkeypatch):
    events = install_agents(monkeypatch, repo)
    evidence = repo.root / "evidence"
    evidence.mkdir()
    target = evidence / "FINAL_REPORT.md"
    target.write_text("immutable historical evidence\n")
    before = evidence_metadata(target)
    loop.AI.rename(repo.root / ".ai-original")
    loop.AI.symlink_to(evidence, target_is_directory=True)
    with pytest.raises(OSError):
        loop.main()
    assert events == []
    assert evidence_metadata(target) == before
    assert target.read_text() == "immutable historical evidence\n"
    assert sorted(p.name for p in evidence.iterdir()) == ["FINAL_REPORT.md"]


def test_report_root_symlink_is_refused(repo, monkeypatch):
    redirect = repo.root / "root-link"
    redirect.symlink_to(repo.root, target_is_directory=True)
    monkeypatch.setattr(loop, "ROOT", redirect)
    monkeypatch.setattr(loop, "AI", redirect / ".ai")
    monkeypatch.setattr(loop, "REPORTS", redirect / ".ai/reports")
    with pytest.raises(OSError):
        loop.save_text(loop.AI / "FINAL_REPORT.md", loop.INCOMPLETE_REPORT)
    assert not (repo.root / ".ai/FINAL_REPORT.md").exists()


def test_report_directory_substitution_during_replace_cannot_redirect_write(repo, monkeypatch):
    evidence = repo.root / "evidence"
    evidence.mkdir()
    target = evidence / "FINAL_REPORT.md"
    target.write_text("immutable historical evidence\n")
    before = evidence_metadata(target)
    replace_report = loop.os.replace

    def redirect(source, destination, **kwargs):
        loop.AI.rename(repo.root / ".ai-original")
        loop.AI.symlink_to(evidence, target_is_directory=True)
        return replace_report(source, destination, **kwargs)

    monkeypatch.setattr(loop.os, "replace", Mock(side_effect=redirect))
    with pytest.raises(OSError, match="directory changed"):
        loop.save_text(loop.AI / "FINAL_REPORT.md", loop.INCOMPLETE_REPORT)
    assert evidence_metadata(target) == before
    assert target.read_text() == "immutable historical evidence\n"
    assert (repo.root / ".ai-original/FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT
    assert not list((repo.root / ".ai-original").glob(".FINAL_REPORT.*.tmp"))


def test_temporary_report_symlink_collision_fails_closed(repo, monkeypatch):
    monkeypatch.setattr(loop.secrets, "token_hex", lambda size: "collision")
    temporary = loop.AI / ".FINAL_REPORT.collision.tmp"
    target = repo.root / "history.py"
    before = evidence_metadata(target)
    temporary.symlink_to(target)
    with pytest.raises(FileExistsError):
        loop.save_text(loop.AI / "FINAL_REPORT.md", loop.INCOMPLETE_REPORT)
    assert temporary.is_symlink()
    assert evidence_metadata(target) == before
    assert target.read_bytes() == b"historical\n"
    assert not (loop.AI / "FINAL_REPORT.md").exists()


@pytest.mark.parametrize("phase", ["claude_plan", "codex_build", "claude_review", "run_verification"])
@pytest.mark.parametrize("outcome", ["success", "failure", "shutdown"])
def test_agent_report_symlink_preserves_evidence_and_authoritative_result(
        repo, monkeypatch, lifecycle_signals, phase, outcome):
    install_agents(monkeypatch, repo)
    original = getattr(loop, phase)
    target = repo.root / "history.py"
    before = evidence_metadata(target)
    final = loop.AI / "FINAL_REPORT.md"

    def redirect(*args):
        final.unlink()
        final.symlink_to(target)
        if outcome == "failure":
            raise RuntimeError("synthetic agent failure")
        if outcome == "shutdown":
            lifecycle_signals[signal.SIGTERM](signal.SIGTERM, None)
        return original(*args)

    monkeypatch.setattr(loop, phase, Mock(side_effect=redirect))
    if outcome == "success":
        loop.main()
        assert "## Status\n\nPASS\n" in final.read_text()
    else:
        error = RuntimeError if outcome == "failure" else SystemExit
        with pytest.raises(error):
            loop.main()
        assert final.read_text() == loop.INCOMPLETE_REPORT
    assert not final.is_symlink()
    assert evidence_metadata(target) == before
    assert target.read_bytes() == b"historical\n"
    assert not list(loop.AI.glob(".FINAL_REPORT.*.tmp"))


def test_report_symlink_after_trusted_escalation_preserves_diagnostics(repo, monkeypatch):
    install_agents(monkeypatch, repo)
    loop.codex_build.side_effect = None
    loop.codex_build.return_value = {"status": "blocked"}
    original_fail = loop.fail
    trusted = []
    target = repo.root / "history.py"
    before = evidence_metadata(target)

    def redirect_then_fail(message, code=1):
        final = loop.AI / "FINAL_REPORT.md"
        trusted.append(final.read_text())
        final.unlink()
        final.symlink_to(target)
        original_fail(message, code)

    monkeypatch.setattr(loop, "fail", redirect_then_fail)
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 4
    assert len(trusted) == 1 and "ESCALATION_REQUIRED" in trusted[0]
    assert (loop.AI / "FINAL_REPORT.md").read_text() == trusted[0]
    assert not (loop.AI / "FINAL_REPORT.md").is_symlink()
    assert evidence_metadata(target) == before
    assert target.read_bytes() == b"historical\n"


@pytest.mark.parametrize("after_replace", [False, True])
def test_atomic_replace_failure_invalidates_generated_pass_and_cleans_temporary(repo, monkeypatch, after_replace):
    install_agents(monkeypatch, repo)
    original = loop.os.replace
    calls = 0

    def fail_once(source, destination, **kwargs):
        nonlocal calls
        if destination == "FINAL_REPORT.md":
            calls += 1
        fail_here = destination == "FINAL_REPORT.md" and calls == 3
        if fail_here and not after_replace:
            raise OSError("synthetic atomic publish failure")
        original(source, destination, **kwargs)
        if fail_here:
            raise OSError("synthetic atomic publish failure")

    monkeypatch.setattr(loop.os, "replace", Mock(side_effect=fail_once))
    with pytest.raises(OSError, match="atomic publish failure"):
        loop.main()
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT
    assert not list(loop.AI.glob(".FINAL_REPORT.*.tmp"))


@pytest.mark.parametrize("phase", ["claude_plan", "codex_build", "claude_review", "run_verification"])
@pytest.mark.parametrize("shutdown", [False, True])
def test_nohup_main_and_command_scopes_keep_ignore_and_authoritative_report(
        repo, monkeypatch, lifecycle_signals, phase, shutdown):
    lifecycle_signals[signal.SIGHUP] = signal.SIG_IGN
    previous = dict(lifecycle_signals)
    install_agents(monkeypatch, repo)
    original = getattr(loop, phase)
    process, _, killpg = mock_process(monkeypatch)

    def communicate(**kwargs):
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        if shutdown and "input" in kwargs:
            lifecycle_signals[signal.SIGTERM](signal.SIGTERM, None)
        return "stdout", "stderr"

    process.communicate.side_effect = communicate

    def execute(*args):
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        repo.process_runner(["synthetic-agent"], timeout=17)
        assert lifecycle_signals[signal.SIGHUP] == signal.SIG_IGN
        return original(*args)

    monkeypatch.setattr(loop, phase, Mock(side_effect=execute))
    if shutdown:
        with pytest.raises(SystemExit) as exc:
            loop.main()
        assert exc.value.code == 128 + signal.SIGTERM
        assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT
        assert process.communicate.call_args.kwargs == {"timeout": 5}
    else:
        loop.main()
        assert "## Status\n\nPASS\n" in (loop.AI / "FINAL_REPORT.md").read_text()
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert lifecycle_signals == previous
    assert all(call.args[1] == signal.SIG_IGN for call in loop.signal.signal.call_args_list
               if call.args[0] == signal.SIGHUP)


def test_workflow_reviews_generated_files_before_targeted_verification(repo, monkeypatch, capsys):
    events = install_agents(monkeypatch, repo)
    loop.main()
    assert events == ["plan", "build", "review", "verify"]
    output = capsys.readouterr().out
    report_text = (repo.root / ".ai/FINAL_REPORT.md").read_text()
    assert "TARGETED_VERIFICATION: PASS" in output
    assert "Full regression" not in output
    assert "## TARGETED_VERIFICATION" in report_text
    assert "## Full Regression" not in report_text
    assert "Historical Untracked Files" in report_text
    assert "## Files Changed\n\n- `new.py`" in report_text
    loop.run_full_tests.assert_not_called()


def test_three_rounds_are_repairs_with_feedback_not_blind_retries(repo, monkeypatch):
    events = install_agents(monkeypatch, repo)
    repo.state.verification_exit = 1
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 2
    assert loop.MAX_ROUNDS == 3
    assert events.count("build") == events.count("verify") == 3
    assert loop.codex_build.call_args_list[1].args[2] == loop.REPORTS / "verification_round_1.txt"
    assert "ESCALATION_REQUIRED" in (repo.root / ".ai/FINAL_REPORT.md").read_text()


def test_unchanged_failed_implementation_is_not_reverified(repo, monkeypatch):
    events = install_agents(monkeypatch, repo, edit=False)
    repo.state.verification_exit = 1
    with pytest.raises(SystemExit):
        loop.main()
    assert events.count("build") == 2
    assert events.count("verify") == 1


@pytest.mark.parametrize("invalid", ["malformed", "unrestricted", "conflicting_options"])
def test_invalid_contract_stops_before_agents_or_legacy(repo, monkeypatch, invalid):
    data = payload()
    data["verification"]["argv"] = (["pytest", "-q"] if invalid == "unrestricted" else
                                    [*R2E_ARGV, "--pyargs"])
    text = "```ai-loop-contract\ninvalid\n```\n" if invalid == "malformed" else task_text(data)
    (repo.root / ".ai/TASK.md").write_text(text)
    events = install_agents(monkeypatch, repo)
    with pytest.raises(SystemExit):
        loop.main()
    assert events == []
    loop.run_full_tests.assert_not_called()
    assert "INCOMPLETE" in (repo.root / ".ai/FINAL_REPORT.md").read_text()


@pytest.mark.parametrize("phase", ["claude_plan", "codex_build", "claude_review"])
def test_unauthorized_writes_stop_at_every_agent_boundary(repo, monkeypatch, phase):
    events = install_agents(monkeypatch, repo)

    def tamper(*args):
        (loop.AI / "FINAL_REPORT.md").write_text("FORGED PASS\n")
        (repo.root / "unauthorized.py").write_text("outside contract")
        if phase == "claude_plan":
            return dict(status="ready")
        if phase == "codex_build":
            return dict(status="implemented")
        return review()

    monkeypatch.setattr(loop, phase, Mock(side_effect=tamper))
    with pytest.raises(SystemExit):
        loop.main()
    assert "verify" not in events
    assert "INCOMPLETE" in (repo.root / ".ai/FINAL_REPORT.md").read_text()


def test_verification_source_mutation_cannot_produce_pass(repo, monkeypatch):
    install_agents(monkeypatch, repo)

    def tamper(*args):
        (loop.AI / "FINAL_REPORT.md").write_text("FORGED PASS\n")
        (repo.root / "new.py").write_text("changed after independent review")
        return True, loop.REPORTS / "verification_round_1.txt"

    monkeypatch.setattr(loop, "run_verification", Mock(side_effect=tamper))
    with pytest.raises(SystemExit):
        loop.main()
    assert "INCOMPLETE" in (repo.root / ".ai/FINAL_REPORT.md").read_text()


@pytest.mark.parametrize("phase", ["startup", "claude_plan", "codex_build", "claude_review", "run_verification"])
@pytest.mark.parametrize("error", [SystemExit(7), KeyboardInterrupt(), RuntimeError("synthetic failure")])
def test_failed_workflow_replaces_forged_pass_and_preserves_diagnostics(repo, monkeypatch, phase, error):
    install_agents(monkeypatch, repo)
    final = repo.root / ".ai/FINAL_REPORT.md"
    final.write_text("STALE PASS\n")
    evidence = loop.REPORTS / "existing_diagnostic.txt"
    evidence.parent.mkdir(parents=True)
    evidence.write_text("valid diagnostics\n")

    def forge(*args):
        final.write_text("FORGED PASS\n")
        raise error

    if phase == "startup":
        monkeypatch.setattr(loop.RunGuards, "start", Mock(side_effect=forge))
    else:
        monkeypatch.setattr(loop, phase, Mock(side_effect=forge))
    with pytest.raises(type(error)):
        loop.main()
    assert final.read_text() == loop.INCOMPLETE_REPORT
    assert evidence.read_text() == "valid diagnostics\n"


@pytest.mark.parametrize("phase,code", [("plan", 3), ("build", 4), ("review", 4), ("verification", 2)])
def test_trusted_escalation_report_survives_failure_and_forgery(repo, monkeypatch, phase, code):
    install_agents(monkeypatch, repo)
    if phase == "plan":
        loop.claude_plan.return_value = {"status": "blocked"}
        loop.claude_plan.side_effect = None
    elif phase == "build":
        loop.codex_build.return_value = {"status": "blocked"}
        loop.codex_build.side_effect = None
    elif phase == "review":
        loop.claude_review.return_value = review("blocked")
        loop.claude_review.side_effect = None
    else:
        repo.state.verification_exit = 1
    original_fail = loop.fail
    trusted = []

    def forge_then_fail(message, exit_code=1):
        final = loop.AI / "FINAL_REPORT.md"
        trusted.append(final.read_text())
        final.write_text("FORGED PASS\n")
        original_fail(message, exit_code)

    monkeypatch.setattr(loop, "fail", forge_then_fail)
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == code
    assert len(trusted) == 1 and "ESCALATION_REQUIRED" in trusted[0]
    assert (loop.AI / "FINAL_REPORT.md").read_text() == trusted[0]


def test_exception_after_generating_pass_invalidates_it(repo, monkeypatch):
    install_agents(monkeypatch, repo)
    original = loop._main

    def late_failure(final):
        original(final)
        assert final.status == "PASS"
        raise RuntimeError("failure after report generation")

    monkeypatch.setattr(loop, "_main", late_failure)
    with pytest.raises(RuntimeError, match="after report generation"):
        loop.main()
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT


@pytest.mark.parametrize("after_write", [False, True])
def test_final_write_error_invalidates_generated_pass(repo, monkeypatch, after_write):
    install_agents(monkeypatch, repo)
    original = loop.save_text
    writes = 0

    def save(path, content):
        nonlocal writes
        if path == loop.AI / "FINAL_REPORT.md":
            writes += 1
        fail_here = path == loop.AI / "FINAL_REPORT.md" and writes == 3
        if fail_here and not after_write:
            raise OSError("synthetic final write failure")
        original(path, content)
        if fail_here:
            raise OSError("synthetic final write failure")

    monkeypatch.setattr(loop, "save_text", save)
    with pytest.raises(OSError, match="synthetic final write failure"):
        loop.main()
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_shutdown_during_final_report_write_invalidates_pass(repo, monkeypatch, lifecycle_signals, number):
    install_agents(monkeypatch, repo)
    original = loop.save_text
    writes = []

    def save(path, content):
        original(path, content)
        if path == loop.AI / "FINAL_REPORT.md":
            writes.append(content)
            if len(writes) == 3:  # Startup, generated PASS, lifecycle final write.
                lifecycle_signals[number](number, None)

    monkeypatch.setattr(loop, "save_text", save)
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 128 + number
    assert "## Status\n\nPASS\n" in writes[2]
    assert writes[-1] == loop.INCOMPLETE_REPORT
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT


@pytest.mark.parametrize("boundary", ["install", "restore"])
@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
def test_signal_handler_failure_cannot_leave_stale_or_generated_pass(repo, monkeypatch, lifecycle_signals, boundary, number):
    events = install_agents(monkeypatch, repo)
    final = loop.AI / "FINAL_REPORT.md"
    final.write_text("STALE PASS\n")
    previous = dict(lifecycle_signals)
    install = loop.signal.signal.side_effect
    failed = False

    def fail_once(signum, handler):
        nonlocal failed
        result = install(signum, handler)
        at_boundary = callable(handler) if boundary == "install" else handler == previous[signum]
        if signum == number and at_boundary and not failed:
            failed = True
            raise RuntimeError("synthetic handler failure")
        return result

    loop.signal.signal.side_effect = fail_once
    with pytest.raises(RuntimeError, match="synthetic handler failure"):
        loop.main()
    assert failed
    assert events == ([] if boundary == "install" else ["plan", "build", "review", "verify"])
    assert final.read_text() == loop.INCOMPLETE_REPORT
    assert lifecycle_signals == previous


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
@pytest.mark.parametrize("phase", ["claude_plan", "codex_build", "claude_review", "run_verification"])
def test_parent_terminal_shutdown_invalidates_report_and_restores_handlers(repo, monkeypatch, lifecycle_signals, number, phase):
    install_agents(monkeypatch, repo)
    previous = dict(lifecycle_signals)

    def terminate(*args):
        (loop.AI / "FINAL_REPORT.md").write_text("FORGED PASS\n")
        lifecycle_signals[number](number, None)

    monkeypatch.setattr(loop, phase, Mock(side_effect=terminate))
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 128 + number
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT
    assert lifecycle_signals == previous


@pytest.mark.parametrize("number", [signal.SIGTERM, signal.SIGHUP])
@pytest.mark.parametrize("phase,command", [
    ("claude_plan", ["claude", "-p"]),
    ("codex_build", ["codex", "exec"]),
    ("claude_review", ["claude", "-p"]),
    ("run_verification", R2E_ARGV),
])
def test_main_shutdown_cleans_active_group_and_invalidates_forgery(repo, monkeypatch, lifecycle_signals, number, phase, command):
    install_agents(monkeypatch, repo)
    previous = dict(lifecycle_signals)
    process, popen, killpg = mock_process(monkeypatch)

    def communicate(**kwargs):
        if "input" in kwargs:
            lifecycle_signals[number](number, None)
        return "shutdown stdout", "shutdown stderr"

    process.communicate.side_effect = communicate

    def execute(*args):
        (loop.AI / "FINAL_REPORT.md").write_text("FORGED PASS\n")
        return repo.process_runner(command, timeout=17)

    monkeypatch.setattr(loop, phase, Mock(side_effect=execute))
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 128 + number
    popen.assert_called_once()
    killpg.assert_called_once_with(process.pid, signal.SIGKILL)
    assert process.communicate.call_count == 2
    assert process.communicate.call_args.kwargs == {"timeout": 5}
    assert (loop.AI / "FINAL_REPORT.md").read_text() == loop.INCOMPLETE_REPORT
    assert lifecycle_signals == previous
    loop.run_full_tests.assert_not_called()


@pytest.mark.parametrize("docs_only,exit_code", [(False, 0), (True, 0), (False, 1)])
def test_legacy_main_preserves_roles_command_and_documentation_skip(repo, monkeypatch, capsys, docs_only, exit_code):
    (repo.root / ".ai/TASK.md").write_text("# Legacy task\n")
    (repo.root / "history.py").unlink()  # Legacy startup requires a clean tree.
    events = install_agents(monkeypatch, repo, edit=not docs_only)
    if docs_only:
        def build(*args):
            events.append("build")
            path = repo.root / "docs/new.md"
            path.parent.mkdir(parents=True)
            path.write_text("# Documentation change\n")
            return {"status": "implemented"}
        monkeypatch.setattr(loop, "codex_build", Mock(side_effect=build))

    command = [loop.sys.executable, "-m", "pytest", "-q"]
    original_run = loop.run.side_effect

    def run(cmd, **kwargs):
        if cmd == command:
            return subprocess.CompletedProcess(cmd, exit_code, "synthetic legacy output", "")
        return original_run(cmd, **kwargs)

    loop.run.side_effect = run
    monkeypatch.setattr(loop, "run_full_tests", Mock(side_effect=repo.legacy_tests))
    if exit_code:
        with pytest.raises(SystemExit) as exc:
            loop.main()
        assert exc.value.code == 2
    else:
        loop.main()
    rounds = 3 if exit_code else 1
    assert events == ["plan"] + ["build", "review", "verify"] * rounds
    assert loop.MAX_ROUNDS == 3
    assert [call.args for call in loop.run_full_tests.call_args_list] == [(n,) for n in range(1, rounds + 1)]
    if docs_only:
        assert not any(call.args[0] == command for call in loop.run.call_args_list)
    else:
        loop.run.assert_any_call(command, timeout=7200)
        assert sum(call.args[0] == command for call in loop.run.call_args_list) == rounds
    report_text = (loop.AI / "FINAL_REPORT.md").read_text()
    status = "ESCALATION_REQUIRED" if exit_code else "PASS"
    assert f"## Status\n\n{status}\n" in report_text
    assert "## Full Regression" in report_text
    assert "TARGETED_VERIFICATION" not in report_text
    assert "Historical Untracked Files" not in report_text
    evidence = (loop.REPORTS / f"full_tests_round_{rounds}.txt").read_text()
    assert ("SKIPPED: documentation-only" if docs_only else "synthetic legacy output") in evidence
    output = capsys.readouterr().out
    if exit_code:
        assert "Full regression: PASS" not in output
        assert loop.codex_build.call_args_list[1].args[2] == loop.REPORTS / "full_tests_round_1.txt"
    else:
        assert "Full regression: PASS" in output


def test_legacy_command_path_is_preserved(monkeypatch):
    expected = (True, Path("legacy_result.txt"))
    legacy = Mock(return_value=expected)
    monkeypatch.setattr(loop, "run_full_tests", legacy)
    assert loop.run_verification(2, None) == expected
    legacy.assert_called_once_with(2)


def test_legacy_startup_still_rejects_historical_untracked_files(repo):
    (repo.root / ".ai/TASK.md").write_text("# Legacy task\n")
    with pytest.raises(SystemExit):
        loop.RunGuards.start()


@pytest.fixture
def external_evidence(tmp_path_factory, repo):
    """Evidence genuinely outside ROOT, including for absolute-link attacks."""
    directory = tmp_path_factory.mktemp("external-report-evidence")
    assert not directory.is_relative_to(repo.root)
    path = directory / "evidence.txt"
    path.write_bytes(b"external immutable evidence\n")
    return path


@pytest.mark.parametrize("writer", ["save_text", "save_json"])
@pytest.mark.parametrize("link_kind", ["absolute", "relative", "dangling", "hardlink"])
def test_all_report_publishers_replace_external_links(repo, external_evidence, writer, link_kind):
    loop.REPORTS.mkdir()
    path = loop.REPORTS / "report.json"
    target = external_evidence.with_name("missing.txt") if link_kind == "dangling" else external_evidence
    if link_kind == "hardlink":
        os.link(target, path)
    else:
        path.symlink_to(os.path.relpath(target, path.parent) if link_kind == "relative" else target)
    before = evidence_metadata(external_evidence)
    if writer == "save_json":
        loop.save_json(path, {"summary": "safe publication"})
        assert json.loads(path.read_text()) == {"summary": "safe publication"}
    else:
        loop.save_text(path, "safe publication\n")
        assert path.read_text() == "safe publication\n"
    assert not path.is_symlink()
    assert path.stat().st_mode & 0o777 == 0o600
    assert external_evidence.read_bytes() == b"external immutable evidence\n"
    after = evidence_metadata(external_evidence)
    # Replacing a hardlink necessarily decrements that inode's link count and
    # updates ctime; it must never rewrite its bytes, mode, identity or mtime.
    assert (after[:3], after[4:6]) == (before[:3], before[4:6])
    if link_kind != "hardlink":
        assert after == before
    else:
        assert after[3] == before[3] - 1
    if link_kind == "dangling":
        assert not target.exists()
    assert sorted(p.name for p in loop.REPORTS.iterdir()) == [path.name]


@pytest.mark.parametrize("directory", ["ROOT", "AI", "REPORTS"])
def test_report_directory_external_symlinks_fail_before_any_write(repo, external_evidence, monkeypatch, directory):
    target_directory = external_evidence.parent
    if directory == "ROOT":
        alias = repo.root.parent / (repo.root.name + "-alias")
        alias.symlink_to(target_directory, target_is_directory=True)
        monkeypatch.setattr(loop, "ROOT", alias)
        monkeypatch.setattr(loop, "AI", alias / ".ai")
        monkeypatch.setattr(loop, "REPORTS", alias / ".ai/reports")
    else:
        path = getattr(loop, directory)
        if path.exists():
            path.rename(path.with_name(path.name + "-original"))
        path.symlink_to(target_directory, target_is_directory=True)
    before = evidence_metadata(external_evidence)
    with pytest.raises(OSError):
        loop.save_text(loop.REPORTS / external_evidence.name, "unsafe")
    assert evidence_metadata(external_evidence) == before
    assert sorted(p.name for p in target_directory.iterdir()) == [external_evidence.name]


@pytest.mark.parametrize("boundary", ["open", "replace"])
@pytest.mark.parametrize("directory", ["AI", "REPORTS"])
def test_report_directory_swaps_cannot_redirect_publication(
        repo, external_evidence, monkeypatch, boundary, directory):
    loop.REPORTS.mkdir()
    path = getattr(loop, directory)
    saved = path.with_name(path.name + "-original")
    target = loop.REPORTS / external_evidence.name
    before = evidence_metadata(external_evidence)
    original_open, original_replace = loop.os.open, loop.os.replace
    swapped = False

    def swap():
        nonlocal swapped
        if not swapped:
            path.rename(saved)
            path.symlink_to(external_evidence.parent, target_is_directory=True)
            swapped = True

    def opening(name, flags, *args, **kwargs):
        if boundary == "open" and name == path.name:
            swap()
        return original_open(name, flags, *args, **kwargs)

    def replacing(source, destination, **kwargs):
        if boundary == "replace":
            swap()
        return original_replace(source, destination, **kwargs)

    monkeypatch.setattr(loop.os, "open", opening)
    monkeypatch.setattr(loop.os, "replace", replacing)
    with pytest.raises(OSError):
        loop.save_text(target, "safe anchored content\n")
    assert swapped
    assert evidence_metadata(external_evidence) == before
    assert external_evidence.read_bytes() == b"external immutable evidence\n"
    assert sorted(p.name for p in external_evidence.parent.iterdir()) == [external_evidence.name]
    assert not list(saved.rglob("*.tmp"))


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_report_exclusive_temporary_collision_never_opens_external_evidence(
        repo, external_evidence, monkeypatch, link_kind):
    loop.REPORTS.mkdir()
    monkeypatch.setattr(loop.secrets, "token_hex", lambda size: "collision")
    path = loop.REPORTS / ".report.collision.tmp"
    if link_kind == "hardlink":
        os.link(external_evidence, path)
    else:
        path.symlink_to(external_evidence)
    before = evidence_metadata(external_evidence)
    with pytest.raises(FileExistsError):
        loop.save_text(loop.REPORTS / "report.txt", "unsafe")
    assert evidence_metadata(external_evidence) == before
    assert external_evidence.read_bytes() == b"external immutable evidence\n"
    assert path.exists() and not (loop.REPORTS / "report.txt").exists()


@pytest.mark.parametrize("after_replace", [False, True])
def test_report_atomic_failure_closes_descriptor_and_cleans_temporary(repo, monkeypatch, after_replace):
    opened = []
    original_open, original_replace = loop.os.open, loop.os.replace

    def opening(name, flags, *args, **kwargs):
        descriptor = original_open(name, flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def replacing(*args, **kwargs):
        if after_replace:
            original_replace(*args, **kwargs)
        raise OSError("synthetic report replacement failure")

    monkeypatch.setattr(loop.os, "open", opening)
    monkeypatch.setattr(loop.os, "replace", replacing)
    with pytest.raises(OSError, match="report replacement failure"):
        loop.save_text(loop.REPORTS / "report.txt", "complete content")
    assert not list(loop.REPORTS.glob("*.tmp"))
    for descriptor in opened:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    if after_replace:
        assert (loop.REPORTS / "report.txt").read_text() == "complete content"


@pytest.mark.parametrize("sink", ["claude", "snapshot", "targeted", "legacy"])
def test_captured_subprocess_output_links_cannot_write_external_evidence(
        repo, external_evidence, sink):
    loop.REPORTS.mkdir()
    names = {
        "claude": ["claude.json", "claude.stderr.txt"],
        "snapshot": ["git_status_round_1.txt", "git_diff_round_1.patch"],
        "targeted": ["verification_round_1.txt"],
        "legacy": ["full_tests_round_1.txt"],
    }[sink]
    for name in names:
        (loop.REPORTS / name).symlink_to(external_evidence)
    before = evidence_metadata(external_evidence)
    if sink == "claude":
        loop.run.side_effect = None
        loop.run.return_value = subprocess.CompletedProcess(
            ["claude"], 0, json.dumps({"structured_output": {"status": "ready"}}), "stderr")
        loop.claude_structured("prompt", loop.PLAN_SCHEMA, loop.REPORTS / names[0])
    elif sink == "snapshot":
        loop.snapshot_git(1)
    elif sink == "targeted":
        assert loop.run_verification(1, loop.parse_execution_contract(task_text()))[0]
    else:
        original_run = loop.run.side_effect
        command = [loop.sys.executable, "-m", "pytest", "-q"]

        def run(cmd, **kwargs):
            if cmd == command:
                return subprocess.CompletedProcess(cmd, 0, "legacy stdout", "legacy stderr")
            return original_run(cmd, **kwargs)

        loop.run.side_effect = run
        assert repo.legacy_tests(1)[0]
    assert evidence_metadata(external_evidence) == before
    assert external_evidence.read_bytes() == b"external immutable evidence\n"
    assert all(not (loop.REPORTS / name).is_symlink() for name in names)


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_codex_cli_output_uses_anonymous_inode_and_safely_publishes_all_sinks(
        repo, external_evidence, monkeypatch, link_kind):
    loop.REPORTS.mkdir()
    names = ["codex_round_1.json", "codex_round_1_stdout.txt", "codex_round_1_stderr.txt", "builder_schema.json"]

    def plant_links():
        for name in names:
            path = loop.REPORTS / name
            path.unlink(missing_ok=True)
            if link_kind == "hardlink":
                os.link(external_evidence, path)
            else:
                path.symlink_to(external_evidence)

    plant_links()  # Stale evidence at startup is unsafe too.
    before = evidence_metadata(external_evidence)
    structured = dict(status="implemented", summary="synthetic", files_changed=[], unresolved_issues=[])
    descriptor_paths = []

    def execute(command, *, prompt, timeout):
        assert command[:3] == ["codex", "exec", "-s"]
        assert command[3] == "workspace-write" and timeout == 7200
        private = Path(command[command.index("-o") + 1])
        assert private.parent == Path(f"/proc/{os.getpid()}/fd")
        assert not private.is_relative_to(repo.root)
        assert private.stat().st_nlink == 0
        assert private.stat().st_mode & 0o777 == 0o600
        descriptor_paths.append(private)
        # Model the implementation agent replanting links while the top-level,
        # unsandboxed Codex CLI still has to write its final -o result.
        plant_links()
        private.write_text(json.dumps(structured))
        assert external_evidence.read_bytes() == b"external immutable evidence\n"
        return subprocess.CompletedProcess(command, 0, "codex stdout", "codex stderr")

    monkeypatch.setattr(loop, "run", Mock(side_effect=execute))
    assert loop.codex_build(1, None, None) == structured
    assert json.loads((loop.REPORTS / names[0]).read_text()) == structured
    assert (loop.REPORTS / names[1]).read_text() == "codex stdout"
    assert (loop.REPORTS / names[2]).read_text() == "codex stderr"
    # The schema is an input, not a post-run output; Codex's replanting cannot
    # induce a later orchestrator write through that link.
    assert all(not (loop.REPORTS / name).is_symlink() for name in names[:3])
    assert len(descriptor_paths) == 1 and not descriptor_paths[0].exists()
    assert external_evidence.read_bytes() == b"external immutable evidence\n"
    after = evidence_metadata(external_evidence)
    assert (after[:3], after[4:6]) == (before[:3], before[4:6])
    if link_kind == "symlink":
        assert after == before
    assert not list(loop.REPORTS.glob("*.tmp"))


def test_codex_cli_output_remains_private_when_agent_redirects_report_directory(
        repo, external_evidence, monkeypatch):
    before = evidence_metadata(external_evidence)
    private_paths = []

    def execute(command, **kwargs):
        private = Path(command[command.index("-o") + 1])
        private_paths.append(private)
        loop.REPORTS.rename(loop.AI / "reports-original")
        loop.REPORTS.symlink_to(external_evidence.parent, target_is_directory=True)
        private.write_text(json.dumps({"status": "implemented", "summary": "private"}))
        return subprocess.CompletedProcess(command, 0, "stdout", "stderr")

    monkeypatch.setattr(loop, "run", Mock(side_effect=execute))
    with pytest.raises(OSError):
        loop.codex_build(1, None, None)
    assert len(private_paths) == 1 and not private_paths[0].exists()
    assert evidence_metadata(external_evidence) == before
    assert sorted(p.name for p in external_evidence.parent.iterdir()) == [external_evidence.name]


@pytest.mark.parametrize("outcome", ["nonzero", "missing", "invalid_json", "exception", "shutdown"])
def test_codex_private_output_cleanup_and_refusal(repo, monkeypatch, outcome):
    private_paths = []

    def execute(command, **kwargs):
        private = Path(command[command.index("-o") + 1])
        private_paths.append(private)
        if outcome == "exception":
            raise OSError("synthetic CLI exception")
        if outcome == "shutdown":
            raise KeyboardInterrupt()
        if outcome != "missing":
            private.write_text("invalid" if outcome == "invalid_json" else json.dumps({"status": "implemented"}))
        return subprocess.CompletedProcess(command, 1 if outcome == "nonzero" else 0, "stdout", "stderr")

    monkeypatch.setattr(loop, "run", Mock(side_effect=execute))
    expected = OSError if outcome == "exception" else KeyboardInterrupt if outcome == "shutdown" else SystemExit
    with pytest.raises(expected):
        loop.codex_build(1, None, None)
    assert len(private_paths) == 1 and not private_paths[0].exists()
    assert not list(loop.REPORTS.glob("*.tmp"))
    if outcome in {"nonzero", "missing", "invalid_json"}:
        assert (loop.REPORTS / "codex_round_1_stdout.txt").read_text() == "stdout"
        assert (loop.REPORTS / "codex_round_1_stderr.txt").read_text() == "stderr"


@pytest.mark.parametrize("facility", ["memfd", "procfs"])
def test_codex_private_output_unavailable_never_falls_back_to_report_path(repo, monkeypatch, facility):
    descriptors = []
    original_create = os.memfd_create

    def create(*args, **kwargs):
        descriptor = original_create(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor

    if facility == "memfd":
        monkeypatch.delattr(loop.os, "memfd_create")
    else:
        monkeypatch.setattr(loop.os, "memfd_create", create)
        monkeypatch.setattr(loop.os, "getpid", lambda: -1)
    with pytest.raises((SystemExit, OSError)):
        loop.codex_build(1, None, None)
    loop.run.assert_not_called()
    for descriptor in descriptors:
        with pytest.raises(OSError):
            os.fstat(descriptor)
    assert (loop.REPORTS / "codex_round_1.json").read_text() == ""


@pytest.mark.parametrize("stdout,expected", [
    ("1 passed in 0.01s\n", 1),
    ("================= 12 passed in 1.02s =================\n", 12),
    ("\x1b[32m2 passed\x1b[0m, \x1b[33m3 skipped\x1b[0m in 0.03s\n", 2),
    ("3 passed, 2 deselected, 1 warning in 60.00s (0:01:00)\n", 3),
    ("1 passed, 2 subtests passed in 0.02s\n", 1),
    ("1 skipped in 0.01s\n", 0),
    ("5 deselected in 0.01s\n", 0),
    ("1 xfailed, 2 xpassed in 0.01s\n", 0),
    ("0 passed, 1 skipped in 0.01s\n", 0),
    ("2 subtests passed in 0.01s\n", 0),
    ("", None), ("s [100%]\n", None), (". [100%]\n", None),
    ("no tests ran in 0.01s\n", None), ("1 test collected in 0.01s\n", None),
    ("test output says 12 passed in 0.01s\n", None),
    ("12 passed in 0.01s\n1 skipped in 0.01s\n", 0),
    ("1 passed in 0.01s\ntrailing unrecognized evidence\n", None),
    ("1 passed, 1 failed in 0.01s\n", None),
    ("1 passed, 1 error in 0.01s\n", None),
    ("1 passed, 2 passed in 0.01s\n", None),
    ("1 passed, 1 unknown in 0.01s\n", None),
])
def test_targeted_pass_evidence_is_explicit_final_and_positive(stdout, expected):
    assert loop.targeted_pass_count(stdout) == expected


@pytest.mark.parametrize("stdout,exit_code,expected", [
    ("1 passed in 0.01s\n", 0, True),
    ("1 passed, 1 skipped in 0.01s\n", 0, True),
    ("1 passed in 0.01s\n", 1, False),
    ("1 skipped in 0.01s\n", 0, False),
    ("3 deselected in 0.01s\n", 0, False),
    ("1 xfailed in 0.01s\n", 0, False),
    ("no tests ran in 0.01s\n", 0, False),
    ("", 0, False),
    (". [100%]\n", 0, False),
])
def test_targeted_result_requires_exit_zero_and_positive_pass_evidence(
        repo, capsys, stdout, exit_code, expected):
    repo.state.verification_stdout = stdout
    repo.state.verification_exit = exit_code
    contract = loop.parse_execution_contract(task_text())
    passed, path = loop.run_verification(1, contract)
    assert passed is expected
    loop.run.assert_called_once_with(R2E_ARGV, timeout=7200)
    evidence = path.read_text()
    assert f"EXIT_CODE: {exit_code}" in evidence
    assert f"RESULT: {'PASS' if expected else 'FAIL'}" in evidence
    assert f"ARGV_JSON: {json.dumps(R2E_ARGV)}" in evidence
    assert f"STDOUT\n{stdout}" in evidence
    assert f"TARGETED_VERIFICATION: {'PASS' if expected else 'FAIL'}" in capsys.readouterr().out
    loop.run_full_tests.assert_not_called()


def test_targeted_quiet_argv_is_preserved_even_when_pass_evidence_is_suppressed(repo):
    argv = ["pytest", "-qq", R2E_ARGV[-1]]
    contract = replace(loop.parse_execution_contract(task_text()), verification_argv=tuple(argv))
    loop.run.side_effect = None
    loop.run.return_value = subprocess.CompletedProcess(argv, 0, ". [100%]\n", "")
    assert not loop.run_verification(1, contract)[0]
    loop.run.assert_called_once_with(argv, timeout=7200)
    loop.run_full_tests.assert_not_called()


@pytest.mark.parametrize("stdout", ["1 skipped in 0.01s\n", "3 deselected in 0.01s\n", ""])
def test_empty_targeted_execution_cannot_publish_final_pass(repo, monkeypatch, stdout):
    events = install_agents(monkeypatch, repo)
    repo.state.verification_stdout = stdout
    with pytest.raises(SystemExit) as exc:
        loop.main()
    assert exc.value.code == 2
    assert events.count("verify") == events.count("build") == loop.MAX_ROUNDS == 3
    assert loop.codex_build.call_args_list[1].args[2] == loop.REPORTS / "verification_round_1.txt"
    report = (loop.AI / "FINAL_REPORT.md").read_text()
    assert "## Status\n\nESCALATION_REQUIRED\n" in report
    assert "## Status\n\nPASS\n" not in report
    loop.run_full_tests.assert_not_called()
