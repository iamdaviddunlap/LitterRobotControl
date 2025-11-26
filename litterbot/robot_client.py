"""Robot client for Whisker API connection management."""

import logging
from typing import Optional

from pylitterbot import Account
from pylitterbot.robot import Robot


logger = logging.getLogger("litter_robot_daemon")


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
