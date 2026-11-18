
"""Transport services: API access only, no product selection or normalization."""


class AcquisitionServices:
    def __init__(self, *, open_data=None, ecds=None, cds=None):
        self.injected = {"open_data": open_data, "ecds": ecds, "cds": cds}

    def retrieve(self, part, config, target):
        service = self.injected[part.transport]
        if service is None:
            if part.transport == "open_data":
                from .ecmwf_open_data import OpenDataService

                service = OpenDataService()
            elif part.transport == "ecds":
                from .ecds import ECDSService

                service = ECDSService()
            else:
                from .cds import CDSService

                service = CDSService()
            self.injected[part.transport] = service
        service.retrieve(part, config, target)
