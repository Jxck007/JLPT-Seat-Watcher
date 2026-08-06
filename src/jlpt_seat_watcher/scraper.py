"""Compatibility alias for :mod:`watchtower.scraper`."""

import sys

from watchtower import scraper as _implementation

sys.modules[__name__] = _implementation
