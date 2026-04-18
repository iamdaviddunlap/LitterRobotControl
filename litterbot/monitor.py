"""Status monitoring with change detection and heartbeat logging."""

import logging
from datetime import datetime
from typing import Optional

from pylitterbot.enums import LitterBoxStatus

from .robot_client import RobotClient
from .state import DaemonState
from .config import Config
from .notifier import Notifier
from .classifier import RecoveryAction


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

    def track_oscillation(self, status: LitterBoxStatus, action: RecoveryAction) -> None:
        """Track oscillation patterns during errors."""
        is_error = (action == RecoveryAction.POWER_CYCLE)

        if not self.state.current_error_occurrence:
            return

        occurrence = self.state.current_error_occurrence

        # Track consecutive error vs transient checks
        if is_error:
            occurrence.consecutive_error_checks += 1
        else:
            # Track unique transient states seen
            if status.name not in occurrence.transient_states_seen:
                occurrence.transient_states_seen.append(status.name)

        # Detect oscillation: error → transient → error
        if self.state.last_check_was_error and not is_error:
            # Just transitioned from error to transient
            pass
        elif not self.state.last_check_was_error and is_error:
            # Just transitioned from transient back to error - that's one oscillation
            self.state.oscillation_cycle_count += 1
            occurrence.oscillation_count += 1

            # Mark as oscillating after 3+ cycles
            if occurrence.oscillation_count >= 3:
                if not occurrence.oscillation_detected:
                    occurrence.oscillation_detected = True
                    logger.info(f"Oscillation pattern detected: {occurrence.oscillation_count} cycles")

        self.state.last_check_was_error = is_error
