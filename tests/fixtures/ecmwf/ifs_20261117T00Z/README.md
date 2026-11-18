# Recorded ECMWF IFS test input

These files contain an attributed, modified subset of actual ECMWF Open Data
retrieved on 17 November 2026 through the production Floodcast `DataManager`
and `ecmwf-opendata` client. The meteorological values are not synthetic.

- Initialization: 17 November 2026, 00 UTC.
- Model: IFS 50r1, distributed at 0.25 degrees.
- Members: control 0 and perturbed member 1.
- Fields: 2 m temperature, 2 m dew point, 10 m u/v wind, surface pressure,
  total precipitation, downward shortwave and downward longwave radiation.
- Instantaneous steps: 0, 3 and 6 hours. Accumulated fields: 3 and 6 hours.
- Spatial subset: latitude 39–40.5 degrees, longitude -9.5 to -7.5 degrees.
- 42 GRIB messages in 16 files. Original downloaded volume: 20,102,931 bytes.

The original global messages were subset to a 7-by-9 grid and repacked as IEEE
64-bit values. Their selected decoded values were checked for exact equality
before and after repacking. Longitude encoding was normalized modulo 360.
The `provenance.json` records both original and derived file hashes, request
selectors, original public index URLs, observed GRIB metadata and hashes of
the canonical outputs produced directly from the original downloads.

The offline replay test substitutes only remote transport. It exercises the
production GRIB decoder, normalization, publication and cache, and compares
the resulting fields and time bounds to those original canonical values.
It neither contacts ECMWF nor tests current archive availability. This sample
does not establish forecast skill or validate any basin configuration.

## Attribution and licence

Contains modified ECMWF Open Data. Source: [ECMWF](https://www.ecmwf.int/en/forecasts/datasets/open-data).
Licensed under [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).
Modifications: spatial subset and lossless repacking of decoded selected
values for offline software tests. ECMWF has not endorsed these tests.
