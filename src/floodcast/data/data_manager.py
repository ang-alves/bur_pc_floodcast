

import logging

from .acquisition.acquisition_service import AcquisitionService
from .config import DataConfig
from .preprocessing.forecast_processor import ForecastProcessor


class DataManager:
    def __init__(self, config, logger=None, *, registries=None, services=None, reader=None):
        self.config = DataConfig.model_validate_json(config.model_dump_json())
        self.logger = logger or logging.getLogger("floodcast.data")
        if registries is None:
            from floodcast.core.registries import Registries

            from .registration import register_data_handlers

            registries = Registries()
            register_data_handlers(registries)
        self.R = registries
        self.acquisition_service = AcquisitionService(
            self.config, self.logger, registries=self.R, services=services
        )
        self.processor = ForecastProcessor(
            self.config, self.logger, registries=self.R, reader=reader
        )

    @classmethod
    def from_file(cls, path, **kwargs):
        return cls(DataConfig.from_file(path), **kwargs)

    def plan(self):
        return self.acquisition_service.plan()

    def acquire_forcings(self):
        return self.acquisition_service.acquire_forcings()

    def run_model_agnostic_preprocessing(self, raw_manifest_path):
        return self.processor.process(raw_manifest_path)

    def validate_readiness(self):
        from .model_ready.readiness import assess_forcing_readiness

        return assess_forcing_readiness(self.config)

    def remap_forcings(self, canonical_manifest_path):
        """Remap every member with the ported SYMFLUENCE remapping components."""
        from .preprocessing.forcing_resampler import ForcingResampler

        return ForcingResampler(self.config, self.logger, registries=self.R).remap(
            canonical_manifest_path
        )

    def prepare_model_forcings(self, remapped_manifest_path):
        """Apply explicit temporal policies and the ported model forcing adapter."""
        from .model_ready.forcing_processor import ModelForcingProcessor

        return ModelForcingProcessor(self.config, self.logger, registries=self.R).process(
            remapped_manifest_path
        )
