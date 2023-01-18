import asyncio
from flask import Flask
from litter_robot_async import get_info, trigger_cleaning


loop = asyncio.get_event_loop()
app = Flask(__name__)


@app.route("/info")
def notify():
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






# from flask import Flask
# from apscheduler.schedulers.background import BackgroundScheduler
# from litter_robot_full_sync import get_info, trigger_cleaning
#
# app = Flask(__name__)
#
#
# @app.route('/trigger_cleaning', methods=['POST'])
# def cleaning_route():
#     return trigger_cleaning()
#     pass
#
#
# @app.route('/info', methods=['GET'])
# def info_route():
#     return get_info()
#
#
# if __name__ == '__main__':
#     app.run(host='0.0.0.0', port=5000)
