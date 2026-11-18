
from ..path_manager import PathManager
from .cloud_downloader import CloudForcingDownloader


class AcquisitionService:
    def __init__(self, config, logger, *, registries, services=None):
        self.paths = PathManager(config)
        self.downloader = CloudForcingDownloader(
            config.forecast, logger, registries=registries, services=services
        )

    def plan(self):
        return self.downloader.plan()

    def acquire_forcings(self):
        plan = self.plan()
        return self.downloader.download_forcing_data(
            self.paths.request_dir(plan.request_sha256) / "raw"
        )
