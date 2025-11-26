#!/usr/bin/env python3
"""
Unified Litter Robot Daemon

Combines monitoring, error recovery, and scheduled cleaning.
Replaces both recovery_daemon.py and away_automation_v2.py.
"""

import asyncio
import logging
import signal
import sys

from litterbot import (
    Config, StateStore, RobotClient, SmartPlugController,
    LogNotifier, WebhookNotifier, ScheduledCleaner,
    StatusMonitor, LitterRobotDaemon
)


def setup_logging(log_file: str = "litter_robot_daemon.log") -> logging.Logger:
    """Configure logging with both file and console output."""
    logger = logging.getLogger("litter_robot_daemon")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


def create_daemon(config: Config) -> LitterRobotDaemon:
    """Factory function to create a fully configured daemon."""
    robot_client = RobotClient(config.whisker_username, config.whisker_password)
    plug = SmartPlugController(config.smart_plug_ip, config.kasa_username, config.kasa_password)
    notifier = WebhookNotifier(config.webhook_url) if config.webhook_url else LogNotifier()
    state_store = StateStore(config.state_file)
    state = state_store.load()

    monitor = StatusMonitor(robot_client, state, config, notifier)
    scheduler = ScheduledCleaner(robot_client, config) if config.enable_scheduled_cleaning else None

    return LitterRobotDaemon(
        config=config,
        robot_client=robot_client,
        plug=plug,
        notifier=notifier,
        state_store=state_store,
        monitor=monitor,
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
