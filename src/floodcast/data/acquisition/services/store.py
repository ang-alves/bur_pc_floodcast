
import os

from ...errors import DataError, DependencyUnavailable


class StoreService:
    endpoint = ""
    token_environment = ""
    dataset = ""

    def __init__(self, client_factory=None):
        self.client_factory = client_factory

    def retrieve(self, part, config, target):
        if part.dataset != self.dataset:
            raise DataError("PRODUCT_MISMATCH", "Dataset does not belong to this service")
        token = os.environ.get(self.token_environment)
        if not token:
            raise DataError(
                "CREDENTIALS_REQUIRED",
                f"Set {self.token_environment}; accept the dataset terms in the store",
            )
        factory = self.client_factory
        if factory is None:
            try:
                from cdsapi import Client
            except ImportError:
                raise DependencyUnavailable("cdsapi>=0.7.7") from None
            factory = Client
        try:
            client = factory(url=self.endpoint, key=token, quiet=True, debug=False)
            client.retrieve(part.dataset, dict(part.payload), str(target))
        except Exception:
            # Do not serialize provider exception text, request URLs or credentials.
            raise DataError(
                "ACQUISITION_FAILED",
                "Store retrieval failed; check permissions, licence and catalogue availability",
            ) from None
