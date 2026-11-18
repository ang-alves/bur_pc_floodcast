# SPDX-License-Identifier: GPL-3.0-or-later
# Architecture adapted from SYMFLUENCE df9b6447080b85ec6566dc7ad4ed901a623ad0bc.
# See docs/architecture/forecast-data-source-map.md and THIRD_PARTY_NOTICES.forecast-data.md.

"""Data failures have stable codes and must not imply absence of flood risk."""


class DataError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class DependencyUnavailable(DataError):
    def __init__(self, package: str):
        super().__init__(
            "OPTIONAL_DEPENDENCY_MISSING", f"Install the forecast-data dependencies: {package}"
        )
