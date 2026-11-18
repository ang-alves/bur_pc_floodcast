# Integrated ECMWF forecast data

This guide describes the integrated repository, superseding the earlier ZIP's
canonical-only status. Baseline Floodcast commit:
`39cd5511a0f85d778e11ec85e0289364449c4b15`.
Reused SYMFLUENCE commit: `df9b6447080b85ec6566dc7ad4ed901a623ad0bc`.

## Executable path and ownership

| Stage | Entry point | Result |
| --- | --- | --- |
| Planning | `DataManager.plan()` | Versioned provider requests; no download |
| Acquisition | `acquire_forcings()` | GRIB files, inventory and `acquisition_manifest.json` |
| Preprocessing | `run_model_agnostic_preprocessing(raw_manifest)` | One canonical NetCDF per variable and `canonical_manifest.json` |
| HRU remapping | `remap_forcings(canonical_manifest)` | `member × lead_time × hru`, geometry/weight provenance and `remapped_manifest.json` |
| SUMMA forcing | `prepare_model_forcings(remapped_manifest)` | One `forcing.nc` and `forcingFileList.txt` per member; `forcing_manifest.json` |

The facade delegates to acquisition services, product handlers, the forecast
processor, ported SYMFLUENCE remapping components and the ported SUMMA forcing
adapter. Provider semantics stay out of `WorkflowOrchestrator`. The Stage 1
installation registry and scientific runtime retain their existing responsibilities.

The application owns `R.steps`, `R.model_adapters`, `R.acquisition_handlers`,
`R.dataset_handlers` and `R.forcing_adapters`. Handler composition is explicit,
atomic, lazy and isolated between application instances. No import installs a
model, inspects Docker, downloads a dataset or creates a global mutable registry.

## Installation

From the repository root in the selected Python 3.12–3.14 environment:

```bash
python -m pip install -e ".[forecast]"
```

`requirements-forecast-data.txt` references this same extra. Scientific dependencies
load when their stage is called. Stage 1's pinned `pydantic` and `filelock` stay
unchanged. The existing Pixi lock was regenerated to include the optional-extra
metadata; its default/dev dependency resolution is unchanged. It does not lock
or install the forecast extra. The verification environment is recorded separately.

## Separate product contracts

| Product | API | Configuration | Temporal/physical distinction |
| --- | --- | --- | --- |
| `ifs_medium_range` | `ecmwf-opendata` | Explicit initialization, `0p25`/`0p1`, native members | Control is `oper/fc`; perturbations `enfo/pf`; preserve both without duplication |
| `s2s_ecds` | `cdsapi`, ECDS endpoint | `s2s-forecasts`, ECMWF origin | Separate product with delayed availability; temperature/dewpoint daily means; precipitation mass accumulation |
| `seasonal_ecmwf` | `cdsapi`, CDS endpoint | `seasonal-original-single-levels`, ECMWF centre and explicit `system` | Native member IDs and source cadence preserved; system is separate from IFS cycle |

The supported parameter subset is declared in `data/catalog.py`. The actual GRIB
metadata must agree with the selected product; aliases never override units or
statistical processing. The source-reuse kit's ECMWF profile resolver is now used
by configuration, provider request generation, cache identity and provenance.
See [provider verification](ecmwf-provider-verification.md) for authoritative links,
cycle boundaries and the observed GRIB table-version difference.

For dates after the documented review window, select the reviewed profile explicitly:

- IFS: `expected_ifs_cycle = "50r1"` and `distribution_profile = "open-data-2026-10-20"`.
- S2S: `expected_ifs_cycle = "50r1"`.
- Seasonal: `system = "51"`.

These pins are validated against actual encoded metadata. They do not promise
availability or infer a future model upgrade. A new provider cycle/system requires
a reviewed profile update. Reforecasts are not silently substituted for forecasts.

ECDS and CDS use separate credentials: `FLOODCAST_ECDS_API_KEY` and
`FLOODCAST_CDS_API_KEY`. The user must have accepted the relevant dataset terms.
Do not put keys in configuration, source files or reports. No authenticated ECDS/CDS
download was exercised in this delivery.

## Configuration and CLI

`examples/forecasts/ifs_to_summa.toml` is a complete example containing all eight
IFS source variables, two members, an HRU geometry and explicit time policies.
Its polygons are **synthetic**, not a calibrated basin. Other examples demonstrate
the separate provider catalogues. File paths resolve relative to the TOML file;
Python API paths must already be absolute.

```bash
floodcast data plan --config examples/forecasts/ifs_to_summa.toml
floodcast data readiness --config examples/forecasts/ifs_to_summa.toml
floodcast data acquire --config examples/forecasts/ifs_to_summa.toml
```

Each stage returns the next manifest path. Pass that exact path to the next stage:

```bash
floodcast data preprocess --config basin.toml --manifest /absolute/raw/acquisition_manifest.json
floodcast data remap --config basin.toml --manifest /absolute/canonical/canonical_manifest.json
floodcast data model-ready --config basin.toml --manifest /absolute/remapped/remapped_manifest.json
```

`python -m floodcast.data` delegates to the same parser. `readiness` is explicitly a
configuration assessment; it cannot certify unseen files.

Open Data is a rolling archive. Change the initialization to a genuinely available
cycle before requesting new data. There is no implicit `latest` or fallback to an
older/incomplete cycle.

## Remapping from the original implementation

The runtime invokes SYMFLUENCE's complete `RemappingWeightGenerator` and
`RemappingWeightApplier` implementations through a forecast boundary. It calls the
historical time-by-HRU operation separately for each native member and restores
forecast coordinates afterwards. CFIF, configuration helpers and supporting
resampling modules are also ported; the original full tree remains separately
preserved for audit. See [source reuse](../source-reuse-remapping.md) and
[the exact runtime inventory](../runtime-source-reuse.json).

HRU IDs, order, geometry version and CRS are explicit. Areas and coverage are
computed in EPSG:6933. Gaps, duplicate IDs, invalid polygons and incomplete source
coverage fail before publication. The historical tiny-grid point-extraction
fallback is not invoked. A genuine 2×2 grid is remapped by polygon intersections.

The weights cache includes complete grid coordinates and bounds, target polygon
bytes, IDs/order, domain, geometry version, algorithm revision and EASYMORE version.
Files and hashes are verified before reuse. Same cell count, filename or declared
geometry version alone does not establish identity.

Supported geometry: regular latitude/longitude grid with at least two centres per
axis, no wrapped antimeridian, up to 250,000 source cells. Crop to the basin plus a
cell margin. Single-cell axes without supplied cell bounds and curvilinear grids
need a separate grid adapter; they produce explicit errors now.

## Time policies and SUMMA

Canonical files retain per-variable lead times and `valid_time_bounds`. Accumulated
precipitation is converted into mass flux and accumulated radiation into mean flux
using the **actual encoded duration**, including the first acquired interval.

The model-forcing configuration declares target window and timestep. For fluxes:

- `interval_policy = "conservative"` aggregates complete native intervals.
- `interval_policy = "uniform"` additionally distributes each native interval
  uniformly into finer intervals, preserving its integral. This is an explicit
  modelling assumption, not newly observed hourly rainfall or radiation.

For instantaneous states:

- `instant_policy = "exact"` requires observations at each target interval start.
- `instant_policy = "linear"` interpolates within the covered source interval.

Neither policy extrapolates, fills gaps, changes daily mean states into instantaneous
states or combines ensemble members. Outputs use interval-start timestamps and
explicit time bounds; `data_step` declares the timestep in seconds.

Wind magnitude and specific humidity use the original upstream calculation helpers
**on the native grid before spatial averaging**. Humidity uses the documented
Magnus water formulation and real surface pressure. Physical ranges are checked
before and after remapping. No default pressure, arbitrary climatology, lapse
correction, bias correction or measurement-height adjustment is supplied.

The original `SUMMAForcingAdapter` maps CFIF variables to `airtemp`, `pptrate`,
`SWRadAtm`, `LWRadAtm`, `spechum`, `windspd` and `airpres`. Each selected native member
gets its own NetCDF and file list with unchanged HRU IDs. Actual HRU geometry/order,
model measurement heights and basin assumptions still need to match the model assets.

`model_ready=true` means the forcing-file contract passed. The manifest separately
states `scientific_validation=not_run` and `model_execution=not_run`. Model state T0,
parameters, routing topology, hydrological validation and model execution remain
outside this data conversion.

The selected S2S and seasonal catalogues lack the needed time-varying ensemble
surface pressure. Those products complete acquisition, canonicalization and HRU
remapping; SUMMA preparation raises an explicit missing-input error. S2S daily mean
temperature presents a further temporal limitation. Mean sea-level pressure is
never treated as surface pressure.

## Application workflow

```python
from floodcast.core.config import RuntimeConfig
from floodcast.data import DataConfig
from floodcast.data.workflow import compose_forecast_workflow, make_forecast_request
from floodcast.project import Floodcast

config = DataConfig.from_file("examples/forecasts/ifs_to_summa.toml")
app = Floodcast(
    RuntimeConfig(data_root=config.data_root),
    code_identity="the-reviewed-source-commit-or-content-hash",
).with_forecast_data()
workflow = compose_forecast_workflow(config, through="model_ready")
request = make_forecast_request(config, t0=config.forecast.cycle)
plan = app.plan(workflow, request)  # No provider access.
record = app.run(workflow, request)
```

For a meteorological-only workflow the explicit T0 labels the requested origin;
it does not certify a hydrological restart. Physical-state selection remains with
the Stage 2 state service. Choose `through="remapped"` for S2S/seasonal.

Acquisition errors, missing members or semantic mismatches block downstream steps.
Published datasets are complete and immutable; interrupted private staging is not
published. Retoma/resume verifies graph, configuration, component revisions, input
geometry and output hashes. ECDS/CDS persistent job reconciliation across a lost
connection is not implemented; inspect the remote request before retrying a
possibly submitted acquisition.

## Reproduce the evidence without credentials

```bash
python examples/workflows/ifs_data_offline_demo.py --output data/ifs_offline_demo
python -B -m pytest -p no:cacheprovider
python tools/verify_source_reuse.py
```

The demonstration uses the bundled spatial subset of an actual ECMWF IFS download;
only transport is replaced. ecCodes, NetCDF, GIS, EASYMORE, model forcing and
orchestration execute normally. Geometry is synthetic and no model binary runs.

[Live IFS verification](../verification/live-ifs.md) records the actual remote
acquisition, four-stage run, unchanged terminal replay, independent spatial
calculation and conservation checks. S2S/seasonal tests encode synthetic values
into actual GRIB1/GRIB2, then use the same real decoder/remapper. They do not prove
live ECDS/CDS access or meteorological/hydrological skill.
