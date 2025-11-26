"""Recovery strategies for handling robot errors."""

import asyncio
import logging
from abc import ABC, abstractmethod

from pylitterbot.robot import Robot

from .classifier import classify_status, RecoveryAction
from .smart_plug import SmartPlugController


logger = logging.getLogger("litter_robot_daemon")


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

        # Step 3: Check status - accept both NONE and WAIT states as success
        logger.info("Step 3: Checking robot status...")
        await robot.refresh()
        status = robot.status

        if status:
            action = classify_status(status)
            if action == RecoveryAction.NONE:
                logger.info(f"Recovery successful! Robot returned to normal state: {status.name}")
                return True
            elif action == RecoveryAction.WAIT:
                logger.info(f"Recovery successful! Robot is operational in transient state: {status.name}")
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
