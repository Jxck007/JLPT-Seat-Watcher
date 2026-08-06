"""Compatibility alias for :mod:`watchtower.models`."""

import sys

from watchtower import models as _implementation

sys.modules[__name__] = _implementation
