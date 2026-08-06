"""Compatibility alias for :mod:`watchtower.monitor`."""

import sys

from watchtower import monitor as _implementation

sys.modules[__name__] = _implementation
