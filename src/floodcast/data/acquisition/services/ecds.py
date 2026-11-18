
from .store import StoreService


class ECDSService(StoreService):
    endpoint = "https://ecds.ecmwf.int/api"
    token_environment = "FLOODCAST_ECDS_API_KEY"
    dataset = "s2s-forecasts"
