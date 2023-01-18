import asyncio

from pylitterbot import Account
from dotenv import load_dotenv
import os
from time import time


def safe_sync_run(func, *args, **kwargs):
    # asyncio.set_event_loop(asyncio.SelectorEventLoop())
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


def get_insight(whisker_account=None):
    if whisker_account is None:
        whisker_account = get_account()
    try:
        result = safe_sync_run(whisker_account.robots[0].get_insight)
        return result
    finally:
        safe_sync_run(whisker_account.disconnect)


def trigger_cleaning(whisker_account=None):
    if whisker_account is None:
        whisker_account = get_account()
    try:
        result = safe_sync_run(whisker_account.robots[0].start_cleaning)
        return result
    finally:
        safe_sync_run(whisker_account.disconnect)


def get_info():
    whisker_account = get_account()
    try:
        robots = [{k: v for k, v in [x.split(': ') for x in str(x).split(', ')]} for x in whisker_account.robots]
        return {
            'robots': robots,
            'user': whisker_account._user,
            'insight': str(get_insight(whisker_account=whisker_account))
        }
    finally:
        safe_sync_run(whisker_account.disconnect)


if __name__ == '__main__':
    start = time()
    info = get_info()
    print(info)
    print(f'Got insight in {time() - start}s')

    start = time()
    insight = get_insight()
    print(insight)
    print(f'Got insight in {time() - start}s')

    # start = time()
    # print(trigger_cleaning())
    # print(f'Triggered cleaning in {time() - start}s')

