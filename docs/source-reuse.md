# Auditable SYMFLUENCE source reuse

Floodcast includes both a preserved source baseline and selected source ports used
by its forecast implementation. These are different deliverables. The preserved
baseline is not imported as an installed SYMFLUENCE package, and its presence does
not mean that all upstream acquisition handlers or historical workflows execute.

The reference is [SYMFLUENCE](https://github.com/symfluence-org/SYMFLUENCE) at commit
`df9b6447080b85ec6566dc7ad4ed901a623ad0bc`. All counts below refer to that exact
revision. No similarity percentage is used to establish reuse: the package records
original bytes, Git blob identities, runtime bytes, explicit adaptations and full
diffs.

## Preserved originals

| Packaged source | Contents | Verification |
| --- | --- | --- |
| `vendor/symfluence-data-df9b6447.tar.gz` | All 205 Python modules under `src/symfluence/data`, plus the exported static import closure and source resources; 903 files total | `vendor/SYMFLUENCE_SOURCE_MANIFEST.json` records path, size, SHA-256 and Git blob SHA-1 for every source file. Its embedded copy must match. |
| `vendor/symfluence-runtime-support-df9b6447.tar.gz` | Two unchanged model adapter originals that are outside the data export's static import closure | The supplemental records in `runtime-source-reuse.json` record the same byte and Git blob identities. |
| `LICENSES/GPL-3.0-or-later.txt` | The complete upstream GPL licence text | Must be byte-identical to the baseline's `LICENSE`. |

The baseline manifest retains its original `runtime_port_validated=false` value.
That flag describes the exported source snapshot. The export does not resolve all
dynamic imports or establish a complete external execution environment.

## Runtime source ports

`docs/runtime-source-reuse.json` is the consolidated map of 18 runtime files. Each
entry identifies its preserved original, source Git blob and SHA-256, runtime
SHA-256, modification classification, explicit changes and forecast usage.
`docs/symfluence-runtime-port.patch` contains their complete source-to-port diffs.
An unchanged source has no diff hunk; its equality is checked by the map.

Source paths in the following table are relative to `src/symfluence`; runtime paths
are relative to `src/floodcast`.

| Source | Runtime destination | Adaptation and actual forecast scope |
| --- | --- | --- |
| `data/preprocessing/resampling/*.py` (9 files) | `data/preprocessing/resampling/*.py` | The full component modules are retained. EASYMORE weight generation/application, file validation and geometry preparation execute through the forecast wrapper. Package exports load lazily. Elevation, historical file processing and point extraction remain optional retained helpers. |
| `data/preprocessing/cfif/*.py` (3 files) | `data/preprocessing/cfif/*.py` | CFIF definitions and conversion implementations are preserved with formatting/type updates. The model-forcing processor uses the variable definitions; importing the package does not imply invoking every converter. |
| `core/mixins/config.py` | `data/preprocessing/resampling/_config.py` | Preserve the configuration mixin; replace its typing-only upstream model import and modernize formatting/types. A separate explicit compatibility view supplies forecast fields. |
| `core/hdf5_safety.py` | `data/preprocessing/resampling/_hdf5_safety.py` | Preserve the HDF5 safety utilities, with formatting/type updates. Remapping invokes the relevant preparation and cache utilities. |
| `models/adapters/base_adapter.py` | `core/modeling/forcing_adapter.py` | Change the ConfigMixin import and typing-only configuration import. Preserve all adapter methods. |
| `models/summa/forcing_adapter.py` | `models/summa/forcing_adapter.py` | Change the base adapter import and remove upstream global registration. Floodcast registers the class explicitly in its application-owned `R`; mappings and methods are unchanged. |
| `data/acquisition/handlers/era5_processing.py` | `data/_upstream/era5_processing.py` | Byte-identical original. The forecast processor calls wind magnitude and specific humidity on the native grid after explicit temporal alignment and physical checks. Other historical helpers are preserved. |
| `data/base_registry.py` | `data/base_registry.py` | Port the lookup and constructor algorithm to an injected application registry and read-only mapping, with explicit versioned component registration. The full interface differs; it is classified as an adapted algorithm rather than an unchanged module. |

All ported files retain the upstream GPL identifier and SYMFLUENCE copyright.
`THIRD_PARTY_NOTICES.forecast-data.md` records attribution and licence scope.
The detailed spatial adaptations and tests are described in
[source-reuse-remapping.md](source-reuse-remapping.md); registry composition is
described in [architecture/forecast-composition.md](architecture/forecast-composition.md).

The new forecast boundary code is separate from this source-port inventory. It
supplies canonical manifests, native ensemble/temporal contracts, strict geometry
identity, cache integrity and publication orchestration. Examples include
`src/floodcast/data/preprocessing/symfluence_bridge.py`,
`src/floodcast/data/preprocessing/forcing_resampler.py` and
`src/floodcast/data/model_ready/forcing_processor.py`. Those files are not presented
as byte copies of the historical upstream facades.

## Verify a downloaded repository

Run from any directory with Python 3.10 or newer:

```bash
python /path/to/bur_pc_floodcast/tools/verify_source_reuse.py
```

The verifier uses only the Python standard library. It needs no upstream clone,
Git command, network access, forecast dependencies or model installation, and does
not import Floodcast. Its default operation is read-only. Exit status `0` reports
verified counts; status `1` reports a missing or mismatching artifact.

It checks both archive hashes, exact source inventories, every original file's
size/SHA-256/Git blob identity, the 205 data-module count, all 18 runtime hashes,
the remapping-specific source map, both source-to-port diffs, retained licence
headers, the GPL text, and repository file references in the architecture docs.
Archive entries are read without extraction; links, unsafe paths and duplicate
members or records are rejected.

After intentionally reviewing and recording a change in the runtime map, regenerate
the patches with:

```bash
python tools/verify_source_reuse.py --write-diffs
python tools/verify_source_reuse.py
```

`--write-diffs` does not refresh source or runtime hashes. It first verifies the
recorded bytes and then writes the two deterministic diffs. A source edit therefore
cannot silently become an accepted port just by regenerating a patch.

This verifies the integrity and internal consistency of the packaged evidence.
The association with the pinned Git tree comes from the source export and checked
Git blob IDs; the verifier does not independently contact GitHub or authenticate a
remote commit. Numerical tests, provider compatibility and hydrological validation
remain separate evidence. In particular, preserving 205 source modules does not
establish that 205 modules execute in the forecast pipeline.
