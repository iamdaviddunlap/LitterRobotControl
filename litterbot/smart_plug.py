"""Smart plug controller for TP-Link Kasa devices."""

import asyncio
import logging
from typing import Optional

from kasa import Discover, Credentials


logger = logging.getLogger("litter_robot_daemon")


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
