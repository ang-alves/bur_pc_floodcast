
from ...catalog import variables
from .base_dataset import BaseDatasetHandler


class S2SHandler(BaseDatasetHandler):
    product = "s2s_ecds"

    def expected_kind(self, field):
        return variables(self.product)[field].kind
