"""A-group test package.

This package has no import-time schema or path side effects. Tests use the real
backend schema from the Colostruct checkout. When running from the A-group
development tree, set ``COLOSTRUCT_REPO_ROOT`` to that checkout; when the tests
live inside the checkout, the repository root is discovered automatically.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path


def resolve_repo_root() -> Path:
    """Return the official Colostruct checkout containing the backend schema.

    Resolution order:
    1. ``COLOSTRUCT_REPO_ROOT`` when set;
    2. the parent of this ``tests`` package (the checkout root when tests are
       installed there).

    Raises ``unittest.SkipTest`` with an actionable message when neither
    location contains ``core/pathology_schema.py``.
    """
    candidates: list[Path] = []
    env_root = os.environ.get("COLOSTRUCT_REPO_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())
    candidates.append(Path(__file__).resolve().parents[1])

    for candidate in candidates:
        if (candidate / "core" / "pathology_schema.py").is_file():
            return candidate.resolve()

    raise unittest.SkipTest(
        "Cannot locate the official Colostruct checkout. Set "
        "COLOSTRUCT_REPO_ROOT to the checkout that contains "
        "core/pathology_schema.py, or run the tests from that checkout."
    )
