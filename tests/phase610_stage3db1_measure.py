"""Orchestrator-run measurements; no timing or memory acceptance thresholds.

Run: python -m tests.phase610_stage3db1_measure /path/to/attribution.json
Generate and measure without physics:
python -m tests.phase610_stage3db1_measure /tmp/b1.json --generate-intervals 2000 --report /tmp/b1-measurements.json
Each aggregation runs in a fresh child; generation is outside measurements.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import tracemalloc
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--operation', choices=['legacy', 'streaming'])
    parser.add_argument('--generate-intervals', type=int)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    path = Path(args.path)
    if args.generate_intervals is not None:
        if args.operation is not None or args.generate_intervals < 1:
            parser.error('generation requires parent mode and a positive interval count')
        from tests.unit.test_phase610_stage3db1_attribution_stream import _source, specs
        # Do not overwrite an existing artifact when generating test input.
        with tempfile.TemporaryDirectory(prefix='rawibumi-b1-fixture-') as directory:
            generated = _source(Path(directory), specs('mixed', args.generate_intervals))
            with path.open('xb') as output, generated.open('rb') as source:
                import shutil
                shutil.copyfileobj(source, output)
    if args.operation is None:
        measurements = []
        for operation in ('legacy', 'streaming'):
            completed = subprocess.run(
                [sys.executable, '-m', 'tests.phase610_stage3db1_measure',
                 str(path), '--operation', operation], check=True,
                capture_output=True, text=True)
            measurements.append(json.loads(completed.stdout))
        if measurements[0]['energy_summary_sha256'] != measurements[1]['energy_summary_sha256']:
            raise ValueError('legacy and streaming energy summary hashes differ')
        report = {'source_path': str(path.resolve()), 'source_bytes': path.stat().st_size,
                  'generated_intervals': args.generate_intervals,
                  'measurements': measurements,
                  'hashes_equal': True}
        rendered = json.dumps(report, indent=2) + '\n'
        if args.report is not None:
            args.report.write_text(rendered, encoding='utf-8')
        print(rendered, end='')
        return
    from tests.unit.test_phase610_stage3db1_attribution_stream import legacy
    from engine.simulation.attribution_energy import aggregate_persisted_attribution
    action = legacy if args.operation == 'legacy' else aggregate_persisted_attribution
    tracemalloc.start()
    start = time.perf_counter()
    result = action(path)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({'operation': args.operation, 'wall_seconds': elapsed,
                      'tracemalloc_peak_bytes': peak,
                      'energy_summary_sha256': result.energy_summary_sha256}))


if __name__ == '__main__':
    main()
