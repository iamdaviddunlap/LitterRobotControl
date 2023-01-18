from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from litter_robot_full_sync import get_info, trigger_cleaning

app = Flask(__name__)


@app.route('/trigger_cleaning', methods=['POST'])
def cleaning_route():
    return trigger_cleaning()
    pass


@app.route('/info', methods=['GET'])
def info_route():
    return get_info()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
