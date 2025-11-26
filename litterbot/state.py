"""State management and persistence for Litter Robot Daemon."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List


@dataclass
class DaemonState:
    """Unified persistent state for all daemon functions."""
    # Status tracking
    current_status: Optional[str] = None
    last_status: Optional[str] = None  # NEW: For change detection
    last_status_change_at: Optional[str] = None  # NEW: When status last changed

    # Recovery tracking
    error_detected_at: Optional[str] = None  # ISO format
    recovery_attempts: int = 0
    total_recoveries: int = 0
    error_action_type: Optional[str] = None  # Type of error: "POWER_CYCLE", "NOTIFY_USER", etc.
    last_error_log_minute: int = -1  # Last minute we logged "error persists" message

    # Scheduled cleaning tracking
    last_scheduled_cleaning: Optional[str] = None  # ISO timestamp of last triggered cleaning
    missed_cleaning_times: List[str] = field(default_factory=list)  # Times missed during errors

    # Monitoring
    last_check_at: Optional[str] = None
    last_notification_at: Optional[str] = None
    last_heartbeat_at: Optional[str] = None  # NEW: Track last heartbeat log

    def to_json(self) -> str:
        """Convert state to JSON string."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, data: str) -> "DaemonState":
        """Create state from JSON string."""
        return cls(**json.loads(data))

    @property
    def error_start_time(self) -> Optional[datetime]:
        """Get error start time as datetime object."""
        if self.error_detected_at:
            return datetime.fromisoformat(self.error_detected_at)
        return None

    @error_start_time.setter
    def error_start_time(self, value: Optional[datetime]):
        """Set error start time from datetime object."""
        self.error_detected_at = value.isoformat() if value else None

    def error_duration_minutes(self) -> float:
        """Calculate how long the robot has been in error state."""
        if not self.error_start_time:
            return 0
        return (datetime.now() - self.error_start_time).total_seconds() / 60

    def status_changed(self, new_status: str) -> bool:
        """Check if status changed since last check."""
        return self.current_status != new_status

    def update_status(self, new_status: str) -> bool:
        """
        Update status and return True if it changed.

        Args:
            new_status: The new status to record

        Returns:
            True if status changed, False if it stayed the same
        """
        if self.status_changed(new_status):
            self.last_status = self.current_status
            self.current_status = new_status
            self.last_status_change_at = datetime.now().isoformat()
            return True
        else:
            # Even if status didn't change, still update current_status
            # (in case it was None initially)
            self.current_status = new_status
            return False


class StateStore:
    """Persists daemon state to disk."""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> DaemonState:
        """Load state from disk, or return fresh state if not found."""
        if self.path.exists():
            try:
                return DaemonState.from_json(self.path.read_text())
            except (json.JSONDecodeError, TypeError) as e:
                import logging
                logging.warning(f"Could not load state file: {e}")
        return DaemonState()

    def save(self, state: DaemonState) -> None:
        """Persist state to disk."""
        self.path.write_text(state.to_json())
