#!/usr/bin/env python3
"""
Test script for Litter Robot Daemon

Runs a single check iteration and exits.
Useful for testing configuration and connectivity.
"""

import asyncio
import logging
import sys

from litter_robot_daemon import create_daemon, setup_logging
from litterbot import Config


async def test():
    """Run a single check and exit."""
    # Setup logging
    logger = setup_logging("data/logs/test_daemon.log")
    logger.info("=" * 60)
    logger.info("Running single daemon check test")
    logger.info("=" * 60)

    try:
        # Load configuration
        config = Config.from_env()
        logger.info(f"Configuration loaded successfully")
        logger.info(f"Check interval: {config.check_interval_seconds}s")
        logger.info(f"Heartbeat interval: {config.heartbeat_interval_minutes} min")
        logger.info(f"Recovery enabled: {config.enable_recovery}")
        logger.info(f"Scheduled cleaning enabled: {config.enable_scheduled_cleaning}")

        # Create daemon
        daemon = create_daemon(config)
        logger.info("Daemon created successfully")

        # Connect to robot
        logger.info("Connecting to Whisker API...")
        await daemon.robot_client.connect()
        logger.info("Connected successfully")

        # Run single check
        logger.info("Running single check...")
        await daemon.check_and_act()
        logger.info("Check complete")

        # Disconnect
        logger.info("Disconnecting...")
        await daemon.robot_client.disconnect()
        logger.info("Disconnected")

        logger.info("=" * 60)
        logger.info("Test completed successfully!")
        logger.info("=" * 60)
        print("\nTest completed successfully! Check test_daemon.log for details.")
        return 0

    except Exception as e:
        logger.error(f"Test failed: {e}", exc_info=True)
        print(f"\nTest failed: {e}")
        print("Check test_daemon.log for details.")
        return 1


def main():
    """Main entry point."""
    exit_code = asyncio.run(test())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
