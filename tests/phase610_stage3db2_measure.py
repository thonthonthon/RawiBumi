"""Fresh-process package verification measurement, with no thresholds.

Run from the repository root:
    python -m tests.phase610_stage3db2_measure /path/to/p96-package
Run the same command in a pre-B2 checkout for a baseline. Package contents
are read only. Larger measurements require independently valid complete
packages; B1's attribution-only synthetic generator is insufficient to
construct reconciled physical, compact and execution-context bindings.
"""
import argparse
import json
from pathlib import Path
import resource
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    args = parser.parse_args()
    from engine.simulation.artifacts import verify_run_package, canonical_object_sha256
    directory = args.package.resolve()
    sizes = {p.relative_to(directory).as_posix(): p.stat().st_size
             for p in sorted(directory.rglob('*')) if p.is_file()}
    start = time.perf_counter()
    report = {'package_path': str(directory), 'artifact_sizes_bytes': sizes}
    try:
        manifest = verify_run_package(directory)
        report.update(success=True, manifest_payload_sha256=manifest['manifest_payload_sha256'],
                      returned_manifest_sha256=canonical_object_sha256(manifest))
    except Exception as exc:
        report.update(success=False, error_type=type(exc).__name__, error=str(exc))
    report['wall_seconds'] = time.perf_counter() - start
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    report['process_peak_rss_bytes'] = peak if sys.platform == 'darwin' else peak * 1024
    print(json.dumps(report, indent=2))
    return 0 if report['success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
