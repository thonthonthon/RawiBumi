"""Private, bounded exact receiver orchestration; no scientific reductions here."""
from __future__ import annotations

import atexit
from collections.abc import Mapping
try:
    import fcntl
except ImportError:  # Unsupported platforms retain serial execution.
    fcntl = None
import json
from multiprocessing.connection import Connection, wait
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

RESERVATION_BYTES = 6 * 1024**3
_THREAD_KEYS = ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')


class ExactReceiverPoolError(RuntimeError):
    """An initiated exact job failed; never retry it with a different mode."""


def _process_identity(pid):
    try:
        # comm may contain spaces or parentheses; starttime is field 22.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19]
    except (OSError, IndexError):
        return None


def _rss(pid):
    try:
        return int(Path(f'/proc/{pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, IndexError, ValueError):
        return 0


def _available_memory():
    fields = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    available = int(fields['MemAvailable'].split()[0]) * 1024
    try:
        maximum = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if maximum != 'max':
            available = min(available, int(maximum)-int(Path('/sys/fs/cgroup/memory.current').read_text()))
    except OSError:
        pass
    return available


def _worker_limit():
    cpus = len(os.sched_getaffinity(0))
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            cpus = min(cpus, int(quota)//int(period))
    except OSError:
        pass
    raw = os.environ.get('RAWIBUMI_SHADING_MAX_WORKERS', '12')
    try:
        requested = int(raw)
    except ValueError as exc:
        raise ExactReceiverPoolError('RAWIBUMI_SHADING_MAX_WORKERS must be a positive integer') from exc
    if requested < 1:
        raise ExactReceiverPoolError('RAWIBUMI_SHADING_MAX_WORKERS must be a positive integer')
    return max(1, min(12, requested, cpus-2))


class _MachineLease:
    """flock is crash-released; PID/start-time records distinguish stale owners.

    Never unlink the lock inode: a waiter on the old inode could otherwise race
    a new owner. The descriptor and lock live for the complete pool lifetime.
    """
    def __init__(self, reservation_bytes=RESERVATION_BYTES):
        self.reservation_bytes = reservation_bytes
        self.fd = None
        self.stale_owner_detected = False

    def acquire(self):
        if fcntl is None:
            return False
        directory = Path(tempfile.gettempdir()) / f'rawibumi-exact-shading-{os.getuid()}'
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid() or directory.stat().st_mode & 0o077:
            return False
        fd = os.open(directory/'machine.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        try:
            previous = os.read(fd, 4096)
            if previous:
                try:
                    owner = json.loads(previous)
                    self.stale_owner_detected = _process_identity(owner['pid']) != owner['start_time']
                except (ValueError, KeyError, TypeError):
                    self.stale_owner_detected = True
            payload = json.dumps({'pid':os.getpid(),'start_time':_process_identity(os.getpid()),'reservation_bytes':self.reservation_bytes}).encode()
            os.lseek(fd, 0, os.SEEK_SET); os.ftruncate(fd, 0); os.write(fd, payload)
            self.fd = fd
            return True
        except BaseException:
            os.close(fd)
            raise

    def close(self):
        if self.fd is not None:
            os.ftruncate(self.fd, 0)
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


class ExactReceiverPool:
    """One coarse request per deterministic receiver partition and channel."""
    def __init__(self, compiled, configuration, receiver_ids, workers, lease):
        self.lease = lease
        self.children = []
        self.closed = False
        self.receiver_ids = tuple(sorted(receiver_ids))
        self.configuration = configuration
        self.temporary = tempfile.TemporaryDirectory(prefix='rawibumi-exact-workers-')
        self.telemetry = {'mode':'parallel','workers':workers,'reservation_bytes':lease.reservation_bytes,
                          'stale_lease_detected':lease.stale_owner_detected,'peak_job_rss_bytes':0,
                          'queries':0,'worker_metrics':{}}
        atexit.register(self.close)
        try:
            for index in range(workers):
                ids = self.receiver_ids[index::workers]
                parent_socket, child_socket = socket.socketpair()
                child_fd = child_socket.fileno()
                bootstrap = Path(self.temporary.name)/f'worker-{index}.json'
                bootstrap.write_text(json.dumps({'fd':child_fd,'parent_pid':os.getpid(),'parent_start':_process_identity(os.getpid())}))
                bootstrap.chmod(0o600)
                environment = dict(os.environ)
                environment.update({key:'1' for key in _THREAD_KEYS})
                environment['RAWIBUMI_SHADING_WORKER'] = '1'
                try:
                    process = subprocess.Popen([sys.executable,'-m','geometry.shading._worker_main',str(bootstrap)],
                                               pass_fds=(child_fd,),env=environment,
                                               cwd=Path(__file__).resolve().parents[2],stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                except BaseException:
                    parent_socket.close(); child_socket.close(); raise
                child_socket.close()
                connection = Connection(parent_socket.detach())
                self.children.append((process, connection, ids))
                connection.send(('initialize', compiled, configuration, ids))
            replies = self._receive([c for _,c,_ in self.children], timeout=60.)
            if any(reply != ('ready',len(ids)) for reply,(_,_,ids) in zip(replies,self.children)):
                raise ExactReceiverPoolError('exact worker initialization protocol mismatch')
        except BaseException:
            self.close()
            raise

    def _check_resources(self):
        total = _rss(os.getpid()) + sum(_rss(p.pid) for p,_,_ in self.children)
        self.telemetry['peak_job_rss_bytes'] = max(total,self.telemetry['peak_job_rss_bytes'])
        if total > self.lease.reservation_bytes:
            raise ExactReceiverPoolError('exact shading job exceeded its memory reservation')
        for process,_,_ in self.children:
            if process.poll() is not None:
                raise ExactReceiverPoolError(f'exact receiver worker exited ({process.returncode})')

    def _receive(self, connections, *, timeout=300.):
        deadline = time.monotonic()+timeout
        pending = set(connections); replies = {}
        while pending:
            self._check_resources()
            if time.monotonic() >= deadline:
                raise ExactReceiverPoolError('exact receiver worker response deadline exceeded')
            for connection in wait(pending, timeout=.1):
                try:
                    reply = connection.recv()
                except (EOFError, OSError) as exc:
                    raise ExactReceiverPoolError('exact receiver worker connection failed') from exc
                if isinstance(reply,tuple) and reply[0] == 'error':
                    raise ExactReceiverPoolError(f'exact receiver worker failed: {reply[1]}')
                replies[connection] = reply; pending.remove(connection)
        return [replies[c] for c in connections]

    def evaluate(self, channel, selected, *, source=None, resolution=None):
        if self.closed:
            raise ExactReceiverPoolError('exact receiver pool is closed')
        selected = set(selected)
        if not selected.issubset(self.receiver_ids):
            raise ExactReceiverPoolError('query receiver outside exact worker partition')
        connections=[]
        try:
            for _,connection,ids in self.children:
                subset = tuple(r for r in ids if r in selected)
                if subset:
                    connection.send(('query',channel,subset,source,resolution)); connections.append(connection)
            result={}
            for reply in self._receive(connections):
                if not isinstance(reply,tuple) or reply[0] != 'result':
                    raise ExactReceiverPoolError('exact worker query protocol mismatch')
                result.update(reply[1]);self.telemetry['worker_metrics'].update(reply[2])
            self.telemetry['queries'] += 1
            return result
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.closed:
            return
        self.closed = True
        # Closing transports causes worker EOF even if the caller raises.
        for process,connection,_ in self.children:
            connection.close()
        for process,_,_ in self.children:
            try:
                process.wait(timeout=2.)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=2.)
                except subprocess.TimeoutExpired:
                    process.kill();process.wait()
            if process.stderr is not None: process.stderr.close()
        self.temporary.cleanup();self.lease.close()
        atexit.unregister(self.close)


# Operational allocation policy, fixed by PERF3 DEC-180 A1 before implementation.
_LATE_PARENT_ALLOWANCE_BYTES = 1536 * 1024**2
_PREPARED_MARGIN_NUMERATOR = 5
_PREPARED_MARGIN_DENOMINATOR = 4
_WORKER_BASE_BYTES = 96 * 1024**2
_WORKER_SCRATCH_MIN_BYTES = 8 * 1024**2
_WORKER_SCRATCH_BYTES_PER_FACE = 2048


class _AdmissionEstimateUnavailable(ValueError):
    """Unrecognized allocation metadata keeps the original admission path."""


def _compiled_python_bytes(value):
    """Count the native compiled graph once, including shared coordinate floats."""
    seen, pending, size = set(), [value], 0
    while pending:
        item = pending.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        kind = type(item)
        if kind not in (dict, list, tuple, str, float, int, bool, type(None)):
            raise _AdmissionEstimateUnavailable('non-native compiled metadata')
        size += sys.getsizeof(item)
        if kind is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif kind in (list, tuple):
            pending.extend(item)
    return size


def _prepared_allocation_upper_counts(compiled, configuration, receiver_ids):
    """Bound allocations of the unchanged sourceward clipper, never ray results.

    Separate NumPy operations reproduce _dot(normal, _sub(point, origin)).
    An output ring has at most its inside vertices plus its crossing edges;
    the original dedupe can only reduce that count, including for concave rings.
    Native input floats remain borrowed; crossing-coordinate floats are new.
    """
    import math
    import numpy as np
    from .beam import _receiver_basis, BeamShadowError, DEFAULT_BEAM_TOLERANCES
    from .prepared import PreparedOccluderFace

    if type(compiled) is not dict or type(configuration) is not dict:
        raise _AdmissionEstimateUnavailable('non-native preparation metadata')
    self_shading = configuration.get('self_shading_enabled')
    if type(self_shading) is not bool:
        raise _AdmissionEstimateUnavailable('self shading must be explicit')
    requested = tuple(receiver_ids)
    receivers = compiled.get('receivers')
    occluders = compiled.get('occluders')
    if type(receivers) not in (list, tuple) or type(occluders) not in (list, tuple):
        raise _AdmissionEstimateUnavailable('missing receiver/occluder metadata')
    if any(type(r) is not dict or type(r.get('receiver_id')) is not str for r in receivers):
        raise _AdmissionEstimateUnavailable('unrecognized receiver identity')
    by_id = {r['receiver_id']: r for r in receivers}
    if len(by_id) != len(receivers) or any(type(r) is not str or r not in by_id for r in requested):
        raise _AdmissionEstimateUnavailable('unresolved receiver identity')
    if len(set(requested)) != len(requested):
        raise _AdmissionEstimateUnavailable('duplicate receiver identity')

    points, owners, starts, previous = [], [], [], []
    if any(type(o) is not dict or type(o.get('occluder_id')) is not str for o in occluders):
        raise _AdmissionEstimateUnavailable('unrecognized occluder identity')
    for occluder in sorted(occluders, key=lambda o: o['occluder_id']):
        if occluder.get('shading_enabled') is not True:
            continue
        source_type = occluder.get('source_entity_type')
        source_id = occluder.get('source_entity_id')
        if type(source_type) is not str or type(source_id) is not str:
            raise _AdmissionEstimateUnavailable('unrecognized occluder source')
        if source_type == 'module_instance' and not self_shading:
            continue
        faces = occluder.get('faces')
        if occluder.get('geometry_type') != 'polygon_faces' or type(faces) not in (list, tuple):
            raise _AdmissionEstimateUnavailable('unsupported face metadata')
        for face in faces:
            if type(face) is not dict or type(face.get('face_id')) is not str:
                raise _AdmissionEstimateUnavailable('unrecognized face identity')
            vertices = face.get('vertices_3d')
            if type(vertices) not in (list, tuple) or len(vertices) < 3:
                raise _AdmissionEstimateUnavailable('unsupported vertex metadata')
            for vertex in vertices:
                if (type(vertex) not in (list, tuple) or len(vertex) != 3
                        or any(type(c) is not float or not math.isfinite(c) for c in vertex)):
                    raise _AdmissionEstimateUnavailable('non-native or nonfinite vertex')
            start = len(points)
            starts.append(start)
            previous.extend([start + len(vertices) - 1] + list(range(start, start + len(vertices) - 1)))
            points.extend(vertices)
            owners.append((source_type, source_id))

    vertices = np.asarray(points, dtype=np.float64).reshape((-1, 3))
    starts = np.asarray(starts, dtype=np.int64)
    previous = np.asarray(previous, dtype=np.int64)
    sample = PreparedOccluderFace('', '', ())
    face_header = sys.getsizeof(sample) + max(296, sys.getsizeof(vars(sample)))
    tuple_header = sys.getsizeof(())
    pointer = sys.getsizeof((None,)) - tuple_header
    point_tuple = sys.getsizeof((0., 0., 0.))
    float_bytes = sys.getsizeof(0.)
    tolerance = DEFAULT_BEAM_TOLERANCES.plane_distance_m
    for rid in requested:
        receiver = by_id[rid]
        source_type, source_id = receiver.get('source_entity_type'), receiver.get('source_entity_id')
        if type(source_type) is not str or type(source_id) is not str:
            raise _AdmissionEstimateUnavailable('unrecognized receiver source')
        try:
            origin, normal, _, _ = _receiver_basis(receiver['vertices_3d'], receiver['normal_xyz'])
        except (BeamShadowError, KeyError, TypeError, ValueError, IndexError) as exc:
            raise _AdmissionEstimateUnavailable('unsupported receiver basis') from exc
        faces = vertex_count = crossings_count = 0
        if len(vertices):
            with np.errstate(over='ignore', invalid='ignore', under='ignore'):
                dx = np.subtract(vertices[:, 0], origin[0])
                dy = np.subtract(vertices[:, 1], origin[1])
                dz = np.subtract(vertices[:, 2], origin[2])
                distances = np.add(np.add(np.multiply(normal[0], dx), np.multiply(normal[1], dy)),
                                   np.multiply(normal[2], dz))
            if not np.isfinite(distances).all():
                raise _AdmissionEstimateUnavailable('nonfinite allocation arithmetic')
            inside = distances >= tolerance
            counts = np.add.reduceat(inside.astype(np.int64), starts)
            crossings = np.add.reduceat(np.not_equal(inside, inside[previous]).astype(np.int64), starts)
            output_count = counts + crossings
            retained = output_count >= 3
            retained &= np.asarray([owner != (source_type, source_id) for owner in owners], dtype=bool)
            faces = int(retained.sum())
            vertex_count = int(output_count[retained].sum())
            crossings_count = int(crossings[retained].sum())
        size = faces * (face_header + tuple_header)
        size += vertex_count * (pointer + point_tuple) + crossings_count * 3 * float_bytes
        size += faces * 144  # Four packed float64/int64 bound arrays; all faces is an upper count.
        size += 4096 + 128 * len(receiver['vertices_3d'])
        yield {'receiver_id': rid, 'face_upper': faces, 'vertex_upper': vertex_count,
               'intersection_vertex_upper': crossings_count, 'prepared_byte_upper': size}


def _receiver_allocation_estimate(compiled, configuration, receiver_ids, parent_rss):
    prepared = faces = vertices = largest = 0
    for row in _prepared_allocation_upper_counts(compiled, configuration, receiver_ids):
        prepared += row['prepared_byte_upper']
        faces += row['face_upper']
        vertices += row['vertex_upper']
        largest = max(largest, row['face_upper'])
    compiled_bytes = _compiled_python_bytes(compiled)
    scratch = max(_WORKER_SCRATCH_MIN_BYTES, _WORKER_SCRATCH_BYTES_PER_FACE * largest)
    margin = (prepared * _PREPARED_MARGIN_NUMERATOR + _PREPARED_MARGIN_DENOMINATOR - 1) // _PREPARED_MARGIN_DENOMINATOR
    base = parent_rss + _LATE_PARENT_ALLOWANCE_BYTES + margin
    per_worker = _WORKER_BASE_BYTES + compiled_bytes + scratch
    return base, per_worker, {
        'admission_estimate_basis': 'sourceward_allocation_v1',
        'prepared_allocation_upper_bytes': prepared, 'prepared_face_upper_count': faces,
        'prepared_vertex_upper_count': vertices, 'compiled_python_bytes': compiled_bytes,
        'late_parent_allowance_bytes': _LATE_PARENT_ALLOWANCE_BYTES,
        'worker_scratch_bytes': scratch,
    }


def _legacy_receiver_allocation_estimate(compiled, receiver_ids, parent_rss):
    """Original admission for metadata outside the native compiled fast path."""
    from .prepared import PreparedOccluderFace
    faces = [face for o in compiled.get('occluders',[]) for face in o.get('faces',[])]
    per_receiver = 0
    for face in faces:
        count = len(face.get('vertices_3d',[])) + 1
        points = tuple(tuple(float(i+j) for j in range(3)) for i in range(count))
        sample = PreparedOccluderFace('', '', points)
        per_receiver += (sys.getsizeof(sample) + sys.getsizeof(vars(sample))
                         + sys.getsizeof(points)
                         + sum(sys.getsizeof(point) + sum(sys.getsizeof(x) for x in point) for point in points)
                         + 160 + 8)
    return parent_rss + len(receiver_ids)*per_receiver, _WORKER_BASE_BYTES, {
        'admission_estimate_basis': 'legacy_unsupported_metadata',
    }


def create_receiver_pool(compiled, configuration, receiver_ids):
    telemetry = {'mode':'serial','workers':1}
    if sys.platform != 'linux':
        return None,{**telemetry,'reason':'unsupported_parallel_platform'}
    if os.environ.get('RAWIBUMI_SHADING_WORKER') or os.environ.get('PYTEST_XDIST_WORKER'):
        return None,{**telemetry,'reason':'nested_or_test_worker'}
    workers = _worker_limit()
    if workers == 1 or len(receiver_ids) < 256:
        return None,{**telemetry,'reason':'configured_serial_or_small_receiver_set'}
    reservation = min(RESERVATION_BYTES, _available_memory()//2)
    parent_rss = _rss(os.getpid())
    try:
        base, per_worker, accounting = _receiver_allocation_estimate(
            compiled, configuration, receiver_ids, parent_rss,
        )
    except _AdmissionEstimateUnavailable:
        base, per_worker, accounting = _legacy_receiver_allocation_estimate(
            compiled, receiver_ids, parent_rss,
        )
    while workers > 1 and base + workers*per_worker > reservation:
        workers -= 1
    estimate = base + workers*per_worker
    if workers < 2 or estimate > reservation:
        return None,{**telemetry,'reason':'memory_reservation_unavailable',
                     'estimated_bytes':estimate,'reservation_bytes':reservation,**accounting}
    lease = _MachineLease(reservation)
    if not lease.acquire():
        return None,{**telemetry,'reason':'machine_lease_busy'}
    pool = ExactReceiverPool(compiled,configuration,receiver_ids,workers,lease)
    pool.telemetry['estimated_bytes'] = estimate
    pool.telemetry.update(accounting)
    return pool,pool.telemetry


class PreparedReceiverMap(Mapping):
    """Lazy parent state; parallel workers own only their receiver partitions."""
    def __init__(self, context, pool):
        self.context=context; self.pool=pool
    def __iter__(self): return iter(self.context.receiver_ids)
    def __len__(self): return len(self.context.receiver_ids)
    def __getitem__(self, key):
        if key not in self.context.receiver_ids: raise KeyError(key)
        return self.context.prepared_query(key)
    def evaluate(self, channel, selected, **kwargs):
        return self.pool.evaluate(channel,selected,**kwargs)
