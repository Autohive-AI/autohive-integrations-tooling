#!/usr/bin/env python3
"""Compatibility CLI for the canonical HiveUp config sync check."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hiveup.checks.config_sync import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
