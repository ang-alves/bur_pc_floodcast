
from ...catalog import variables
from .base_dataset import BaseDatasetHandler


class IFSHandler(BaseDatasetHandler):
    product = "ifs_medium_range"

    def expected_kind(self, field):
        return variables(self.product)[field].kind
