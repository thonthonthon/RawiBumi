"""Isolated bootstrap: never import the caller's __main__ or browser API."""
from __future__ import annotations
import json
from multiprocessing.connection import Connection
import os
from pathlib import Path
import sys


def main():
    from .parallel import _process_identity
    from .prepared import prepare_directional_receiver,calculate_prepared_direct_beam_shadow
    from .sky import calculate_sky_visibility
    from .ground import calculate_ground_visibility
    bootstrap=json.loads(Path(sys.argv[1]).read_text())
    connection=Connection(bootstrap['fd'])
    try:
        tag,compiled,configuration,ids=connection.recv()
        if tag != 'initialize': raise ValueError('invalid exact worker initialization')
        self_shading=bool(configuration['self_shading_enabled'])
        prepared={rid:prepare_directional_receiver(compiled,receiver_id=rid,self_shading_enabled=self_shading) for rid in ids}
        connection.send(('ready',len(prepared)))
        while True:
            if not connection.poll(1.):
                if _process_identity(bootstrap['parent_pid']) != bootstrap['parent_start']: break
                continue
            tag,channel,selected,source,resolution=connection.recv()
            if tag != 'query': raise ValueError('invalid exact worker command')
            results={}
            for rid in selected:
                if channel == 'beam':
                    result=calculate_prepared_direct_beam_shadow(prepared[rid],sun_vector_xyz=source)
                elif channel == 'sky':
                    result=calculate_sky_visibility(compiled,receiver_id=rid,self_shading_enabled=self_shading,resolution=resolution,prepared_query=prepared[rid])
                elif channel == 'ground':
                    result=calculate_ground_visibility(compiled,receiver_id=rid,self_shading_enabled=self_shading,resolution=resolution,prepared_query=prepared[rid])
                else: raise ValueError('unknown exact shading channel')
                results[rid]=result
            metrics={rid:dict(p._bounds.metrics) for rid,p in prepared.items() if p._bounds is not None}
            connection.send(('result',results,metrics))
    except (EOFError,BrokenPipeError):
        pass
    except BaseException as exc:
        try: connection.send(('error',f'{type(exc).__name__}: {exc}'))
        except (OSError,EOFError): pass
        raise
    finally:
        connection.close()


if __name__ == '__main__': main()
