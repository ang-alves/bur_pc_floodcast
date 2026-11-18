
from .store import StoreService


class CDSService(StoreService):
    endpoint = "https://cds.climate.copernicus.eu/api"
    token_environment = "FLOODCAST_CDS_API_KEY"
    dataset = "seasonal-original-single-levels"
