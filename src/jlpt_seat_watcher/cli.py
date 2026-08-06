"""Compatibility alias for :mod:`watchtower.cli`."""

import sys

from watchtower import cli as _implementation

sys.modules[__name__] = _implementation
