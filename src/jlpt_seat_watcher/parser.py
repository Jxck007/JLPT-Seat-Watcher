"""Compatibility alias for :mod:`watchtower.parser`."""

import sys

from watchtower import parser as _implementation

sys.modules[__name__] = _implementation
