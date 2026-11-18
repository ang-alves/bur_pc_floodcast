
from .registry import AcquisitionRegistry


class CloudForcingDownloader:
    def __init__(self, config, logger, *, registries, services=None):
        self.config, self.logger = config, logger
        self.registry = AcquisitionRegistry(registries)
        self.services = services

    def handler(self):
        return self.registry.get_handler(
            self.config.product, self.config, self.logger, services=self.services
        )

    def plan(self):
        return self.handler().plan()

    def download_forcing_data(self, output_dir):
        return self.handler().download(output_dir)
