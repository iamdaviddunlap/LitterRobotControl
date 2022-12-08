import asyncio

from pylitterbot import Account
from dotenv import load_dotenv
import os


async def get_account():
    load_dotenv()
    username = os.getenv('WHISKER_USERNAME')
    password = os.getenv('WHISKER_PASSWORD')
    account = Account()
    await account.connect(username=username, password=password, load_robots=True)
    return account

WHISKER_ACCOUNT = asyncio.run(get_account())


def scheduled_refresh():
    global WHISKER_ACCOUNT
    print('refreshing account...')
    new_account = asyncio.run(get_account())
    WHISKER_ACCOUNT = new_account
    print('finished refreshing account')


def trigger_cleaning():
    success = asyncio.run(WHISKER_ACCOUNT.robots[0].start_cleaning())
    return success


def do_sync(func):
    asyncio.get_event_loop().close()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        res = loop.run_until_complete(func())
    finally:
        loop.close()
    return res


def get_info():
    robots = [{k: v for k, v in [x.split(': ') for x in str(x).split(', ')]} for x in WHISKER_ACCOUNT.robots]
    return {
        'robots': robots,
        'user': WHISKER_ACCOUNT._user,
        'insight': asyncio.run(WHISKER_ACCOUNT.robots[0].get_insight())
    }


# async def get_insight():
#     try:
#         a = []
#         for robot in WHISKER_ACCOUNT.robots:
#             a = await robot.get_insight()
#     except Exception as e:
#         if str(e) != 'Event loop is closed':
#             raise e
#         else:
#             return a
#     finally:
#         return a


# async def main():
#     try:
#         account = await get_account()
#
#         # Print robots associated with account.
#         print("Robots:")
#         for robot in account.robots:
#             print(robot)
#
#             test = await robot.get_insight()
#             print(test)
#     finally:
#         # Disconnect from the API.
#         await account.disconnect()


# asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# if __name__ == "__main__":
#     try:
#         print(do_sync(get_insight))
#     except Exception as e:
#         x = 1