"""On-demand R14 measurement; a budget miss is reported, never approximated away."""
from time import perf_counter,process_time
from engine.simulation import run_canonical_simulation
from engine.simulation.artifacts import verify_run_package
import os
import platform
import resource
from tests.integration.test_rb_use5a_circular_roof import physics_fixture


def test_ten_mixed_mppts_five_classes_with_shaded_counterfactual(tmp_path,record_property):
    elapsed={}
    for name in ('baseline','mixed'):
        project,config,store=physics_fixture(tmp_path/name,baseline=name=='baseline',canonical=True)
        print(f'USE5 runtime {name}: starting full-year canonical run (including shading counterfactual and persistence)',flush=True)
        start=perf_counter()
        cpu_start=process_time()
        result=run_canonical_simulation(project,config,revision_store=store,
            output_directory=tmp_path/name/'outputs',simulation_run_id='use5-runtime-'+name,
            engine_version='use5-runtime-test',executed_at='2026-11-14T00:00:00Z')
        assert result.simulation_run['status'] in {'completed','completed_with_warnings'},result.simulation_run
        verify_run_package(result.artifact_directory)
        backend=result.backend_result
        assert len(backend.groups)==5
        if name=='mixed':assert len(backend.metadata['mixed_orientation']['mppts'])==10
        assert backend.metadata['installed_dc_kwp']==55.
        assert backend.metadata['shading_energy_counterfactual']
        elapsed[name]=perf_counter()-start
        print(f'USE5 runtime {name}: {elapsed[name]:.6f} s wall, {process_time()-cpu_start:.6f} s CPU',flush=True)
    print(f'USE5 hardware: {platform.machine()} {platform.processor()}; CPUs={os.cpu_count()}; OMP_NUM_THREADS={os.environ.get('OMP_NUM_THREADS', 'unset')}; peak RSS={resource.getrusage(resource.RUSAGE_SELF).ru_maxrss} KiB',flush=True)
    ratio=elapsed['mixed']/elapsed['baseline']
    print(f'USE5 runtime ratio T_mixed/T_baseline={ratio:.6f}; target <= 1.25; physics unchanged',flush=True)
    record_property('runtime_ratio',ratio)
    assert ratio<=1.25,f'R14 runtime budget exceeded: {ratio:.6f}; escalate without reducing physics'
