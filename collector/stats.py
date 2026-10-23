from dataclasses import dataclass
from collections import defaultdict
from datetime import date, time, timedelta

from collector.resolve_arrivals import ConfirmedArrival


@dataclass
class SlotStats:
    """Statistics for one route number's N-th arrival of the day, across multiple days."""
    routeno: str
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
    Compute statistics for bus arrivals grouped by (route number, slot index) across days.

    Logic:
    1. Filter out dates older than as_of - window_days
    2. For each remaining date, sort arrivals by time, split them by route number, and assign
       slot indices (1-based) within each route. 노선별로 따로 세는 이유: 하루 전체에서 "몇 번째 차"로만
       세면 한 노선이 빠진 날 다른 노선이 앞 슬롯으로 밀려 시각이 섞인다. (2026-10-22 사용자 요청으로
       노선 번호별 집계 - 이전 명세의 "노선 구분 없이 방향 기준으로 합산"을 대체)
    3. Group arrivals by (routeno, slot_index) across all dates
    4. For each group, compute min/max/avg time and sample_count (dates that have this slot)

    Args:
        confirmed_by_date: Dictionary mapping date to list of ConfirmedArrival
        as_of: Reference date for the rolling window
        window_days: Number of days to look back (default 30)

    Returns:
        List of SlotStats sorted by average time, then route number, then slot_index
    """
    # Calculate cutoff date (exclude dates before or equal to this)
    cutoff_date = as_of - timedelta(days=window_days)

    # Filter dates within the window and sort by date
    valid_dates = sorted([d for d in confirmed_by_date.keys() if d > cutoff_date])

    if not valid_dates:
        return []

    # Group arrivals by slot_index across all dates
    slot_times: dict[tuple[str, int], list[time]] = defaultdict(list)
    slot_dates: dict[tuple[str, int], set[date]] = defaultdict(set)

    for d in valid_dates:
        # Sort arrivals by time for this date, then number them within each route
        per_route: dict[str, list[ConfirmedArrival]] = defaultdict(list)
        for arrival in sorted(confirmed_by_date[d], key=lambda a: a.arrival_time.time()):
            per_route[arrival.routeno].append(arrival)

        for routeno, route_arrivals in per_route.items():
            for slot_index, arrival in enumerate(route_arrivals, start=1):
                slot_times[(routeno, slot_index)].append(arrival.arrival_time.time())
                slot_dates[(routeno, slot_index)].add(d)

    # Compute stats for each (routeno, slot_index)
    results = []
    for (routeno, slot_index), times in slot_times.items():
        min_time = min(times)
        max_time = max(times)

        # Calculate average time
        # Convert each time to minutes since midnight, average, convert back
        minutes_list = [t.hour * 60 + t.minute for t in times]
        avg_minutes = round(sum(minutes_list) / len(minutes_list))
        avg_hours = avg_minutes // 60
        avg_mins = avg_minutes % 60
        avg_time = time(avg_hours, avg_mins)

        sample_count = len(slot_dates[(routeno, slot_index)])

        results.append(
            SlotStats(
                routeno=routeno,
                slot_index=slot_index,
                min_time=min_time,
                max_time=max_time,
                avg_time=avg_time,
                sample_count=sample_count,
            )
        )

    results.sort(key=lambda s: (s.avg_time, s.routeno, s.slot_index))
    return results
