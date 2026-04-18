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

    async def execute(self, robot: Robot, attempt: int, stabilization_minutes: float = 3.0) -> bool:
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
                # CRITICAL FIX: Don't immediately declare success for transient states
                # Monitor for stabilization period to ensure error doesn't return
                logger.info(f"Robot in transient state: {status.name} - monitoring for {stabilization_minutes:.1f} min stabilization...")
                return await self._monitor_stabilization(robot, stabilization_minutes)

        # Step 4: If still in error, try triggering a clean cycle
        if status and classify_status(status) == RecoveryAction.POWER_CYCLE:
            logger.info("Step 4: Triggering clean cycle to clear error...")
            try:
                await robot.start_cleaning()
                await asyncio.sleep(60)  # Wait for cycle to progress
                await robot.refresh()
                status = robot.status

                action = classify_status(status) if status else None
                if action == RecoveryAction.NONE:
                    logger.info(f"Recovery successful after clean cycle! Status: {status.name}")
                    return True
                elif action == RecoveryAction.WAIT:
                    logger.info(f"Robot in transient state after clean cycle: {status.name} - monitoring stabilization...")
                    return await self._monitor_stabilization(robot, stabilization_minutes)
            except Exception as e:
                logger.error(f"Failed to trigger clean cycle: {e}")

        logger.warning(f"Recovery incomplete. Robot status: {status.name if status else 'Unknown'}")
        return False

    async def _monitor_stabilization(self, robot: Robot, stabilization_minutes: float) -> bool:
        """
        Monitor robot for stabilization period to ensure error doesn't immediately return.

        Returns True if robot either:
        - Reaches stable state (READY, CLEAN_CYCLE_COMPLETE)
        - Remains in transient states for full stabilization period without returning to error

        Returns False if robot returns to error state during stabilization.
        """
        from datetime import datetime, timedelta

        stabilization_end = datetime.now() + timedelta(minutes=stabilization_minutes)
        check_interval_seconds = 10  # Check every 10 seconds

        while datetime.now() < stabilization_end:
            await asyncio.sleep(check_interval_seconds)
            await robot.refresh()
            status = robot.status

            if not status:
                logger.warning("Lost robot status during stabilization monitoring")
                return False

            action = classify_status(status)

            # If reached stable state, declare success immediately
            if action == RecoveryAction.NONE:
                elapsed = (datetime.now() - (stabilization_end - timedelta(minutes=stabilization_minutes))).total_seconds()
                logger.info(f"Recovery confirmed stable after {elapsed:.0f}s - reached {status.name}")
                return True

            # If returned to error state, recovery failed
            if action == RecoveryAction.POWER_CYCLE:
                elapsed = (datetime.now() - (stabilization_end - timedelta(minutes=stabilization_minutes))).total_seconds()
                logger.warning(f"Recovery failed - error returned after {elapsed:.0f}s ({status.name})")
                return False

            # Still in transient state (WAIT) - continue monitoring
            # logger.debug(f"Stabilization check: {status.name} (OK)")

        # Made it through full stabilization period without returning to error
        logger.info(f"Recovery confirmed stable after {stabilization_minutes:.1f} min monitoring")
        return True
