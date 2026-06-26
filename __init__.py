from __future__ import annotations

import sys
from pathlib import Path

_src = Path(__file__).with_name("src")
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from hermes_tag import register  # noqa: E402

__all__ = ["register"]
