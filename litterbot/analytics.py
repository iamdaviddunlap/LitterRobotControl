"""Historical error analysis and metrics."""

from dataclasses import dataclass
from typing import List

from .state import ErrorOccurrence


@dataclass
class RecoveryMetrics:
    """Aggregated recovery statistics for an error type."""
    total_occurrences: int
    successful_recoveries: int
    success_rate: float
    avg_duration_minutes: float
    oscillation_rate: float  # % of errors that oscillated

    # Breakdown by recovery method
    power_cycle_count: int = 0
    self_resolved_count: int = 0
    manual_intervention_count: int = 0


class ErrorAnalytics:
    """Analyzes error history for patterns and trends."""

    @staticmethod
    def get_metrics_for_error_type(history: List[ErrorOccurrence], error_type: str) -> RecoveryMetrics:
        """Calculate metrics for a specific error type."""
        relevant = [e for e in history if e.error_type == error_type]

        if not relevant:
            return RecoveryMetrics(0, 0, 0.0, 0.0, 0.0)

        total = len(relevant)
        successful = sum(1 for e in relevant if e.recovery_successful)
        oscillating = sum(1 for e in relevant if e.oscillation_detected)
        avg_duration = sum(e.duration_minutes for e in relevant) / total

        return RecoveryMetrics(
            total_occurrences=total,
            successful_recoveries=successful,
            success_rate=successful / total if total > 0 else 0.0,
            avg_duration_minutes=avg_duration,
            oscillation_rate=oscillating / total if total > 0 else 0.0,
            power_cycle_count=sum(1 for e in relevant if e.recovery_method == "power_cycle"),
            self_resolved_count=sum(1 for e in relevant if e.recovery_method == "self_resolved"),
            manual_intervention_count=sum(1 for e in relevant if e.recovery_method == "manual"),
        )

    @staticmethod
    def get_oscillating_errors_that_self_resolved(history: List[ErrorOccurrence], error_type: str) -> int:
        """Count how many oscillating errors self-resolved without intervention."""
        return sum(1 for e in history
                  if e.error_type == error_type
                  and e.oscillation_detected
                  and e.recovery_method == "self_resolved")

    @staticmethod
    def get_oscillating_errors_needing_power_cycle(history: List[ErrorOccurrence], error_type: str) -> int:
        """Count how many oscillating errors needed power cycle."""
        return sum(1 for e in history
                  if e.error_type == error_type
                  and e.oscillation_detected
                  and e.recovery_method == "power_cycle")
