# Forecast data composition

The forecast package shares one application-owned `Registries` object with the
Stage 2 facade and orchestrator. Installation records remain in the separate
Stage 1 installation registry.

## Components

| Registry family | Contract | Built-in component IDs |
| --- | --- | --- |
| `R.acquisition_handlers` | `ffw.acquisition/v1` | `ifs_medium_range`, `s2s_ecds`, `seasonal_ecmwf` |
| `R.dataset_handlers` | `ffw.dataset/v1` | `ifs_medium_range`, `s2s_ecds`, `seasonal_ecmwf` |
| `R.forcing_adapters` | `ffw.forcing-adapter/v1` | `summa` |
| `R.steps` | `ffw.step/v1` | `forecast.acquire`, `forecast.normalize`, `forecast.remap`, `forecast.model_ready` |

Registry factories for acquisition, preprocessing and forcing return **classes**.
The lookup facade or processor creates an instance with its explicit configuration.
Step factories return step instances for the corresponding execution. Registering
components never starts a provider request or model execution.

`register_data_handlers(R)` loads built-in implementations in a temporary registry
before checking every destination family. An import failure or existing built-in
ID leaves all application families unchanged. Custom nonconflicting IDs may coexist.
Calling it twice is an error; composition is explicit and does not silently replace
an implementation. `register_forecast_steps(R)` similarly checks all four step IDs
before adding any of them.

## Source reuse boundary

`src/floodcast/data/base_registry.py` ports the lookup algorithm from
[`src/symfluence/data/base_registry.py`](https://github.com/symfluence-org/SYMFLUENCE/blob/df9b6447080b85ec6566dc7ad4ed901a623ad0bc/src/symfluence/data/base_registry.py).

Preserved behavior includes lowercase normalization, handler-class lookup, explicit
unknown-handler failure, deterministic listing, availability checks, and the common
`handler_class(config, logger, **kwargs)` constructor. The original GPL header is
retained. The necessary adaptation replaces class-level access to global `R` with
an injected application registry. A read-only mapping adapter translates the
original lookup contract to Floodcast's versioned component registrations; it does
not duplicate registry state. Forecast preprocessing does not inherit the upstream
implicit hourly timestep: each variable retains its native temporal support until
an explicit model-forcing policy is applied.

## Public composition

```python
from floodcast.core.config import RuntimeConfig
from floodcast.data import DataConfig
from floodcast.data.workflow import compose_forecast_workflow, make_forecast_request
from floodcast.project import Floodcast

config = DataConfig.from_file("examples/forecasts/ifs_medium_range.toml")
app = Floodcast(
    RuntimeConfig(data_root=config.data_root),
    code_identity="your-exact-source-revision",
).with_forecast_data()

# This works for acquisition-only examples, without HRU/model configuration.
definition = compose_forecast_workflow(config, through="canonical")
request = make_forecast_request(config, t0=config.forecast.cycle)
plan = app.plan(definition, request)  # No acquisition or model execution.

# Explicitly starts provider acquisition and normalization:
# record = app.run(definition, request)
```

For the complete forcing graph, use `through="model_ready"` and supply the
`remapping` and `model_forcing` configuration sections. `through="remapped"`
stops after spatial mapping. The helper's T0 argument remains explicit: passing a
cycle time here does not establish that any compatible hydrological restart exists.
This workflow prepares meteorological input; it does not initialize or run SUMMA.

`app.data(config)` creates a `DataManager` using the same `R` and rejects a different
`data_root`. The facade does not automatically compose handlers; call
`with_forecast_data()` first or supply your own registered families.

## Step boundaries and evidence

| Step | Input setting | Required manifest | Output stage |
| --- | --- | --- | --- |
| `forecast.acquire` | `data` | None | Raw forecast |
| `forecast.normalize` | `data`, `acquisition_step` | `acquisition_manifest.json` | Canonical grid |
| `forecast.remap` | `data`, `normalize_step` | `canonical_manifest.json` | HRU fields |
| `forecast.model_ready` | `data`, `remapping_step` | `remapped_manifest.json` | Model forcing files |

Each step checks domain and cycle against the workflow request, verifies all source
step evidence hashes, requires exactly one expected input manifest, and emits
hashes for its manifest and data files. Successful forcing preparation is recorded
as `MODEL_FORCING_COMPLETE_MODEL_EXECUTION_NOT_VALIDATED`; it is not scientific
acceptance of a model run or forecast.

All composed data and forcing-adapter revisions contribute to the workflow
fingerprint. `make_forecast_request` captures target geometry bytes as hashed
inputs; shapefiles include required `.shp`, `.shx`, `.dbf` and `.prj` companions,
and `.cpg` when present. Consequently, a changed geometry cannot silently reuse a
previous completed workflow through the provided helper. The runtime verifies
inputs and outputs again on resume. Completed workflows remain immutable.

Acquisition steps are not declared replay-safe because a provider job may still
exist after interruption. Processing steps use cache and atomic publication and
are declared replay-safe. Provider-specific remote-job reconciliation is separate
from these registry and orchestration guarantees.

## CLI

The main CLI and `python -m floodcast.data` use the same argument and action path:

```bash
floodcast data plan --config examples/forecasts/ifs_medium_range.toml
floodcast data acquire --config forecast.toml
floodcast data preprocess --config forecast.toml --manifest /path/acquisition_manifest.json
floodcast data remap --config forecast.toml --manifest /path/canonical_manifest.json
floodcast data model-ready --config forecast.toml --manifest /path/remapped_manifest.json
```

These commands read forecast configuration, not the installation/runtime TOML
schema. Help and parser imports do not load numerical libraries or model services.
`plan` does not create a data directory or contact a provider. The Stage 1 command
arguments, configuration loading, and exit-status mappings remain unchanged.

## Verification scope

`tests/unit/forecast_integration/test_composition.py` checks application isolation,
atomic registration, custom components, handler lookup, all four step boundaries,
source-evidence checks on resume, forcing-adapter revision fingerprints, facade data
root agreement, and CLI separation. The four-stage boundary test uses controlled
processor outputs to isolate orchestration behavior; it is not a substitute for the
separate numerical remapping and model-forcing integration tests.
