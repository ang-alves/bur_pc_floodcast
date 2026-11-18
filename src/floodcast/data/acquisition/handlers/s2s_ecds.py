
from ...catalog import S2S, variables
from ...contracts import RequestPart
from ..base import BaseAcquisitionHandler


class S2SECDSAcquirer(BaseAcquisitionHandler):
    product = S2S

    def build_parts(self):
        f, parts = self.config, []
        roles = (["control"] if 0 in f.members else []) + (["perturbed"] if any(f.members) else [])
        for role in roles:
            for field, leads in sorted(f.fields.items()):
                for chunk in self.chunks(leads):
                    payload = {
                        "origin": "ecmwf",
                        "forecast_type": role + "_forecast",
                        "level_type": "single_level",
                        "variable": [variables(S2S)[field].api_name],
                        "year": [f.cycle.strftime("%Y")],
                        "month": [f.cycle.strftime("%m")],
                        "day": [f.cycle.strftime("%d")],
                        "time": ["00:00"],
                        "leadtime_hour": [f"{h:03d}" for h in chunk],
                        "data_format": "grib",
                    }
                    payload["grid"] = "1.5/1.5"
                    if f.bbox is not None and f.bbox.west < f.bbox.east:
                        payload["area"] = [f.bbox.north, f.bbox.west, f.bbox.south, f.bbox.east]
                    # No unsupported member-number field. All perturbed members are fetched.
                    parts.append(
                        RequestPart(
                            part_id=f"part-{len(parts):05d}",
                            transport="ecds",
                            dataset="s2s-forecasts",
                            role=role,
                            payload=payload,
                        )
                    )
        return tuple(parts)
