"""Frozen canonical-token oracle and bounded exact digest regressions."""
from hashlib import sha256
from pathlib import Path
from copy import deepcopy
import json
import math
import random
import shutil
import struct
from urllib.parse import urlparse,unquote

import numpy as np
import pandas as pd
import pytest
from typing import Any

from engine.simulation import artifacts as a

# Original pre-A7 canonical serializer, retained as an independent oracle.
def reference_scalar(value: Any) -> str:
    if value is None or value is pd.NA:
        return "null"
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if np.isnan(number):
            return "nan"
        if np.isposinf(number):
            return "+inf"
        if np.isneginf(number):
            return "-inf"
        return format(number, ".17g")
    return str(value)


def reference_bytes(frame):
    header="opensimpv.dataframe.logical.v0.1\n"+"|".join(str(c) for c in frame.columns)+"\n"
    return (header+"".join("\x1f".join(reference_scalar(v) for v in row)+"\n" for row in frame.itertuples(index=False,name=None))).encode('utf-8')


def values():
    rng=random.Random(18007)
    return [None,pd.NA,pd.NaT,True,False,np.bool_(True),np.bool_(False),1,-1,np.int8(-7),np.uint64(2**64-1),0.,-0.,np.float32(.1),np.longdouble('.1234567890123456789'),float('nan'),float('inf'),-float('inf'),np.nextafter(0.,1.),np.finfo(float).max,'','a\x1fb\n🌞',pd.Timestamp('2023-01-01',tz='Asia/Jakarta'),pd.Timestamp('2023-11-05T00:30:00-04:00'),np.datetime64('2023-01-01'),np.datetime64('NaT'),*[struct.unpack('>d',rng.getrandbits(64).to_bytes(8,'big'))[0] for _ in range(12000)]]


@pytest.mark.parametrize('limits',[(4096,1024*1024),(3,32),(0,0)])
def test_exact_tokens_for_seeded_binary64_and_eviction(limits):
    cache=a._LogicalTokenCache(max_entries=limits[0],max_bytes=limits[1])
    for value in values():
        expected=reference_scalar(value)
        assert a._logical_scalar(value)==expected
        assert cache.token(value)==expected
        assert cache.retained_bytes<=limits[1]
        assert len(cache._entries)<=limits[0]
    assert cache.token(0.)=='0' and cache.token(-0.)=='-0'
    assert cache.token(True)=='true' and cache.token(1)=='1' and cache.token(1.)=='1'


def test_unknown_and_subclass_values_preserve_original_fallback():
    class Text(str):
        def __str__(self):return 'custom-text'
    class Number(float):
        def __float__(self):return .125
    class Object:
        def __str__(self):return 'custom-object'
    cache=a._LogicalTokenCache(max_entries=2,max_bytes=16)
    for value in (Text('x'),Number(7),Object(),10**1000,'x'*10000):
        assert a._logical_scalar(value)==reference_scalar(value)
        assert cache.token(value)==reference_scalar(value)
    assert cache.retained_bytes<=16


@pytest.mark.parametrize('kind',['object','nullable','datetime','empty','float'])
def test_exact_digest_bytes_across_dtypes_chunking_and_cache_lifetimes(kind):
    if kind=='object':frame=pd.DataFrame({'mixed':pd.Series([None,True,1,1.,-0.,np.float32(.1),'a\x1fb\n'],dtype=object)})
    elif kind=='nullable':frame=pd.DataFrame({'i':pd.Series([1,None,2],dtype='Int64'),'b':pd.Series([True,None,False],dtype='boolean'),'s':pd.Series(['x',None,'z'],dtype='string')})
    elif kind=='datetime':frame=pd.DataFrame({'time':pd.date_range('2023-11-04',periods=50,freq='h',tz='America/Havana')})
    elif kind=='empty':frame=pd.DataFrame({'empty':pd.Series([],dtype=float)})
    else:frame=pd.DataFrame({'f':pd.Series(values()[12:20]*30,dtype=float)})
    raw=reference_bytes(frame);expected=sha256(raw).hexdigest()
    assert a.dataframe_logical_sha256(frame)==expected
    for chunk_size in (1,3,17,8192):
        digest=sha256();cache=a._LogicalTokenCache(max_entries=3,max_bytes=48)
        if len(frame)==0:a._update_dataframe_logical_digest(digest,frame,include_header=True,_token_cache=cache)
        for start in range(0,len(frame),chunk_size):a._update_dataframe_logical_digest(digest,frame.iloc[start:start+chunk_size],include_header=start==0,_token_cache=cache)
        assert digest.hexdigest()==expected


def receiver_frame(rows=18000):
    index=pd.date_range('2023-01-01',periods=rows,freq='h',tz='Asia/Jakarta')
    return pd.DataFrame({'interval_start':index,'evaluation_time':index+pd.Timedelta(minutes=30),'receiver_id':['r-0001']*rows,'receiver_area_m2':[2.5]*rows,'beam_visibility_factor':([0.,1.,.125]*(rows//3+1))[:rows],'quality_flags_json':['[]']*rows,'shading_result_id':['synthetic-result']*rows})


def test_private_spool_skips_hashing_and_keeps_exact_parquet_bytes(tmp_path,monkeypatch):
    frame=receiver_frame();public=a.ReceiverFactorParquetSink(output_directory=tmp_path/'canonical',simulation_run_id='test')
    for start in range(0,len(frame),8192):public.write(frame.iloc[start:start+8192])
    reference=public.finalize();raw=public._final_path.read_bytes()
    spool=a._ReceiverFactorSpool(output_directory=tmp_path/'private',simulation_run_id='test')
    def forbidden(*args,**kwargs):raise AssertionError('private temporary digest was computed')
    monkeypatch.setattr(a,'_update_dataframe_logical_digest',forbidden)
    for start in range(0,len(frame),8192):spool.write(frame.iloc[start:start+8192])
    path=spool.finalize()
    assert isinstance(path,Path) and path.read_bytes()==raw
    assert spool.telemetry()==public.telemetry()
    assert sha256(raw).hexdigest()==reference['sha256']
    with pytest.raises(RuntimeError,match='closed'):spool.write(frame.iloc[:1])


@pytest.mark.parametrize('writer',[a.ReceiverFactorParquetSink,a._ReceiverFactorSpool])
def test_spool_validation_and_exception_cleanup_stay_identical(tmp_path,writer):
    frame=receiver_frame(3);sink=writer(output_directory=tmp_path,simulation_run_id='test')
    with pytest.raises(ValueError,match='missing'):sink.write(frame.drop(columns=['receiver_id']))
    sink.write(frame)
    with pytest.raises(ValueError,match='columns changed'):sink.write(frame.assign(unexpected=1))
    sink.abort();assert not sink._temp_path.exists() and sink._writer is None
    with pytest.raises(RuntimeError,match='closed'):sink.finalize()
    empty=writer(output_directory=tmp_path,simulation_run_id='empty')
    with pytest.raises(RuntimeError,match='no rows'):empty.finalize()
    assert not empty._temp_path.exists()


def test_private_writer_keeps_run_summary_manifests_and_factor_bytes(tmp_path,monkeypatch):
    from tests.unit.test_phase49c_reference_projects import _reference
    from tests.unit.test_rb_mesh1_tables import _convert_design_to_explicit
    from apps.api.study import _phase5_configuration,_validation_configuration
    from validation.engineering import validate_engineering_design
    from engine.simulation import build_design_revision_store,run_validated_design_simulation
    from engine.simulation import multi_group
    r=_reference('R5');scene,electrical=_convert_design_to_explicit(r['scene'],r['electrical'],r['components']);project=r['project_revision']
    config=_phase5_configuration(project,configuration_id='mesh1-private-reference-proof');config['shading_configuration']['self_shading_enabled']=True
    report=validate_engineering_design(scene,electrical,project_revision_id=project['project_revision_id'],component_revisions=r['components'],configuration=_validation_configuration(),design_validation_report_id='private-reference-proof',generated_at='2026-11-04T00:00:00Z')
    assert not report['blocking_simulation']
    reference_accesses=[]
    class ReferencePathSpool(a.ReceiverFactorParquetSink):
        def finalize(self):
            reference=super().finalize()
            # Strict mapping makes any hidden consumer beyond URI a failure.
            class UriOnly:
                def __getitem__(self,key):
                    reference_accesses.append(key)
                    assert key=='uri'
                    return reference[key]
            return Path(unquote(urlparse(UriOnly()['uri']).path))
    results=[]
    for writer in (ReferencePathSpool,a._ReceiverFactorSpool):
        monkeypatch.setattr(multi_group,'_ReceiverFactorSpool',writer)
        result=run_validated_design_simulation(project,config,revision_store=build_design_revision_store(scene,electrical,r['weather'],r['components']),design_validation_report=report,output_directory=tmp_path/'stable',simulation_run_id='same-run',engine_version='mesh1-proof',executed_at='2026-11-04T00:00:00Z')
        assert result.backend_result is not None,result.simulation_run
        a.verify_run_package(result.artifact_directory)
        payloads={str(p.relative_to(result.artifact_directory)):p.read_bytes() for p in result.artifact_directory.rglob('*') if p.is_file()}
        results.append((a.canonical_json_bytes(result.simulation_run),payloads))
        shutil.rmtree(result.artifact_directory)
    assert reference_accesses==['uri','uri']
    assert results[0][0]==results[1][0],'run payload differs'
    assert results[0][1].keys()==results[1][1].keys()
    for name in results[0][1]:assert results[0][1][name]==results[1][1][name],name
    assert {'summary-result.json','run-package-manifest.json','reproducibility-manifest.json','shading-receiver-factors.parquet'}.issubset(results[0][1])


def test_interleaved_group_spools_preserve_final_chunks_hashes_and_bytes(tmp_path):
    from engine.simulation.multi_group import _merge_receiver_spools
    frames=[receiver_frame(9000).assign(receiver_id=f'r-{group:04d}') for group in range(3)]
    outputs=[]
    for label,writer in (('reference',a.ReceiverFactorParquetSink),('private',a._ReceiverFactorSpool)):
        paths=[]
        for group,frame in enumerate(frames):
            sink=writer(output_directory=tmp_path/label,simulation_run_id=f'g{group}')
            for start in range(0,len(frame),8192):sink.write(frame.iloc[start:start+8192])
            result=sink.finalize()
            paths.append(result if isinstance(result,Path) else Path(unquote(urlparse(result['uri']).path)))
            assert sink.max_chunk_rows<=8192
        reference=_merge_receiver_spools(paths,tmp_path/'stable','final')
        final=Path(unquote(urlparse(reference['uri']).path))
        outputs.append((reference,final.read_bytes()))
        assert reference['row_count']==27000
        frame=pd.read_parquet(final)
        assert frame[['interval_start','receiver_id']].equals(frame.sort_values(['interval_start','receiver_id'],kind='stable')[['interval_start','receiver_id']].reset_index(drop=True))
        shutil.rmtree(final.parent)
    assert outputs[0]==outputs[1]
