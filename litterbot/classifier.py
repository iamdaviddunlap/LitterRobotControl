"""Status classification system for determining recovery actions."""

from enum import Enum, auto

from pylitterbot.enums import LitterBoxStatus


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
    LitterBoxStatus.CAT_SENSOR_TIMING: RecoveryAction.WAIT,
    LitterBoxStatus.CAT_SENSOR_INTERRUPTED: RecoveryAction.WAIT,
    LitterBoxStatus.STARTUP_CAT_SENSOR_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.STARTUP_PINCH_DETECT: RecoveryAction.POWER_CYCLE,

    # User intervention required - notify but don't auto-recover
    LitterBoxStatus.DRAWER_FULL: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.DRAWER_FULL_1: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.DRAWER_FULL_2: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.STARTUP_DRAWER_FULL: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.BONNET_REMOVED: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.OFFLINE: RecoveryAction.NOTIFY_USER,

    # Unknown/placeholder status - treat as transient to avoid false error timers
    LitterBoxStatus.UNKNOWN: RecoveryAction.WAIT,
}


def classify_status(status: LitterBoxStatus) -> RecoveryAction:
    """Determine what action to take for a given status."""
    return STATUS_ACTIONS.get(status, RecoveryAction.NOTIFY_USER)
