# SYMFLUENCE source reuse in the integrated repository

Reference commit: `df9b6447080b85ec6566dc7ad4ed901a623ad0bc`.
The two input deliverables were the forecast-data implementation and the original
source-reuse kit. The cumulative forecast patch also supplied the Stage 2 foundation.

## Preserved source versus running code

The original **205 Python files under `src/symfluence/data`** are preserved
byte-for-byte in `vendor/symfluence-data-df9b6447.tar.gz`, with statically identified
support modules and resources. This source archive is not installed as a second
SYMFLUENCE package and does not introduce a global upstream `R`.

The executable transplants are tracked separately in `runtime-source-reuse.json`:
resampling components, CFIF, configuration/HDF5 helpers, the registry lookup,
meteorological calculation helpers, the forcing-adapter base and SUMMA adapter.
The latter runtime modules actually execute in the tested data path. Dormant
upstream utilities remain clearly identified; source preservation is not a claim
that every historical handler is enabled in Floodcast.

| Responsibility | Runtime treatment |
| --- | --- |
| DataManager / acquisition service / downloader delegation | Integrated forecast-specific facades from the earlier ZIP, with real registry/configuration links |
| BaseRegistry lookup | Ported original resolution algorithm with application-owned `R` |
| IFS / S2S / seasonal handlers | Forecast-specific implementations with separate acquisition and preprocessing families |
| ECMWF profile resolver | Reused source-reuse kit module, now called by configuration, requests and provenance |
| ForcingResampler facade | Forecast wrapper coordinating ported generator/applier, explicit HRU identity and per-member operations |
| Nine resampling modules | Complete source ports, with documented imports and forecast boundary corrections |
| CFIF | Original definitions/converters used by the port and SUMMA transformation |
| ERA5 meteorological helpers | Original complete module preserved; wind/humidity functions used, ERA5 deaccumulation heuristics not called for forecasts |
| ForcingAdapter and SUMMAForcingAdapter | Original class implementations with scoped import/registration adaptations |
| Historical observation/attribute acquisition and unrelated datasets | Original source archived; not activated in the operational forecast path |

## Why the boundaries change

An upstream historical time axis is insufficient to identify forecast initialization,
member and valid interval. The wrapper retains those identities and calls the
historical remapper per member. The old small-grid point extraction, geometry
repair/renumbering and weak cache identity are unsuitable as implicit forecast
fallbacks and are bypassed or replaced with explicit validation.

The Stage 1 `RuntimeConfig` is retained for execution/installation. `DataConfig`
adds forecast, remapping and model-forcing contracts. A narrow typed view supplies
the fields consumed by the reused remapping components; it is not a fictitious
complete `SymfluenceConfig`. Neither original core is overwritten.

The source archives, upstream Git blob identities, current hashes and diffs make
reuse inspectable. Run `python tools/verify_source_reuse.py` without a source clone
or network access. The old migration/export scripts remain useful for refreshing
source, but are no longer the only delivered functionality.
