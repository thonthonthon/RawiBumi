"""Exact private receiver transport, nonblocking leases and failure cleanup."""
from copy import deepcopy
import json
import os
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from geometry.shading import compile_shading_geometry
from geometry.shading import parallel
from geometry.shading.snapshot import evaluate_beam_shading_snapshot
from geometry.shading.sky_snapshot import evaluate_sky_shading_snapshot
from geometry.shading.ground_snapshot import evaluate_ground_shading_snapshot
from tests.unit.test_rb_mesh1_acceleration import synthetic_scene,forced_maps,configuration,exact_payload


@pytest.fixture
def isolated_lease_directory(tmp_path,monkeypatch):
    # Exercise real flock/PID identities without competing with another job.
    monkeypatch.setattr(parallel.tempfile,'gettempdir',lambda:str(tmp_path))
    return tmp_path


@pytest.mark.parametrize('workers',[1,2,12])
def test_real_isolated_workers_preserve_full_snapshots_and_subsets(workers,isolated_lease_directory):
    compiled=compile_shading_geometry(synthetic_scene(9));reference,fast=forced_maps(compiled);config=configuration()
    lease=parallel._MachineLease();assert lease.acquire()
    pool=parallel.ExactReceiverPool(compiled,config,list(reference),workers,lease)
    carrier=parallel.PreparedReceiverMap(SimpleNamespace(receiver_ids=tuple(reference),prepared_query=lambda rid:fast[rid]),pool)
    children=[p for p,_,_ in pool.children]
    try:
        # The source is normalized twice by the existing snapshot/kernel chain;
        # transport must not introduce another normalization or reduction.
        for subset in (list(reference),list(reference)[::2]):
            for direction in ((.3,.4,1.),(-.8,.2,.03),(0,0,-1)):
                kwargs=dict(shading_configuration=config,receiver_ids=subset,sun_vector_xyz=direction)
                actual=evaluate_beam_shading_snapshot(compiled,prepared_queries=carrier,**kwargs)
                expected=evaluate_beam_shading_snapshot(compiled,prepared_queries=reference,**kwargs)
                exact_payload(actual.shading_result,expected.shading_result,label=f'workers={workers},beam={direction}')
            for name,fn in (('sky',evaluate_sky_shading_snapshot),('ground',evaluate_ground_shading_snapshot)):
                kwargs=dict(shading_configuration=config,receiver_ids=subset)
                actual=fn(compiled,prepared_queries=carrier,**kwargs).shading_result
                expected=fn(compiled,prepared_queries=reference,**kwargs).shading_result
                exact_payload(actual,expected,label=f'workers={workers},{name},subset={subset}')
        assert pool.telemetry['mode']=='parallel'
        assert pool.telemetry['workers']==workers
        assert pool.telemetry['peak_job_rss_bytes']<parallel.RESERVATION_BYTES
    finally:
        pool.close()
    assert all(p.poll() is not None for p in children)
    assert not Path(pool.temporary.name).exists()
    replacement=parallel._MachineLease();assert replacement.acquire();replacement.close()


def test_machine_lease_is_nonblocking_and_detects_pid_reuse(isolated_lease_directory):
    first=parallel._MachineLease();assert first.acquire()
    second=parallel._MachineLease();assert not second.acquire()
    # The current PID with a different start time models a stale reused PID.
    os.lseek(first.fd,0,os.SEEK_SET);os.ftruncate(first.fd,0)
    os.write(first.fd,json.dumps({'pid':os.getpid(),'start_time':'not-the-current-start'}).encode())
    # Simulate a crash: OS descriptor close releases flock without cleanup.
    os.close(first.fd);first.fd=None
    assert second.acquire();assert second.stale_owner_detected
    second.close()


def test_busy_machine_lease_selects_serial_before_any_worker(isolated_lease_directory,monkeypatch):
    compiled=compile_shading_geometry(synthetic_scene(9));ids=['synthetic-'+str(i) for i in range(256)]
    monkeypatch.delenv('PYTEST_XDIST_WORKER',raising=False)
    monkeypatch.setattr(parallel,'_worker_limit',lambda:12)
    monkeypatch.setattr(parallel,'_available_memory',lambda:64*1024**3)
    first=parallel._MachineLease();assert first.acquire()
    try:
        pool,telemetry=parallel.create_receiver_pool(compiled,configuration(),ids)
        assert pool is None and telemetry['mode']=='serial' and telemetry['reason']=='machine_lease_busy'
    finally:first.close()


@pytest.mark.parametrize('environment,reason',[
    ({'RAWIBUMI_SHADING_WORKER':'1'},'nested_or_test_worker'),
    ({'PYTEST_XDIST_WORKER':'gw0'},'nested_or_test_worker'),
    ({'RAWIBUMI_SHADING_MAX_WORKERS':'1'},'configured_serial_or_small_receiver_set'),
])
def test_oversubscription_falls_back_before_work(environment,reason,monkeypatch):
    for key in ('RAWIBUMI_SHADING_WORKER','PYTEST_XDIST_WORKER','RAWIBUMI_SHADING_MAX_WORKERS'):monkeypatch.delenv(key,raising=False)
    for key,value in environment.items():monkeypatch.setenv(key,value)
    pool,telemetry=parallel.create_receiver_pool({},configuration(),['r']*256)
    assert pool is None and telemetry['mode']=='serial' and telemetry['reason']==reason


def test_worker_death_aborts_without_serial_reexecution(isolated_lease_directory):
    compiled=compile_shading_geometry(synthetic_scene(9));reference,_=forced_maps(compiled)
    lease=parallel._MachineLease();assert lease.acquire()
    pool=parallel.ExactReceiverPool(compiled,configuration(),list(reference),2,lease)
    children=[p for p,_,_ in pool.children]
    children[0].kill();children[0].wait()
    with pytest.raises((parallel.ExactReceiverPoolError,BrokenPipeError)):
        pool.evaluate('beam',list(reference),source=(.3,.4,1.))
    assert pool.closed and all(p.poll() is not None for p in children)
    replacement=parallel._MachineLease();assert replacement.acquire();replacement.close()


def test_reservation_is_a_cap_limited_by_available_memory_and_worker_count(isolated_lease_directory,monkeypatch):
    monkeypatch.delenv('PYTEST_XDIST_WORKER',raising=False)
    monkeypatch.setattr(parallel,'_worker_limit',lambda:12)
    monkeypatch.setattr(parallel,'_available_memory',lambda:2*1024**3)
    captured={}
    class Pool:
        def __init__(self,compiled,configuration,ids,workers,lease):
            captured.update(workers=workers,reservation=lease.reservation_bytes)
            self.telemetry={'mode':'parallel','workers':workers};self.lease=lease
        def close(self):self.lease.close()
    monkeypatch.setattr(parallel,'ExactReceiverPool',Pool)
    pool,telemetry=parallel.create_receiver_pool({'occluders':[]},configuration(),['r'+str(i) for i in range(256)])
    try:
        assert pool is not None and telemetry['mode']=='parallel'
        assert captured['reservation']==1024**3
        assert 2<=captured['workers']<12
    finally:pool.close()


def test_initialization_failure_releases_lease(isolated_lease_directory):
    compiled=compile_shading_geometry(synthetic_scene(9))
    lease=parallel._MachineLease();assert lease.acquire()
    with pytest.raises(parallel.ExactReceiverPoolError):
        parallel.ExactReceiverPool(compiled,configuration(),['unknown-receiver'],2,lease)
    replacement=parallel._MachineLease();assert replacement.acquire();replacement.close()
