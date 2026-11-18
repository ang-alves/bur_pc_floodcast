
from ...catalog import SEASONAL, variables
from ...contracts import RequestPart
from ..base import BaseAcquisitionHandler


class SeasonalCDSAcquirer(BaseAcquisitionHandler):
    product = SEASONAL

    def build_parts(self):
        f, parts = self.config, []
        for field, leads in sorted(f.fields.items()):
            for chunk in self.chunks(leads):
                payload = {
                    "originating_centre": "ecmwf",
                    "system": f.system,
                    "variable": [variables(SEASONAL)[field].api_name],
                    "year": [f.cycle.strftime("%Y")],
                    "month": [f.cycle.strftime("%m")],
                    "day": ["01"],
                    "leadtime_hour": [str(h) for h in chunk],
                    "data_format": "grib",
                }
                if f.bbox is not None and f.bbox.west < f.bbox.east:
                    payload["area"] = [f.bbox.north, f.bbox.west, f.bbox.south, f.bbox.east]
                parts.append(
                    RequestPart(
                        part_id=f"part-{len(parts):05d}",
                        transport="cds",
                        dataset="seasonal-original-single-levels",
                        role="ensemble",
                        payload=payload,
                    )
                )
        return tuple(parts)
