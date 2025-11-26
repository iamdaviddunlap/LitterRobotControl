import asyncio
import os
from kasa import Discover, Credentials
from dotenv import dotenv_values

# Load environment variables
config = dotenv_values(".env")

# Your Kasa account details (REQUIRED for KP125M)
KASA_USERNAME = config.get('KASA_USERNAME')
KASA_PASSWORD = config.get('KASA_PASSWORD')
DEVICE_IP = config.get('SMART_PLUG_IP', '192.168.0.80')


async def main():
    # Create credentials object
    creds = Credentials(KASA_USERNAME, KASA_PASSWORD)

    try:
        # Discover and connect to the device
        plug = await Discover.discover_single(DEVICE_IP, credentials=creds)
        await plug.update()

        print(f"Connected to: {plug.alias}")
        print(f"Current State: {'ON' if plug.is_on else 'OFF'}")

        # Toggle the plug
        # print("Toggling plug...")
        # if plug.is_on:
        #     await plug.turn_off()
        # else:
        #     await plug.turn_on()

        # Verify the change
        await plug.update()
        print(f"New State: {'ON' if plug.is_on else 'OFF'}")

        # Optional: Read Energy Monitoring Data (if supported by firmware)
        if "Energy" in plug.modules:
            energy = plug.modules["Energy"]
            print(f"Current Power: {energy.current_consumption} W")

    except Exception as e:
        print(f"Error: {e}")
        print("Tip: Ensure your IP is correct, device is reachable, and credentials are valid.")

    finally:
        # Properly close the connection
        await plug.disconnect()


if __name__ == "__main__":
    asyncio.run(main())