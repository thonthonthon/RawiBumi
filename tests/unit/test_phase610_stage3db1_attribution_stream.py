"""B1 parity, framing, ownership and incremental source consumption contracts."""
import json
from pathlib import Path
import tempfile

import pandas as pd
import pytest
from jsonschema import ValidationError

from engine.simulation.artifacts import ElectricalIntervalStore
from engine.simulation.attribution_energy import (
    DetailedDCAttributionEnergySummary, _from_source, aggregate_persisted_attribution,
    verify_energy_summary)
from engine.simulation.attribution_json_stream import open_persisted_attribution
from engine.simulation.detailed_attribution import DetailedDCAttributionResult
from tests.unit.test_phase69b_attribution_energy import _source, _powers


def legacy(path):
    """Independent pre-B1 materializing path, also used by the measurement harness."""
    record = json.loads(path.read_text(encoding='utf-8'))
    source = DetailedDCAttributionResult.freeze(record['payload'], _decoded=True)
    assert source.attribution_result_sha256 == record['attribution_result_sha256']
    return DetailedDCAttributionEnergySummary.freeze(
        _from_source(source, record['payload']), _decoded=True)


def specs(kind, count=4):
    missing = _powers(); missing['N'] = None
    recovery = _powers(); recovery['U'] = 80.
    choices = {'dark': [None], 'daylight': [_powers()],
               'mixed': [None, _powers()], 'partial': [_powers(), missing, None],
               'unavailable': [missing], 'recovery': [_powers(), recovery]}
    start = pd.Timestamp('2026-01-31T23:00:00+07:00')
    return [((start + pd.Timedelta(hours=i)).isoformat(), 3600,
             choices[kind][i % len(choices[kind])], ['raison_é\\"\n']) for i in range(count)]


@pytest.mark.parametrize('kind', ['dark', 'daylight', 'mixed', 'partial', 'unavailable', 'recovery'])
@pytest.mark.parametrize('chunk_size', [1, 3])
def test_exact_legacy_parity(tmp_path, kind, chunk_size):
    path = _source(tmp_path, specs(kind, 28))
    expected = legacy(path)
    with open_persisted_attribution(path, chunk_size=chunk_size) as (source, payload):
        actual = DetailedDCAttributionEnergySummary.freeze(_from_source(source, payload), _decoded=True)
        assert actual == expected
        assert actual.record() == expected.record()
        store = payload['intervals']
        directory = store.directory
    assert store.closed and not directory.exists()
    assert aggregate_persisted_attribution(path) == expected
    verify_energy_summary(actual, path)


@pytest.mark.parametrize('read_size', [1, 2, 3, 7, 65536])
@pytest.mark.parametrize('indent,ascii_strings', [(None, True), (2, False)])
def test_format_and_token_boundaries(tmp_path, read_size, indent, ascii_strings):
    path = _source(tmp_path, specs('partial'))
    expected = legacy(path)
    record = json.loads(path.read_text())
    # Reverse every object, putting the payload before the embedded hash and
    # moving intervals relative to the header; Unicode appears in reason codes.
    def reverse(value):
        if isinstance(value, dict):
            return {k: reverse(v) for k, v in reversed(list(value.items()))}
        if isinstance(value, list):
            return [reverse(v) for v in value]
        return value
    path.write_text(json.dumps(reverse(record), indent=indent, ensure_ascii=ascii_strings), encoding='utf-8')
    with open_persisted_attribution(path, chunk_size=3, _read_size=read_size) as (source, payload):
        assert DetailedDCAttributionEnergySummary.freeze(_from_source(source, payload), _decoded=True) == expected


@pytest.mark.parametrize('damage', ['missing_file', 'empty', 'outer_truncated', 'array_truncated',
    'interval_truncated', 'utf8', 'utf8_interval', 'escape', 'trailing', 'missing_intervals', 'missing_payload',
    'missing_hash', 'removed_interval', 'reorder', 'duplicate_interval', 'duration', 'value',
    'hash', 'policy', 'duplicate_key', 'trailing_comma', 'invalid_array'])
def test_corruption_cleans_owned_store(tmp_path, monkeypatch, damage):
    path = _source(tmp_path, specs('daylight'))
    record = json.loads(path.read_text())
    raw = path.read_bytes()
    rows = record['payload']['intervals']
    if damage == 'missing_file': path.unlink()
    elif damage == 'empty': path.write_bytes(b'')
    elif damage == 'outer_truncated': path.write_bytes(raw[:-1])
    elif damage == 'array_truncated': path.write_bytes(raw[:raw.index(b'"intervals"') + 14])
    elif damage == 'interval_truncated': path.write_bytes(raw[:raw.index(b'"intervals"') + 100])
    elif damage == 'utf8': path.write_bytes(raw + b'\xff')
    elif damage == 'utf8_interval':
        # An incomplete multibyte sequence inside an interval string, rather
        # than a bad byte after the document has already ended.
        marker = b'"evaluation_time": "'
        offset = raw.index(marker, raw.index(b'"intervals"')) + len(marker)
        path.write_bytes(raw[:offset] + b'\xc3(' + raw[offset:])
    elif damage == 'escape': path.write_bytes(raw.replace(b'"payload"', b'"pay\\qload"', 1))
    elif damage == 'trailing': path.write_bytes(raw + b' {}')
    elif damage == 'duplicate_key': path.write_bytes(b'{"payload":{},' + raw[1:])
    elif damage == 'trailing_comma': path.write_bytes(raw[:-1] + b',}')
    else:
        if damage == 'missing_intervals': del record['payload']['intervals']
        elif damage == 'missing_payload': del record['payload']
        elif damage == 'missing_hash': del record['attribution_result_sha256']
        elif damage == 'removed_interval': rows.pop()
        elif damage == 'reorder': rows.reverse()
        elif damage == 'duplicate_interval': rows[1] = rows[0]
        elif damage == 'duration': rows[0]['duration_seconds'] += 1
        elif damage == 'value': rows[0]['ledger']['bases']['U']['power_w'] += 1
        elif damage == 'hash': record['attribution_result_sha256'] = '0' * 64
        elif damage == 'policy': record['payload']['numerical_policy']['max_iterations'] += 1
        elif damage == 'invalid_array': record['payload']['intervals'] = {}
        path.write_text(json.dumps(record))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    messages = {
        'outer_truncated': 'truncated', 'array_truncated': 'truncated',
        'interval_truncated': 'truncated', 'trailing': 'trailing attribution JSON content',
        'hash': 'source hash mismatch', 'reorder': 'interval alignment mismatch',
        'duplicate_interval': 'interval alignment mismatch', 'duration': 'interval alignment mismatch',
        'policy': 'unsupported detailed attribution numerical policy',
        'duplicate_key': 'duplicate attribution JSON key',
        'value': 'attribution channel/telescope semantics mismatch',
        'removed_interval': 'attribution duration-based energy mismatch',
        'missing_intervals': 'missing attribution intervals',
        'missing_payload': 'missing attribution record content',
        'missing_hash': 'missing attribution record content',
    }
    error_types = UnicodeDecodeError if damage.startswith('utf8') else (ValueError, KeyError, OSError, ValidationError)
    with pytest.raises(error_types, match=messages.get(damage)):
        with open_persisted_attribution(path, chunk_size=1, _read_size=1):
            pytest.fail('invalid source yielded a result')
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


def test_cleanup_on_consumer_and_storage_failure(tmp_path, monkeypatch):
    path = _source(tmp_path, specs('daylight'))
    monkeypatch.setattr(tempfile, 'tempdir', str(tmp_path))
    with pytest.raises(RuntimeError, match='consumer'):
        with open_persisted_attribution(path):
            raise RuntimeError('consumer')
    assert not list(tmp_path.glob('rawibumi-electrical-*'))
    original = Path.open
    def fail_write(self, mode='r', *args, **kwargs):
        if mode == 'xb' and self.name.startswith('chunk-'):
            raise OSError('controlled storage failure')
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', fail_write)
    with pytest.raises(OSError, match='controlled storage failure'):
        aggregate_persisted_attribution(path)
    assert not list(tmp_path.glob('rawibumi-electrical-*'))


def test_incremental_long_history(tmp_path, monkeypatch):
    path = _source(tmp_path, specs('mixed', 1000))
    expected = legacy(path)
    original = ElectricalIntervalStore.append
    offsets = []
    original_open = Path.open
    opened = []
    def track_open(self, *args, **kwargs):
        result = original_open(self, *args, **kwargs)
        if self == path:
            opened.append(result)
        return result
    def append(self, row):
        offsets.append(opened[0].tell())
        return original(self, row)
    monkeypatch.setattr(Path, 'open', track_open)
    monkeypatch.setattr(ElectricalIntervalStore, 'append', append)
    with open_persisted_attribution(path, chunk_size=3, _read_size=7) as (source, payload):
        assert len(offsets) == 1000
        assert offsets[0] < path.stat().st_size
        assert offsets == sorted(offsets)
        assert payload['intervals'].peak_buffered_records <= 3
        assert DetailedDCAttributionEnergySummary.freeze(_from_source(source, payload), _decoded=True) == expected
