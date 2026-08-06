"""Send a high-priority test notification."""

from watchtower.cli import main

raise SystemExit(main(["notify-test", "--priority", "high"]))
