# SYMFLUENCE source reuse and forecast remapping

The consolidated [source reuse inventory](source-reuse.md) covers these 14 ports
and the four additional model-adapter, ERA5-processing and registry ports. Run
`python tools/verify_source_reuse.py` to check their packaged originals, runtime
hashes, licence text and complete diffs without an external upstream checkout.

## Source and scope

The source is the real SYMFLUENCE checkout at commit
`df9b6447080b85ec6566dc7ad4ed901a623ad0bc`, not a reconstruction from an architecture diagram.
The source tree contains 205 Python files under `src/symfluence/data`.
The repository's upstream snapshot preserves that tree; the runtime port described
here reuses the complete implementations of the following modules:

| SYMFLUENCE source | Floodcast destination |
| --- | --- |
| `data/preprocessing/resampling/*.py` — all 9 modules | `data/preprocessing/resampling/*.py` |
| `data/preprocessing/cfif/*.py` — all 3 modules | `data/preprocessing/cfif/*.py` |
| `core/mixins/config.py` | `data/preprocessing/resampling/_config.py` |
| `core/hdf5_safety.py` | `data/preprocessing/resampling/_hdf5_safety.py` |

These are source ports under GPL-3.0-or-later, retaining the upstream copyright
headers. `remapping-source-provenance.json` records source paths, Git blob IDs,
source SHA-256, port SHA-256 and modification classifications.
`symfluence-remapping-port.patch` records the complete source-to-port diff.
Formatting and type-annotation modernization follow this repository's Ruff rules;
the original source remains available for byte comparison.

The forecast-facing `ForcingResampler` coordinates the ported components.
The old historical facade's paths, filename/year selection and point fallback are
not suitable forecast contracts. The actual weight-generation and application
algorithms come from `RemappingWeightGenerator` and `RemappingWeightApplier`,
whose original complete implementations are present and execute at runtime.

## Executed path

1. Read and verify the canonical manifest, every file hash and the requested
   domain, product, cycle, native members, leads, variables and ECMWF provenance.
2. Read authoritative HRU geometry, require CRS, unique positive integer IDs,
   valid nonempty polygons, positive areas and optional exact expected ID order.
3. Construct source-cell polygons from the exact regular latitude/longitude
   centres. The construction follows the source ERA5 handler's polygon loop.
4. Check each HRU's covered area against the configured tolerance in EPSG:6933.
   Inadequate coverage is an error; enlarge the acquired forecast bbox.
5. Generate EASYMORE intersection weights using the ported generator.
   Geometry preprocessing operates only on private copies of already validated
   HRUs, so the original source's duplicate-ID dissolve/renumber paths are never
   invoked by the forecast facade.
6. Reuse the exact weights with the ported applier, separately for every native
   ensemble member. Each input to EASYMORE is time × latitude × longitude.
7. Reassemble member × lead_time × hru output. Restore original member IDs,
   member roles, reference time, valid times and interval bounds. Verify that
   EASYMORE returned the same valid times and exact HRU IDs, then restore the
   authoritative HRU order.
8. Publish all requested variables and `remapped_manifest.json` together.
   Verify inputs and geometry again before publication.

The remapped result contains HRU centres as `latitude(hru)` and
`longitude(hru)`, `hruId(hru)` and `hru_area(hru)` in square metres.
It remains `model_ready=false`: time alignment and model-specific forcing
contracts are separate processing stages.

## Why the port differs from upstream

| Adaptation | Reason |
| --- | --- |
| Replace four upstream infrastructure imports with local compatibility imports | Reuse the component implementation without loading the entire historical SYMFLUENCE workflow and configuration model. |
| Explicit compatibility view for domain, forcing and path fields | Forecast configuration is already validated. No silent dict fallback or fabricated historical configuration is used. |
| Lazy component exports | Unused elevation/point helper dependencies are not mandatory for forecast remapping. |
| Add dewpoint, mean-sea-level pressure and the forecast radiation CF names to detected variables | Preserve meteorological identity across the original per-file remapper. Mean-sea-level pressure is not converted to surface pressure. |
| Provide grid resolution for 2 × 2 grids as well as singleton grids in the generator | Exercise a legitimate small-grid area intersection. The public forecast boundary rejects singleton coordinates without explicit cell bounds. |
| Validate finite data instead of a 100 KB minimum file size | Small basins and short forecast windows produce valid small NetCDFs. |
| Execute each member independently | The original component contract is time × HRU and does not define an ensemble dimension. |
| Exact cache identity and integrity validation outside the original generator | A source-cell count cannot distinguish equal-size grids with shifted centres; filename existence cannot prove file integrity. |
| Strict preflight for HRU IDs and geometry | Existing domain identity must not be silently dissolved, repaired or renumbered. |

The original point-scale, elevation and file-processing components are retained.
The forecast path does not call their automatic tiny-grid bypass, nearest-cell
replication, elevation correction or historical filename/year selection.
No hidden interpolation or lapse-rate correction is performed.

## Cache and publication

Weight identity includes:

- complete source centre and inferred cell-bound coordinates;
- ordered HRU IDs and polygon WKB after explicit CRS conversion;
- declared geometry version;
- domain ID;
- spatial coverage tolerance;
- port revision, pinned upstream commit and installed EASYMORE version.

The cache manifest hashes every produced weight and geometry file.
The selected CSV, companion NetCDF and target shapefile components must all
appear in the verified inventory. Unsafe paths, symbolic links, duplicate
inventory entries, missing files and altered bytes are rejected.

Changing the real HRU geometry while keeping the same path and declared version
changes the cache and publication identities. An existing valid result is not
overwritten. Corrupt caches are preserved for inspection, not silently reused.

The public read-only verification API is:

```python
from floodcast.data.preprocessing.forcing_resampler import ForcingResampler

remapper = ForcingResampler(config, logger, registries=R)
result = remapper.remap(canonical_manifest_path)
verified = remapper.verify(result.manifest_path)
```

The reusable numerical boundary is:

```python
from floodcast.data.preprocessing.symfluence_bridge import remap_dataset

dataset, provenance = remap_dataset(
    canonical_dataset,
    config.remapping.target_path,
    config.remapping.hru_id_field,
    cache_dir,
    domain_id=config.domain_id,
    geometry_version=config.remapping.geometry_version,
    minimum_coverage=config.remapping.minimum_coverage,
    expected_hru_ids=config.remapping.expected_hru_ids,
    logger=logger,
)
```

It accepts several canonical variables and preserves native ensemble members.
Nonlinear transformations such as wind magnitude and specific humidity should
be computed on the source grid before this boundary.

## Verification and limits

`tests/unit/forecast_remapping/test_symfluence_remapping.py` executes real
EASYMORE, GeoPandas, Shapely, pyproj and NetCDF I/O. The main test uses a 2 × 2
grid, two different HRU shapes, two native ensemble members and two forecast
intervals. It checks a one-cell HRU exactly and an HRU spanning unequal-area
latitude cells against an independently calculated area-weighted value.

Other checks cover cache reuse, grid changes without cell-count changes,
geometry changes without path changes, member and interval preservation,
multiple CFIF variables, duplicate/reordered HRU IDs, missing CRS, missing
spatial coverage, singleton grids and corrupted cached weights.
The product integration tests in
`tests/unit/forecast_data/test_store_remapping.py` additionally execute S2S
GRIB2 and seasonal GRIB1 encoding/decoding with ecCodes, cached acquisition with
an injected local transport, canonical publication and real EASYMORE remapping.
They verify 24-hour precipitation/radiation bounds and integrals, S2S daily-mean
temperature semantics, explicitly selected seasonal system 51, extra downloaded
members filtered without renumbering, and preservation of seasonal native
members 2 and 7. The S2S daily mean fails conversion to an instantaneous model
state; incomplete forcing sets fail rather than substituting mean-sea-level
pressure. Read-only verification performs no remote retrieval.
Meteorological fields and HRU polygons in these tests are synthetic fixtures.
Passing these tests is software and spatial-contract evidence, not basin
calibration, forecast skill or operational flood-warning validation.

The implemented public grid adapter supports increasing regular rectilinear
latitude/longitude grids with at least two centres along each axis and at most
250,000 cells. Wrapped dateline cells, curvilinear grids and singleton coordinate
arrays require an explicit bounds/grid adapter and currently produce errors.
Configure a basin-scale acquisition bbox before remapping a global forecast.
Temporal downscaling, model forcing completeness and radiation/precipitation
interval treatment remain explicit responsibilities of the subsequent stage.
