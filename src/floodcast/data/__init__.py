

"""Forecast data facade. Provider SDKs and numerical libraries load on demand."""

DATA_VERSION = "0.0.1"
DATA_REVISION = "ffw-ecmwf-data"


def __getattr__(name):
    if name == "DataManager":
        from .data_manager import DataManager

        return DataManager
    if name == "DataConfig":
        from .config import DataConfig

        return DataConfig
    raise AttributeError(name)


__all__ = ["DataManager", "DataConfig"]
