import asyncio

from pylitterbot import Account
from dotenv import dotenv_values
import os


async def get_account():
    # Load the environment variables from the ".env" file.
    config = dotenv_values(".env")
    username = config.get('WHISKER_USERNAME')
    password = config.get('WHISKER_PASSWORD')

    # Connect to the account and load the robots associated with it.
    account = Account()
    await account.connect(username=username, password=password, load_robots=True)

    return account


async def get_insight(whisker_account=None):
    owns_account = whisker_account is None
    if owns_account:
        whisker_account = await get_account()
    try:
        result = await whisker_account.robots[0].get_insight()
        return result
    finally:
        if owns_account:
            await whisker_account.disconnect()


async def trigger_cleaning(whisker_account=None):
    owns_account = whisker_account is None
    if owns_account:
        whisker_account = await get_account()
    try:
        result = await whisker_account.robots[0].start_cleaning()
        return result
    finally:
        if owns_account:
            await whisker_account.disconnect()


async def get_info():
    whisker_account = await get_account()
    try:
        robots = [{k: v for k, v in [x.split(': ') for x in str(x).split(', ')]} for x in whisker_account.robots]
        return {
            'robots': robots,
            'user': whisker_account._user,
            'insight': str(await get_insight(whisker_account=whisker_account))
        }
    finally:
        await whisker_account.disconnect()
