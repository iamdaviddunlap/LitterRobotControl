#!/usr/bin/env python3
"""Display recovery statistics from daemon state."""

import sys
from pathlib import Path
from litterbot.state import StateStore
from litterbot.analytics import ErrorAnalytics


def main():
    state_file = Path("data/state/daemon_state.json")
    if not state_file.exists():
        print(f"Error: State file not found at {state_file}")
        sys.exit(1)

    store = StateStore(state_file)
    state = store.load()

    if not state.error_history:
        print("No error history available yet.")
        return

    print("=" * 60)
    print("LITTER ROBOT RECOVERY STATISTICS")
    print("=" * 60)
    print(f"Total errors recorded: {len(state.error_history)}")
    print()

    # Get unique error types
    error_types = set(e.error_type for e in state.error_history)

    analytics = ErrorAnalytics()
    for error_type in sorted(error_types):
        metrics = analytics.get_metrics_for_error_type(state.error_history, error_type)

        print(f"{error_type}:")
        print(f"  Occurrences: {metrics.total_occurrences}")
        print(f"  Success rate: {metrics.success_rate:.1%}")
        print(f"  Avg duration: {metrics.avg_duration_minutes:.1f} min")
        print(f"  Oscillation rate: {metrics.oscillation_rate:.1%}")
        print(f"  Recovery methods:")
        print(f"    - Power cycle: {metrics.power_cycle_count}")
        print(f"    - Self-resolved: {metrics.self_resolved_count}")
        print(f"    - Manual: {metrics.manual_intervention_count}")
        print()

    # Current error status
    if state.current_error_occurrence:
        print("CURRENT ERROR IN PROGRESS:")
        occ = state.current_error_occurrence
        print(f"  Type: {occ.error_type}")
        print(f"  Started: {occ.started_at}")
        print(f"  Oscillating: {occ.oscillation_detected} ({occ.oscillation_count} cycles)")
        print(f"  Timeout: {occ.timeout_used_minutes:.0f} min")
        print(f"  Reason: {occ.adaptive_timeout_reason}")
        print()


if __name__ == "__main__":
    main()
