import asyncio

from pylitterbot import Account
from dotenv import load_dotenv

load_dotenv()
username = os.getenv('WHISKER_USERNAME')
password = os.getenv('WHISKER_PASSWORD')


async def main():
    # Create an account.
    account = Account()

    try:
        # Connect to the API and load robots.
        await account.connect(username=username, password=password, load_robots=True)

        # Print robots associated with account.
        print("Robots:")
        for robot in account.robots:
            print(robot)

            test = await robot.start_cleaning()
            print(test)
    finally:
        # Disconnect from the API.
        await account.disconnect()


if __name__ == "__main__":
    asyncio.run(main())