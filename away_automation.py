import schedule
import time
from datetime import datetime
from pytz import timezone
from litter_robot_sync import trigger_cleaning


def job():
    # Get the current time in Mountain Time
    current_time = datetime.now(timezone('US/Mountain'))
    print("Current Mountain Time is: ", current_time)

    # Define the specific times you want to trigger the cleaning
    trigger_times = ['02:29', '11:29', '16:29', '23:29']

    # Check if the current time (rounded down to the nearest minute) is in the list of trigger times
    if current_time.strftime('%H:%M') in trigger_times:
        print(f'Triggering cleaning. Current time is {current_time}')
        trigger_cleaning()


def main():
    # Schedule the job every minute
    schedule.every(1).minutes.do(job)

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == '__main__':
    main()
