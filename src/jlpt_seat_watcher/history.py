"""Compatibility alias for :mod:`watchtower.history`."""

import sys

from watchtower import history as _implementation

sys.modules[__name__] = _implementation
