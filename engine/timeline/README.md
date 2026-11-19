# Simulation timeline

Phase 3.1 converts canonical interval-start weather into a strict simulation timeline.

For every weather row the timeline records:

```text
interval_start
interval_end
interval_midpoint
evaluation_time
duration_seconds
```

For V0.1 quasi-steady simulation:

```text
evaluation_time
    =
interval_midpoint
    +
time_semantics.representative_time.solar_evaluation_offset_minutes
```

Timeline construction never resamples implicitly. The requested simulation timestep must
match the current canonical weather series resolution; explicit weather resampling belongs to
the weather transformation layer.

The builder rejects:

- timezone-naive timestamps;
- duplicates/non-monotonic timestamps;
- cadence that disagrees with `series_resolution_seconds`;
- unsupported representative-time policies;
- mismatched requested simulation timestep.
