# Weather resolution conversion


Weather resolution conversion is explicit and versioned.


The current deterministic baseline supports integer-ratio conversion.


## Aggregation


Higher-resolution interval means are aggregated using equal-duration arithmetic means.
For interval-average irradiance this preserves integrated energy exactly.


## Disaggregation


The current baseline is:


```text
algorithm = interval_mean_hold
algorithm_version = 0.1
```


Every child interval receives the source interval-average value. Irradiance therefore
satisfies:


```text
sum(child interval energy) = source interval energy
```


within numerical tolerance.


This is a conservative **energy-preserving baseline**, not a claim of reconstructed
subhourly weather variability.


The simulation specification prefers a future solar-geometry-informed intrainterval shape
that is normalized back to source energy. The exact shaping model remains an open v0.2
decision, so no hidden interpolation is added in Phase 3.8.


Any working cadence finer than the native source resolution must remain visibly derived.


Provider-generated native subhourly data are different: a Meteonorm/provider one-minute
series may itself be synthetic upstream, but RawiBumi must preserve that provider
provenance rather than relabeling it as RawiBumi disaggregation.


The Phase 3 temporal-execution layer exposes native cadence, input-series cadence, working
simulation cadence, transformation method, and interval-level lineage.