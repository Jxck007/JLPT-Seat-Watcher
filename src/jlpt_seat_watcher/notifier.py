"""Compatibility alias for :mod:`watchtower.notifier`."""

import sys

from watchtower import notifier as _implementation

sys.modules[__name__] = _implementation
