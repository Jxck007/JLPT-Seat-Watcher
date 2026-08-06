"""Run JLPT Seat Watcher continuously."""

from watchtower.cli import main

raise SystemExit(main(["daemon"]))
