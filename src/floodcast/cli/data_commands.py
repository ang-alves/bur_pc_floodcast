"""Data command dispatch, independent of installation/runtime configuration."""

from __future__ import annotations

import json
import tomllib


def run_data(args, config=None, *, json_output=True):
    from pydantic import ValidationError

    from floodcast.core.errors import FloodcastError
    from floodcast.data.data_manager import DataManager
    from floodcast.data.errors import DataError

    manifest_methods = {
        "preprocess": "run_model_agnostic_preprocessing",
        "remap": "remap_forcings",
        "model-ready": "prepare_model_forcings",
    }
    if args.action in manifest_methods and args.manifest is None:
        raise FloodcastError(
            "INVALID_CONFIG", "forecast-data", f"{args.action} requires --manifest"
        )
    try:
        manager = DataManager.from_file(args.config)
        if args.action == "plan":
            result = manager.plan()
        elif args.action == "readiness":
            result = manager.validate_readiness()
        elif args.action == "acquire":
            result = manager.acquire_forcings()
        else:
            result = getattr(manager, manifest_methods[args.action])(args.manifest.resolve())
    except (ValidationError, tomllib.TOMLDecodeError) as exc:
        raise FloodcastError("INVALID_CONFIG", "forecast-data", str(exc)) from exc
    except DataError as exc:
        raise FloodcastError("VALIDATION_FAILED", "forecast-data", f"{exc.code}: {exc}") from exc
    if hasattr(result, "model_dump"):
        result = result.model_dump(mode="json")
    print(json.dumps(result, indent=2))
    return 0
