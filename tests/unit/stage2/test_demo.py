import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "examples/workflows/stage2_foundation_demo.py"


@pytest.mark.parametrize(
    "args,exit_code,expected",
    [
        (["--outcome", "activate"], 0, "succeeded"),
        (["--outcome", "do_not_activate"], 0, "succeeded"),
        (["--outcome", "indeterminate"], 2, "indeterminate"),
        (["--fail-forecast"], 1, "failed"),
    ],
)
def test_demo_branches_are_synthetic(args, exit_code, expected, tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, str(DEMO), "--data-root", str(tmp_path / "data"), *args],
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == exit_code, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == expected
    assert payload["scope"] == "SYNTHETIC_DEMO_NO_SCIENTIFIC_MODEL_EXECUTED"
    assert Path(payload["manifest"]).is_file()
    if "--fail-forecast" in args:
        assert payload["steps"]["maintain_state"] == "succeeded"
        assert payload["steps"]["report"] == "succeeded"


def test_demo_plan_only_does_not_create_data(tmp_path):
    data = tmp_path / "data"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, str(DEMO), "--data-root", str(data), "--plan-only"],
        env=env,
        check=False,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["executed"] is False
    assert not data.exists()
