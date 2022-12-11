import asyncio

from pylitterbot import Account
from dotenv import load_dotenv
import os
import json


def safe_sync_run(func, *args, **kwargs):
    result = asyncio.get_event_loop().run_until_complete(func(*args, **kwargs))
    return result


def get_account():
    # Load the environment variables from the ".env" file.
    load_dotenv()
    username = os.getenv('WHISKER_USERNAME')
    password = os.getenv('WHISKER_PASSWORD')

    # Connect to the account and load the robots associated with it.
    account = Account()
    safe_sync_run(account.connect, username=username, password=password, load_robots=True)

    return account


WHISKER_ACCOUNT = get_account()


def scheduled_refresh():
    global WHISKER_ACCOUNT
    print('refreshing account...')
    new_account = get_account()
    WHISKER_ACCOUNT = new_account
    print('finished refreshing account')


async def get_insight():
    result = await WHISKER_ACCOUNT.robots[0].get_insight()
    return result


async def trigger_cleaning():
    success = await WHISKER_ACCOUNT.robots[0].start_cleaning()
    return success


def get_info():
    robots = [{k: v for k, v in [x.split(': ') for x in str(x).split(', ')]} for x in WHISKER_ACCOUNT.robots]
    return {
        'robots': robots,
        'user': WHISKER_ACCOUNT._user,
        'insight': str(safe_sync_run(get_insight))
    }


if __name__ == '__main__':
    try:
        info = get_info()
        print(json.dumps(info, indent=1))
    finally:
        # Disconnect from the API.
        safe_sync_run(WHISKER_ACCOUNT.disconnect)
