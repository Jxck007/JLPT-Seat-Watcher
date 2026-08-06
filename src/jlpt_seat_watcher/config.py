"""Compatibility alias for :mod:`watchtower.config`."""

import sys

from watchtower import config as _implementation

sys.modules[__name__] = _implementation
