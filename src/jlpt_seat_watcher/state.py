"""Compatibility alias for :mod:`watchtower.state`."""

import sys

from watchtower import state as _implementation

sys.modules[__name__] = _implementation
