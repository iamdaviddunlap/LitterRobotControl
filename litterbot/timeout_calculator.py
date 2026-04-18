"""Adaptive timeout calculation based on error history."""

from typing import Tuple

from .state import DaemonState
from .analytics import ErrorAnalytics
from .config import Config


class TimeoutCalculator:
    """Calculates optimal recovery timeout based on historical patterns."""

    def __init__(self, config: Config):
        self.config = config
        self.analytics = ErrorAnalytics()

    def calculate_timeout(self, state: DaemonState, error_type: str) -> Tuple[float, str]:
        """
        Calculate adaptive timeout in minutes.

        Returns:
            (timeout_minutes, reason_string)
        """
        base_timeout = self.config.error_timeout_minutes
        occurrence = state.current_error_occurrence

        # Default: use base timeout
        if not occurrence:
            return base_timeout, "No error occurrence tracked"

        # Strategy 0 (HIGHEST PRIORITY): Post-recovery errors → fast retry
        # If error occurred shortly after a recovery attempt, use fast-retry timeout
        if state.is_post_recovery_error(window_minutes=self.config.post_recovery_error_window_minutes):
            timeout = self.config.post_recovery_retry_timeout_minutes
            return timeout, f"Fast-retry after failed recovery (attempt #{state.recovery_attempts + 1})"

        # Strategy 1: Persistent (non-oscillating) errors → faster intervention
        if not occurrence.oscillation_detected and occurrence.consecutive_error_checks >= 5:
            timeout = base_timeout * 0.4  # 30min → 12min
            timeout = max(timeout, self.config.min_timeout_minutes)
            return timeout, "Persistent non-oscillating error - faster intervention"

        # Strategy 2: Oscillating errors - check history
        if occurrence.oscillation_detected and occurrence.oscillation_count >= 3:
            # Look at historical oscillating errors of this type
            history = state.error_history[-50:]  # Last 50 errors
            self_resolved = self.analytics.get_oscillating_errors_that_self_resolved(history, error_type)
            needed_power = self.analytics.get_oscillating_errors_needing_power_cycle(history, error_type)

            total_oscillating = self_resolved + needed_power

            if total_oscillating == 0:
                # No history - use default
                return base_timeout, "Oscillating but no historical data"

            # If >50% self-resolve, wait longer
            self_resolve_rate = self_resolved / total_oscillating
            if self_resolve_rate > 0.5:
                timeout = base_timeout * 1.5  # 30min → 45min
                timeout = min(timeout, self.config.max_timeout_minutes)
                return timeout, f"Oscillating - historically {self_resolve_rate:.0%} self-resolve"

            # If <50% self-resolve, intervene sooner
            timeout = base_timeout * 0.5  # 30min → 15min
            timeout = max(timeout, self.config.min_timeout_minutes)
            return timeout, f"Oscillating but rarely self-resolves ({self_resolve_rate:.0%})"

        # Default
        return base_timeout, "Using default timeout"
