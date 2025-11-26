#!/usr/bin/env python3
"""
Away Automation v2 - Unified Litter Robot Monitoring Daemon

Combines error monitoring/recovery with scheduled cleaning automation.

Features:
- Fully async with proper connection management
- Smart error classification (power-cycleable vs user-intervention)
- Automatic error recovery via smart plug control
- Scheduled cleaning at configured times
- Skip cleanings during error states
- Catch-up missed cleanings after recovery
- State persistence for crash recovery
- Webhook notification support
"""

import asyncio
import json
import logging
import signal
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Optional, Callable, Any, List

from dotenv import dotenv_values
from kasa import Discover, Credentials
from pylitterbot import Account
from pylitterbot.enums import LitterBoxStatus
from pylitterbot.robot import Robot
from pytz import timezone


# ============================================================================
# Configuration
# ============================================================================

@dataclass
class Config:
    """Type-safe configuration with validation."""
    # Whisker API
    whisker_username: str
    whisker_password: str

    # Smart plug
    kasa_username: str
    kasa_password: str
    smart_plug_ip: str

    # Timing
    check_interval_seconds: int = 60
    error_timeout_minutes: int = 30
    power_cycle_wait_seconds: int = 7
    post_recovery_wait_seconds: int = 120  # Check every 2 min during recovery
    max_recovery_attempts: int = 3

    # Persistence
    state_file: Path = field(default_factory=lambda: Path("data/state/away_automation_state.json"))

    # Notifications
    webhook_url: Optional[str] = None

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "Config":
        """Load configuration from .env file."""
        config = dotenv_values(env_path)

        required = ["WHISKER_USERNAME", "WHISKER_PASSWORD",
                    "KASA_USERNAME", "KASA_PASSWORD", "SMART_PLUG_IP"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

        return cls(
            whisker_username=config["WHISKER_USERNAME"],
            whisker_password=config["WHISKER_PASSWORD"],
            kasa_username=config["KASA_USERNAME"],
            kasa_password=config["KASA_PASSWORD"],
            smart_plug_ip=config["SMART_PLUG_IP"],
            check_interval_seconds=int(config.get("CHECK_INTERVAL_SECONDS", 60)),
            error_timeout_minutes=int(config.get("ERROR_TIMEOUT_MINUTES", 30)),
            power_cycle_wait_seconds=int(config.get("POWER_CYCLE_WAIT_SECONDS", 7)),
            max_recovery_attempts=int(config.get("MAX_RECOVERY_ATTEMPTS", 3)),
            webhook_url=config.get("WEBHOOK_URL"),
        )


# ============================================================================
# Logging Setup
# ============================================================================

def setup_logging(log_file: str = "data/logs/away_automation_v2.log") -> logging.Logger:
    """Configure logging with both file and console output."""
    logger = logging.getLogger("away_automation_v2")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


# ============================================================================
# State Classification
# ============================================================================

class RecoveryAction(Enum):
    """What action should be taken for an error state."""
    NONE = auto()           # Normal operation, no action needed
    WAIT = auto()           # Transient state, wait and see
    POWER_CYCLE = auto()    # Attempt automatic recovery via power cycle
    NOTIFY_USER = auto()    # Requires human intervention, send alert


# Categorize all LitterBoxStatus values by recovery action
STATUS_ACTIONS: dict[LitterBoxStatus, RecoveryAction] = {
    # Normal states - no action needed
    LitterBoxStatus.READY: RecoveryAction.NONE,
    LitterBoxStatus.CLEAN_CYCLE_COMPLETE: RecoveryAction.NONE,
    LitterBoxStatus.OFF: RecoveryAction.NONE,

    # Transient states - wait and see
    LitterBoxStatus.CLEAN_CYCLE: RecoveryAction.WAIT,
    LitterBoxStatus.EMPTY_CYCLE: RecoveryAction.WAIT,
    LitterBoxStatus.CAT_DETECTED: RecoveryAction.WAIT,
    LitterBoxStatus.POWER_UP: RecoveryAction.WAIT,
    LitterBoxStatus.POWER_DOWN: RecoveryAction.WAIT,
    LitterBoxStatus.PAUSED: RecoveryAction.WAIT,  # User might have paused intentionally

    # Power-cycleable errors - automatic recovery possible
    LitterBoxStatus.OVER_TORQUE_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.DUMP_POSITION_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.HOME_POSITION_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.DUMP_HOME_POSITION_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.PINCH_DETECT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.CAT_SENSOR_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.CAT_SENSOR_TIMING: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.CAT_SENSOR_INTERRUPTED: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.STARTUP_CAT_SENSOR_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.STARTUP_PINCH_DETECT: RecoveryAction.POWER_CYCLE,

    # User intervention required - notify but don't auto-recover
    LitterBoxStatus.DRAWER_FULL: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.DRAWER_FULL_1: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.DRAWER_FULL_2: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.STARTUP_DRAWER_FULL: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.BONNET_REMOVED: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.OFFLINE: RecoveryAction.NOTIFY_USER,
}


def classify_status(status: LitterBoxStatus) -> RecoveryAction:
    """Determine what action to take for a given status."""
    return STATUS_ACTIONS.get(status, RecoveryAction.NOTIFY_USER)


# ============================================================================
# State Persistence
# ============================================================================

@dataclass
class MonitorState:
    """Persistent state that survives daemon restarts."""
    # Recovery tracking
    current_status: Optional[str] = None
    error_detected_at: Optional[str] = None  # ISO format
    recovery_attempts: int = 0
    last_check_at: Optional[str] = None
    last_notification_at: Optional[str] = None
    total_recoveries: int = 0

    # Scheduled cleaning tracking
    last_scheduled_cleaning: Optional[str] = None  # ISO timestamp of last triggered cleaning
    missed_cleaning_times: List[str] = field(default_factory=list)  # Times missed during errors

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> "MonitorState":
        return cls(**json.loads(data))

    @property
    def error_start_time(self) -> Optional[datetime]:
        if self.error_detected_at:
            return datetime.fromisoformat(self.error_detected_at)
        return None

    @error_start_time.setter
    def error_start_time(self, value: Optional[datetime]):
        self.error_detected_at = value.isoformat() if value else None

    def error_duration_minutes(self) -> float:
        if not self.error_start_time:
            return 0
        return (datetime.now() - self.error_start_time).total_seconds() / 60


class StateStore:
    """Persists monitor state to disk."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> MonitorState:
        """Load state from disk, or return fresh state if not found."""
        if self.path.exists():
            try:
                return MonitorState.from_json(self.path.read_text())
            except (json.JSONDecodeError, TypeError) as e:
                logger.warning(f"Could not load state file: {e}")
        return MonitorState()

    def save(self, state: MonitorState) -> None:
        """Persist state to disk."""
        self.path.write_text(state.to_json())


# ============================================================================
# Robot Client
# ============================================================================

class RobotClient:
    """Manages connection to Whisker API with automatic reconnection."""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self._account: Optional[Account] = None
        self._connected = False

    async def connect(self) -> None:
        """Establish connection to Whisker API."""
        if self._connected:
            return

        self._account = Account()
        await self._account.connect(
            username=self.username,
            password=self.password,
            load_robots=True
        )
        self._connected = True
        logger.info("Connected to Whisker API")

    async def disconnect(self) -> None:
        """Close connection."""
        if self._account and self._connected:
            try:
                await self._account.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._connected = False
                self._account = None

    async def ensure_connected(self) -> None:
        """Reconnect if necessary."""
        if not self._connected:
            await self.connect()

    async def get_robot(self) -> Optional[Robot]:
        """Get the first robot, reconnecting if necessary."""
        await self.ensure_connected()

        if not self._account or not self._account.robots:
            logger.error("No robots found in account")
            return None

        robot = self._account.robots[0]
        await robot.refresh()
        return robot

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.disconnect()


# ============================================================================
# Smart Plug Controller
# ============================================================================

class SmartPlugController:
    """Controls TP-Link Kasa smart plug."""

    def __init__(self, ip: str, username: str, password: str):
        self.ip = ip
        self.credentials = Credentials(username, password)

    async def power_cycle(self, off_duration: int = 7) -> bool:
        """Turn off, wait, turn on. Returns True if successful."""
        plug = None
        try:
            plug = await Discover.discover_single(self.ip, credentials=self.credentials)
            await plug.update()

            logger.info(f"Turning OFF smart plug at {self.ip}")
            await plug.turn_off()

            await asyncio.sleep(off_duration)

            logger.info(f"Turning ON smart plug at {self.ip}")
            await plug.turn_on()

            await plug.update()
            logger.info(f"Power cycle complete (plug is {'ON' if plug.is_on else 'OFF'})")
            return plug.is_on

        except Exception as e:
            logger.error(f"Power cycle failed: {e}")
            return False
        finally:
            if plug:
                try:
                    await plug.disconnect()
                except Exception:
                    pass

    async def is_on(self) -> Optional[bool]:
        """Check if plug is currently on."""
        try:
            plug = await Discover.discover_single(self.ip, credentials=self.credentials)
            await plug.update()
            result = plug.is_on
            await plug.disconnect()
            return result
        except Exception as e:
            logger.error(f"Could not check plug status: {e}")
            return None


# ============================================================================
# Notifier
# ============================================================================

class Notifier(ABC):
    """Abstract base for notification services."""

    @abstractmethod
    async def send(self, title: str, message: str, severity: str = "info") -> bool:
        """Send a notification. Returns True if successful."""
        pass


class LogNotifier(Notifier):
    """Notifier that just logs (for testing or when no webhook configured)."""

    async def send(self, title: str, message: str, severity: str = "info") -> bool:
        level = {"error": logging.ERROR, "warning": logging.WARNING}.get(severity, logging.INFO)
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


# ============================================================================
# Recovery Strategies
# ============================================================================

class RecoveryStrategy(ABC):
    """Base class for recovery strategies."""

    @abstractmethod
    async def execute(self, robot: Robot, attempt: int) -> bool:
        """Execute recovery. Returns True if robot is recovered."""
        pass


class PowerCycleRecovery(RecoveryStrategy):
    """Recovery via smart plug power cycle."""

    def __init__(self, plug: SmartPlugController, wait_seconds: int = 7):
        self.plug = plug
        self.wait_seconds = wait_seconds

    async def execute(self, robot: Robot, attempt: int) -> bool:
        logger.info(f"=== Power Cycle Recovery (Attempt {attempt}) ===")

        # Step 1: Power cycle
        logger.info("Step 1: Power cycling...")
        if not await self.plug.power_cycle(self.wait_seconds):
            logger.error("Power cycle failed")
            return False

        # Step 2: Wait for robot to boot
        logger.info("Step 2: Waiting for robot to initialize...")
        await asyncio.sleep(30)  # Give robot time to boot

        # Step 3: Check status
        logger.info("Step 3: Checking robot status...")
        await robot.refresh()
        status = robot.status

        if status and classify_status(status) == RecoveryAction.NONE:
            logger.info(f"Recovery successful! Robot is now: {status.name}")
            return True

        # Step 4: If still in error, try triggering a clean cycle
        if status and classify_status(status) == RecoveryAction.POWER_CYCLE:
            logger.info("Step 4: Triggering clean cycle to clear error...")
            try:
                await robot.start_cleaning()
                await asyncio.sleep(60)  # Wait for cycle to progress
                await robot.refresh()
                status = robot.status

                if status and classify_status(status) in (RecoveryAction.NONE, RecoveryAction.WAIT):
                    logger.info(f"Recovery successful after clean cycle! Status: {status.name}")
                    return True
            except Exception as e:
                logger.error(f"Failed to trigger clean cycle: {e}")

        logger.warning(f"Recovery incomplete. Robot status: {status.name if status else 'Unknown'}")
        return False


# ============================================================================
# Scheduled Cleaner
# ============================================================================

class ScheduledCleaner:
    """Manages scheduled cleaning triggers."""

    # ===== SCHEDULED CLEANING CONFIGURATION =====
    # Modify these values to change the schedule:
    CLEANING_TIMES = ['02:29', '11:29', '16:29', '23:29']  # HH:MM format (24-hour)
    TIMEZONE = 'US/Mountain'  # pytz timezone string
    # ===========================================

    def __init__(self, robot_client: RobotClient):
        self.robot_client = robot_client
        self.timezone = timezone(self.TIMEZONE)
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
        if current_minute in self.CLEANING_TIMES:
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


# ============================================================================
# Recovery Daemon (Base)
# ============================================================================

class RecoveryDaemon:
    """Main orchestrator for robot monitoring and recovery."""

    def __init__(
        self,
        config: Config,
        robot_client: RobotClient,
        plug: SmartPlugController,
        notifier: Notifier,
        state_store: StateStore,
    ):
        self.config = config
        self.robot_client = robot_client
        self.plug = plug
        self.notifier = notifier
        self.state_store = state_store
        self.state = state_store.load()
        self.recovery_strategy = PowerCycleRecovery(plug, config.power_cycle_wait_seconds)
        self._running = False

    async def check_and_recover(self) -> None:
        """Single check iteration: get status, evaluate, recover if needed."""
        try:
            robot = await self.robot_client.get_robot()
            if not robot:
                logger.warning("Could not get robot")
                return

            status = robot.status
            if not status:
                logger.warning("Robot returned no status")
                return

            self.state.current_status = status.name
            self.state.last_check_at = datetime.now().isoformat()

            action = classify_status(status)

            # Handle based on action type
            if action == RecoveryAction.NONE:
                await self._handle_normal(status)
            elif action == RecoveryAction.WAIT:
                await self._handle_transient(status)
            elif action == RecoveryAction.POWER_CYCLE:
                await self._handle_recoverable_error(robot, status)
            elif action == RecoveryAction.NOTIFY_USER:
                await self._handle_user_intervention(status)

            self.state_store.save(self.state)

        except Exception as e:
            logger.error(f"Check failed: {e}", exc_info=True)

    async def _handle_normal(self, status: LitterBoxStatus) -> None:
        """Robot is operating normally."""
        if self.state.error_detected_at:
            logger.info(f"Robot recovered to normal state: {status.name}")
            self.state.error_detected_at = None
            self.state.recovery_attempts = 0

    async def _handle_transient(self, status: LitterBoxStatus) -> None:
        """Robot is in a transient state (cleaning, cat detected, etc.)."""
        logger.debug(f"Transient state: {status.name}")
        # Don't reset error timer for transient states

    async def _handle_recoverable_error(self, robot: Robot, status: LitterBoxStatus) -> None:
        """Robot is in an error that might be fixed by power cycling."""
        now = datetime.now()

        # Start tracking error if new
        if not self.state.error_detected_at:
            self.state.error_start_time = now
            logger.warning(f"Error detected: {status.name} - starting timer")
            return

        # Check if error has persisted long enough
        duration = self.state.error_duration_minutes()
        logger.info(f"Error persists: {status.name} ({duration:.1f} min)")

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
        # Only notify once per error occurrence
        if not self.state.error_detected_at:
            self.state.error_start_time = datetime.now()
            logger.warning(f"User intervention required: {status.name}")
            await self.notifier.send(
                "Litter Robot Needs Attention",
                f"Robot is in {status.name} state and requires manual intervention.",
                severity="warning"
            )
        else:
            duration = self.state.error_duration_minutes()
            logger.info(f"Awaiting user intervention: {status.name} ({duration:.1f} min)")

    async def run(self) -> None:
        """Main monitoring loop."""
        self._running = True
        logger.info("=" * 60)
        logger.info("Away Automation v2 Starting")
        logger.info("=" * 60)
        logger.info(f"Check interval: {self.config.check_interval_seconds}s")
        logger.info(f"Error timeout: {self.config.error_timeout_minutes} min")
        logger.info(f"Max recovery attempts: {self.config.max_recovery_attempts}")
        logger.info("=" * 60)

        # Load any persisted state
        if self.state.error_detected_at:
            logger.info(f"Resuming with error state from {self.state.error_detected_at}")
            logger.info(f"Recovery attempts so far: {self.state.recovery_attempts}")

        try:
            async with self.robot_client:
                while self._running:
                    await self.check_and_recover()
                    await asyncio.sleep(self.config.check_interval_seconds)
        except asyncio.CancelledError:
            logger.info("Daemon cancelled")
        finally:
            self.state_store.save(self.state)
            logger.info("State saved. Daemon stopped.")

    def stop(self) -> None:
        """Signal the daemon to stop."""
        self._running = False


# ============================================================================
# Away Automation Daemon (Extended)
# ============================================================================

class AwayAutomationDaemon(RecoveryDaemon):
    """Combined monitoring, recovery, and scheduled cleaning daemon."""

    def __init__(
        self,
        config: Config,
        robot_client: RobotClient,
        plug: SmartPlugController,
        notifier: Notifier,
        state_store: StateStore,
        scheduler: ScheduledCleaner,
    ):
        super().__init__(config, robot_client, plug, notifier, state_store)
        self.scheduler = scheduler

    async def check_and_recover(self) -> None:
        """Extended to include scheduled cleaning checks."""
        # 1. Do recovery check (existing logic)
        await super().check_and_recover()

        # 2. Check if it's time for scheduled cleaning
        await self._check_scheduled_cleaning()

    async def _check_scheduled_cleaning(self) -> None:
        """Check and trigger scheduled cleanings."""
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
        """Main monitoring loop with scheduled cleaning info."""
        logger.info("=" * 60)
        logger.info("Away Automation v2 Starting")
        logger.info("=" * 60)
        logger.info(f"Check interval: {self.config.check_interval_seconds}s")
        logger.info(f"Error timeout: {self.config.error_timeout_minutes} min")
        logger.info(f"Max recovery attempts: {self.config.max_recovery_attempts}")
        logger.info(f"Scheduled cleanings: {', '.join(self.scheduler.CLEANING_TIMES)} {self.scheduler.TIMEZONE}")
        logger.info("=" * 60)

        # Call parent run method
        await super().run()


# ============================================================================
# Main Entry Point
# ============================================================================

def create_daemon(config: Config) -> AwayAutomationDaemon:
    """Factory function to create a fully configured daemon."""
    robot_client = RobotClient(config.whisker_username, config.whisker_password)
    plug = SmartPlugController(config.smart_plug_ip, config.kasa_username, config.kasa_password)
    notifier = WebhookNotifier(config.webhook_url) if config.webhook_url else LogNotifier()
    state_store = StateStore(config.state_file)
    scheduler = ScheduledCleaner(robot_client)

    return AwayAutomationDaemon(
        config=config,
        robot_client=robot_client,
        plug=plug,
        notifier=notifier,
        state_store=state_store,
        scheduler=scheduler,
    )


async def async_main() -> None:
    """Async entry point."""
    config = Config.from_env()
    daemon = create_daemon(config)

    # Handle shutdown signals (Unix only - Windows uses KeyboardInterrupt)
    if sys.platform != 'win32':
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, daemon.stop)

    await daemon.run()


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
