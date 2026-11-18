
from ...errors import DataError, DependencyUnavailable


class OpenDataService:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory

    def retrieve(self, part, config, target):
        factory = self.client_factory
        if factory is None:
            try:
                from ecmwf.opendata import Client
            except ImportError:
                raise DependencyUnavailable("ecmwf-opendata") from None
            factory = Client
        try:
            client = factory(
                source=config.source,
                model="ifs",
                resol=config.resolution,
                infer_stream_keyword=False,
                maximum_retries=2,
                retry_after=2,
            )
            client.retrieve(request=dict(part.payload), target=str(target))
        except Exception:
            # SDK exceptions may embed signed URLs. Do not retain their strings.
            raise DataError(
                "ACQUISITION_FAILED", "Open Data retrieval failed; no cycle fallback was attempted"
            ) from None
