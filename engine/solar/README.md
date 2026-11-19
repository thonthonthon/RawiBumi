# Solar geometry

Phase 3.1 implements the first numerical solar-position layer.

Current model:

```text
solar_position.nrel_spa.pvlib.v0.1
```

Implementation:

```python
pvlib.solarposition.spa_python(..., how="numpy", numthreads=1)
```

The canonical azimuth convention is:

```text
0°   North
90°  East
180° South
270° West
```

Solar position is evaluated at the timeline representative time:

```text
interval midpoint + explicit solar_evaluation_offset_minutes
```

Outputs are interval-start indexed and include:

- apparent zenith;
- true zenith;
- apparent elevation;
- true elevation;
- azimuth;
- equation of time;
- the exact evaluation timestamp used.

Pressure uses canonical weather pressure when complete, otherwise standard-atmosphere pressure
derived from site elevation. Temperature uses canonical ambient temperature when complete,
otherwise the SPA 12 °C default. The source used is recorded in the result metadata.

The numerical benchmark `SOL-POS-001` is the published NREL SPA reference case frozen in
`tests/benchmarks/solar_position_nrel_spa.yaml`.
