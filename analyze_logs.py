#!/usr/bin/env python3
"""Analyze litter robot daemon logs for patterns and statistics."""

import re
from datetime import datetime
from collections import defaultdict, Counter
from pathlib import Path

log_file = Path("data/logs/litter_robot_daemon.log")

# Parse log entries
cat_usage_times = []
error_occurrences = []
recovery_attempts = []
scheduled_cleanings = []

with open(log_file) as f:
    current_error_start = None
    
    for line in f:
        # Extract timestamp and message
        match = re.match(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if not match:
            continue
        timestamp_str = match.group(1)
        timestamp = datetime.fromisoformat(timestamp_str)
        
        # Cat usage (CAT_SENSOR_TIMING indicates cat detected/using box)
        if 'CAT_SENSOR_TIMING' in line and 'Status changed:' in line and '-> CAT_SENSOR_TIMING' in line:
            cat_usage_times.append(timestamp)
        
        # Error detection
        if 'Error detected: OVER_TORQUE_FAULT' in line:
            current_error_start = timestamp
        
        # Recovery attempts
        if 'Attempting recovery' in line and current_error_start:
            duration = (timestamp - current_error_start).total_seconds() / 60
            error_occurrences.append({
                'start': current_error_start,
                'recovery_start': timestamp,
                'duration_minutes': duration
            })
            current_error_start = None
        
        # Scheduled cleanings
        if 'Scheduled cleaning time:' in line:
            scheduled_cleanings.append(timestamp)

# Analysis
print("=" * 70)
print("LITTER ROBOT LOG ANALYSIS")
print("=" * 70)
print(f"Log period: {len(cat_usage_times) + len(error_occurrences)} days of data")
print()

# Cat usage patterns
print("CAT USAGE PATTERNS")
print("-" * 70)
print(f"Total cat visits detected: {len(cat_usage_times)}")

if cat_usage_times:
    hours = Counter(t.hour for t in cat_usage_times)
    print("\nVisits by hour of day:")
    for hour in sorted(hours.keys()):
        bar = '█' * hours[hour]
        print(f"  {hour:02d}:00-{hour:02d}:59 | {bar} ({hours[hour]})")
    
    # Peak hours
    sorted_hours = sorted(hours.items(), key=lambda x: x[1], reverse=True)
    print(f"\nPeak usage hours:")
    for hour, count in sorted_hours[:5]:
        print(f"  {hour:02d}:00-{hour:02d}:59: {count} visits")
    
    # Calculate average daily visits
    if cat_usage_times:
        days = (cat_usage_times[-1] - cat_usage_times[0]).days + 1
        avg_daily = len(cat_usage_times) / max(days, 1)
        print(f"\nAverage visits per day: {avg_daily:.1f}")

print()
print("ERROR & RECOVERY PATTERNS")
print("-" * 70)
print(f"Total OVER_TORQUE_FAULT errors: {len(error_occurrences)}")

if error_occurrences:
    durations = [e['duration_minutes'] for e in error_occurrences]
    avg_duration = sum(durations) / len(durations)
    min_duration = min(durations)
    max_duration = max(durations)
    
    print(f"Average time before recovery: {avg_duration:.1f} minutes")
    print(f"Min time before recovery: {min_duration:.1f} minutes")
    print(f"Max time before recovery: {max_duration:.1f} minutes")
    
    # Errors by hour
    error_hours = Counter(e['start'].hour for e in error_occurrences)
    print("\nErrors by hour of day:")
    for hour in sorted(error_hours.keys()):
        bar = '█' * error_hours[hour]
        print(f"  {hour:02d}:00-{hour:02d}:59 | {bar} ({error_hours[hour]})")
    
    # Calculate average daily errors
    if error_occurrences:
        days = (error_occurrences[-1]['start'] - error_occurrences[0]['start']).days + 1
        avg_daily_errors = len(error_occurrences) / max(days, 1)
        print(f"\nAverage errors per day: {avg_daily_errors:.1f}")

print()
print("SCHEDULED CLEANING")
print("-" * 70)
print(f"Total scheduled cleanings: {len(scheduled_cleanings)}")
if scheduled_cleanings:
    days = (scheduled_cleanings[-1] - scheduled_cleanings[0]).days + 1
    expected = days * 4  # 4 cleanings per day
    print(f"Expected cleanings ({days} days × 4/day): {expected}")
    print(f"Success rate: {len(scheduled_cleanings)/expected*100:.1f}%")

print()
print("RECOMMENDATIONS")
print("-" * 70)

# Check if errors cluster around scheduled cleaning times
if error_occurrences and scheduled_cleanings:
    errors_after_scheduled = 0
    for error in error_occurrences:
        for cleaning in scheduled_cleanings:
            time_diff = (error['start'] - cleaning).total_seconds() / 60
            if 0 < time_diff < 15:  # Within 15 min after scheduled cleaning
                errors_after_scheduled += 1
                break
    
    if errors_after_scheduled > len(error_occurrences) * 0.5:
        print(f"⚠️  {errors_after_scheduled}/{len(error_occurrences)} errors occur shortly after scheduled cleanings")
        print("   Consider adjusting scheduled cleaning times to avoid peak error times")

# Timeout recommendation
if error_occurrences and all(e['duration_minutes'] > 29 for e in error_occurrences):
    print("⚠️  ALL errors are waiting full 30-minute timeout before recovery")
    print("   Consider reducing ERROR_TIMEOUT_MINUTES to intervene faster")
    print(f"   Suggested: 15 minutes (would save ~{len(error_occurrences) * 15:.0f} min total downtime)")

