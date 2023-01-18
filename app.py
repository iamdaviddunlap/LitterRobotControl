import asyncio
from flask import Flask
from litter_robot_async import get_info, trigger_cleaning
from time import time
import datetime


loop = asyncio.get_event_loop()
app = Flask(__name__)
startup_time = time()


@app.route("/liveness", methods=['GET'])
def liveness():
    return f'App has been live for {datetime.timedelta(seconds=(time() - startup_time))}'


@app.route("/info", methods=['GET'])
def report_info():
    info = loop.run_until_complete(get_info())
    return info


@app.route('/trigger_cleaning', methods=['POST'])
def cleaning_route():
    success = loop.run_until_complete(trigger_cleaning())
    if success:
        return '', 200
    else:
        return str(success), 500


if __name__ == "__main__":
    app.run(debug=False, use_reloader=False)
