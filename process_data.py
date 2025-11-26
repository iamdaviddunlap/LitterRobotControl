from litter_robot_sync import get_account, safe_sync_run
from pylitterbot.enums import LitterBoxStatus
import datetime
import matplotlib.pyplot as plt
import pytz
from collections import Counter
import pandas as pd


def get_litter_box_trigger_datetime_list(limit=10000000000000):
    """
    Find all the times that a litter box clean cycle was triggered. We filter to only look at clean cycle, no other
    events. We also pass an absurdly large limit to be sure that we are getting the entire history.
    :return:
    """
    whisker_account = get_account()
    try:
        full_history = safe_sync_run(whisker_account.robots[0].get_activity_history, limit=limit)
        if len(full_history) == limit:
            return get_litter_box_trigger_datetime_list(limit=limit * 2)
        datetime_lst = [x.timestamp for x in full_history if x.action == LitterBoxStatus.CLEAN_CYCLE]
        return datetime_lst
    finally:
        safe_sync_run(whisker_account.disconnect)


def generate_histogram():
    datetime_list = get_litter_box_trigger_datetime_list()

    # Convert datetime objects to Mountain Time
    mountain = pytz.timezone('America/Denver')
    datetime_list_mountain = [dt.astimezone(mountain) for dt in datetime_list]

    # Extract time from datetime and convert it to decimal hours
    time_list = [(dt.hour + dt.minute / 60) for dt in datetime_list_mountain]

    # Create bins for every 30 min interval from 12am to 11:30pm
    bins = [i / 2 for i in range(49)]

    fig, ax = plt.subplots(figsize=(10, 5))

    # Create histogram
    ax.hist(time_list, bins=bins, edgecolor='black')

    # Label x-axis as 'Time' and y-axis as 'Count'
    ax.set_xlabel('Time (Mountain Time)')
    ax.set_ylabel('Count')

    # Modify x-axis labels to 24-hour format and rotate labels
    labels = ['12 AM', '1 AM', '2 AM', '3 AM', '4 AM', '5 AM', '6 AM', '7 AM', '8 AM', '9 AM', '10 AM', '11 AM',
              '12 PM', '1 PM', '2 PM', '3 PM', '4 PM', '5 PM', '6 PM', '7 PM', '8 PM', '9 PM', '10 PM', '11 PM', '12 AM']
    ax.set_xticks([i/2 for i in range(0, 49, 2)])  # Set x-ticks every hour (2 half-hours)
    ax.set_xticklabels(labels, rotation=45)

    # Show plot
    plt.tight_layout()  # adjusts subplot params so that the subplot fits into the figure area
    plt.show()



def find_best_times():
    datetime_list = get_litter_box_trigger_datetime_list()

    # Convert to Mountain Time
    mt = pytz.timezone('America/Denver')
    mt_times = [t.astimezone(mt) for t in datetime_list]

    # Count events per day
    day_counts = Counter(t.date() for t in mt_times)
    most_common_num_events = max(set(day_counts.values()), key=list(day_counts.values()).count)

    print(f'It is most common to have {most_common_num_events} events per day.')

    # Convert times to minutes past midnight
    times_to_minutes = [(t.hour * 60 + t.minute) for t in [dt.time() for dt in mt_times]]

    # Bin the times
    time_bins = pd.cut(times_to_minutes, most_common_num_events, labels=False)

    # Get the most common bins
    bin_counts = Counter(time_bins)
    most_common_bins = bin_counts.most_common(most_common_num_events)

    # Get the bin boundaries in minutes
    bins = pd.cut(times_to_minutes, most_common_num_events, labels=False, retbins=True)[1]

    # Get the midpoint of each bin in minutes
    midpoints = [(bins[i] + bins[i+1]) / 2 for i in range(len(bins)-1)]

    # Convert midpoints back to time format
    common_times = []
    for midpoint in midpoints:
        hours = int(midpoint // 60)
        minutes = int(midpoint % 60)
        common_times.append(f'{hours:02d}:{minutes:02d}')

    return common_times


if __name__ == '__main__':
    # generate_histogram()
    find_best_times()
