"""Status monitoring with change detection and heartbeat logging."""

import logging
from datetime import datetime
from typing import Optional

from pylitterbot.enums import LitterBoxStatus

from .robot_client import RobotClient
from .state import DaemonState
from .config import Config
from .notifier import Notifier


logger = logging.getLogger("litter_robot_daemon")


class StatusMonitor:
    """Monitors robot status with change detection and heartbeat logging."""

    def __init__(
        self,
        robot_client: RobotClient,
        state: DaemonState,
        config: Config,
        notifier: Notifier,
    ):
        self.robot_client = robot_client
        self.state = state
        self.config = config
        self.notifier = notifier

    async def check_status(self) -> Optional[LitterBoxStatus]:
        """
        Check robot status and log changes immediately.

        Returns current status or None if unavailable.
        Logs:
        - Immediate log when status changes
        - Heartbeat log every N minutes (configurable)
        - Error/warning logs for significant events
        """
        robot = await self.robot_client.get_robot()
        if not robot or not robot.status:
            logger.warning("Could not get robot status")
            return None

        status = robot.status
        self.state.last_check_at = datetime.now().isoformat()

        # Change detection - log immediately when status changes
        if self.state.update_status(status.name):
            # Format: "Status changed: OLD_STATUS -> NEW_STATUS"
            old_status = self.state.last_status or "None"
            logger.info(f"Status changed: {old_status} -> {status.name}")

        # Heartbeat logging - periodic confirmation daemon is alive
        if self._should_log_heartbeat():
            logger.info(f"Heartbeat: Robot status is {status.name}")
            self.state.last_heartbeat_at = datetime.now().isoformat()

        return status

    def _should_log_heartbeat(self) -> bool:
        """Check if it's time for a heartbeat log."""
        if not self.state.last_heartbeat_at:
            return True

        last_heartbeat = datetime.fromisoformat(self.state.last_heartbeat_at)
        elapsed = (datetime.now() - last_heartbeat).total_seconds() / 60
        return elapsed >= self.config.heartbeat_interval_minutes
