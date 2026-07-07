"""Project version metadata."""

import os
from pathlib import Path


DEFAULT_VERSION = "1.0"


def _load_version() -> str:
    configured = os.environ.get("APP_VERSION", "").strip()
    if configured:
        return configured

    version_file = Path.cwd() / "VERSION"
    if version_file.is_file():
        value = version_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    return DEFAULT_VERSION


APP_VERSION = _load_version()
