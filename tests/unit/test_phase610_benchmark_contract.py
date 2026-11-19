"""Lightweight harness checks; no detailed physical/counterfactual execution."""
from tests.unit._availability import missing_commit
from pathlib import Path
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import benchmark_phase610 as bench
from benchmark_phase610_fixtures import build_fixture, prepare_physical, boundary_overrides


@pytest.mark.parametrize("case,count,cadence", [("B0", 1, 3600), ("B1", 1, 3600), ("B2", 24, 3600), ("B3", 96, 900)])
def test_fixture_timeline_and_policy(case, count, cadence):
    f = build_fixture(case)
    assert len(f["weather"].series) == count
    assert f["configuration"]["simulation_timestep_seconds"] == cadence
    assert f["weather"].dataset["series_resolution_seconds"] == cadence
    assert f["configuration"]["shading_configuration"]["electrical_shading_configuration"]["scientific_options"]["string_sample_count"] == 101
    assert len(f["design"]["strings"]) == 2
    assert len(f["design"]["mppt_instances"]) == 1
    assert f["configuration"]["numerical_options"]["module_overrides"]["module_quality_loss_fraction"] == 0
    if case in ("B2", "B3"):
        assert f["weather"].series.index[0].isoformat() == "2026-03-21T00:00:00+07:00"
        assert f["weather"].dataset["end_time"] == "2026-03-22T00:00:00+07:00"
        assert f["weather"].dataset["native_resolution_seconds"] == cadence
        assert (f["weather"].series.dni_w_m2 == 0).all()
        assert f["weather"].series.ghi_w_m2.equals(f["weather"].series.dhi_w_m2)


def test_b1_new_reference_not_long_history():
    f = build_fixture("B1")
    assert f["weather"].series.index[0].isoformat() == "2026-03-21T10:00:00+07:00"
    assert f["weather"].series.ghi_w_m2.iloc[0] == 400
    args = prepare_physical(f)
    assert len(args["module_inputs"]) == 4


def test_source_guard_accepts_only_explicit_files(monkeypatch):
    if reason := missing_commit('phase-6.9-validated'):
        pytest.skip(reason)
    original = bench.git
    def fake(*args):
        if args[:2] == ("diff", "--name-only"):
            return "engine/simulation/detailed_backend.py"
        return original(*args)
    monkeypatch.setattr(bench, "git", fake)
    with pytest.raises(ValueError, match="scientific source guard blocked"):
        bench.source_guard()


@pytest.fixture
def controlled_stage1_git(monkeypatch):
    """Accepted checkpoint Git responses, restored automatically after each test."""
    if reason := missing_commit(bench.CHECKPOINT):
        pytest.skip(reason)
    stage1_files = {
        "tools/benchmark_phase610.py",
        "tools/benchmark_phase610_fixtures.py",
        "tests/unit/test_phase610_benchmark_contract.py",
    }
    assert bench.PERMITTED == stage1_files
    checkpoint_tree = bench.git("rev-parse", bench.CHECKPOINT + "^{tree}")
    responses = {
        ("rev-parse", "phase-6.9-validated^{}"): bench.BASE_COMMIT,
        ("rev-parse", "phase-6.9-validated^{tree}"): bench.BASE_TREE,
        ("rev-parse", "HEAD"): bench.CHECKPOINT,
        ("rev-parse", "HEAD^{tree}"): checkpoint_tree,
        ("branch", "--show-current"): "phase-6.10-performance-annualization",
        ("diff", "--name-only", "phase-6.9-validated", "--"): "\n".join(sorted(stage1_files)),
        ("ls-files", "--others", "--exclude-standard"): "",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr(bench, "git", lambda *args: responses[args])
    return stage1_files, checkpoint_tree, responses


def test_source_guard_current_changes_permitted(controlled_stage1_git):
    # Exercise the real decision logic independently of the active candidate.
    stage1_files, checkpoint_tree, responses = controlled_stage1_git
    result = bench.source_guard()
    assert set(result["changed_files"]) == stage1_files
    assert result["head_commit"] == bench.CHECKPOINT
    assert result["head_tree"] == checkpoint_tree
    assert result["validated_commit"] == bench.BASE_COMMIT
    assert result["validated_tree"] == bench.BASE_TREE
    assert result["dirty"] is False
    assert len(result["harness_content_sha256"]) == 64

    # Permitted infrastructure edits stay accepted but must remain visibly dirty.
    responses[("status", "--porcelain")] = " M tools/benchmark_phase610.py"
    dirty = bench.source_guard()
    assert dirty["dirty"] is True
    assert dirty["status"] == responses[("status", "--porcelain")]

    # Neither tracked candidate kernels nor new untracked scientific files are
    # permissible under the Stage 1 guard. No guard implementation is mocked.
    for forbidden in (
        "shading/electrical/substring_reference.py",
        "shading/electrical/module_iv.py",
        "shading/electrical/module_series_adapter.py",
        "shading/electrical/dc_attribution.py",
    ):
        responses[("diff", "--name-only", "phase-6.9-validated", "--")] = "\n".join(sorted(stage1_files | {forbidden}))
        responses[("status", "--porcelain")] = " M " + forbidden
        with pytest.raises(ValueError, match="scientific source guard blocked") as rejected:
            bench.source_guard()
        assert forbidden in str(rejected.value)
    responses[("diff", "--name-only", "phase-6.9-validated", "--")] = "\n".join(sorted(stage1_files))
    forbidden = "shading/electrical/unreviewed_model.py"
    responses[("ls-files", "--others", "--exclude-standard")] = forbidden
    responses[("status", "--porcelain")] = "?? " + forbidden
    with pytest.raises(ValueError, match="scientific source guard blocked") as rejected:
        bench.source_guard()
    assert forbidden in str(rejected.value)


def test_external_wrappers_forward_and_restore_on_exception(monkeypatch):
    import pvlib
    import shading.electrical.substring_reference as branch
    import shading.electrical.dc_attribution as dc
    marker = object()
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        if kwargs.get("fail"):
            raise ValueError("original failure")
        return marker
    monkeypatch.setattr(pvlib.pvsystem, "v_from_i", original)
    monkeypatch.setattr(branch, "_branch_current_at_voltage", original)
    monkeypatch.setattr(dc, "_branch_current_at_voltage", original)
    counter = bench.Counters()
    with pytest.raises(ValueError, match="original failure"):
        with counter.installed():
            assert pvlib.pvsystem.v_from_i(7, flag=True) is marker
            assert branch._branch_current_at_voltage(3) is marker
            assert dc._branch_current_at_voltage(4) is marker
            pvlib.pvsystem.v_from_i(9, fail=True)
    assert pvlib.pvsystem.v_from_i is original
    assert branch._branch_current_at_voltage is original
    assert dc._branch_current_at_voltage is original
    assert calls == [((7,), {"flag": True}), ((3,), {}), ((4,), {}), ((9,), {"fail": True})]
    assert counter.record()["pvlib_v_from_i"] == 2
    assert counter.record()["branch_current_inversion"] == 2
    assert counter.record()["mppt_base_knot_count"] is None


def test_isc_scope_restores_and_counts_only_nested_states(monkeypatch):
    import shading.electrical.string_iv as string
    monkeypatch.setattr(string, "_string_state_at_current", lambda *a, **k: (0., []))
    def isc(*args, **kwargs):
        string._string_state_at_current([], 0.)
        return 0.
    monkeypatch.setattr(string, "_solve_string_isc", isc)
    counter = bench.Counters()
    with counter.installed():
        string._solve_string_isc([])
        string._string_state_at_current([], 0.)
    assert counter.isc_depth == 0
    assert counter.record()["string_isc_solves"] == 1
    assert counter.record()["string_states_during_isc"] == 1
    assert counter.record()["string_state_evaluations"] == 2


def test_boundary_overrides_restore():
    import engine.simulation.detailed_backend as backend
    original = backend.solve_pvsyst_module_thermal_coupling
    with boundary_overrides("B0"):
        assert backend.solve_pvsyst_module_thermal_coupling is not original
    assert backend.solve_pvsyst_module_thermal_coupling is original


def test_exact_parity_and_statistics_are_mode_separated():
    assert bench.parity({"physical": [1.]}, {"physical": [1.]})["status"] == "passed"
    assert bench.parity({"physical": [1.]}, {"physical": [1. + 1e-12]})["status"] == "failed"
    rows = [{"case": "B1", "path": "A", "status": "completed", "mode": mode,
             "timing": {"execution_wall_seconds": value}} for mode, value in
            [("timing", 2.), ("timing", 4.), ("counters", 100.)]]
    assert bench.statistics_for(rows)["B1-A"] == {"samples_seconds": [2., 4.], "median_seconds": 3., "min_seconds": 2., "max_seconds": 4.}


def test_primary_scope_and_linux_rss():
    assert "physical_execution" in bench.measurement_scope("B")["excludes"]
    assert "persistence" in bench.measurement_scope("C")["includes"]
    if sys.platform.startswith("linux"):
        assert bench.rss_bytes() == int(bench.resource.getrusage(bench.resource.RUSAGE_SELF).ru_maxrss * 1024)


def _sealed_reference(tmp_path):
    if reason := missing_commit(bench.CHECKPOINT):
        pytest.skip(reason)
    root = tmp_path / "reference"
    root.mkdir()
    env = {"packages": {"numpy": "frozen"}, "source": {"head_commit": bench.CHECKPOINT,
        "head_tree": bench.git("rev-parse", bench.CHECKPOINT + "^{tree}")}}
    manifest = {"environment": env, "diagnostics": "off", "cases": ["B1"]}
    fixture = {"sha256": "f" * 64, "numerical_policy": {"string_sample_count": 101}}
    snapshot = {"physical": {"power": 1.0000000000001}}
    bench.write_json(root / "scientific.json", snapshot)
    records = [{"case": "B1", "path": "A", "status": "completed", "fixture": fixture,
        "scientific_snapshot_sha256": bench.digest(snapshot), "scientific_hashes": {}}]
    seal = bench.seal_baseline(root, manifest, records)
    return root, seal, env, fixture


def test_baseline_seal_rejects_overwrite_and_tamper(tmp_path):
    root, seal, env, _ = _sealed_reference(tmp_path)
    pinned = hashlib.sha256((root / "baseline-seal.json").read_bytes()).hexdigest()
    assert bench.load_baseline(root, pinned) == seal
    with pytest.raises(FileExistsError):
        bench.seal_baseline(root, {"environment": env, "diagnostics": "off", "cases": []}, [])
    bench.write_json(root / "scientific.json", {"physical": {"power": 0}})
    with pytest.raises(ValueError, match="integrity"):
        bench.load_baseline(root, pinned)


def test_pinned_seal_and_added_files_rejected(tmp_path):
    root, _, _, _ = _sealed_reference(tmp_path)
    with pytest.raises(ValueError, match="seal hash"):
        bench.load_baseline(root, "0" * 64)
    (root / "extra").write_text("unexpected")
    with pytest.raises(ValueError, match="integrity"):
        bench.load_baseline(root)


def test_comparison_separates_source_but_rejects_environment_fixture_policy(tmp_path):
    _, seal, env, fixture = _sealed_reference(tmp_path)
    candidate = {**env, "source": {"head_commit": "candidate", "production_diff_sha256": "patch"}}
    bench.comparison_compatibility(seal, candidate, fixture, "B1", "A", "off")
    with pytest.raises(ValueError, match="environment/dependency"):
        bench.comparison_compatibility(seal, {**candidate, "packages": {"numpy": "drift"}}, fixture, "B1", "A", "off")
    for altered in ({**fixture, "sha256": "changed"}, {**fixture, "numerical_policy": {"string_sample_count": 102}}):
        with pytest.raises(ValueError, match="fixture/numerical policy"):
            bench.comparison_compatibility(seal, candidate, altered, "B1", "A", "off")
    with pytest.raises(ValueError, match="diagnostics"):
        bench.comparison_compatibility(seal, candidate, fixture, "B1", "A", "on")


def test_benchmark_semantics_drift_rejected(tmp_path):
    _, seal, env, fixture = _sealed_reference(tmp_path)
    seal["benchmark_identity"]["snapshot_schema"] = "different"
    with pytest.raises(ValueError, match="semantics"):
        bench.comparison_compatibility(seal, env, fixture, "B1", "A", "off")


def test_candidate_patch_scope_and_hash_are_exact(monkeypatch, tmp_path):
    _, seal, _, _ = _sealed_reference(tmp_path)
    original = bench.git
    patch = b"reviewed production diff\n"
    untracked = ""
    def fake(*args):
        if args[:2] == ("diff", "--name-only"):
            return "shading/electrical/substring_reference.py"
        if args == ("ls-files", "--others", "--exclude-standard"):
            return untracked
        return original(*args)
    monkeypatch.setattr(bench, "git", fake)
    monkeypatch.setattr(bench, "production_patch", lambda base: patch)
    review = {"baseline_commit": bench.CHECKPOINT, "production_files": ["shading/electrical/substring_reference.py"],
        "production_diff_sha256": hashlib.sha256(patch).hexdigest()}
    result = bench.candidate_source_guard(seal, review)
    assert result["production_changed_files"] == review["production_files"]
    for changed in ({**review, "production_files": []}, {**review, "production_diff_sha256": "0" * 64}):
        with pytest.raises(ValueError, match="scope/hash"):
            bench.candidate_source_guard(seal, changed)
    untracked = "unexpected-candidate.py"
    with pytest.raises(ValueError, match="untracked candidate files"):
        bench.candidate_source_guard(seal, review)
    with pytest.raises(ValueError, match="scientific source guard blocked"):
        bench.source_guard()


def test_endpoint_observers_forward_without_recalculating_and_restore(monkeypatch):
    import shading.electrical.substring_reference as branch
    import shading.electrical.dc_attribution as dc
    calls = []
    def ceiling(b, states):
        calls.append("ceiling")
        return 5.0
    def voltage(b, states, *, current_a):
        calls.append(current_a)
        if current_a == 3:
            raise ValueError("original failure")
        return 10 - current_a
    for module in (branch, dc):
        monkeypatch.setattr(module, "_branch_current_ceiling", ceiling)
        monkeypatch.setattr(module, "evaluate_series_branch_voltage", voltage)
    b, states = {}, {}
    counter = bench.Counters()
    with pytest.raises(ValueError, match="original failure"):
        with counter.installed():
            assert branch._branch_current_ceiling(b, states) == 5.0
            assert dc.evaluate_series_branch_voltage(b, states, current_a=0.0) == 10
            assert branch.evaluate_series_branch_voltage(b, states, current_a=5.0) == 5
            branch.evaluate_series_branch_voltage(b, states, current_a=3)
    assert calls == ["ceiling", 0.0, 5.0, 3]
    for module in (branch, dc):
        assert module._branch_current_ceiling is ceiling
        assert module.evaluate_series_branch_voltage is voltage
    assert counter.record()["branch_current_ceiling_evaluations"] == 1
    assert counter.record()["branch_open_voltage_evaluations"] == 1
    assert counter.record()["branch_endpoint_voltage_evaluations"] == 1


def test_unobserved_ceiling_is_null_not_inferred(monkeypatch):
    import shading.electrical.substring_reference as branch
    monkeypatch.setattr(branch, "evaluate_series_branch_voltage", lambda *a, **k: 0.0)
    counter = bench.Counters()
    with counter.installed():
        branch.evaluate_series_branch_voltage({}, {}, current_a=2.0)
    assert counter.record()["branch_endpoint_voltage_evaluations"] is None


def test_reference_controller_refuses_existing_directory(tmp_path, controlled_stage1_git):
    assert bench.source_guard()["head_commit"] == bench.CHECKPOINT
    root = tmp_path / "existing"
    root.mkdir()
    marker = root / "manifest.json"
    marker.write_text("do not overwrite")
    with pytest.raises(FileExistsError, match="references/results are never overwritten"):
        bench.controller(SimpleNamespace(command="prepare", output=root, seal_baseline=False))
    assert marker.read_text() == "do not overwrite"


def test_exact_parity_distinguishes_missing_null_and_numeric_types():
    assert bench.parity({}, {"missing": None})["status"] == "failed"
    assert bench.parity({"power": 1.0}, {"power": 1})["status"] == "failed"
    assert bench.parity({"power": 0.0}, {"power": -0.0})["status"] == "failed"


def test_candidate_untracked_and_wrong_baseline_rejected(monkeypatch, tmp_path):
    _, seal, _, _ = _sealed_reference(tmp_path)
    review = {"baseline_commit": "wrong", "production_files": [], "production_diff_sha256": "0" * 64}
    with pytest.raises(ValueError, match="baseline identity"):
        bench.candidate_source_guard(seal, review)
    review["baseline_commit"] = bench.CHECKPOINT
    original = bench.git
    def fake(*args):
        return "shading/electrical/unreviewed.py" if args[0] == "ls-files" else original(*args)
    monkeypatch.setattr(bench, "git", fake)
    with pytest.raises(ValueError, match="untracked"):
        bench.candidate_source_guard(seal, review)
