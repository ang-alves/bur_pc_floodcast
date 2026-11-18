from ...catalog import variables
from .base_dataset import BaseDatasetHandler


class SeasonalHandler(BaseDatasetHandler):
    product = "seasonal_ecmwf"

    def expected_kind(self, field):
        return variables(self.product)[field].kind
