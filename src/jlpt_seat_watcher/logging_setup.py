"""Compatibility alias for :mod:`watchtower.logging_setup`."""

import sys

from watchtower import logging_setup as _implementation

sys.modules[__name__] = _implementation
