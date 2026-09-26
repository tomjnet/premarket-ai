"""The optional C++20 module ``premarket_fastpath`` (``cpp/fastpath``).

The ai-api image installs it as a wheel. Without it, the pure-Python
reference implementations in ``normalize`` and ``simhash`` are used, which
return the same results (checked by the parity tests), only slower.
``PREMARKET_FASTPATH=required`` turns a missing module into an error, so an
image can't silently fall back.
"""

from __future__ import annotations

import os
import types

try:
    import premarket_fastpath as _module
except ImportError:  # pragma: no cover - depends on the image
    _module = None


class FastpathMissingError(RuntimeError):
    """PREMARKET_FASTPATH=required, but the module isn't installed."""


def module() -> types.ModuleType | None:
    """The native module, or None when it isn't installed."""
    return _module


def backend() -> str:
    """``native`` or ``python``: which implementation is in use."""
    return "python" if _module is None else "native"


def check_required() -> None:
    """Fails when PREMARKET_FASTPATH=required and the module is missing.

    Raises:
        FastpathMissingError: The module is required but not installed.
    """
    required = os.environ.get("PREMARKET_FASTPATH", "").strip().lower()
    if required == "required" and _module is None:
        raise FastpathMissingError(
            "PREMARKET_FASTPATH=required but premarket_fastpath isn't "
            "installed (build the ai-api image with the fastpath context)"
        )
