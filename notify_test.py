"""Send a high-priority test notification."""

from jlpt_seat_watcher.cli import main

raise SystemExit(main(["notify-test", "--priority", "high"]))
