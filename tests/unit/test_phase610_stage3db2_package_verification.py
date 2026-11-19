"""B2 persisted-package streaming, binding and resource ownership regressions."""
from contextlib import contextmanager
import json
from pathlib import Path
import shutil
import tempfile

import pytest
from jsonschema import ValidationError

from engine.simulation import attribution_json_stream as streaming
from engine.simulation import detailed_attribution, attribution_energy
from engine.simulation.artifacts import (
    _build_run_package_manifest, canonical_object_sha256, verify_run_package,
)
from tests.unit.test_phase610_stage3a_interval_contract import dark_canonical_fixture


@pytest.fixture(scope='module', params=[False, True])
def persisted_package(tmp_path_factory, request):
    from engine.simulation.canonical import run_canonical_simulation
    fixture = dark_canonical_fixture()
    fixture['configuration']['output_configuration']['detailed_diagnostics'] = request.param
    result = run_canonical_simulation(fixture['project'], fixture['configuration'],
        revision_store=fixture['store'], output_directory=tmp_path_factory.mktemp('b2'),
        engine_version='b2-test', simulation_run_id='b2-verification')
    assert result.standard_timeseries is not None
    yield result.artifact_directory
    result.detailed_backend_result.close()
    result.detailed_attribution_result.close()


@pytest.fixture
def package(tmp_path, persisted_package):
    directory = tmp_path / 'package'
    shutil.copytree(persisted_package, directory)
    return directory


def refresh(directory):
    manifest = _build_run_package_manifest(directory, simulation_run_id='b2-verification')
    (directory / 'run-package-manifest.json').write_text(json.dumps(manifest))


def test_manifest_parity_no_full_read_and_lifetime(package, tmp_path, monkeypatch):
    expected = json.loads((package / 'run-package-manifest.json').read_text())
    original_reader = streaming.open_persisted_attribution
    original_read = Path.read_text
    captured = []
    stages = []

    @contextmanager
    def tracked(path):
        with original_reader(path) as pair:
            captured.append(pair[1]['intervals'])
            yield pair

    def read(path, *args, **kwargs):
        assert path != package / 'detailed-dc-attribution.json', 'full attribution read'
        return original_read(path, *args, **kwargs)

    def wrap(module, name):
        original = getattr(module, name)
        def check(*args, **kwargs):
            store = kwargs['_payload']['intervals']
            assert store is captured[0] and not store.closed
            assert store.directory.exists()
            stages.append(name)
            return original(*args, **kwargs)
        monkeypatch.setattr(module, name, check)

    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(streaming, 'open_persisted_attribution', tracked)
    monkeypatch.setattr(Path, 'read_text', read)
    wrap(detailed_attribution, 'verify_attribution_sources')
    wrap(detailed_attribution, 'verify_attribution_diagnostics')
    wrap(attribution_energy, 'verify_energy_summary')
    assert verify_run_package(package) == expected
    assert len(captured) == 1
    assert stages == ['verify_attribution_sources'] + (
        ['verify_attribution_diagnostics'] if (package / 'detailed-dc-attribution-diagnostics.json').exists() else []
    ) + ['verify_energy_summary']
    assert captured[0].closed and not captured[0].directory.exists()
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


@pytest.mark.parametrize('stage', ['verify_attribution_sources', 'verify_attribution_diagnostics', 'verify_energy_summary'])
def test_consumer_failure_closes_store(package, tmp_path, monkeypatch, stage):
    if stage == 'verify_attribution_diagnostics' and not (package / 'detailed-dc-attribution-diagnostics.json').exists():
        pytest.skip('diagnostics disabled')
    captured = []
    original = streaming.open_persisted_attribution
    @contextmanager
    def tracked(path):
        with original(path) as pair:
            captured.append(pair[1]['intervals'])
            yield pair
    def fail(*args, **kwargs):
        assert kwargs['_payload']['intervals'] is captured[0]
        assert not captured[0].closed
        raise ValueError('injected dependent validation failure')
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    monkeypatch.setattr(streaming, 'open_persisted_attribution', tracked)
    module = attribution_energy if stage == 'verify_energy_summary' else detailed_attribution
    monkeypatch.setattr(module, stage, fail)
    with pytest.raises(ValueError, match='injected dependent validation failure'):
        verify_run_package(package)
    assert captured[0].closed and not captured[0].directory.exists()
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


@pytest.mark.parametrize('artifact', [
    'detailed-dc-attribution.json', 'detailed-execution-context.json', 'simulation-run.json',
    'detailed-selected-mppt.json', 'detailed-dc-attribution-energy-summary.json',
    'detailed-dc-attribution-diagnostics.json', 'detailed-attribution-diagnostic-index.json',
    'detailed-attribution-diagnostic-chunks', 'detailed-electrical-intervals',
    'run-package-manifest.json',
])
def test_file_corruption(package, artifact):
    path = package / artifact
    if not path.exists():
        pytest.skip('optional artifact absent')
    if path.is_dir():
        path = next(p for p in sorted(path.rglob('*')) if p.is_file())
    path.write_bytes(path.read_bytes() + b' ')
    if artifact == 'run-package-manifest.json':
        record = json.loads(path.read_text())
        record['manifest_payload_sha256'] = '0' * 64
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='hash mismatch'):
        verify_run_package(package)


@pytest.mark.parametrize('damage', ['hash', 'model', 'truncated', 'coverage', 'energy', 'diagnostics'])
def test_scientific_corruption_with_consistent_file_manifest(package, tmp_path, monkeypatch, damage):
    name = {'energy': 'detailed-dc-attribution-energy-summary.json',
            'diagnostics': 'detailed-dc-attribution-diagnostics.json'}.get(damage, 'detailed-dc-attribution.json')
    path = package / name
    if not path.exists():
        pytest.skip('diagnostics disabled')
    record = json.loads(path.read_text())
    if damage == 'hash': record['attribution_result_sha256'] = '0' * 64
    elif damage == 'model': record['payload']['attribution_model_id'] = 'invalid'
    elif damage == 'coverage': record['payload']['intervals'].pop()
    elif damage == 'energy': record['energy_summary_sha256'] = '0' * 64
    elif damage == 'diagnostics': record['attribution_result_sha256'] = '0' * 64
    path.write_text(json.dumps(record))
    if damage == 'truncated': path.write_bytes(path.read_bytes()[:-1])
    refresh(package)
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    expected_error = ValidationError if damage == 'model' else ValueError
    with pytest.raises(expected_error):
        verify_run_package(package)
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


def test_rehashed_attribution_rejects_physical_source_forgery(package, tmp_path, monkeypatch):
    path = package / 'detailed-dc-attribution.json'
    record = json.loads(path.read_text())
    record['payload']['source_numerical_result_sha256'] = '0' * 64
    record['attribution_result_sha256'] = canonical_object_sha256(record['payload'])
    path.write_text(json.dumps(record))
    context_path = package / 'detailed-execution-context.json'
    context = json.loads(context_path.read_text())
    context['dc_attribution_reference']['attribution_result_sha256'] = record['attribution_result_sha256']
    context_path.write_text(json.dumps(context))
    refresh(package)
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    with pytest.raises(ValueError, match='attribution scientific/physical source identity mismatch'):
        verify_run_package(package)
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


def test_non_detailed_package_does_not_open_attribution(tmp_path, monkeypatch):
    (tmp_path / 'simulation-run.json').write_text(json.dumps({'simulation_run_id': 'b2-verification'}))
    refresh(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('non-detailed package opened attribution')
    monkeypatch.setattr(streaming, 'open_persisted_attribution', forbidden)
    expected = json.loads((tmp_path / 'run-package-manifest.json').read_text())
    assert verify_run_package(tmp_path) == expected


def test_legacy_materialized_reader_returns_identical_manifest(package, monkeypatch):
    # Compare accepted v1 records through the old decoding/validation path.
    # Only substitute the reader; all cross-artifact checks still run.
    before = {p: p.read_bytes() for p in package.rglob('*') if p.is_file()}
    actual = verify_run_package(package)
    @contextmanager
    def legacy(path):
        record = json.loads(path.read_text())
        source = detailed_attribution.DetailedDCAttributionResult.freeze(record['payload'], _decoded=True)
        assert source.attribution_result_sha256 == record['attribution_result_sha256']
        yield source, record['payload']
    monkeypatch.setattr(streaming, 'open_persisted_attribution', legacy)
    assert verify_run_package(package) == actual
    assert {p: p.read_bytes() for p in package.rglob('*') if p.is_file()} == before


def test_detailed_without_attribution_or_energy(package, monkeypatch):
    context_path = package / 'detailed-execution-context.json'
    context = json.loads(context_path.read_text())
    context.pop('dc_attribution_reference')
    context.pop('dc_attribution_energy_reference')
    context_path.write_text(json.dumps(context))
    for name in ('detailed-dc-attribution.json', 'detailed-dc-attribution-energy-summary.json',
                 'detailed-dc-attribution-diagnostics.json', 'detailed-attribution-diagnostic-index.json',
                 'detailed-attribution-diagnostic-chunks'):
        path = package / name
        if path.is_dir(): shutil.rmtree(path)
        elif path.exists(): path.unlink()
    refresh(package)
    def forbidden(*args, **kwargs):
        pytest.fail('package without attribution opened reader')
    monkeypatch.setattr(streaming, 'open_persisted_attribution', forbidden)
    assert verify_run_package(package) == json.loads((package / 'run-package-manifest.json').read_text())


def test_external_pre_b2_package():
    import os
    path = os.environ.get('RAWIBUMI_B2_REFERENCE_PACKAGE')
    if not path:
        pytest.skip('set RAWIBUMI_B2_REFERENCE_PACKAGE to an accepted P96 package')
    directory = Path(path)
    expected = json.loads((directory / 'run-package-manifest.json').read_text())
    assert verify_run_package(directory) == expected


def test_attribution_without_energy(package):
    path = package / 'detailed-execution-context.json'
    context = json.loads(path.read_text())
    context.pop('dc_attribution_energy_reference')
    path.write_text(json.dumps(context))
    (package / 'detailed-dc-attribution-energy-summary.json').unlink()
    refresh(package)
    assert verify_run_package(package) == json.loads((package / 'run-package-manifest.json').read_text())


@pytest.mark.parametrize('damage', ['duplicate', 'curve'])
def test_legacy_diagnostic_scientific_checks(package, damage):
    path = package / 'detailed-dc-attribution-diagnostics.json'
    if not path.exists():
        pytest.skip('diagnostics disabled')
    record = json.loads(path.read_text())
    if damage == 'duplicate':
        record['curves'].append(record['curves'][0])
    else:
        row = next((row for row in record['curves'] if row['curves']), record['curves'][0])
        # Dark intervals legitimately have no counterfactual curves. Adding
        # one then corrupts the expected empty curve-hash mapping as well.
        key = next(iter(row['curves']), 'U')
        row['curves'][key] = {'tampered': True}
    path.write_text(json.dumps(record))
    # Exercise the still-supported non-indexed diagnostics contract so that
    # scientific checks, rather than index-to-file checks, detect the forgery.
    (package / 'detailed-attribution-diagnostic-index.json').unlink()
    shutil.rmtree(package / 'detailed-attribution-diagnostic-chunks')
    refresh(package)
    message = ('duplicate attribution diagnostic scope' if damage == 'duplicate'
               else 'attribution counterfactual diagnostic curve hash mismatch')
    with pytest.raises(ValueError, match=message):
        verify_run_package(package)
