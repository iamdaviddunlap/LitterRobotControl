"""Notification system for alerts and status updates."""

import logging
from abc import ABC, abstractmethod


logger = logging.getLogger("litter_robot_daemon")


class Notifier(ABC):
    """Abstract base for notification services."""

    @abstractmethod
    async def send(self, title: str, message: str, severity: str = "info") -> bool:
        """Send a notification. Returns True if successful."""
        pass


class LogNotifier(Notifier):
    """Notifier that just logs (for testing or when no webhook configured)."""

    async def send(self, title: str, message: str, severity: str = "info") -> bool:
        level = {
            "error": logging.ERROR,
            "warning": logging.WARNING
        }.get(severity, logging.INFO)
        logger.log(level, f"[NOTIFICATION] {title}: {message}")
        return True


class WebhookNotifier(Notifier):
    """Sends notifications via HTTP webhook (e.g., Discord, Slack, ntfy)."""

    def __init__(self, url: str):
        self.url = url

    async def send(self, title: str, message: str, severity: str = "info") -> bool:
        try:
            import aiohttp
            payload = {"title": title, "message": message, "severity": severity}
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload) as resp:
                    return resp.status < 400
        except Exception as e:
            logger.error(f"Webhook notification failed: {e}")
            return False
