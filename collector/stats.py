from dataclasses import dataclass
from datetime import date, time, timedelta

from collector.resolve_arrivals import ConfirmedArrival


@dataclass
class SlotStats:
    """Statistics for a single arrival slot across multiple days."""
    slot_index: int
    min_time: time
    max_time: time
    avg_time: time
    sample_count: int


def compute_stats(
    confirmed_by_date: dict[date, list[ConfirmedArrival]],
    as_of: date,
    window_days: int = 30
) -> list[SlotStats]:
    """
    Compute statistics for bus arrivals grouped by slot index across days.

    Logic:
    1. Filter out dates older than as_of - window_days
    2. For each remaining date, sort arrivals by time and assign slot indices (1-based)
    3. Group arrivals by slot_index across all dates
    4. For each slot_index, compute min/max/avg time and sample_count (dates that have this slot)

    Args:
        confirmed_by_date: Dictionary mapping date to list of ConfirmedArrival
        as_of: Reference date for the rolling window
        window_days: Number of days to look back (default 30)

    Returns:
        List of SlotStats sorted by slot_index
    """
    # Calculate cutoff date (exclude dates before or equal to this)
    cutoff_date = as_of - timedelta(days=window_days)

    # Filter dates within the window and sort by date
    valid_dates = sorted([d for d in confirmed_by_date.keys() if d > cutoff_date])

    if not valid_dates:
        return []

    # Group arrivals by slot_index across all dates
    slot_times: dict[int, list[time]] = {}
    slot_dates: dict[int, set[date]] = {}

    for d in valid_dates:
        arrivals = confirmed_by_date[d]
        # Sort arrivals by time for this date
        sorted_arrivals = sorted(arrivals, key=lambda a: a.arrival_time.time())

        # Assign slot indices (1-based) and collect times
        for slot_index, arrival in enumerate(sorted_arrivals, start=1):
            if slot_index not in slot_times:
                slot_times[slot_index] = []
                slot_dates[slot_index] = set()

            slot_times[slot_index].append(arrival.arrival_time.time())
            slot_dates[slot_index].add(d)

    # Compute stats for each slot_index
    results = []
    for slot_index in sorted(slot_times.keys()):
        times = slot_times[slot_index]
        min_time = min(times)
        max_time = max(times)

        # Calculate average time
        # Convert each time to minutes since midnight, average, convert back
        minutes_list = [t.hour * 60 + t.minute for t in times]
        avg_minutes = round(sum(minutes_list) / len(minutes_list))
        avg_hours = avg_minutes // 60
        avg_mins = avg_minutes % 60
        avg_time = time(avg_hours, avg_mins)

        sample_count = len(slot_dates[slot_index])

        results.append(
            SlotStats(
                slot_index=slot_index,
                min_time=min_time,
                max_time=max_time,
                avg_time=avg_time,
                sample_count=sample_count,
            )
        )

    return results
