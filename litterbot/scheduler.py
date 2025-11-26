"""Scheduled cleaning management."""

import logging
from datetime import datetime
from typing import Optional
from pytz import timezone

from .robot_client import RobotClient
from .config import Config


logger = logging.getLogger("litter_robot_daemon")


class ScheduledCleaner:
    """Manages scheduled cleaning triggers."""

    def __init__(self, robot_client: RobotClient, config: Config):
        self.robot_client = robot_client
        self.cleaning_times = config.cleaning_times
        self.timezone = timezone(config.timezone)
        self._last_check_minute: Optional[str] = None  # Track to avoid duplicate triggers

    def should_clean_now(self, last_cleaning_time: Optional[datetime]) -> tuple[bool, Optional[str]]:
        """
        Check if current time matches a scheduled time.

        Returns: (should_clean, time_string)
        - should_clean: True if it's time to trigger a cleaning
        - time_string: The matched time string (HH:MM) or None
        """
        now = datetime.now(self.timezone)
        current_minute = now.strftime('%H:%M')

        # Prevent duplicate triggers within the same minute
        if current_minute == self._last_check_minute:
            return False, None

        self._last_check_minute = current_minute

        # Check if current time matches any scheduled time
        if current_minute in self.cleaning_times:
            # Check if we already cleaned at this time today
            if last_cleaning_time:
                last_clean_minute = last_cleaning_time.astimezone(self.timezone).strftime('%H:%M')
                last_clean_date = last_cleaning_time.astimezone(self.timezone).date()
                today = now.date()

                # Already cleaned at this time today
                if last_clean_date == today and last_clean_minute == current_minute:
                    return False, None

            return True, current_minute

        return False, None

    async def trigger_cleaning(self) -> bool:
        """Trigger a cleaning cycle via robot API."""
        try:
            robot = await self.robot_client.get_robot()
            if not robot:
                logger.error("Could not get robot for scheduled cleaning")
                return False

            logger.info("Triggering scheduled cleaning cycle")
            await robot.start_cleaning()
            logger.info("Scheduled cleaning triggered successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to trigger scheduled cleaning: {e}", exc_info=True)
            return False
