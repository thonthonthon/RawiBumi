# Weather providers


This package implements the Phase 6.0B coordinate-driven acquisition boundary.


## Invariant


```text
provider transport
!=
meteorological source product
!=
source-owned resource method
!=
RawiBumi canonical mapping
```


Every request names exactly one `source_id`. Unknown or unavailable sources fail
closed. No adapter may silently choose another meteorological source.


## Open-Meteo historical adapter


Phase 6.0B initially exposes:


```text
open_meteo_archive_era5
    -> models=era5
```


The following Open-Meteo modes are deliberately not used as substitutes:


- `best_match`;
- `era5_seamless`;
- implicit provider-default model selection.


Those modes combine/select multiple upstream products and would erase the explicit
source identity required by Phase 6.0A.


ERA5-Land is also not exposed as a complete PV-resource source in this tranche.
If it is added later, it must remain its own source product and its variable
availability must be handled explicitly rather than filled from ERA5 without a
separate engineering decision.


## Raw snapshot identity


Provider responses may be stored by `FileSystemWeatherSnapshotStore`.


Snapshots are content-addressed by SHA-256:


```text
weather-snapshot://sha256/<digest>
```


Simulation consumes the pinned canonical `WeatherDataset`, never the live API.


## CI


Blocking tests parse frozen response fixtures. Live provider access is not required
for regression tests.