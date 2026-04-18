"""Configuration management for Litter Robot Daemon."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

from dotenv import dotenv_values


@dataclass
class Config:
    """Type-safe configuration with validation."""
    # Whisker API credentials
    whisker_username: str
    whisker_password: str

    # Smart plug credentials
    kasa_username: str
    kasa_password: str
    smart_plug_ip: str

    # Timing - Updated defaults for faster polling
    check_interval_seconds: int = 10  # Changed from 60 to 10
    heartbeat_interval_minutes: int = 5  # NEW: Periodic alive log
    error_timeout_minutes: float = 30  # Changed to float to allow fractional minutes
    power_cycle_wait_seconds: int = 7
    post_recovery_wait_seconds: int = 120
    max_recovery_attempts: int = 3
    error_log_milestones: List[int] = field(default_factory=lambda: [1, 5, 10, 15, 20, 25, 29])

    # Feature flags
    enable_recovery: bool = True
    enable_scheduled_cleaning: bool = True

    # Scheduled cleaning configuration
    cleaning_times: List[str] = field(default_factory=lambda: ['02:29', '11:29', '16:29', '23:29'])
    timezone: str = 'US/Mountain'

    # Adaptive timeout configuration
    min_timeout_minutes: int = 5
    max_timeout_minutes: int = 60

    # Post-recovery configuration
    recovery_stabilization_minutes: float = 3.0  # How long to monitor after power cycle
    post_recovery_error_window_minutes: float = 3.0  # Time window to consider "post-recovery error"
    post_recovery_retry_timeout_minutes: float = 5.0  # Fast retry timeout for post-recovery errors

    # Error recording threshold
    min_error_duration_minutes: float = 3.0  # Only record errors lasting > this duration

    # Analytics
    analytics_history_size: int = 100

    # Persistence
    state_file: Path = field(default_factory=lambda: Path("data/state/daemon_state.json"))

    # Notifications
    webhook_url: Optional[str] = None

    @classmethod
    def from_env(cls, env_path: Optional[str] = None) -> "Config":
        """Load configuration from .env file."""
        if env_path is None:
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
        config = dotenv_values(env_path)

        required = ["WHISKER_USERNAME", "WHISKER_PASSWORD",
                    "KASA_USERNAME", "KASA_PASSWORD", "SMART_PLUG_IP"]
        missing = [k for k in required if not config.get(k)]
        if missing:
            raise ValueError(f"Missing required config: {', '.join(missing)}")

        # Parse cleaning times if provided
        cleaning_times = ['02:29', '11:29', '16:29', '23:29']
        if config.get("CLEANING_TIMES"):
            cleaning_times = [t.strip() for t in config["CLEANING_TIMES"].split(",")]

        # Parse error log milestones
        error_log_milestones = [1, 5, 10, 15, 20, 25, 29]
        if config.get("ERROR_LOG_MILESTONES"):
            error_log_milestones = [int(m.strip()) for m in config["ERROR_LOG_MILESTONES"].split(",")]

        # Parse feature flags
        enable_recovery = config.get("ENABLE_RECOVERY", "true").lower() in ("true", "1", "yes")
        enable_scheduled_cleaning = config.get("ENABLE_SCHEDULED_CLEANING", "true").lower() in ("true", "1", "yes")

        return cls(
            whisker_username=config["WHISKER_USERNAME"],
            whisker_password=config["WHISKER_PASSWORD"],
            kasa_username=config["KASA_USERNAME"],
            kasa_password=config["KASA_PASSWORD"],
            smart_plug_ip=config["SMART_PLUG_IP"],
            check_interval_seconds=int(config.get("CHECK_INTERVAL_SECONDS", 10)),
            heartbeat_interval_minutes=int(config.get("HEARTBEAT_INTERVAL_MINUTES", 5)),
            error_timeout_minutes=float(config.get("ERROR_TIMEOUT_MINUTES", 30)),
            power_cycle_wait_seconds=int(config.get("POWER_CYCLE_WAIT_SECONDS", 7)),
            max_recovery_attempts=int(config.get("MAX_RECOVERY_ATTEMPTS", 3)),
            error_log_milestones=error_log_milestones,
            enable_recovery=enable_recovery,
            enable_scheduled_cleaning=enable_scheduled_cleaning,
            cleaning_times=cleaning_times,
            timezone=config.get("TIMEZONE", "US/Mountain"),
            min_timeout_minutes=int(config.get("MIN_TIMEOUT_MINUTES", 5)),
            max_timeout_minutes=int(config.get("MAX_TIMEOUT_MINUTES", 60)),
            recovery_stabilization_minutes=float(config.get("RECOVERY_STABILIZATION_MINUTES", 3.0)),
            post_recovery_error_window_minutes=float(config.get("POST_RECOVERY_ERROR_WINDOW_MINUTES", 3.0)),
            post_recovery_retry_timeout_minutes=float(config.get("POST_RECOVERY_RETRY_TIMEOUT_MINUTES", 5.0)),
            min_error_duration_minutes=float(config.get("MIN_ERROR_DURATION_MINUTES", 3.0)),
            analytics_history_size=int(config.get("ANALYTICS_HISTORY_SIZE", 100)),
            webhook_url=config.get("WEBHOOK_URL"),
        )
