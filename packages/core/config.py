from __future__ import annotations

import pathlib
from typing import Any, Dict

import yaml


def load_config(path: str) -> Dict[str, Any]:
    with pathlib.Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
