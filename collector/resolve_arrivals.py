from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from collector.models import ArrivalObservation


@dataclass
class PollSnapshot:
    """A single polling snapshot with observations."""
    polled_at: datetime
    observations: list[ArrivalObservation]


@dataclass
class ConfirmedArrival:
    """A confirmed bus arrival."""
    arrival_time: datetime
    routeid: str
    routeno: str


def resolve_arrivals(
    snapshots: list[PollSnapshot],
    noise_eta_threshold_min: float = 5.0
) -> list[ConfirmedArrival]:
    """
    Process polling snapshots to produce confirmed arrival events.

    Logic:
    1. Track "open candidates" per routeid (last observed time, ETA, route number)
    2. For each snapshot:
       - Update candidates that appear in this snapshot
       - For candidates that disappear (not in this snapshot):
         * If last ETA <= noise_eta_threshold_min: record as confirmed arrival
         * Otherwise: discard as noise
    3. Don't record candidates still open at the end of snapshots

    Args:
        snapshots: List of polling snapshots in chronological order
        noise_eta_threshold_min: ETA threshold to distinguish real arrivals from noise

    Returns:
        List of confirmed arrivals in chronological order
    """
    # Track open candidates: routeid -> (polled_at, eta_min, routeno)
    open_candidates: dict[str, tuple[datetime, float, str]] = {}
    confirmed_arrivals: list[ConfirmedArrival] = []

    for snapshot in snapshots:
        # Get the set of routeids in this snapshot
        current_routeids = {obs.routeid for obs in snapshot.observations}

        # Find candidates that disappeared (were open, now not in snapshot)
        disappeared = set(open_candidates.keys()) - current_routeids

        for routeid in disappeared:
            polled_at, eta_min, routeno = open_candidates[routeid]

            # If ETA is small enough, record as confirmed arrival
            if eta_min <= noise_eta_threshold_min:
                arrival_time = polled_at + timedelta(minutes=eta_min)
                confirmed_arrivals.append(
                    ConfirmedArrival(arrival_time, routeid, routeno)
                )
            # Otherwise discard as noise

            # Remove from open candidates
            del open_candidates[routeid]

        # Update candidates that appear in this snapshot
        for observation in snapshot.observations:
            open_candidates[observation.routeid] = (
                snapshot.polled_at,
                observation.eta_min,
                observation.routeno
            )

    # Don't record candidates still open at the end of snapshots
    # (they are already not in confirmed_arrivals)

    return confirmed_arrivals
