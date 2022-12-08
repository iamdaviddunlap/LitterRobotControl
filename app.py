from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
from litter_robot import WHISKER_ACCOUNT, scheduled_refresh, trigger_cleaning, get_info

app = Flask(__name__)


@app.route('/trigger_cleaning', methods=['POST'])
def cleaning_route():
    return trigger_cleaning()


@app.route('/info', methods=['GET'])
def info_route():
    return get_info()


sched = BackgroundScheduler(daemon=True, timezone='US/Mountain')
sched.add_job(scheduled_refresh, 'cron', hour='*')
sched.start()


if __name__ == '__main__':
    print('test')
    print(WHISKER_ACCOUNT)
    app.run(host='0.0.0.0', port=5000)
