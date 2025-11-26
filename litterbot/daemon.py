"""Main daemon orchestrator for monitoring, recovery, and scheduled cleaning."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from pylitterbot.enums import LitterBoxStatus

from .config import Config
from .state import DaemonState, StateStore
from .robot_client import RobotClient
from .smart_plug import SmartPlugController
from .notifier import Notifier
from .classifier import classify_status, RecoveryAction
from .recovery import PowerCycleRecovery
from .scheduler import ScheduledCleaner
from .monitor import StatusMonitor


logger = logging.getLogger("litter_robot_daemon")


class LitterRobotDaemon:
    """
    Unified daemon for robot monitoring, recovery, and scheduled cleaning.

    Combines functionality from RecoveryDaemon and AwayAutomationDaemon.
    """

    def __init__(
        self,
        config: Config,
        robot_client: RobotClient,
        plug: SmartPlugController,
        notifier: Notifier,
        state_store: StateStore,
        monitor: StatusMonitor,
        scheduler: Optional[ScheduledCleaner] = None,
    ):
        self.config = config
        self.robot_client = robot_client
        self.plug = plug
        self.notifier = notifier
        self.state_store = state_store
        self.monitor = monitor
        self.scheduler = scheduler
        self.state = state_store.load()
        self.recovery_strategy = PowerCycleRecovery(plug, config.power_cycle_wait_seconds)
        self._running = False

    def _reset_error_tracking(self) -> None:
        """Clear error timers/attempts when state returns to non-error or changes type."""
        self.state.error_start_time = None
        self.state.recovery_attempts = 0
        self.state.error_action_type = None
        self.state.last_error_log_minute = -1

    async def check_and_act(self) -> None:
        """
        Single iteration: check status, recover if needed, handle scheduled cleanings.
        """
        try:
            # 1. Check status (with change detection + heartbeat)
            status = await self.monitor.check_status()
            if not status:
                return

            action = classify_status(status)

            # 2. Handle recovery (if enabled)
            if self.config.enable_recovery:
                if action == RecoveryAction.NONE:
                    await self._handle_normal(status)
                elif action == RecoveryAction.WAIT:
                    await self._handle_transient(status)
                elif action == RecoveryAction.POWER_CYCLE:
                    await self._handle_recoverable_error(status)
                elif action == RecoveryAction.NOTIFY_USER:
                    await self._handle_user_intervention(status)

            # 3. Handle scheduled cleaning (if enabled)
            if self.config.enable_scheduled_cleaning and self.scheduler:
                await self._check_scheduled_cleaning()

            self.state_store.save(self.state)

        except Exception as e:
            logger.error(f"Check failed: {e}", exc_info=True)

    async def _handle_normal(self, status: LitterBoxStatus) -> None:
        """Robot is operating normally."""
        if self.state.error_detected_at:
            logger.info(f"Robot recovered to normal state: {status.name}")
            self._reset_error_tracking()

    async def _handle_transient(self, status: LitterBoxStatus) -> None:
        """Robot is in a transient state (cleaning, cat detected, etc.)."""
        if self.state.error_detected_at:
            # During POWER_CYCLE errors, transient states are part of oscillation
            # Don't clear the timer - let it continue counting
            if self.state.error_action_type == "POWER_CYCLE":
                logger.debug(f"Transient oscillation during error: {status.name}")
                return
            else:
                # Robot genuinely recovered from non-power-cycle error
                logger.info(f"Robot recovered to operational state: {status.name}")
                self._reset_error_tracking()
        else:
            logger.debug(f"Transient state: {status.name}")

    async def _handle_recoverable_error(self, status: LitterBoxStatus) -> None:
        """Robot is in an error that might be fixed by power cycling."""
        now = datetime.now()

        # If this is a new error state, restart the timer/attempts
        if self.state.error_detected_at and self.state.last_status and self.state.last_status != self.state.current_status:
            logger.info(f"New error detected ({status.name}) - resetting previous error timer")
            self._reset_error_tracking()

        # Start tracking error if new
        if not self.state.error_detected_at:
            self.state.error_start_time = now
            self.state.error_action_type = "POWER_CYCLE"
            logger.warning(f"Error detected: {status.name} - starting timer")
            return

        # Check if error has persisted long enough
        duration = self.state.error_duration_minutes()

        # Log only at milestone durations to avoid spam
        current_minute = int(duration)
        if current_minute in self.config.error_log_milestones and current_minute != self.state.last_error_log_minute:
            logger.warning(f"Error persisting: {status.name} ({duration:.1f}/{self.config.error_timeout_minutes} min)")
            self.state.last_error_log_minute = current_minute

        if duration < self.config.error_timeout_minutes:
            return  # Not yet time to recover

        # Check max attempts
        if self.state.recovery_attempts >= self.config.max_recovery_attempts:
            logger.error(f"Max recovery attempts ({self.config.max_recovery_attempts}) reached")
            await self.notifier.send(
                "Litter Robot Recovery Failed",
                f"Robot stuck in {status.name} after {self.state.recovery_attempts} recovery attempts. Manual intervention required.",
                severity="error"
            )
            return

        # Attempt recovery
        self.state.recovery_attempts += 1
        logger.info(f"Attempting recovery #{self.state.recovery_attempts}")

        # Get fresh robot reference for recovery
        robot = await self.robot_client.get_robot()
        if not robot:
            logger.error("Could not get robot for recovery")
            return

        success = await self.recovery_strategy.execute(robot, self.state.recovery_attempts)

        if success:
            self.state.error_detected_at = None
            self.state.recovery_attempts = 0
            self.state.total_recoveries += 1
            await self.notifier.send(
                "Litter Robot Recovered",
                f"Automatic recovery successful after {status.name} error.",
                severity="info"
            )

    async def _handle_user_intervention(self, status: LitterBoxStatus) -> None:
        """Robot needs human help (drawer full, bonnet removed, etc.)."""
        if self.state.error_detected_at and self.state.last_status and self.state.last_status != self.state.current_status:
            logger.info(f"New user-intervention state ({status.name}) - resetting previous error timer")
            self._reset_error_tracking()

        # Only notify once per error occurrence
        if not self.state.error_detected_at:
            self.state.error_start_time = datetime.now()
            self.state.error_action_type = "NOTIFY_USER"
            logger.warning(f"User intervention required: {status.name}")
            await self.notifier.send(
                "Litter Robot Needs Attention",
                f"Robot is in {status.name} state and requires manual intervention.",
                severity="warning"
            )
        else:
            duration = self.state.error_duration_minutes()
            logger.info(f"Awaiting user intervention: {status.name} ({duration:.1f} min)")

    async def _check_scheduled_cleaning(self) -> None:
        """Check and trigger scheduled cleanings."""
        if not self.scheduler:
            return

        # Parse last scheduled cleaning time
        last_cleaning_time = None
        if self.state.last_scheduled_cleaning:
            try:
                last_cleaning_time = datetime.fromisoformat(self.state.last_scheduled_cleaning)
            except (ValueError, TypeError):
                pass

        # Check if it's a scheduled time
        should_clean, time_str = self.scheduler.should_clean_now(last_cleaning_time)

        if not should_clean:
            return

        # Skip if in error state - track as missed
        if self.state.error_detected_at:
            if time_str and time_str not in self.state.missed_cleaning_times:
                logger.warning(f"Skipping scheduled cleaning at {time_str} - robot in error state")
                self.state.missed_cleaning_times.append(time_str)
                self.state_store.save(self.state)
            return

        # If just recovered from error, trigger any missed cleanings first
        if self.state.missed_cleaning_times:
            await self._trigger_missed_cleanings()
            return

        # Normal scheduled cleaning
        logger.info(f"Scheduled cleaning time: {time_str}")
        success = await self.scheduler.trigger_cleaning()

        if success:
            self.state.last_scheduled_cleaning = datetime.now().isoformat()
            self.state_store.save(self.state)
            await self.notifier.send(
                "Scheduled Cleaning Triggered",
                f"Cleaning triggered at scheduled time: {time_str}",
                severity="info"
            )

    async def _trigger_missed_cleanings(self) -> None:
        """Trigger catch-up cleaning for missed scheduled times."""
        if not self.state.missed_cleaning_times:
            return

        missed_count = len(self.state.missed_cleaning_times)
        logger.info(f"Triggering catch-up cleaning for {missed_count} missed schedule(s): {', '.join(self.state.missed_cleaning_times)}")

        success = await self.scheduler.trigger_cleaning()

        if success:
            self.state.last_scheduled_cleaning = datetime.now().isoformat()
            missed_times = self.state.missed_cleaning_times.copy()
            self.state.missed_cleaning_times.clear()
            self.state_store.save(self.state)

            await self.notifier.send(
                "Catch-up Cleaning Triggered",
                f"Triggered catch-up cleaning for {missed_count} missed schedule(s): {', '.join(missed_times)}",
                severity="info"
            )
        else:
            logger.error("Failed to trigger catch-up cleaning - will retry on next check")

    async def run(self) -> None:
        """Main monitoring loop."""
        self._running = True
        self._log_startup()

        # Load any persisted state
        if self.state.error_detected_at:
            logger.info(f"Resuming with error state from {self.state.error_detected_at}")
            logger.info(f"Recovery attempts so far: {self.state.recovery_attempts}")

        try:
            async with self.robot_client:
                while self._running:
                    await self.check_and_act()
                    await asyncio.sleep(self.config.check_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Daemon cancelled")
        finally:
            self.state_store.save(self.state)
            logger.info("State saved. Daemon stopped.")

    def stop(self) -> None:
        """Signal the daemon to stop."""
        self._running = False

    def _log_startup(self):
        """Log daemon configuration on startup."""
        logger.info("=" * 60)
        logger.info("Litter Robot Daemon Starting")
        logger.info("=" * 60)
        logger.info(f"Check interval: {self.config.check_interval_seconds}s")
        logger.info(f"Heartbeat interval: {self.config.heartbeat_interval_minutes} min")
        logger.info(f"Error timeout: {self.config.error_timeout_minutes} min")
        logger.info(f"Max recovery attempts: {self.config.max_recovery_attempts}")
        logger.info(f"Recovery enabled: {self.config.enable_recovery}")
        logger.info(f"Scheduled cleaning enabled: {self.config.enable_scheduled_cleaning}")
        if self.config.enable_scheduled_cleaning and self.scheduler:
            logger.info(f"Cleaning times: {', '.join(self.config.cleaning_times)} {self.config.timezone}")
        logger.info("=" * 60)
