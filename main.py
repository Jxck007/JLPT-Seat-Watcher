"""Run JLPT Seat Watcher continuously."""

from jlpt_seat_watcher.cli import main

raise SystemExit(main(["daemon"]))
