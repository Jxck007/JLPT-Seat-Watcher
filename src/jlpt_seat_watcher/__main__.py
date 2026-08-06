"""Backward-compatible ``python -m jlpt_seat_watcher`` entry point."""

from watchtower.cli import main

raise SystemExit(main())
