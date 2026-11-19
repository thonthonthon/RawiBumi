"""Verified snapshot admission, bounded native rendering and fail-closed PDF protection."""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
import base64
import binascii
import hmac
import json
import logging
from math import isfinite,isclose
import os
from pathlib import Path
import re
import selectors
import secrets
import shutil
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import pandas as pd
from jsonschema import FormatChecker, ValidationError
from engine.simulation.artifacts import canonical_json_bytes
from engine.simulation.canonical import _assert_output_schema
from reporting.exports.csv_export import load_source

# A minute leap year has 527,040 intervals; reserve 1,024 entries for contract headroom.
MAX_LIST_ITEMS = 528064
# Address contract is 2,000 characters; reserve 48 characters of headroom.
MAX_STRING_CHARS = 2048
MAX_CONTEXT_BYTES = 32 * 1024 * 1024
# Conservative tree accounting includes six-byte escaping of all native timestamps.
MAX_TREE_BYTES = 160 * 1024 * 1024
MAX_NODES = 4_000_000
MAX_DEPTH = 32
MAX_OBJECT_KEYS = 128
# Snapshot JSON + its JSON string escaping + 4 MiB PNG in base64, bounded independently.
MAX_PROJECTION_BYTES = 48 * 1024 * 1024
MAX_PDF_BYTES = 8 * 1024 * 1024
MAX_STDERR_BYTES = 4096
# Amendment 6: 10k modules / 31 inverters / 556 strings, three annual runs per locale.
# Highest simultaneous Python + Node + Chromium PSS: 1,158,359,040 bytes; ceil(peak × 1.5).
MAX_RSS_BYTES = 1_737_538_560
WORKER_TIMEOUT_SECONDS = 40
MAX_PLAN_BYTES = 4 * 1024 * 1024
MAX_PLAN_PIXELS = 4096
WORKER = Path(__file__).with_name("native_pdf_worker.cjs")
logger = logging.getLogger(__name__)
IDENTITY_FIELDS = ("project_revision_id", "scene_revision_id", "electrical_revision_id", "weather_revision_id", "simulation_configuration_id", "engine_version")

class NativePDFError(ValueError):
    """Snapshot admission, unavailable runtime, protection or bounded worker failure."""


def _memory_limit_bytes():
    value = os.environ.get("RAWIBUMI_PDF_MEMORY_LIMIT_MIB")
    if value is None:
        return MAX_RSS_BYTES
    if not re.fullmatch(r"[1-9][0-9]{2,3}", value) or not 768 <= int(value) <= 2048:
        raise NativePDFError("invalid native PDF memory limit configuration")
    return int(value) * 1024 * 1024


def _unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _finite_float(text: str) -> float:
    value = float(text)
    if not isfinite(value):
        raise ValueError("nonfinite JSON number")
    return value


def _invalid_constant(text: str):
    raise ValueError("nonfinite JSON constant")


def _bound_json(directory: Path, package: dict, name: str, role: str) -> tuple[dict, str]:
    entries = [a for a in package["artifacts"] if a["relative_path"] == name]
    if len(entries) != 1 or entries[0]["role"] != role:
        raise ValueError(f"{name} is absent or has the wrong artifact role")
    raw = (directory / name).read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != entries[0]["sha256"] or len(raw) != entries[0]["byte_size"]:
        raise ValueError(f"{name} byte hash/size mismatch")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                       parse_float=_finite_float, parse_constant=_invalid_constant)
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain a JSON object")
    return value, digest


def _timestamp(value: str) -> pd.Timestamp:
    # The canonical schema helper does not enable format validation.
    if not isinstance(value, str) or not FormatChecker().conforms(value, "date-time"):
        raise ValueError("invalid persisted date-time")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError("persisted date-time must be timezone-aware")
    return stamp


def _public_convention(value: str) -> str:
    """An engine time-convention token. Like _public_token, but ';' may join fixed vocabulary parts
    (Open-Meteo: "…:solar_preceding_hour_mean;state_instant_at_label"); still no paths or free text."""
    if (not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9_@.+:-]+(;[A-Za-z0-9_@.+:-]+)*", value)
            or any(part in {".", ".."} or part.lower().startswith("file:") for part in value.split(";"))):
        raise ValueError("source time convention is not a public token")
    return value


def _public_token(value: str) -> str:
    # Do not publish free-text metadata or paths under the guise of identities.
    if (not isinstance(value, str)
            or not re.fullmatch(r"[A-Za-z0-9_@.+:-]+", value)
            or value in {".", ".."} or value.lower().startswith("file:")):
        raise ValueError("source identity is not a public identifier")
    return value


def verify_report_source(source, run_directory):
    directory = Path(run_directory)
    try:
        if ".." in directory.parts or any(p.is_symlink() for p in (directory, *directory.parents)):
            raise ValueError("report package path uses traversal or a symlink")
        verified = load_source(directory, project_id=source.project_id,
                               run_id=source.run["simulation_run_id"], saved=source.run, require_hourly=False)
        if (verified.run != source.run or verified.package != source.package
                or verified.reference != source.reference or verified.columns != source.columns
                or not verified.frame.equals(source.frame)):
            raise ValueError("report source does not match the persisted run/package")
        run, _ = _bound_json(directory, verified.package, "simulation-run.json", "simulation_run")
        reproduction, _ = _bound_json(directory, verified.package,
                                       "reproducibility-manifest.json", "reproducibility_manifest")
        summary, summary_digest = _bound_json(directory, verified.package,
                                             "summary-result.json", "summary_result")
        _assert_output_schema(summary, "summary-result.schema.json")
        _assert_output_schema(reproduction, "reproducibility-manifest.schema.json")
        if run != verified.run or reproduction != run["reproducibility_manifest"]:
            raise ValueError("report run/reproducibility snapshot mismatch")
        if summary["simulation_run_id"] != run["simulation_run_id"]:
            raise ValueError("summary run ID mismatch")
        if run["summary_result"] is not None and run["summary_result"] != summary:
            raise ValueError("persisted summary disagrees with embedded run summary")
        for key in IDENTITY_FIELDS:
            if key in reproduction and reproduction[key] != run[key]:
                raise ValueError(f"run/reproducibility identity mismatch: {key}")
        for key in ("component_revision_manifest", "model_manifest", "detailed_execution_identity"):
            if reproduction.get(key) != run.get(key):
                raise ValueError(f"run/reproducibility identity mismatch: {key}")
        if reproduction["input_hashes"]["combined_input_sha256"] != run["input_hash"]:
            raise ValueError("canonical input identity mismatch")
        if _timestamp(run["completed_at"]) < _timestamp(run["started_at"]):
            raise ValueError("run completion precedes its start")

        frame = verified.frame
        start = frame["timestamp"].iloc[0]
        dt = frame["interval_seconds"]
        if not (dt == dt.iloc[0]).all() or dt.iloc[0] <= 0 or not (frame.timestamp.diff().dropna() == pd.Timedelta(seconds=float(dt.iloc[0]))).all():
            raise ValueError("report intervals must be contiguous with a uniform positive cadence")
        cadence = float(dt.iloc[0])
        if reproduction['simulation_timestep_seconds'] != cadence or reproduction['working_weather_resolution_seconds'] != cadence:
            raise ValueError("report source cadence disagrees with reproducibility manifest")
        end = frame["timestamp"].iloc[-1] + pd.Timedelta(seconds=cadence)
        duration_hours = float(dt.sum()) / 3600
        if (_timestamp(summary["period_start_time"]) != start
                or _timestamp(summary["period_end_time"]) != end
                or not isclose(summary["period_duration_hours"], duration_hours, rel_tol=0, abs_tol=1e-9)):
            raise ValueError("summary executed period disagrees with hourly source")
        if summary["annual_energy_wh"] is not None:
            if duration_hours not in {8760, 8784} or summary["annual_energy_wh"] != summary["total_energy_wh"]:
                raise ValueError("summary annual energy is not a complete-year executed total")
        for key in IDENTITY_FIELDS: _public_token(run[key])
        for key in ("source_timestamp_convention", "representative_time_policy"): _public_convention(reproduction[key])
        return summary
    except ValidationError as exc:
        raise ValueError("invalid persisted report source schema") from exc
    except (OSError, UnicodeError, KeyError, TypeError, AttributeError, IndexError, OverflowError) as exc:
        raise ValueError("report source is missing, unreadable or malformed") from exc


def _bound_tree(value, depth=0, budget=None):
    """Bound before canonical serialization, including non-projected hourly data.

    Budget overestimates JSON escaping, so admission can be stricter than the
    byte limit. Exact builtins only; cycles terminate at the depth limit.
    """
    if budget is None:
        budget = [MAX_TREE_BYTES, MAX_NODES]
    budget[1] -= 1
    if depth > MAX_DEPTH or budget[1] < 0:
        raise NativePDFError("context nesting/node limit exceeded")
    kind = type(value)
    if kind is dict:
        if len(value) > MAX_OBJECT_KEYS:
            raise NativePDFError("context object limit exceeded")
        budget[0] -= 2 + 2 * len(value)
        for key, child in value.items():
            if type(key) is not str:
                raise NativePDFError("context object keys must be strings")
            _bound_tree(key, depth + 1, budget)
            _bound_tree(child, depth + 1, budget)
    elif kind is list:
        if len(value) > MAX_LIST_ITEMS:
            raise NativePDFError("context list limit exceeded")
        budget[0] -= 2 + len(value)
        for child in value:
            _bound_tree(child, depth + 1, budget)
    elif kind is str:
        if len(value) > MAX_STRING_CHARS:
            raise NativePDFError("context string limit exceeded")
        try:
            value.encode("utf-8")
        except UnicodeError as exc:
            raise NativePDFError("context contains invalid Unicode") from exc
        budget[0] -= 2 + 6 * len(value)
    elif kind is float:
        if not isfinite(value):
            raise NativePDFError("context contains a nonfinite number")
        budget[0] -= 32
    elif kind is int:
        if abs(value) > 2**53-1:
            raise NativePDFError("context exceeds the safe integer range")
        budget[0] -= 80
    elif value is None or kind is bool:
        budget[0] -= 5
    else:
        raise NativePDFError("context must contain plain JSON values")
    if budget[0] < 0:
        raise NativePDFError("context size limit exceeded")


def validate_plan_png(value):
    """Decode, inspect and re-encode; only fresh pixel data crosses the worker boundary."""
    if value is None: return None
    def reject(reason): raise ValueError("Invalid plan_figure_png: " + reason)
    prefix = 'data:image/png;base64,'
    if type(value) is not str or not value.startswith(prefix) or len(value) > len(prefix)+4*((MAX_PLAN_BYTES+2)//3):
        reject('expected a PNG data URL of at most 4 MiB')
    try: raw=base64.b64decode(value[len(prefix):],validate=True)
    except (ValueError,binascii.Error): reject('invalid base64')
    if len(raw)>MAX_PLAN_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n'): reject('expected a PNG of at most 4 MiB')
    # Pillow accepts some bytes after IEND: reject trailing/polyglot content explicitly.
    offset=8
    while offset+12<=len(raw):
        length=int.from_bytes(raw[offset:offset+4],'big'); kind=raw[offset+4:offset+8]
        if kind in {b'acTL',b'fcTL',b'fdAT'}: reject('animated PNG is not allowed')
        offset+=12+length
        if offset>len(raw): reject('truncated PNG')
        if kind==b'IEND':
            if length or offset!=len(raw): reject('trailing PNG content')
            break
    else: reject('missing PNG end')
    try:
        from PIL import Image
        with Image.open(BytesIO(raw)) as image:
            if image.format!='PNG' or not (0<image.width<=MAX_PLAN_PIXELS and 0<image.height<=MAX_PLAN_PIXELS): reject('dimensions exceed 4096 by 4096')
            if getattr(image,'n_frames',1)!=1 or getattr(image,'is_animated',False): reject('animated PNG is not allowed')
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            image.load()
            fresh=Image.frombytes('RGBA',image.size,image.convert('RGBA').tobytes())
            output=BytesIO();fresh.save(output,format='PNG')
        clean=output.getvalue()
        if len(clean)>MAX_PLAN_BYTES: reject('re-encoded PNG exceeds 4 MiB')
        return prefix+base64.b64encode(clean).decode('ascii')
    except ValueError as exc:
        if str(exc).startswith('Invalid plan_figure_png:'): raise
        raise ValueError('Invalid plan_figure_png: unreadable PNG') from exc
    except Exception as exc:
        raise ValueError('Invalid plan_figure_png: unreadable PNG') from exc


def _text(value, *, maximum=128):
    if (type(value) is not str or not value or len(value) > maximum
            or any(unicodedata.category(c).startswith("C") for c in value)):
        raise NativePDFError("invalid or oversized public text")
    return value


def _convention(value):
    """A time-convention token whose fixed parts may be joined by ';' (Open-Meteo); each part is a public token."""
    value = _text(value)
    for part in value.split(";"):
        _token(part)
    return value


def _token(value):
    value = _text(value)
    if (not re.fullmatch(r"[A-Za-z0-9_@.+:-]+", value) or value in {".", ".."}
            or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", value)):
        raise NativePDFError("identity is not a public token")
    return value


def _timezone(value):
    value = _text(value, maximum=64)
    if (not re.fullmatch(r"[A-Za-z0-9_+:/.-]+", value) or ".." in value
            or value.startswith("/") or "://" in value
            or value.lower().startswith(("file:", "http:", "https:", "data:"))):
        raise NativePDFError("invalid public timezone")
    fixed = re.fullmatch(r"(?:UTC)?([+-])(\d{2}):(\d{2})", value)
    if fixed:
        if int(fixed[2]) > 23 or int(fixed[3]) > 59:
            raise NativePDFError("invalid fixed-offset timezone")
    else:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise NativePDFError("unsupported public timezone name") from exc
    return value


def prepare_snapshot(snapshot, *, locale='en', plan_figure_png=None):
    if type(locale) is not str or locale not in {'en','id'}: raise NativePDFError('locale must be en or id')
    if type(snapshot) is not dict or snapshot.get('schema')!='rawibumi.report_snapshot.v1': raise NativePDFError('invalid report snapshot')
    _bound_tree(snapshot)
    data=dict(snapshot);digest=data.pop('snapshot_sha256',None)
    raw=canonical_json_bytes(data)
    if len(raw)>MAX_CONTEXT_BYTES: raise NativePDFError('snapshot size limit exceeded')
    if type(digest) is not str or not re.fullmatch(r'[0-9a-f]{64}',digest) or not hmac.compare_digest(sha256(raw).hexdigest(),digest):
        raise NativePDFError('snapshot digest mismatch')
    for key in ('identity','site','design_view','summary','monthly','hourly_ac','annual_pxx','method','provenance','checks'):
        if type(data.get(key)) is not dict: raise NativePDFError('missing snapshot section: '+key)
    try:
        for key in ('project_id','simulation_run_id','project_revision_id','scene_revision_id','electrical_revision_id','weather_revision_id','engine_version'):
            _token(data['identity'][key])
        for key in ('package_manifest_sha256','input_hash'):
            if not re.fullmatch(r'[0-9a-f]{64}',data['identity'][key]): raise ValueError('invalid identity digest')
        summary=data['summary']
        _assert_output_schema(summary,'summary-result.schema.json')
        if summary['simulation_run_id']!=data['identity']['simulation_run_id']: raise ValueError('summary identity mismatch')
        start=_timestamp(summary['period_start_time']);end=_timestamp(summary['period_end_time'])
        duration=summary['period_duration_hours']
        if end<=start or not isclose((end-start).total_seconds()/3600,duration,rel_tol=0,abs_tol=1e-9): raise ValueError('invalid executed period')
        if summary['annual_energy_wh'] is not None and (duration not in (8760,8784) or summary['annual_energy_wh']!=summary['total_energy_wh']): raise ValueError('invalid annual total')
        months=summary['monthly_energy'];keys=[row['month'] for row in months]
        if not keys or keys!=sorted(set(keys)): raise ValueError('duplicate or unordered months')
        final_month=(end-pd.Timedelta(nanoseconds=1)).strftime('%Y-%m')
        for key in keys:
            if not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',key) or key.startswith('0000') or not start.strftime('%Y-%m')<=key<=final_month: raise ValueError('invalid source month')
        if not isclose(sum(row['energy_wh'] for row in months),summary['total_energy_wh'],rel_tol=1e-9,abs_tol=1e-6): raise ValueError('monthly reconciliation failed')
        cadence=data['hourly_ac']['interval_seconds']
        if type(cadence) not in (int,float) or cadence<=0: raise ValueError('invalid cadence')
        provenance=data['provenance'];_timezone(provenance['source_timezone'])
        for key in ('source_timestamp_convention','representative_time_policy'): _convention(provenance['source_interval'][key])
        if not re.fullmatch(r'[0-9a-f]{64}',provenance['source_dataset']['sha256']): raise ValueError('invalid dataset digest')
        limits=data['method']['limits']
        if not isinstance(limits,list) or any(type(row) is not dict or not all(type(row.get(key)) is str for key in ('code','en','id')) for row in limits): raise ValueError('invalid method limits')
        if len({row['code'] for row in limits})!=len(limits): raise ValueError('duplicate method limit')
    except NativePDFError:
        raise
    except (ValueError,TypeError,KeyError,ValidationError,AttributeError) as exc:
        raise NativePDFError('invalid snapshot content') from exc
    return {'snapshot_json':raw.decode('utf-8'),'snapshot_sha256':digest,'locale':locale,
        'watermark':'free_community','plan_figure_png':validate_plan_png(plan_figure_png)}


def _configured_path(name, *, directory=False):
    value = os.environ.get(name)
    if not value or not Path(value).is_absolute():
        raise NativePDFError(f"{name} must explicitly name an absolute runtime path")
    path = Path(value).resolve()
    if not (path.is_dir() if directory else path.is_file()):
        raise NativePDFError(f"{name} is unavailable")
    return path


def _group_rss(group, known):
    """Conservative descendant RSS screen and PID identity tracker.

    A breach requires a confirming PSS measurement before rejection.
    This sampled watchdog is not an OS-enforced allocation barrier.
    """
    table = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # comm may contain spaces or parentheses. Remaining fields begin
            # with state; ppid=1, pgrp=2, starttime=19, resident pages=21.
            fields = stat[stat.rfind(")") + 2:].split()
            table[int(entry.name)] = (int(fields[1]), int(fields[2]), fields[19],
                                      max(0, int(fields[21])) * os.sysconf("SC_PAGE_SIZE"))
        except (FileNotFoundError, ProcessLookupError):
            continue  # Process exited between reads.
        except (OSError, ValueError, IndexError) as exc:
            raise NativePDFError("cannot monitor worker process memory") from exc
    selected = {pid for pid, (_, pgrp, start, _) in table.items()
                if pid == group or pgrp == group or known.get(pid) == start}
    while True:
        children = {pid for pid, (parent, _, _, _) in table.items() if parent in selected}
        if children.issubset(selected):
            break
        selected.update(children)
    for pid in selected:
        known[pid] = table[pid][2]
    return sum(table[pid][3] for pid in selected)


def _group_pss(known):
    """Proportional memory of tracked live descendants, failing closed if unreadable.

    Called only after the conservative RSS screening budget is exceeded. PID
    start times prevent including reused PIDs; exited/zombie tasks contribute 0.
    A production cgroup must still enforce the physical hard allocation ceiling.
    """
    total = 0
    for pid, started in tuple(known.items()):
        directory = Path(f"/proc/{pid}")
        try:
            stat = (directory / "stat").read_text()
            fields = stat[stat.rfind(")") + 2:].split()
            if fields[19] != started or fields[0] in {"Z", "X"}:
                continue
            value = None
            with (directory / "smaps_rollup").open(encoding="ascii") as stream:
                for line in stream:
                    if line.startswith("Pss:"):
                        parts = line.split()
                        if len(parts) != 3 or parts[2] != "kB":
                            raise NativePDFError("cannot monitor worker proportional memory")
                        value = int(parts[1]) * 1024
                        break
            if value is None:
                raise NativePDFError("cannot monitor worker proportional memory")
            # An exiting/reused PID must not be charged to this worker.
            after = (directory / "stat").read_text()
            after_fields = after[after.rfind(")") + 2:].split()
            if after_fields[19] == started and after_fields[0] not in {"Z", "X"}:
                total += value
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (OSError, UnicodeError, IndexError, ValueError) as exc:
            raise NativePDFError("cannot monitor worker proportional memory") from exc
    return total


def _kill_tree(process, known):
    # Refresh before stopping the parent; Playwright's detached Chromium process
    # may have a different pgrp. Never signal a reused descendant PID.
    try:
        _group_rss(process.pid, known)
    except NativePDFError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for pid, started in known.items():
        if pid == process.pid:
            continue
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
            if stat[stat.rfind(")") + 2:].split()[19] == started:
                os.kill(pid, signal.SIGKILL)
        except (FileNotFoundError, ProcessLookupError):
            pass
    # SIGKILL delivery is asynchronous. Wait briefly for observed detached
    # descendants to stop before TemporaryDirectory removes their profiles.
    deadline = time.monotonic() + 2
    while True:
        running = False
        for pid, started in known.items():
            try:
                stat = Path(f"/proc/{pid}/stat").read_text()
                fields = stat[stat.rfind(")") + 2:].split()
                running |= fields[19] == started and fields[0] not in {"Z", "X"}
            except (FileNotFoundError, ProcessLookupError):
                pass
        if not running:
            return
        if time.monotonic() >= deadline:
            raise NativePDFError("native PDF descendant cleanup timeout")
        time.sleep(0.01)


def _run_worker(payload, runtime, chromium, node):
    memory_limit = _memory_limit_bytes()
    if not sys.platform.startswith("linux") or not Path("/proc/self/status").is_file():
        raise NativePDFError("native PDF requires Linux /proc process-tree limits")
    if not WORKER.is_file() or WORKER.is_symlink():
        raise NativePDFError("packaged native PDF worker is unavailable")
    if len(payload) > MAX_PROJECTION_BYTES:
        raise NativePDFError("worker input size limit exceeded")
    # Chromium profiles/caches go under this disposable directory; no run writes.
    with TemporaryDirectory(prefix="rawibumi-native-pdf-") as scratch:
        env = {"PATH": str(node.parent) + ":/usr/bin:/bin", "LANG": "C.UTF-8",
               "HOME": scratch, "TMPDIR": scratch, "XDG_CACHE_HOME": scratch,
               "RAWIBUMI_PDF_RUNTIME_ROOT": str(runtime),
               "RAWIBUMI_PDF_CHROMIUM_EXECUTABLE": str(chromium)}
        process = None
        known = {}
        try:
            process = subprocess.Popen(
                [str(node), "--max-old-space-size=128", str(WORKER.resolve())],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                shell=False, start_new_session=True, cwd=scratch, env=env, close_fds=True,
            )
            output, errors = bytearray(), bytearray()
            sent = 0
            deadline = time.monotonic() + WORKER_TIMEOUT_SECONDS
            with selectors.DefaultSelector() as selector:
                for stream, event in ((process.stdin, selectors.EVENT_WRITE),
                                      (process.stdout, selectors.EVENT_READ),
                                      (process.stderr, selectors.EVENT_READ)):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, event)
                while selector.get_map() or process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise NativePDFError("native PDF worker timeout")
                    # Aggregate RSS is a fast upper-bound screen, but
                    # shared Chromium mappings must not be charged once per process.
                    if _group_rss(process.pid, known) > memory_limit:
                        if _group_pss(known) > memory_limit:
                            raise NativePDFError("native PDF worker memory limit exceeded")
                    for key, _ in selector.select(timeout=0.05):
                        stream = key.fileobj
                        if stream is process.stdin:
                            try:
                                sent += os.write(stream.fileno(), payload[sent:sent + 4096])
                            except BrokenPipeError:
                                sent = len(payload)
                            if sent == len(payload):
                                selector.unregister(stream)
                                stream.close()
                            continue
                        chunk = os.read(stream.fileno(), 65536)
                        if not chunk:
                            selector.unregister(stream)
                            stream.close()
                            continue
                        target = output if stream is process.stdout else errors
                        limit = MAX_PDF_BYTES if stream is process.stdout else MAX_STDERR_BYTES
                        if len(target) + len(chunk) > limit:
                            raise NativePDFError("native PDF worker output/diagnostic limit exceeded")
                        target.extend(chunk)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NativePDFError("native PDF worker timeout")
            code = process.wait(timeout=remaining)
            if code != 0:
                # Only expose fixed diagnostic tokens, never raw paths/logs.
                diagnostic = errors.decode("ascii", errors="replace").strip()
                if not re.fullmatch(r"PDF_[A-Z_]+", diagnostic):
                    diagnostic = "PDF_WORKER_FAILED"
                raise NativePDFError(f"native PDF worker failed: {diagnostic}")
            if errors or not output.startswith(b"%PDF-") or not output.rstrip().endswith(b"%%EOF"):
                raise NativePDFError("native PDF worker returned invalid PDF or diagnostics")
            return bytes(output)
        except subprocess.TimeoutExpired as exc:
            raise NativePDFError("native PDF worker timeout") from exc
        except OSError as exc:
            raise NativePDFError("native PDF worker could not start or communicate") from exc
        finally:
            if process is not None:
                try:
                    _kill_tree(process, known)
                finally:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        raise NativePDFError("native PDF process cleanup timeout") from exc
                    finally:
                        for stream in (process.stdin, process.stdout, process.stderr):
                            if stream and not stream.closed:
                                stream.close()


def render_native_pdf(snapshot: dict, *, locale="en", plan_figure_png=None) -> bytes:
    """Render an already verified context, never authorizing its caller.

    Runtime configuration belongs to the trusted process environment, never to
    the report context. No fallback to a frontend install or package download.
    """
    projection = prepare_snapshot(snapshot, locale=locale, plan_figure_png=plan_figure_png)
    runtime = _configured_path("RAWIBUMI_PDF_RUNTIME_ROOT", directory=True)
    chromium = _configured_path("RAWIBUMI_PDF_CHROMIUM_EXECUTABLE")
    node_value = os.environ.get("RAWIBUMI_PDF_NODE") or shutil.which("node")
    if not node_value or not Path(node_value).is_absolute() or not os.access(node_value, os.X_OK):
        raise NativePDFError("native PDF Node runtime is unavailable")
    if not os.access(chromium, os.X_OK):
        raise NativePDFError("configured Chromium is not executable")
    raw = _run_worker(canonical_json_bytes(projection), runtime, chromium, Path(node_value).resolve())
    try:
        import pikepdf

        output = BytesIO()
        with pikepdf.open(BytesIO(raw)) as document:
            document.save(output, encryption=pikepdf.Encryption(
                user="", owner=secrets.token_urlsafe(32), R=6, aes=True,
                allow=pikepdf.Permissions(print_highres=True, print_lowres=True, accessibility=True,
                    modify_other=False, extract=False, modify_annotation=False,
                    modify_form=False, modify_assembly=False)))
        protected = output.getvalue()
        if len(protected) > MAX_PDF_BYTES:
            raise NativePDFError("protected native PDF output limit exceeded")
        return protected
    except Exception:
        logger.exception("Native PDF protection failed")
        raise NativePDFError("native PDF protection failed") from None
