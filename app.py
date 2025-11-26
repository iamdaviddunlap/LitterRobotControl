import asyncio
from flask import Flask
from litter_robot_async import get_info, trigger_cleaning
from time import time
import datetime


def run_async(coro):
    """Run an async coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


app = Flask(__name__)
startup_time = time()


@app.route("/liveness", methods=['GET'])
def liveness():
    return f'App has been live for {datetime.timedelta(seconds=(time() - startup_time))}'


@app.route("/info", methods=['GET'])
def report_info():
    info = run_async(get_info())
    return info


@app.route('/trigger_cleaning', methods=['POST'])
def cleaning_route():
    success = run_async(trigger_cleaning())
    if success:
        return '', 200
    else:
        return str(success), 500


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
