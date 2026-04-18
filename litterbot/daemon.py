"""Main daemon orchestrator for monitoring, recovery, and scheduled cleaning."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from pylitterbot.enums import LitterBoxStatus

from .config import Config
from .state import DaemonState, StateStore, ErrorOccurrence
from .robot_client import RobotClient
from .smart_plug import SmartPlugController
from .notifier import Notifier
from .classifier import classify_status, RecoveryAction
from .recovery import PowerCycleRecovery
from .scheduler import ScheduledCleaner
from .monitor import StatusMonitor
from .analytics import ErrorAnalytics
from .timeout_calculator import TimeoutCalculator


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
        self.timeout_calculator = TimeoutCalculator(config)
        self.analytics = ErrorAnalytics()
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
            # Record self-resolution in history
            if self.state.current_error_occurrence:
                occurrence = self.state.current_error_occurrence
                occurrence.ended_at = datetime.now().isoformat()
                occurrence.duration_minutes = (datetime.fromisoformat(occurrence.ended_at) -
                                              datetime.fromisoformat(occurrence.started_at)).total_seconds() / 60
                occurrence.recovery_method = "self_resolved"
                occurrence.recovery_successful = True

                # Only record errors that persisted longer than minimum threshold
                if occurrence.duration_minutes >= self.config.min_error_duration_minutes:
                    # Add to history (keep last analytics_history_size occurrences)
                    self.state.error_history.append(occurrence)
                    if len(self.state.error_history) > self.config.analytics_history_size:
                        self.state.error_history.pop(0)

                    logger.info(f"Robot self-resolved from {occurrence.error_type} after {occurrence.duration_minutes:.1f} min")
                else:
                    # Brief error - don't record in history
                    logger.info(f"Brief error cleared: {occurrence.error_type} after {occurrence.duration_minutes:.1f} min (below {self.config.min_error_duration_minutes} min threshold)")

                self.state.current_error_occurrence = None
            else:
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

            # Check if this is a post-recovery error (don't reset attempt counter)
            is_post_recovery = self.state.is_post_recovery_error(
                window_minutes=self.config.post_recovery_error_window_minutes
            )

            if is_post_recovery:
                seconds_since_recovery = (now - datetime.fromisoformat(self.state.last_recovery_at)).total_seconds()
                logger.warning(
                    f"Error detected: {status.name} - {seconds_since_recovery:.0f}s after recovery "
                    f"(attempt #{self.state.recovery_attempts + 1} will retry)"
                )
            else:
                # Fresh error - reset attempt counter
                self.state.recovery_attempts = 0
                logger.warning(f"Error detected: {status.name} - starting timer")

            # Create error occurrence for tracking
            self.state.current_error_occurrence = ErrorOccurrence(
                error_type=status.name,
                started_at=now.isoformat(),
            )

            # Initialize oscillation tracking state
            self.state.last_check_was_error = True
            self.state.oscillation_cycle_count = 0

            return

        # Track oscillation pattern
        action = classify_status(status)
        self.monitor.track_oscillation(status, action)

        # Check if error has persisted long enough
        duration = self.state.error_duration_minutes()

        # Calculate adaptive timeout
        adaptive_timeout, timeout_reason = self.timeout_calculator.calculate_timeout(
            self.state, status.name
        )

        # Update occurrence with timeout info
        if self.state.current_error_occurrence:
            self.state.current_error_occurrence.timeout_used_minutes = adaptive_timeout
            self.state.current_error_occurrence.adaptive_timeout_reason = timeout_reason

        # Log milestone with adaptive timeout
        current_minute = int(duration)
        if current_minute in self.config.error_log_milestones and current_minute != self.state.last_error_log_minute:
            logger.warning(
                f"Error persisting: {status.name} ({duration:.1f}/{adaptive_timeout:.0f} min) - {timeout_reason}"
            )
            self.state.last_error_log_minute = current_minute

        if duration < adaptive_timeout:
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

        # Execute recovery with stabilization monitoring
        success = await self.recovery_strategy.execute(
            robot,
            self.state.recovery_attempts,
            stabilization_minutes=self.config.recovery_stabilization_minutes
        )

        # Track recovery time (regardless of success/failure)
        self.state.last_recovery_at = datetime.now().isoformat()

        if success:
            # Record successful recovery in history
            if self.state.current_error_occurrence:
                occurrence = self.state.current_error_occurrence
                occurrence.ended_at = datetime.now().isoformat()
                occurrence.duration_minutes = (datetime.fromisoformat(occurrence.ended_at) -
                                              datetime.fromisoformat(occurrence.started_at)).total_seconds() / 60
                occurrence.recovery_method = "power_cycle"
                occurrence.recovery_attempts = self.state.recovery_attempts
                occurrence.recovery_successful = True

                # Only record errors that persisted longer than minimum threshold
                # (Power-cycled errors are typically >5 min, so this should always pass)
                if occurrence.duration_minutes >= self.config.min_error_duration_minutes:
                    # Add to history (keep last analytics_history_size occurrences)
                    self.state.error_history.append(occurrence)
                    if len(self.state.error_history) > self.config.analytics_history_size:
                        self.state.error_history.pop(0)

                self.state.current_error_occurrence = None

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
