
from ...catalog import IFS
from ...contracts import RequestPart
from ...ecmwf_profiles import resolve_config_profiles
from ..base import BaseAcquisitionHandler


class IFSOpenDataAcquirer(BaseAcquisitionHandler):
    product = IFS

    def build_parts(self):
        f = self.config
        access = resolve_config_profiles(f)["access"]
        parts = []
        roles = (["control"] if 0 in f.members else []) + (["perturbed"] if any(f.members) else [])
        for role in roles:
            for field, leads in sorted(f.fields.items()):
                for chunk in self.chunks(leads):
                    selection = access[
                        "control_selection" if role == "control" else "perturbed_selection"
                    ]
                    payload = {
                        "date": f.cycle.strftime("%Y%m%d"),
                        "time": f.cycle.hour,
                        **selection,
                        "levtype": "sfc",
                        "param": [field],
                        "step": list(chunk),
                    }
                    if role == "perturbed":
                        payload["number"] = [m for m in f.members if m != 0]
                    parts.append(
                        RequestPart(
                            part_id=f"part-{len(parts):05d}",
                            transport="open_data",
                            role=role,
                            payload=payload,
                        )
                    )
        return tuple(parts)
