"""Backward-compatible alias for the JLPT Chennai scraper."""

import sys

from watchtower.adapters.jlpt_chennai import scraper as _implementation

sys.modules[__name__] = _implementation
