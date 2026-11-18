# ECMWF provider contracts and verification

Reviewed on 17 November 2026. This is an implementation evidence record, not a
hydrological or operational validation certificate.

## Product identity and the reused profile resolver

`floodcast.data.ecmwf_profiles` is the resolver from the earlier
`ffw_symfluence_source_reuse_20261117.zip`, integrated into the forecast
configuration and acquisition plan. Its product-specific model and distribution
profiles participate in the request hash and are carried into canonical output.
It keeps the SYMFLUENCE source commit, IFS model cycle, distribution profile,
forecast reference time and seasonal system as separate identities.

| Product | Reviewed access contract | Temporal support relevant to forcing |
|---|---|---|
| IFS medium range | `ecmwf-opendata`, `model=ifs`; control `oper/fc`, perturbed `enfo/pf`; explicit `0p25` or `0p1` | 00/12 UTC: steps 0–144 every 3 h, then 150–360 every 6 h. 06/18 UTC: steps 0–144 every 3 h. |
| ECMWF S2S | `https://ecds.ecmwf.int/api`, dataset `s2s-forecasts`, `origin=ecmwf`, separate control/perturbed requests | `2t` and `2d` are daily means; wind is 6-hourly; precipitation is accumulated in kg m-2; downward radiation is accumulated energy at daily cadence. |
| ECMWF seasonal | `https://cds.climate.copernicus.eu/api`, `seasonal-original-single-levels`, `originating_centre=ecmwf`, explicit `system` | Temperature, dew point and wind are 6-hourly; precipitation and downward radiation are daily accumulated fields. The implemented subset does not contain surface pressure. |

Sources: [Open Data product definition](https://www.ecmwf.int/en/forecasts/datasets/open-data),
[ECDS API setup](https://ecds.ecmwf.int/how-to-api),
[S2S parameter definitions](https://confluence.ecmwf.int/spaces/S2S/pages/26903293/Parameters),
[seasonal dataset](https://cds.climate.copernicus.eu/datasets/seasonal-original-single-levels?tab=overview),
[seasonal parameter encodings](https://confluence.ecmwf.int/spaces/CKB/pages/212446622/Parameters+GRIB+encoding+details).

ECDS does not offer the old WebAPI `number` selector for perturbed S2S requests.
The acquisition retrieves the returned ensemble and the normalizer selects the
requested native member IDs without renumbering. This behaviour follows the
[ECMWF API migration examples](https://confluence.ecmwf.int/spaces/DAC/pages/540541961/Examples+of+the+current+and+future+retrieval+requests).

## Version boundaries

- Medium-range 50r1 starts on **12 May 2026 at 06 UTC**. The former date-only
  guard incorrectly excluded the 06, 12 and 18 UTC runs on that date.
- S2S 50r1 starts on **13 May 2026 at 00 UTC**. The S2S model history independently
  dates 48r1 to 27 June 2023 and 49r1 to 12 November 2024.
- The 20 October 2026 distribution update introduces `0p1`, separate surface and
  pressure-level files at that resolution, later publication, and changed GRIB
  packing precision. It does not introduce a new IFS model cycle. Because the
  announcement does not establish an initialization-hour cutover, that day's
  configuration must explicitly select its distribution profile.
- `system=51` denotes the CDS SEAS5.1 representation; it is not IFS cycle 50r1.
  ECMWF's system 5 and 51 integrations are the same, but the spatial
  interpolation changed. Remapping caches must therefore include the actual
  grid and selected system identity.

Sources: [50r1 implementation](https://confluence.ecmwf.int/spaces/FCST/pages/567162191/Implementation+of+IFS+Cycle+50r1),
[S2S model history](https://confluence.ecmwf.int/spaces/S2S/pages/47288128/ECMWF+Model),
[SEAS5 contribution](https://confluence.ecmwf.int/spaces/CKB/pages/83404143/Description+of+SEAS5-v20171101+C3S+contribution).

The historical resolver stops at the reviewed history date. The configuration
bridge also supports later forecast dates through an explicit pinned profile:
IFS requires `expected_ifs_cycle="50r1"` and
`distribution_profile="open-data-2026-10-20"`; S2S requires
`expected_ifs_cycle="50r1"`; seasonal requires `system="51"`.
Provenance labels this selection `explicit_pinned_profile_beyond_reviewed_history`
instead of pretending the future model cycle was inferred. GRIB must confirm
the corresponding model identifier or seasonal system. A later provider upgrade
therefore requires a reviewed policy update rather than silent acceptance.
Reforecast version identity cannot be inferred from its historical valid date
and remains a separately required product policy.

## Decoding and normalization checks

The reader checks ECMWF centre, regular grid and spacing, message length/shape,
cycle, member, field, units, statistical processing, and the requested forecast
type. For the enabled IFS 50r1 access profile it also compares the atmospheric
`generatingProcessIdentifier` against the documented value 161. A seasonal
system encoded in the GRIB must match the explicit CDS selection.

Observed GRIB edition, model identifier, table version, forecast type, stream
and seasonal system are preserved separately from the timeline-derived cycle.
Table versions are recorded, not substituted using a date-based assumption.

Native ecCodes tests exposed a compatibility issue absent from mocked decoders:
statistically processed S2S temperatures can decode to dedicated mean IDs
`228004` and `235168`. The S2S catalog accepts these and the legacy daily-mean
identifiers while still requiring `stepType=avg`, Kelvin and an explicit
24-hour interval. An instantaneous field cannot be accepted through an alias.
See the [temperature parameter definition](https://codes.ecmwf.int/grib/param-db/167)
and [ecCodes statistical parameter changes](https://confluence.ecmwf.int/spaces/MTG2US/pages/402637221/Changes+in+ecCodes+version+2.35.0+compared+to+the+previous+version).

Accumulated precipitation and radiation are differenced only when the encoded
windows support it, then divided by their actual durations. Unexplained negative
increments, overlapping windows, missing selected members, duplicate messages,
mixed grids and non-finite output fail before canonical publication.

## Verification layers

`tests/unit/forecast_data/test_ecmwf_profiles.py` reuses the migration kit's
boundary tests and tests the live configuration/plan integration.
`tests/unit/forecast_data/test_native_grib.py` creates actual GRIB1/GRIB2 binary
messages with ecCodes and reads them through the production decoder, including
precipitation conversion, ensemble identity, daily means and rejection of wrong
model/system identifiers. These generated meteorological fields are synthetic.

### Actual IFS acquisition and replay

The production acquisition and normalization path was also exercised against
ECMWF Open Data for the **17 November 2026 00 UTC** run: control plus perturbation
1, eight meteorological fields, steps 0/3/6 h for instantaneous fields and 3/6 h
for accumulated fields. The SDK downloaded **42 messages in 16 assets,
20,102,931 bytes**. ecCodes decoded those original global messages and the
processor published all eight canonical files for a 7-by-9 regional grid.

The messages actually encoded `generatingProcessIdentifier=161` and
`tablesVersion=32`. The latter is retained as observed even though the general
50r1 announcement describes a transition to table 35; it does not override the
received representation. This is why scientific model identity and GRIB
representation are recorded independently.

A small attributed subset is included at
`tests/fixtures/ecmwf/ifs_20261117T00Z/`. Its 42 messages were spatially subset and
repacked as IEEE64, with exact equality checks on the decoded retained values.
`test_recorded_ifs.py` verifies that the offline replay reproduces the canonical
values and interval bounds from the original global downloads, using recorded
hashes. Only transport is substituted during this replay; ecCodes and the
production normalizer run normally. The fixture provenance contains original
and derived hashes and the CC-BY-4.0 attribution.

Tests with substituted clients verify request construction, cache behaviour and
failure publication. They do not prove server authorization, service
availability or the meteorological validity of a forecast. ECDS and CDS live
acceptance requires the user's relevant account and accepted dataset licence.

The scientific limitations remain explicit: S2S daily means require a justified
temporal policy before subdaily hydrological use, and the selected S2S/seasonal
subsets do not provide the time-varying ensemble surface pressure needed for the
SUMMA forcing contract. Mean sea-level pressure is not silently substituted.
