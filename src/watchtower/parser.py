"""Backward-compatible alias for the JLPT Chennai parser."""

import sys

from watchtower.adapters.jlpt_chennai import parser as _implementation

sys.modules[__name__] = _implementation
