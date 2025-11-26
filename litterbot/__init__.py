"""Litter Robot Daemon - Unified monitoring, recovery, and automation."""

from .config import Config
from .state import DaemonState, StateStore
from .robot_client import RobotClient
from .smart_plug import SmartPlugController
from .notifier import Notifier, LogNotifier, WebhookNotifier
from .classifier import RecoveryAction, classify_status
from .recovery import RecoveryStrategy, PowerCycleRecovery
from .scheduler import ScheduledCleaner
from .monitor import StatusMonitor
from .daemon import LitterRobotDaemon

__all__ = [
    "Config",
    "DaemonState",
    "StateStore",
    "RobotClient",
    "SmartPlugController",
    "Notifier",
    "LogNotifier",
    "WebhookNotifier",
    "RecoveryAction",
    "classify_status",
    "RecoveryStrategy",
    "PowerCycleRecovery",
    "ScheduledCleaner",
    "StatusMonitor",
    "LitterRobotDaemon",
]
