"""Built-in website adapters."""

from watchtower.adapters.base import NotificationEvent, WebsiteAdapter
from watchtower.adapters.jlpt_chennai import JlptChennaiAdapter

__all__ = ("JlptChennaiAdapter", "NotificationEvent", "WebsiteAdapter")
