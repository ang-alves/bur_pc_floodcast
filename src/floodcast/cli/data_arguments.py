"""Forecast CLI arguments; importing help must remain free of data dependencies."""

from __future__ import annotations

from pathlib import Path


def add_data_arguments(parser):
    parser.add_argument(
        "action", choices=("plan", "acquire", "preprocess", "remap", "model-ready", "readiness")
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Forecast TOML; relative paths resolve against this file's directory",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="Input acquisition, canonical, or remapped manifest for the selected action",
    )
